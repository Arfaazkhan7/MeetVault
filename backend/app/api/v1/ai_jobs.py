from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.meeting_dependencies import get_meeting_and_authorize
from app.db.session import get_db
from app.models.ai_job import AIJob
from app.models.meeting import Meeting


router = APIRouter(prefix="/meetings/{meeting_id}/ai-jobs", tags=["ai-jobs"])


def _serialize(job: AIJob) -> dict:
    return {
        "public_id": job.public_id,
        "meeting_id": job.meeting_id,
        "recording_id": job.recording_id,
        "company_id": job.company_id,
        "job_type": job.job_type,
        "status": job.status,
        "retry_count": job.retry_count,
        "max_retries": job.max_retries,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
        "failed_at": job.failed_at,
        "error_message": job.error_message,
        "provider": job.provider,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


@router.get("")
def list_meeting_ai_jobs(
    meeting: Meeting = Depends(get_meeting_and_authorize),
    db: Session = Depends(get_db),
):
    jobs = (
        db.query(AIJob)
        .filter(AIJob.meeting_id == meeting.public_id)
        .order_by(AIJob.created_at.desc())
        .all()
    )
    return [_serialize(job) for job in jobs]
