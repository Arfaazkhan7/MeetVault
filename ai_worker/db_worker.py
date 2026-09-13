import logging
import signal
import time
from datetime import datetime, timezone

from app.db.session import SessionLocal
from app.models.ai_job import AIJob
from .config import settings
from .tasks import process_recording

logger = logging.getLogger(__name__)
_running = True


def _stop(_signum, _frame):
    global _running
    _running = False


def _claim_next_job() -> str | None:
    db = SessionLocal()
    try:
        query = db.query(AIJob).filter(AIJob.status == "QUEUED").order_by(AIJob.created_at.asc())
        try:
            job = query.with_for_update(skip_locked=True).first()
        except Exception:
            job = query.first()
        if not job:
            return None
        job.status = "RUNNING"
        job.started_at = datetime.now(timezone.utc)
        job.error_message = None
        db.commit()
        return job.public_id
    finally:
        db.close()


def run_database_worker() -> None:
    global _running
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    logger.info("MeetVault database AI worker started")
    while _running:
        job_id = _claim_next_job()
        if job_id:
            logger.info("Processing AI job %s", job_id)
            try:
                process_recording.run(job_id)
            except Exception:
                logger.exception("AI job %s failed", job_id)
        else:
            time.sleep(settings.poll_interval_seconds)
    logger.info("MeetVault database AI worker stopped")
