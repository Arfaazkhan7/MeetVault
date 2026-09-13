from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.ai_job import AIJob
from app.models.recording import MeetingRecording
from app.models.user import User


def _next_ai_job_id(db: Session) -> str:
    count = db.query(AIJob).count() + 1
    return f"AIJ-{count:04d}"


def get_or_create_recording_ai_job(
    db: Session,
    *,
    recording: MeetingRecording,
    requested_by: User,
    provider: str | None,
) -> AIJob:
    existing = (
        db.query(AIJob)
        .filter(
            AIJob.recording_id == str(recording.id),
            AIJob.job_type == "MEETING_AI_PIPELINE",
        )
        .first()
    )
    if existing:
        return existing

    job = AIJob(
        public_id=_next_ai_job_id(db),
        meeting_id=recording.meeting_id,
        recording_id=str(recording.id),
        company_id=recording.company_id,
        requested_by_user_id=requested_by.public_id,
        status="QUEUED",
        provider=provider,
    )
    db.add(job)
    db.flush()
    return job


def mark_ai_job_running(db: Session, job: AIJob) -> AIJob:
    job.status = "RUNNING"
    job.started_at = datetime.now(timezone.utc)
    job.error_message = None
    db.commit()
    db.refresh(job)
    return job


def mark_ai_job_completed(db: Session, job: AIJob) -> AIJob:
    job.status = "COMPLETED"
    job.completed_at = datetime.now(timezone.utc)
    job.error_message = None
    db.commit()
    db.refresh(job)
    return job


def mark_ai_job_failed(db: Session, job: AIJob, error: str) -> AIJob:
    job.status = "FAILED"
    job.failed_at = datetime.now(timezone.utc)
    job.retry_count += 1
    job.error_message = error[:4000]
    db.commit()
    db.refresh(job)
    return job
