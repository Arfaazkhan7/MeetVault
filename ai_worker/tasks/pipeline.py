"""
Master pipeline for meeting intelligence processing.

Flow:
  QUEUED → FETCHING_AUDIO → TRANSCRIBING → DIARIZING → BUILDING_TRANSCRIPT
         → EXTRACTING_INTELLIGENCE → UPDATING_RAG → COMPLETED

Diarization uses the pyannoteAI REST API (https://api.pyannote.ai).
Transcription uses the Hugging Face Inference API (openai/whisper-large-v3).
Analysis uses the backend's MeetingAnalysisService (LLM provider from config).
"""
import logging
import os
import tempfile
from uuid import UUID

from app.db.session import SessionLocal
from ai_worker.config import settings
from ai_worker.core.job_manager import JobManager
from app.models.meeting import Meeting
from app.models.recording import MeetingRecording
from app.models.transcript import TranscriptSegment as DbTranscriptSegment
from app.services.storage_service import get_storage_service

logger = logging.getLogger(__name__)

# How long the signed URL should stay valid for pyannoteAI to download the file
_SIGNED_URL_EXPIRE_SECONDS = 3600  # 1 hour


def _log_config_status():
    """Log presence/absence of required env vars WITHOUT printing their values."""
    required = {
        "DATABASE_URL": os.getenv("DATABASE_URL"),
        "SUPABASE_URL": os.getenv("SUPABASE_URL"),
        "SUPABASE_SERVICE_ROLE_KEY": os.getenv("SUPABASE_SERVICE_ROLE_KEY"),
        "HF_TOKEN": os.getenv("HF_TOKEN"),
        "PYANNOTEAI_API_KEY": os.getenv("PYANNOTEAI_API_KEY"),
    }
    for name, value in required.items():
        status = "configured" if (value and value.strip()) else "MISSING"
        logger.info("Config check — %s: %s", name, status)


def process_meeting_intelligence(ai_job_id: str):
    """
    Synchronous pipeline entry point (called by Celery task or DB worker).
    """
    logger.info("Starting intelligence pipeline for AI Job: %s", ai_job_id)
    _log_config_status()

    db = SessionLocal()
    manager = JobManager(db)
    job = manager.get_job(ai_job_id)

    if not job:
        logger.error("Job %s not found in database.", ai_job_id)
        db.close()
        return

    recording = None
    meeting = None

    try:
        if job.status == "COMPLETED":
            logger.info("Job %s already completed. Skipping.", ai_job_id)
            db.close()
            return

        if job.retry_count >= job.max_retries:
            logger.warning("Job %s exceeded max retries (%d).", ai_job_id, job.max_retries)
            db.close()
            return

        manager.mark_started(job)

        # ── Load related records ─────────────────────────────────────────────
        recording = db.query(MeetingRecording).filter(
            MeetingRecording.id == UUID(job.recording_id)
        ).first()
        meeting = db.query(Meeting).filter(
            Meeting.public_id == job.meeting_id
        ).first()

        if not recording or not meeting:
            raise RuntimeError(
                f"Recording (id={job.recording_id}) or Meeting (id={job.meeting_id}) "
                "not found in database."
            )

        recording.processing_status = "PROCESSING"
        meeting.transcription_status = "processing"
        meeting.analysis_status = "processing"
        db.commit()

        # ── Stage 1: Fetch audio ──────────────────────────────────────────────
        manager.update_stage(job, "FETCHING_AUDIO")
        storage = get_storage_service()
        audio_bytes = storage.download_private_file(path=recording.storage_path)

        suffix = (
            "." + recording.original_filename.rsplit(".", 1)[-1]
            if "." in recording.original_filename
            else ".bin"
        )

        # Write audio to a temp file for transcription.
        # Keep it alive across stages by NOT using context manager delete=True here.
        tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        try:
            tmp.write(audio_bytes)
            tmp.flush()
            tmp.close()
            audio_path = tmp.name

            # ── Stage 2: Transcription ────────────────────────────────────────
            manager.update_stage(job, "TRANSCRIBING")
            from ai_worker.providers import transcribe
            try:
                segments = transcribe(audio_path)
            except Exception as exc:
                raise RuntimeError(f"Transcription failed: {exc}") from exc

            if not segments:
                raise RuntimeError(
                    "Transcription produced 0 segments. "
                    "The audio may be empty or in an unsupported format."
                )
            logger.info("Transcription produced %d segment(s).", len(segments))

            # ── Stage 3: Diarization via pyannoteAI ──────────────────────────
            manager.update_stage(job, "DIARIZING")
            from ai_worker.diarization.diarization import diarize, DiarizationError

            # Create a time-limited signed URL so pyannoteAI can download the audio
            try:
                audio_url = storage.create_signed_url(
                    path=recording.storage_path,
                    expires_in_seconds=_SIGNED_URL_EXPIRE_SECONDS,
                )
                logger.info("Created signed URL for diarization (expires in %ds).", _SIGNED_URL_EXPIRE_SECONDS)
            except Exception as exc:
                raise RuntimeError(
                    f"Failed to create signed URL for diarization: {exc}"
                ) from exc

            try:
                speaker_turns = diarize(audio_url)
            except DiarizationError as exc:
                raise RuntimeError(f"Diarization failed: {exc}") from exc

            logger.info("Diarization returned %d speaker turn(s).", len(speaker_turns))

        finally:
            # Always clean up the temp file
            try:
                os.unlink(tmp.name)
            except OSError:
                pass

        # ── Stage 4: Align speakers with transcript ──────────────────────────
        manager.update_stage(job, "BUILDING_TRANSCRIPT")
        from ai_worker.diarization.speaker_mapping import align_speakers
        mapped_segments = align_speakers(segments, speaker_turns)

        # Validate that we actually got multi-speaker output when diarization worked
        unique_speakers = set(s.speaker_label for s in mapped_segments if s.speaker_label)
        logger.info(
            "Transcript aligned: %d segment(s), %d unique speaker(s): %s",
            len(mapped_segments), len(unique_speakers), sorted(unique_speakers)
        )

        # Persist transcript segments
        db.query(DbTranscriptSegment).filter(
            DbTranscriptSegment.meeting_id == meeting.public_id
        ).delete()

        for segment in mapped_segments:
            db.add(DbTranscriptSegment(
                meeting_id=meeting.public_id,
                speaker_label=segment.speaker_label or "SPEAKER_UNKNOWN",
                start_time=segment.start_time,
                end_time=segment.end_time,
                text=segment.text,
                language=None,
            ))
        db.commit()
        logger.info("Saved %d transcript segment(s) to database.", len(mapped_segments))

        # Create speaker mappings (SPEAKER_00 → unmapped, available for UI assignment)
        from app.services.speaker_mapping_service import SpeakerMappingService
        mapping_service = SpeakerMappingService()
        mapping_service.create_speaker_mappings(
            db=db,
            meeting=meeting,
            speaker_labels=sorted(unique_speakers),
        )

        # ── Stage 5 & 6: AI Analysis ─────────────────────────────────────────
        manager.update_stage(job, "EXTRACTING_INTELLIGENCE")
        try:
            from app.services.meeting_analysis_service import MeetingAnalysisService
            analysis_service = MeetingAnalysisService()
            analysis_service.analyze_meeting(db=db, meeting=meeting, force_reanalysis=True)
        except Exception as exc:
            logger.warning(
                "Meeting analysis failed (non-fatal): %s. "
                "Transcript is saved; analysis can be retried.",
                exc
            )

        # ── Stage 7: Embeddings / RAG ─────────────────────────────────────────
        manager.update_stage(job, "UPDATING_RAG")
        try:
            from app.services.embedding_service import EmbeddingService
            EmbeddingService.index_meeting_entities(
                db, company_id=meeting.company_id, meeting_id=meeting.public_id
            )
        except Exception as exc:
            logger.warning("RAG indexing failed (non-fatal): %s", exc)

        # ── Complete ──────────────────────────────────────────────────────────
        meeting.transcription_status = "completed"
        meeting.analysis_status = "completed"
        recording.processing_status = "COMPLETED"
        manager.mark_completed(job)
        logger.info("Pipeline completed successfully for job %s.", ai_job_id)

    except Exception as exc:
        # Mark everything failed with a useful error message
        error_msg = str(exc)
        logger.exception("Pipeline FAILED for job %s: %s", ai_job_id, error_msg)

        manager.mark_failed(job, error_msg)

        # Reload recording/meeting in case they were not set yet
        if recording is None and job.recording_id:
            recording = db.query(MeetingRecording).filter(
                MeetingRecording.id == UUID(job.recording_id)
            ).first()
        if meeting is None and job.meeting_id:
            meeting = db.query(Meeting).filter(
                Meeting.public_id == job.meeting_id
            ).first()

        if recording:
            recording.processing_status = "FAILED"
            recording.processing_error = error_msg
        if meeting:
            meeting.transcription_status = "failed"
            meeting.transcription_error = error_msg
            meeting.analysis_status = "failed"
            meeting.analysis_error = error_msg

        try:
            db.commit()
        except Exception:
            logger.exception("Failed to commit failure status for job %s", ai_job_id)

        raise

    finally:
        db.close()
