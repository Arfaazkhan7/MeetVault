import logging
import tempfile
from typing import Any, Dict, Optional
from uuid import UUID

from celery import Celery

from .config import settings
from .providers import analyze, transcribe

logger = logging.getLogger(__name__)
celery_app = Celery("meetvault_ai_worker", broker=settings.broker_url, backend=settings.broker_url)
celery_app.conf.update(task_serializer="json", result_serializer="json", accept_content=["json"], task_acks_late=True)


@celery_app.task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def process_meeting(self, meeting_id: str, audio_path: str, title: str, language: Optional[str] = None) -> Dict[str, Any]:
    """Transcribe and analyze one recording; the caller persists the returned result."""
    logger.info("Processing meeting %s", meeting_id)
    segments = transcribe(audio_path, language)
    result = {"meeting_id": meeting_id, "segments": [s.as_dict() for s in segments]}
    result["analysis"] = analyze(title, segments).as_dict()
    return result


@celery_app.task(name="ai_worker.tasks.process_recording", bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def process_recording(self, ai_job_id: str, language: Optional[str] = None) -> Dict[str, Any]:
    from app.db.session import SessionLocal
    from app.models.ai_job import AIJob
    from app.models.meeting import Meeting
    from app.models.recording import MeetingRecording
    from app.models.transcript import TranscriptSegment as DbTranscriptSegment
    from app.services.ai_job_service import mark_ai_job_completed, mark_ai_job_failed, mark_ai_job_running
    from app.services.storage_service import get_storage_service

    db = SessionLocal()
    try:
        job = db.query(AIJob).filter(AIJob.public_id == ai_job_id).first()
        if not job:
            raise RuntimeError(f"AI job not found: {ai_job_id}")

        mark_ai_job_running(db, job)
        recording = db.query(MeetingRecording).filter(MeetingRecording.id == UUID(job.recording_id)).first()
        meeting = db.query(Meeting).filter(Meeting.public_id == job.meeting_id).first()
        if not recording or not meeting:
            raise RuntimeError("Recording or meeting for AI job was not found")

        recording.processing_status = "PROCESSING"
        meeting.transcription_status = "processing"
        meeting.analysis_status = "processing"
        db.commit()

        content = get_storage_service().download_private_file(path=recording.storage_path)
        suffix = "." + recording.original_filename.rsplit(".", 1)[-1] if "." in recording.original_filename else ".bin"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as audio_file:
            audio_file.write(content)
            audio_file.flush()
            segments = transcribe(audio_file.name, language)

        db.query(DbTranscriptSegment).filter(DbTranscriptSegment.meeting_id == meeting.public_id).delete()
        for segment in segments:
            db.add(
                DbTranscriptSegment(
                    meeting_id=meeting.public_id,
                    speaker_label=segment.speaker_label or "SPEAKER_0",
                    start_time=segment.start_time,
                    end_time=segment.end_time,
                    text=segment.text,
                    language=language,
                )
            )

        result = {"meeting_id": meeting.public_id, "segments": [s.as_dict() for s in segments]}
        result["analysis"] = analyze(meeting.title, segments).as_dict()
        meeting.transcription_status = "completed"
        meeting.analysis_status = "completed"
        recording.processing_status = "COMPLETED"
        db.commit()
        mark_ai_job_completed(db, job)
        return result
    except Exception as exc:
        db.rollback()
        job = db.query(AIJob).filter(AIJob.public_id == ai_job_id).first()
        if job:
            mark_ai_job_failed(db, job, str(exc))
            meeting = db.query(Meeting).filter(Meeting.public_id == job.meeting_id).first()
            recording = db.query(MeetingRecording).filter(MeetingRecording.id == UUID(job.recording_id)).first()
            if meeting:
                meeting.transcription_status = "failed"
                meeting.transcription_error = str(exc)
                meeting.analysis_status = "failed"
                meeting.analysis_error = str(exc)
            if recording:
                recording.processing_status = "FAILED"
                recording.processing_error = str(exc)
            db.commit()
        raise
    finally:
        db.close()
