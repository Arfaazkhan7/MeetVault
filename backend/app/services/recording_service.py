import logging
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import HTTPException, UploadFile, status
import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.enums import RecordingProcessingStatus
from app.models.ai_job import AIJob
from app.models.meeting import Meeting
from app.models.recording import MeetingRecording
from app.models.user import User
from app.services.ai_job_service import get_or_create_recording_ai_job, mark_ai_job_failed
from app.services.storage_service import StorageService

logger = logging.getLogger("recording_service")


ALLOWED_RECORDING_TYPES = {
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/opus": ".opus",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/mp4": ".m4a",
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
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
        "file_size_bytes": recording.file_size_bytes or 0,
        "duration_seconds": recording.duration_seconds,
        "processing_status": recording.processing_status,
        "processing_error": recording.processing_error,
        "session_id": getattr(recording, "session_id", None),
        "egress_id": getattr(recording, "egress_id", None),
        "source": getattr(recording, "source", None),
        "ai_job_id": getattr(recording, "ai_job_id", None),
        "created_at": recording.created_at,
    }


async def start_automatic_recording_session(
    db: Session,
    *,
    meeting: Meeting,
    current_user: User,
) -> dict:
    """
    Initiate an automatic recording lifecycle session for a meeting.
    Idempotent: returns existing active recording if already in STARTING or RECORDING status.
    """
    logger.info(
        "[RECORDING_START_REQUEST] meeting_id=%s user_id=%s",
        meeting.public_id,
        current_user.public_id,
    )

    # Check for existing active recording session
    active_rec = (
        db.query(MeetingRecording)
        .filter(
            MeetingRecording.meeting_id == meeting.public_id,
            MeetingRecording.deleted_at.is_(None),
            MeetingRecording.processing_status.in_([
                RecordingProcessingStatus.STARTING.value,
                RecordingProcessingStatus.RECORDING.value,
            ]),
        )
        .first()
    )
    if active_rec:
        logger.info(
            "[RECORDING_SESSION_REUSED] id=%s session_id=%s status=%s",
            active_rec.id,
            active_rec.session_id,
            active_rec.processing_status,
        )
        return _serialize_recording(active_rec)

    session_id = f"REC-SESS-{uuid4().hex[:12]}"
    source = "client_mixed_audio"
    egress_id = None

    # Attempt LiveKit server-side egress if configured
    try:
        from app.services.livekit_service import room_name_for_meeting, start_room_composite_audio_egress
        room_name = room_name_for_meeting(meeting)
        output_file = f"meeting-{meeting.public_id}-{session_id}.mp4"
        egress_id, egress_err = await start_room_composite_audio_egress(room_name, output_file)
        if egress_id:
            source = "livekit_egress"
            logger.info("[LIVEKIT_EGRESS_STARTED] egress_id=%s room=%s", egress_id, room_name)
        elif egress_err:
            logger.info("[LIVEKIT_EGRESS_SKIPPED] %s - falling back to client mixed audio capture", egress_err)
    except Exception as exc:
        logger.warning("[LIVEKIT_EGRESS_EXCEPTION] %s - using client mixed audio capture", exc)

    recording = MeetingRecording(
        meeting_id=meeting.public_id,
        company_id=meeting.company_id,
        uploaded_by_user_id=current_user.public_id,
        session_id=session_id,
        egress_id=egress_id,
        source=source,
        storage_backend="supabase",
        storage_bucket=settings.SUPABASE_STORAGE_BUCKET,
        storage_path=None,
        original_filename=f"meeting-{meeting.public_id}.webm",
        file_type="audio/webm",
        file_size_bytes=0,
        duration_seconds=None,
        processing_status=RecordingProcessingStatus.RECORDING.value,
    )
    db.add(recording)
    db.commit()
    db.refresh(recording)

    logger.info(
        "[RECORDING_SESSION_INITIALIZED] id=%s session_id=%s source=%s",
        recording.id,
        session_id,
        source,
    )
    return _serialize_recording(recording)


async def stop_automatic_recording_session(
    db: Session,
    *,
    meeting: Meeting,
    current_user: User,
    session_id: str | None = None,
) -> dict:
    """
    Signal recording stop and transition status to FINALIZING.
    Stops LiveKit Egress if running.
    """
    logger.info(
        "[RECORDING_STOP_REQUEST] meeting_id=%s user_id=%s session_id=%s",
        meeting.public_id,
        current_user.public_id,
        session_id,
    )

    query = db.query(MeetingRecording).filter(
        MeetingRecording.meeting_id == meeting.public_id,
        MeetingRecording.deleted_at.is_(None),
    )
    if session_id:
        query = query.filter(MeetingRecording.session_id == session_id)
    else:
        query = query.filter(
            MeetingRecording.processing_status.in_([
                RecordingProcessingStatus.STARTING.value,
                RecordingProcessingStatus.RECORDING.value,
            ])
        )

    recording = query.first()
    if not recording:
        # If no active recording in STARTING/RECORDING, check for already finalizing or queued
        latest = (
            db.query(MeetingRecording)
            .filter(
                MeetingRecording.meeting_id == meeting.public_id,
                MeetingRecording.deleted_at.is_(None),
            )
            .order_by(MeetingRecording.created_at.desc())
            .first()
        )
        if latest:
            return _serialize_recording(latest)
        raise HTTPException(status_code=404, detail="No active recording session found for this meeting")

    # Stop LiveKit egress if this session used server egress
    if recording.egress_id:
        try:
            from app.services.livekit_service import stop_livekit_egress
            await stop_livekit_egress(recording.egress_id)
            logger.info("[LIVEKIT_EGRESS_STOPPED] egress_id=%s", recording.egress_id)
        except Exception as exc:
            logger.warning("[LIVEKIT_EGRESS_STOP_ERROR] %s", exc)

    recording.processing_status = RecordingProcessingStatus.FINALIZING.value
    db.commit()
    db.refresh(recording)

    logger.info("[RECORDING_STATUS_FINALIZING] id=%s meeting_id=%s", recording.id, meeting.public_id)
    return _serialize_recording(recording)


async def finalize_recording(
    db: Session,
    *,
    meeting: Meeting,
    current_user: User,
    content: bytes,
    filename: str,
    content_type: str,
    duration_seconds: int | None,
    storage: StorageService,
    session_id: str | None = None,
    source: str = "client_mixed_audio",
) -> dict:
    """
    Core recording finalization pipeline:
    1. Validation: content non-empty, type allowed, size within bounds.
    2. Idempotency: prevents duplicate uploads / duplicate AI jobs.
    3. Storage: persists durably into private storage bucket.
    4. Database: updates MeetingRecording and Meeting models.
    5. Automatic Transcription Job Dispatch: creates AIJob and enqueues it.
    """
    # ── 1. Media Validation ────────────────────────────────────────────────
    if not content or len(content) == 0:
        logger.error("[FINALIZATION_ERROR] Empty recording content for meeting_id=%s", meeting.public_id)
        raise HTTPException(status_code=400, detail="Recording file is empty")

    if content_type not in ALLOWED_RECORDING_TYPES:
        logger.error("[FINALIZATION_ERROR] Unsupported content-type '%s' for meeting_id=%s", content_type, meeting.public_id)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported recording file type",
        )

    if len(content) > settings.MAX_RECORDING_UPLOAD_BYTES:
        logger.error("[FINALIZATION_ERROR] Recording exceeds limit (%d > %d)", len(content), settings.MAX_RECORDING_UPLOAD_BYTES)
        raise HTTPException(status_code=413, detail="Recording file is too large")

    # Normalize duration (minimum 1 second if provided)
    if duration_seconds is not None:
        duration_seconds = max(1, duration_seconds)

    # ── 2. Idempotency & Deduplication ─────────────────────────────────────
    # If a recording is already queued/processing/completed for this exact session,
    # or an active recording exists with matching size/duration, avoid duplicate dispatch.
    existing_job_recording = (
        db.query(MeetingRecording)
        .filter(
            MeetingRecording.meeting_id == meeting.public_id,
            MeetingRecording.deleted_at.is_(None),
            MeetingRecording.processing_status.in_([
                RecordingProcessingStatus.QUEUED.value,
                RecordingProcessingStatus.PROCESSING.value,
                RecordingProcessingStatus.COMPLETED.value,
            ]),
        )
        .order_by(MeetingRecording.created_at.desc())
        .first()
    )

    if session_id:
        existing_by_session = (
            db.query(MeetingRecording)
            .filter(
                MeetingRecording.session_id == session_id,
                MeetingRecording.processing_status.in_([
                    RecordingProcessingStatus.QUEUED.value,
                    RecordingProcessingStatus.PROCESSING.value,
                    RecordingProcessingStatus.COMPLETED.value,
                ]),
            )
            .first()
        )
        if existing_by_session:
            logger.info(
                "[DUPLICATE_FINALIZATION_IGNORED] Session %s already finalized (id=%s)",
                session_id,
                existing_by_session.id,
            )
            existing_job = (
                db.query(AIJob)
                .filter(AIJob.recording_id == str(existing_by_session.id))
                .first()
            )
            payload = _serialize_recording(existing_by_session)
            if existing_job:
                payload["ai_job_id"] = existing_job.public_id
            return payload

    # ── 3. Find or Create Recording Entity ─────────────────────────────────
    recording = None
    if session_id:
        recording = (
            db.query(MeetingRecording)
            .filter(
                MeetingRecording.session_id == session_id,
                MeetingRecording.deleted_at.is_(None),
            )
            .first()
        )
    if not recording:
        # Check if an active session in RECORDING or FINALIZING exists for this meeting
        recording = (
            db.query(MeetingRecording)
            .filter(
                MeetingRecording.meeting_id == meeting.public_id,
                MeetingRecording.deleted_at.is_(None),
                MeetingRecording.processing_status.in_([
                    RecordingProcessingStatus.RECORDING.value,
                    RecordingProcessingStatus.FINALIZING.value,
                ]),
            )
            .first()
        )

    # ── 4. Upload to Durable Private Storage ──────────────────────────────
    storage_path = _recording_storage_path(meeting, current_user, filename or "meeting-recording.webm")
    try:
        stored = storage.upload_private_file(
            path=storage_path,
            content=content,
            content_type=content_type,
        )
    except Exception as exc:
        logger.error("[STORAGE_UPLOAD_ERROR] Failed uploading recording to storage: %s", exc)
        if recording:
            recording.processing_status = RecordingProcessingStatus.FAILED.value
            recording.processing_error = f"Storage upload failed: {exc}"
            db.commit()
        raise HTTPException(status_code=500, detail=f"Failed to store recording artifact: {exc}")

    # ── 5. Persist Recording Metadata ─────────────────────────────────────
    if not recording:
        recording = MeetingRecording(
            meeting_id=meeting.public_id,
            company_id=meeting.company_id,
            uploaded_by_user_id=current_user.public_id,
            session_id=session_id or f"REC-AUTO-{uuid4().hex[:10]}",
            source=source,
        )
        db.add(recording)

    recording.storage_backend = stored.backend
    recording.storage_bucket = stored.bucket
    recording.storage_path = stored.path
    recording.original_filename = filename or "recording.webm"
    recording.file_type = content_type
    recording.file_size_bytes = len(content)
    recording.duration_seconds = duration_seconds
    recording.processing_status = RecordingProcessingStatus.QUEUED.value
    recording.processing_error = None

    meeting.recording_url = stored.path
    meeting.transcription_status = "queued"
    meeting.analysis_status = "queued"

    db.flush()

    # ── 6. Automatic Transcription Job Dispatch ───────────────────────────
    job = get_or_create_recording_ai_job(
        db,
        recording=recording,
        requested_by=current_user,
        provider=settings.LLM_PROVIDER,
    )
    db.commit()
    db.refresh(recording)

    _enqueue_ai_job(db, job.public_id)

    logger.info(
        "[RECORDING_FINALIZED_AND_DISPATCHED] recording_id=%s meeting_id=%s ai_job_id=%s bytes=%d duration=%s",
        recording.id,
        meeting.public_id,
        job.public_id,
        recording.file_size_bytes,
        recording.duration_seconds,
    )

    payload = _serialize_recording(recording)
    payload["ai_job_id"] = job.public_id
    return payload


async def create_recording_from_upload(
    db: Session,
    *,
    meeting: Meeting,
    current_user: User,
    upload: UploadFile,
    duration_seconds: int | None,
    storage: StorageService,
    session_id: str | None = None,
) -> dict:
    """
    Standard upload endpoint handler, delegating to finalize_recording.
    Preserves exact backward compatibility with existing tests and clients.
    """
    content_type = upload.content_type or "application/octet-stream"
    content = await upload.read()
    filename = upload.filename or "recording.webm"

    return await finalize_recording(
        db,
        meeting=meeting,
        current_user=current_user,
        content=content,
        filename=filename,
        content_type=content_type,
        duration_seconds=duration_seconds,
        storage=storage,
        session_id=session_id,
        source="client_mixed_audio",
    )


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


async def handle_livekit_webhook_event(
    db: Session,
    event_payload: dict,
    storage: StorageService,
) -> dict:
    """
    Handle verified LiveKit webhook events (egress_ended, room_finished, etc.).
    Automatically finalizes egress recording artifacts and dispatches AI jobs.
    """
    event_type = event_payload.get("event")
    logger.info("[LIVEKIT_WEBHOOK_EVENT] event=%s", event_type)

    if event_type == "egress_ended":
        egress_info = event_payload.get("egress_info", {})
        egress_id = egress_info.get("egress_id")
        status_val = egress_info.get("status")
        error_msg = egress_info.get("error")

        if not egress_id:
            return {"status": "ignored", "reason": "No egress_id in event"}

        recording = db.query(MeetingRecording).filter(
            MeetingRecording.egress_id == egress_id,
            MeetingRecording.deleted_at.is_(None),
        ).first()

        if not recording:
            logger.warning("[LIVEKIT_WEBHOOK_UNMATCHED] No recording found for egress_id=%s", egress_id)
            return {"status": "unmatched", "egress_id": egress_id}

        meeting = db.query(Meeting).filter(Meeting.public_id == recording.meeting_id).first()

        # Check if egress failed
        if status_val in ("EGRESS_FAILED", "FAILED", 3):
            recording.processing_status = RecordingProcessingStatus.FAILED.value
            recording.processing_error = error_msg or "LiveKit egress execution failed"
            if meeting:
                meeting.transcription_status = "failed"
                meeting.transcription_error = recording.processing_error
            db.commit()
            logger.error("[LIVEKIT_EGRESS_FAILED] egress_id=%s error=%s", egress_id, recording.processing_error)
            return {"status": "failed", "recording_id": str(recording.id), "error": recording.processing_error}

        # Egress succeeded: files output produced
        file_results = egress_info.get("file_results") or []
        first_file = file_results[0] if file_results else {}
        filename = first_file.get("filename") or f"meeting-{recording.meeting_id}.mp4"
        duration = first_file.get("duration") or egress_info.get("duration")
        duration_seconds = int(duration / 1_000_000_000) if duration and duration > 1000000 else (duration or None)

        recording.original_filename = filename
        recording.file_type = "video/mp4" if filename.endswith(".mp4") else "audio/webm"
        recording.duration_seconds = duration_seconds
        recording.file_size_bytes = first_file.get("size") or recording.file_size_bytes or 0
        recording.processing_status = RecordingProcessingStatus.QUEUED.value
        recording.processing_error = None

        if meeting:
            meeting.recording_url = recording.storage_path or filename
            meeting.transcription_status = "queued"
            meeting.analysis_status = "queued"

        # Dispatch AI Job
        uploader = db.query(User).filter(User.public_id == recording.uploaded_by_user_id).first()
        if uploader:
            job = get_or_create_recording_ai_job(
                db,
                recording=recording,
                requested_by=uploader,
                provider=settings.LLM_PROVIDER,
            )
            db.commit()
            _enqueue_ai_job(db, job.public_id)
            logger.info("[LIVEKIT_EGRESS_FINALIZED_AND_DISPATCHED] recording_id=%s ai_job_id=%s", recording.id, job.public_id)

        return {"status": "processed", "recording_id": str(recording.id)}

    elif event_type == "room_finished":
        room = event_payload.get("room", {})
        room_name = room.get("name", "")
        # Extract meeting ID if pattern is meeting-<id>
        if room_name.startswith("meeting-"):
            meeting_id = room_name[len("meeting-"):]
            active_rec = db.query(MeetingRecording).filter(
                MeetingRecording.meeting_id == meeting_id,
                MeetingRecording.processing_status == RecordingProcessingStatus.RECORDING.value,
                MeetingRecording.deleted_at.is_(None),
            ).first()
            if active_rec:
                active_rec.processing_status = RecordingProcessingStatus.FINALIZING.value
                db.commit()
                logger.info("[ROOM_FINISHED_FINALIZING] meeting_id=%s recording_id=%s", meeting_id, active_rec.id)

        return {"status": "processed", "event": "room_finished"}

    return {"status": "ignored", "event": event_type}
