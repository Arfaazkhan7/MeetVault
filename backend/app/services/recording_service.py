from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import HTTPException, UploadFile, status
import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.enums import RecordingProcessingStatus
from app.models.meeting import Meeting
from app.models.recording import MeetingRecording
from app.models.user import User
from app.services.ai_job_service import get_or_create_recording_ai_job, mark_ai_job_failed
from app.services.storage_service import StorageService


ALLOWED_RECORDING_TYPES = {
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/mp4": ".m4a",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
}


def _recording_storage_path(meeting: Meeting, user: User, filename: str) -> str:
    suffix = Path(filename).suffix.lower() or ".bin"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    tenant_id = meeting.company_id or f"personal/{user.public_id}"
    return f"{tenant_id}/{meeting.public_id}/{timestamp}-{user.public_id}-{uuid4()}{suffix}"


def _serialize_recording(recording: MeetingRecording) -> dict:
    return {
        "id": str(recording.id),
        "meeting_id": recording.meeting_id,
        "company_id": recording.company_id,
        "uploaded_by_user_id": recording.uploaded_by_user_id,
        "storage_backend": recording.storage_backend,
        "storage_bucket": recording.storage_bucket,
        "storage_path": recording.storage_path,
        "original_filename": recording.original_filename,
        "file_type": recording.file_type,
        "file_size_bytes": recording.file_size_bytes,
        "duration_seconds": recording.duration_seconds,
        "processing_status": recording.processing_status,
        "processing_error": recording.processing_error,
        "ai_job_id": getattr(recording, "ai_job_id", None),
        "created_at": recording.created_at,
    }


async def create_recording_from_upload(
    db: Session,
    *,
    meeting: Meeting,
    current_user: User,
    upload: UploadFile,
    duration_seconds: int | None,
    storage: StorageService,
) -> dict:
    content_type = upload.content_type or "application/octet-stream"
    if content_type not in ALLOWED_RECORDING_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported recording file type",
        )

    content = await upload.read()
    if not content:
        raise HTTPException(status_code=400, detail="Recording file is empty")
    if len(content) > settings.MAX_RECORDING_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Recording file is too large")

    storage_path = _recording_storage_path(meeting, current_user, upload.filename or "recording")
    stored = storage.upload_private_file(
        path=storage_path,
        content=content,
        content_type=content_type,
    )
    recording = MeetingRecording(
        meeting_id=meeting.public_id,
        company_id=meeting.company_id,
        uploaded_by_user_id=current_user.public_id,
        storage_backend=stored.backend,
        storage_bucket=stored.bucket,
        storage_path=stored.path,
        original_filename=upload.filename or "recording",
        file_type=content_type,
        file_size_bytes=len(content),
        duration_seconds=duration_seconds,
        processing_status=RecordingProcessingStatus.UPLOADED.value,
    )
    db.add(recording)
    meeting.recording_url = stored.path
    meeting.transcription_status = "queued"
    meeting.analysis_status = "queued"
    recording.processing_status = RecordingProcessingStatus.QUEUED.value
    db.flush()

    job = get_or_create_recording_ai_job(
        db,
        recording=recording,
        requested_by=current_user,
        provider=settings.LLM_PROVIDER,
    )
    db.commit()
    db.refresh(recording)
    _enqueue_ai_job(db, job.public_id)
    payload = _serialize_recording(recording)
    payload["ai_job_id"] = job.public_id
    return payload


def _enqueue_ai_job(db: Session, job_id: str) -> None:
    queue_backend = settings.AI_WORKER_QUEUE.lower()
    if queue_backend == "database":
        return
    try:
        if queue_backend == "cloudflare":
            if not settings.CLOUDFLARE_AI_QUEUE_URL or not settings.CLOUDFLARE_AI_QUEUE_SECRET:
                raise RuntimeError("Cloudflare AI queue URL/secret is not configured")
            response = httpx.post(
                settings.CLOUDFLARE_AI_QUEUE_URL,
                json={"job_id": job_id},
                headers={"x-meetvault-worker-secret": settings.CLOUDFLARE_AI_QUEUE_SECRET},
                timeout=10,
            )
            response.raise_for_status()
            return

        from celery import Celery

        celery = Celery("meetvault_api", broker=settings.REDIS_URL, backend=settings.REDIS_URL)
        celery.send_task("ai_worker.tasks.process_recording", args=[job_id])
    except Exception as exc:
        from app.models.ai_job import AIJob

        job = db.query(AIJob).filter(AIJob.public_id == job_id).first()
        if job:
            mark_ai_job_failed(db, job, f"AI worker queue unavailable: {exc}")


def list_meeting_recordings(db: Session, meeting: Meeting) -> list[dict]:
    recordings = db.query(MeetingRecording).filter(
        MeetingRecording.meeting_id == meeting.public_id,
        MeetingRecording.company_id == meeting.company_id,
        MeetingRecording.deleted_at.is_(None),
    ).order_by(MeetingRecording.created_at.desc()).all()
    return [_serialize_recording(recording) for recording in recordings]


def get_recording_or_404(db: Session, meeting: Meeting, recording_id: str) -> MeetingRecording:
    try:
        uuid_value = UUID(recording_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Recording not found")
    recording = db.query(MeetingRecording).filter(
        MeetingRecording.id == uuid_value,
        MeetingRecording.meeting_id == meeting.public_id,
        MeetingRecording.company_id == meeting.company_id,
        MeetingRecording.deleted_at.is_(None),
    ).first()
    if not recording:
        raise HTTPException(status_code=404, detail="Recording not found")
    return recording


def create_recording_signed_url(
    db: Session,
    *,
    meeting: Meeting,
    recording_id: str,
    storage: StorageService,
) -> dict:
    recording = get_recording_or_404(db, meeting, recording_id)
    expires = settings.RECORDING_SIGNED_URL_EXPIRE_SECONDS
    return {
        "recording_id": str(recording.id),
        "url": storage.create_signed_url(
            path=recording.storage_path,
            expires_in_seconds=expires,
        ),
        "expires_in_seconds": expires,
    }


def update_recording_status(
    db: Session,
    *,
    meeting: Meeting,
    recording_id: str,
    processing_status: str,
    processing_error: str | None,
) -> dict:
    recording = get_recording_or_404(db, meeting, recording_id)
    recording.processing_status = processing_status
    recording.processing_error = processing_error
    db.commit()
    db.refresh(recording)
    return _serialize_recording(recording)
