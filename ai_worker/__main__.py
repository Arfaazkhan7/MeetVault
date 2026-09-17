"""
MeetVault AI Worker entrypoint.

Validates required configuration at startup and selects the queue backend.
"""
import logging
import os
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ai_worker")

from .config import settings


def _startup_validation() -> bool:
    """
    Check that required environment variables are present.
    Logs their status without revealing actual values.
    Returns True if all required vars are present, False otherwise.
    """
    required = {
        "DATABASE_URL": os.getenv("DATABASE_URL"),
        "SUPABASE_URL": os.getenv("SUPABASE_URL"),
        "SUPABASE_SERVICE_ROLE_KEY": os.getenv("SUPABASE_SERVICE_ROLE_KEY"),
        "HF_TOKEN": os.getenv("HF_TOKEN"),
        "PYANNOTEAI_API_KEY": os.getenv("PYANNOTEAI_API_KEY"),
    }

    logger.info("=== MeetVault AI Worker — Configuration Status ===")
    all_ok = True
    for name, value in required.items():
        configured = bool(value and value.strip())
        status = "configured" if configured else "MISSING ⚠"
        logger.info("  %-30s %s", name + ":", status)
        if not configured:
            all_ok = False

    # Non-fatal optional vars
    optional = {
        "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY"),
        "TRANSCRIPTION_PROVIDER": settings.transcription_provider,
        "LLM_PROVIDER": settings.analysis_provider,
    }
    logger.info("--- Optional / Informational ---")
    for name, value in optional.items():
        display = value if value else "(not set)"
        logger.info("  %-30s %s", name + ":", display)

    logger.info("==================================================")
    return all_ok


if __name__ == "__main__":
    pass
else:
    ok = _startup_validation()
    if not ok:
        logger.warning(
            "One or more required environment variables are MISSING. "
            "Jobs that need them will fail with a clear error message. "
            "Set them in the Render dashboard (never in source code)."
        )

if settings.queue_backend.lower() == "celery":
    from .tasks import celery_app
    celery_app.worker_main(["worker", "--loglevel=INFO"])
else:
    from .db_worker import run_database_worker
    run_database_worker()
