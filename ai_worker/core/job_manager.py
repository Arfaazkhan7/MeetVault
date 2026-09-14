import logging
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.models.processing_job import ProcessingJob

logger = logging.getLogger(__name__)

class JobManager:
    def __init__(self, db: Session):
        self.db = db

    def create_or_get_job(self, meeting_id: str, job_type: str = "MEETING_INTELLIGENCE") -> ProcessingJob:
        job = self.db.query(ProcessingJob).filter(
            ProcessingJob.meeting_id == meeting_id,
            ProcessingJob.job_type == job_type
        ).first()

        if not job:
            job = ProcessingJob(
                meeting_id=meeting_id,
                job_type=job_type,
                status="QUEUED",
                current_stage="QUEUED",
                attempt_count=0
            )
            self.db.add(job)
            self.db.commit()
            self.db.refresh(job)
        return job

    def mark_started(self, job: ProcessingJob):
        job.status = "PROCESSING"
        job.current_stage = "INITIALIZING"
        job.attempt_count += 1
        job.started_at = datetime.now(timezone.utc)
        job.last_error = None
        self.db.commit()

    def update_stage(self, job: ProcessingJob, stage: str):
        job.current_stage = stage
        self.db.commit()
        logger.info(f"Job {job.id} (Meeting {job.meeting_id}) advanced to stage: {stage}")

    def mark_completed(self, job: ProcessingJob):
        job.status = "COMPLETED"
        job.current_stage = "COMPLETED"
        job.completed_at = datetime.now(timezone.utc)
        self.db.commit()
        logger.info(f"Job {job.id} (Meeting {job.meeting_id}) completed successfully.")

    def mark_failed(self, job: ProcessingJob, error_msg: str):
        job.status = "FAILED"
        job.last_error = error_msg
        self.db.commit()
        logger.error(f"Job {job.id} (Meeting {job.meeting_id}) failed: {error_msg}")

