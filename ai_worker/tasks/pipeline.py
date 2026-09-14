import logging
import tempfile
from uuid import UUID
from app.db.session import SessionLocal
from ai_worker.core.job_manager import JobManager
from app.models.meeting import Meeting
from app.models.recording import MeetingRecording
from app.models.transcript import TranscriptSegment as DbTranscriptSegment
from app.services.storage_service import get_storage_service

logger = logging.getLogger(__name__)

def process_meeting_intelligence(ai_job_id: str):
    """
    Master pipeline for meeting intelligence.
    Runs synchronously (invoked by Celery or DB Worker).
    """
    logger.info(f"Starting intelligence pipeline for AI Job: {ai_job_id}")
    db = SessionLocal()
    manager = JobManager(db)
    job = manager.get_job(ai_job_id)

    if not job:
        logger.error(f"Job {ai_job_id} not found.")
        db.close()
        return

    try:
        if job.status == "COMPLETED":
            logger.info(f"Job {ai_job_id} already completed. Skipping.")
            return

        if job.retry_count >= job.max_retries:
            logger.warning(f"Job {ai_job_id} exceeded max attempts.")
            return

        manager.mark_started(job)

        recording = db.query(MeetingRecording).filter(MeetingRecording.id == UUID(job.recording_id)).first()
        meeting = db.query(Meeting).filter(Meeting.public_id == job.meeting_id).first()
        if not recording or not meeting:
            raise RuntimeError("Recording or meeting not found for this job")

        recording.processing_status = "PROCESSING"
        meeting.transcription_status = "processing"
        meeting.analysis_status = "processing"
        db.commit()

        # Stage 1: Audio Retrieval & Validation
        manager.update_stage(job, "FETCHING_AUDIO")
        storage = get_storage_service()
        content = storage.download_private_file(path=recording.storage_path)
        suffix = "." + recording.original_filename.rsplit(".", 1)[-1] if "." in recording.original_filename else ".bin"
        
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as audio_file:
            audio_file.write(content)
            audio_file.flush()

            # Stage 2: Transcription
            manager.update_stage(job, "TRANSCRIBING")
            from ai_worker.providers import transcribe
            # language can be pulled from meeting config in future
            segments = transcribe(audio_file.name)

            # Stage 3: Diarization
            manager.update_stage(job, "DIARIZING")
            from ai_worker.diarization.diarization import diarize
            speaker_turns = diarize(audio_file.name)

            # Stage 4: Speaker Mapping & Transcript Segments
            manager.update_stage(job, "BUILDING_TRANSCRIPT")
            from ai_worker.diarization.speaker_mapping import align_speakers
            mapped_segments = align_speakers(segments, speaker_turns)

            db.query(DbTranscriptSegment).filter(DbTranscriptSegment.meeting_id == meeting.public_id).delete()
            for segment in mapped_segments:
                db.add(
                    DbTranscriptSegment(
                        meeting_id=meeting.public_id,
                        speaker_label=segment.speaker_label or "SPEAKER_0",
                        start_time=segment.start_time,
                        end_time=segment.end_time,
                        text=segment.text,
                        language=None,
                    )
                )
            db.commit()

        # Stage 5: AI Structured Extraction
        manager.update_stage(job, "EXTRACTING_INTELLIGENCE")
        # TODO: Implement structured extraction

        # Stage 6: Summary Generation
        manager.update_stage(job, "GENERATING_SUMMARY")
        # TODO: Implement summary generation

        # Stage 7: Embeddings / RAG Update
        manager.update_stage(job, "UPDATING_RAG")
        # TODO: Implement embedding generation

        meeting.transcription_status = "completed"
        meeting.analysis_status = "completed"
        recording.processing_status = "COMPLETED"
        manager.mark_completed(job)

    except Exception as e:
        logger.exception(f"Pipeline failed for job {ai_job_id}")
        manager.mark_failed(job, str(e))
        
        # Also mark recording and meeting as failed
        recording = db.query(MeetingRecording).filter(MeetingRecording.id == UUID(job.recording_id)).first()
        meeting = db.query(Meeting).filter(Meeting.public_id == job.meeting_id).first()
        if meeting:
            meeting.transcription_status = "failed"
            meeting.transcription_error = str(e)
            meeting.analysis_status = "failed"
            meeting.analysis_error = str(e)
        if recording:
            recording.processing_status = "FAILED"
            recording.processing_error = str(e)
        db.commit()
        
        raise
    finally:
        db.close()
