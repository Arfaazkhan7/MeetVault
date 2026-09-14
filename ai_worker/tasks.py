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
    from ai_worker.tasks.pipeline import process_meeting_intelligence
    process_meeting_intelligence(ai_job_id)
    return {"status": "success", "ai_job_id": ai_job_id}
