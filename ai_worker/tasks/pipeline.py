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

        if not recording.storage_path:
            raise RuntimeError(
                f"Recording (id={job.recording_id}) has not been finalized (storage_path is empty)."
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
                logger.info(
                    "Transcription produced 0 segments (empty audio or silence) for meeting %s.",
                    meeting.public_id,
                )
                # Clean up any stale unconfirmed segments from previous runs
                stale_unconfirmed = (
                    db.query(DbTranscriptSegment)
                    .filter(
                        DbTranscriptSegment.meeting_id == meeting.public_id,
                        DbTranscriptSegment.speaker_confirmed == False,
                    )
                    .all()
                )
                for old in stale_unconfirmed:
                    db.delete(old)

                meeting.transcription_status = "completed"
                meeting.transcription_error = None
                meeting.analysis_status = "completed"
                meeting.analysis_error = None
                recording.processing_status = "COMPLETED"
                recording.processing_error = None
                db.commit()
                manager.mark_completed(job)
                logger.info("Pipeline completed cleanly for silent/empty recording (job %s).", ai_job_id)
                return

            logger.info("Transcription produced %d segment(s).", len(segments))

            # ── Stage 3: Diarization via pyannoteAI ──────────────────────────
            manager.update_stage(job, "DIARIZING")
            from ai_worker.diarization.diarization import diarize, DiarizationError

            speaker_turns = []
            try:
                # Create a time-limited signed URL so pyannoteAI can download the audio
                audio_url = storage.create_signed_url(
                    path=recording.storage_path,
                    expires_in_seconds=_SIGNED_URL_EXPIRE_SECONDS,
                )
                logger.info("Created signed URL for diarization (expires in %ds).", _SIGNED_URL_EXPIRE_SECONDS)
                speaker_turns = diarize(audio_url)
                logger.info("Diarization returned %d speaker turn(s).", len(speaker_turns))
            except Exception as exc:
                logger.warning(
                    "Diarization skipped or encountered an error (%s); falling back to single-speaker labeling.",
                    exc,
                )
                speaker_turns = []

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

        # ── Idempotent Transactional Persistence ──────────────────────────────
        # Load existing segments to preserve user-confirmed mappings and avoid stale/duplicate state
        existing_segments = (
            db.query(DbTranscriptSegment)
            .filter(DbTranscriptSegment.meeting_id == meeting.public_id)
            .order_by(DbTranscriptSegment.start_time)
            .all()
        )
        existing_by_seg_id = {s.segment_id: s for s in existing_segments if s.segment_id}
        confirmed_by_spk = {
            s.speaker_label: (s.user_id, s.speaker_confirmed)
            for s in existing_segments
            if s.speaker_confirmed
        }

        active_segment_ids = set()

        for idx, segment in enumerate(mapped_segments):
            # Validate timestamps
            start_ts = max(0.0, float(segment.start_time))
            end_ts = max(start_ts, float(segment.end_time))

            # Deterministic stable segment identifier: <meeting_public_id>:<index:04d>
            stable_id = segment.segment_id or f"{meeting.public_id}:{idx:04d}"
            active_segment_ids.add(stable_id)

            existing_seg = existing_by_seg_id.get(stable_id)
            if existing_seg is None and idx < len(existing_segments):
                existing_seg = existing_segments[idx]

            speaker_label = segment.speaker_label or "SPEAKER_UNKNOWN"
            user_id = None
            is_confirmed = False

            if existing_seg and existing_seg.speaker_confirmed:
                # User has confirmed this segment's speaker mapping; PRESERVE IT!
                speaker_label = existing_seg.speaker_label
                user_id = existing_seg.user_id
                is_confirmed = True
            elif speaker_label in confirmed_by_spk:
                # User previously confirmed this speaker label across the meeting
                user_id, is_confirmed = confirmed_by_spk[speaker_label]

            if existing_seg:
                # Update existing segment in place
                existing_seg.recording_id = str(recording.id)
                existing_seg.segment_id = stable_id
                existing_seg.start_time = start_ts
                existing_seg.end_time = end_ts
                existing_seg.text = segment.text
                existing_seg.language = segment.language or existing_seg.language
                existing_seg.confidence = segment.confidence
                existing_seg.translated_text = segment.translated_text or existing_seg.translated_text
                existing_seg.words = segment.words
                if not existing_seg.speaker_confirmed:
                    existing_seg.speaker_label = speaker_label
                    existing_seg.user_id = user_id
                    existing_seg.speaker_confirmed = is_confirmed
            else:
                # Insert new segment with stable identity
                new_seg = DbTranscriptSegment(
                    meeting_id=meeting.public_id,
                    recording_id=str(recording.id),
                    segment_id=stable_id,
                    speaker_label=speaker_label,
                    user_id=user_id,
                    speaker_confirmed=is_confirmed,
                    start_time=start_ts,
                    end_time=end_ts,
                    text=segment.text,
                    language=segment.language,
                    confidence=segment.confidence,
                    translated_text=segment.translated_text,
                    words=segment.words,
                )
                db.add(new_seg)

        # Remove stale unconfirmed segments from previous runs that are beyond current count
        for old in existing_segments:
            if (old.segment_id not in active_segment_ids) and not old.speaker_confirmed:
                db.delete(old)

        db.commit()
        logger.info(
            "Idempotently persisted %d transcript segment(s) to database (protected confirmed mappings).",
            len(mapped_segments),
        )

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
