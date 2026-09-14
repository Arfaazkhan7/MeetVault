import logging
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.models.ai_job import AIJob

logger = logging.getLogger(__name__)

class JobManager:
    def __init__(self, db: Session):
        self.db = db

    def get_job(self, ai_job_id: str) -> AIJob | None:
        return self.db.query(AIJob).filter(AIJob.public_id == ai_job_id).first()

    def mark_started(self, job: AIJob):
        job.status = "PROCESSING"
        job.current_stage = "INITIALIZING"
        job.retry_count += 1
        job.started_at = datetime.now(timezone.utc)
        job.error_message = None
        self.db.commit()

    def update_stage(self, job: AIJob, stage: str):
        job.current_stage = stage
        self.db.commit()
        logger.info(f"AIJob {job.public_id} (Meeting {job.meeting_id}) advanced to stage: {stage}")

    def mark_completed(self, job: AIJob):
        job.status = "COMPLETED"
        job.current_stage = "COMPLETED"
        job.completed_at = datetime.now(timezone.utc)
        self.db.commit()
        logger.info(f"AIJob {job.public_id} (Meeting {job.meeting_id}) completed successfully.")

    def mark_failed(self, job: AIJob, error_msg: str):
        job.status = "FAILED"
        job.error_message = error_msg
        job.failed_at = datetime.now(timezone.utc)
        self.db.commit()
        logger.error(f"AIJob {job.public_id} (Meeting {job.meeting_id}) failed: {error_msg}")


