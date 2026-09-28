import json
import logging
import os
import time
from typing import Any

from .db_worker import process_one_queued_job

logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())


def handler(event: dict[str, Any] | None, _context: Any) -> dict[str, Any]:
    """AWS Lambda entry point for the database-queue AI worker.

    Invoke this with EventBridge on a short schedule. The handler processes a
    bounded number of queued jobs and exits, which works better on serverless
    compute than a forever-running worker loop.
    """

    event = event or {}
    max_jobs = int(event.get("max_jobs") or os.getenv("AI_WORKER_LAMBDA_MAX_JOBS", "1"))
    max_seconds = int(event.get("max_seconds") or os.getenv("AI_WORKER_LAMBDA_MAX_SECONDS", "600"))
    deadline = time.monotonic() + max(1, max_seconds)

    processed: list[str] = []
    while len(processed) < max_jobs and time.monotonic() < deadline:
        job_id = process_one_queued_job()
        if not job_id:
            break
        processed.append(job_id)

    body = {
        "ok": True,
        "processed_count": len(processed),
        "processed_job_ids": processed,
    }
    return {
        "statusCode": 200,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(body),
    }
