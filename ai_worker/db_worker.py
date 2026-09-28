import logging
import signal
import time
from datetime import datetime, timedelta, timezone

from app.db.session import SessionLocal
from app.models.ai_job import AIJob
from .config import settings
from .tasks import process_recording

logger = logging.getLogger(__name__)
_running = True


def _stop(_signum, _frame):
    global _running
    _running = False


def _recover_stale_jobs(db) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=settings.stale_job_minutes)
    stale_jobs = (
        db.query(AIJob)
        .filter(AIJob.status == "PROCESSING", AIJob.started_at.isnot(None), AIJob.started_at < cutoff)
        .all()
    )
    for job in stale_jobs:
        job.status = "QUEUED"
        job.current_stage = "RETRY_QUEUED"
        job.error_message = "Recovered after worker interruption"
    return len(stale_jobs)


def _claim_next_job() -> str | None:
    db = SessionLocal()
    try:
        recovered = _recover_stale_jobs(db)
        query = (
            db.query(AIJob)
            .filter(AIJob.status == "QUEUED")
            .order_by(AIJob.created_at.asc())
            .with_for_update(skip_locked=True)
        )
        job = query.first()
        if recovered:
            logger.warning("Recovered %s stale AI job(s)", recovered)
        if not job:
            if recovered:
                db.commit()
            return None
        job.status = "RUNNING"
        job.started_at = datetime.now(timezone.utc)
        job.error_message = None
        db.commit()
        return job.public_id
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def process_one_queued_job() -> str | None:
    """Claim and process one queued database AI job."""
    job_id = _claim_next_job()
    if not job_id:
        return None
    logger.info("Processing AI job %s", job_id)
    try:
        process_recording.run(job_id)
    except Exception:
        logger.exception("AI job %s failed", job_id)
    return job_id


def run_database_worker() -> None:
    global _running
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    logger.info("MeetVault database AI worker started")
    retry_delay = max(1.0, settings.poll_interval_seconds)
    while _running:
        try:
            job_id = process_one_queued_job()
            retry_delay = max(1.0, settings.poll_interval_seconds)
            if not job_id:
                time.sleep(settings.poll_interval_seconds)
        except Exception:
            logger.exception("AI worker database poll failed; retrying in %.1fs", retry_delay)
            time.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 60.0)
    logger.info("MeetVault database AI worker stopped")
