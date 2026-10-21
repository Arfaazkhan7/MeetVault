import logging
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import HTTPException, UploadFile, status
import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.runtime import IS_WORKERS
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


def _sanitize_storage_path(path: str | None) -> str:
    """Sanitize storage path for safe logging without exposing query tokens or signatures."""
    if not path:
        return "none"
    clean_path = path.split("?")[0].split("#")[0]
    parts = clean_path.split("/")
    if len(parts) > 2:
        return f"{parts[0]}/.../{parts[-1]}"
    return clean_path


def _to_utc_aware(dt: datetime | None) -> datetime | None:
    """Normalize naive or aware datetime to UTC-aware datetime for safe comparisons."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


_orphan_cleanup_lock = threading.Lock()


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
        "is_audio_purged": getattr(recording, "is_audio_purged", False),
        "audio_purged_at": getattr(recording, "audio_purged_at", None),
        "retention_policy": getattr(recording, "retention_policy", "ephemeral_transcript_only"),
        "cleanup_error": getattr(recording, "cleanup_error", None),
        "cleanup_retry_count": getattr(recording, "cleanup_retry_count", 0),
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
    try:
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
    except Exception as exc:
        logger.error(
            "[RECORDING_DISPATCH_FAILED] AI job enqueue failed for recording_id=%s: %s. Initiating emergency audio purge.",
            recording.id,
            exc,
        )
        recording.processing_status = RecordingProcessingStatus.FAILED.value
        recording.processing_error = f"AI job dispatch failed: {exc}"
        meeting.transcription_status = "failed"
        meeting.transcription_error = recording.processing_error
        db.commit()
        purge_recording_audio(db, recording, storage)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Recording saved but AI processing dispatch failed: {exc}",
        )


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
            if IS_WORKERS:
                from workers import env
                from pyodide.ffi import run_sync
                run_sync(env.AI_JOBS.send({"job_id": job_id}))
                return
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
    if getattr(recording, "is_audio_purged", False) or not recording.storage_path:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Audio recording has been permanently purged in accordance with zero-retention transcript policy. Only transcript text is durably stored.",
        )
    expires = settings.RECORDING_SIGNED_URL_EXPIRE_SECONDS
    return {
        "recording_id": str(recording.id),
        "url": storage.create_signed_url(
            path=recording.storage_path,
            expires_in_seconds=expires,
        ),
        "expires_in_seconds": expires,
    }


def purge_recording_audio(
    db: Session,
    recording: MeetingRecording,
    storage: StorageService,
    reason: str = "manual_or_event",
) -> bool:
    """
    Purge meeting audio artifact permanently from storage and clear reference from database.
    Enforces MeetVault's strict zero-retention policy for meeting audio.
    CRITICAL: Only marks is_audio_purged = True and clears storage_path when deletion is verified.
    If deletion fails, retains storage_path and records cleanup_error for bounded retry.
    """
    if recording.is_audio_purged:
        return True

    purged = False
    if recording.storage_path:
        path = recording.storage_path
        deletion_confirmed = False
        cleanup_err = None
        try:
            res = storage.delete_private_file(path=path)
            if res is True:
                deletion_confirmed = True
            elif hasattr(storage, "file_exists") and not storage.file_exists(path=path):
                # Object is confirmed gone (idempotent / already deleted)
                deletion_confirmed = True
            else:
                cleanup_err = "Storage provider reported deletion failure (returned False)"
        except Exception as exc:
            cleanup_err = f"Storage deletion exception: {exc}"

        if deletion_confirmed:
            purged = True
            recording.storage_path = None
            recording.is_audio_purged = True
            recording.audio_purged_at = datetime.now(timezone.utc)
            recording.cleanup_error = None
            logger.info(
                "[AUDIO_PURGED] Verified removal of audio artifact for recording_id=%s path=%s reason=%s",
                recording.id,
                _sanitize_storage_path(path),
                reason,
            )
        else:
            purged = False
            recording.cleanup_error = cleanup_err
            recording.cleanup_retry_count = (getattr(recording, "cleanup_retry_count", 0) or 0) + 1
            logger.warning(
                "[AUDIO_PURGE_ERROR] Could not delete audio for recording_id=%s path=%s: %s",
                recording.id,
                _sanitize_storage_path(path),
                cleanup_err,
            )
    else:
        recording.is_audio_purged = True
        purged = True

    # Clear meeting.recording_url only if no other active unpurged recording exists for this meeting
    meeting = db.query(Meeting).filter(Meeting.public_id == recording.meeting_id).first()
    if meeting and meeting.recording_url:
        other_active = (
            db.query(MeetingRecording)
            .filter(
                MeetingRecording.meeting_id == meeting.public_id,
                MeetingRecording.id != recording.id,
                MeetingRecording.deleted_at.is_(None),
                MeetingRecording.storage_path.isnot(None),
                MeetingRecording.is_audio_purged.is_(False),
            )
            .first()
        )
        if not other_active:
            meeting.recording_url = None
        elif other_active.storage_path:
            meeting.recording_url = other_active.storage_path

    db.commit()
    db.refresh(recording)
    return purged


def reconcile_and_purge_orphaned_audio(
    db: Session,
    storage: StorageService,
    company_id: str | None = None,
    max_age_minutes: int = 15,
    max_retries: int = 5,
) -> dict:
    """
    Reconciliation mechanism to discover and purge orphaned audio objects.
    Targets recordings under ephemeral_transcript_only retention policy that:
      - Still have a storage_path
      - Have is_audio_purged == False
      - Have completed/failed processing, missing AI jobs, or have timed out beyond max_age_minutes
    Enforces:
      - Unambiguous recording-to-job matching (never newest meeting-level job)
      - Active recording and active job preservation (never delete in-flight audio)
      - Company/tenant isolation
      - Concurrency safety with thread locking and row-level locking where supported
      - Bounded retries and sanitized logging
    """
    with _orphan_cleanup_lock:
        now = datetime.now(timezone.utc)
        threshold = now - timedelta(minutes=max_age_minutes)

        query = (
            db.query(MeetingRecording)
            .filter(
                MeetingRecording.deleted_at.is_(None),
                MeetingRecording.storage_path.isnot(None),
                MeetingRecording.is_audio_purged.is_(False),
                MeetingRecording.cleanup_retry_count < max_retries,
            )
        )
        if company_id:
            query = query.filter(MeetingRecording.company_id == company_id)

        # Concurrency control: on PostgreSQL, use SELECT FOR UPDATE SKIP LOCKED
        if hasattr(db.bind, "dialect") and getattr(db.bind.dialect, "name", "") == "postgresql":
            query = query.with_for_update(skip_locked=True)

        unpurged_recordings = query.all()

        stats = {
            "scanned": len(unpurged_recordings),
            "purged": 0,
            "failed": 0,
            "skipped_active": 0,
            "skipped_ambiguous": 0,
        }

        for rec in unpurged_recordings:
            # Check idempotency: could have been purged concurrently
            try:
                db.refresh(rec)
            except Exception:
                continue

            if rec.is_audio_purged or not rec.storage_path:
                continue

            retention_policy = getattr(rec, "retention_policy", "ephemeral_transcript_only") or "ephemeral_transcript_only"
            if retention_policy != "ephemeral_transcript_only":
                logger.info(
                    "[ORPHAN_RECONCILE_SKIP] recording_id=%s tenant=%s retention_policy=%s != ephemeral",
                    rec.id,
                    rec.company_id or "personal",
                    retention_policy,
                )
                continue

            # Active recording state check: live meeting actively capturing/finalizing
            if rec.processing_status in (
                RecordingProcessingStatus.STARTING.value,
                RecordingProcessingStatus.RECORDING.value,
                RecordingProcessingStatus.FINALIZING.value,
            ):
                stats["skipped_active"] += 1
                logger.info(
                    "[ORPHAN_RECONCILE_SKIP_ACTIVE] recording_id=%s meeting_id=%s status=%s is in active capture/finalization",
                    rec.id,
                    rec.meeting_id,
                    rec.processing_status,
                )
                continue

            # ── Step 1: Unambiguous Job Matching for this Recording ───────────────
            matching_jobs: list[AIJob] = []

            # 1a. Explicit reference via ai_job_id column
            if getattr(rec, "ai_job_id", None):
                job_by_id = db.query(AIJob).filter(AIJob.public_id == rec.ai_job_id).first()
                if job_by_id:
                    matching_jobs.append(job_by_id)

            # 1b. Direct foreign reference via AIJob.recording_id
            jobs_by_rec = db.query(AIJob).filter(AIJob.recording_id == str(rec.id)).all()
            for j in jobs_by_rec:
                if j not in matching_jobs:
                    matching_jobs.append(j)

            should_purge = False
            purge_reason = "unknown"
            rec_created = _to_utc_aware(rec.created_at)

            if matching_jobs:
                # Check for any active in-flight processing jobs for THIS recording
                active_jobs = [j for j in matching_jobs if j.status in ("QUEUED", "RUNNING", "PROCESSING")]
                if active_jobs:
                    stats["skipped_active"] += 1
                    logger.info(
                        "[ORPHAN_RECONCILE_SKIP_ACTIVE_JOB] recording_id=%s has active job(s): %s",
                        rec.id,
                        [j.public_id for j in active_jobs],
                    )
                    continue

                completed_jobs = [j for j in matching_jobs if j.status == "COMPLETED"]
                failed_jobs = [j for j in matching_jobs if j.status == "FAILED"]

                if completed_jobs:
                    # Associated job successfully completed: zero-retention purge required
                    should_purge = True
                    purge_reason = "associated_job_completed"
                elif failed_jobs:
                    # Check if any failed job is still eligible for automatic retry and within timeout
                    retriable_jobs = [j for j in failed_jobs if j.retry_count < j.max_retries]
                    if retriable_jobs and (rec_created and rec_created > threshold):
                        stats["skipped_active"] += 1
                        logger.info(
                            "[ORPHAN_RECONCILE_SKIP_RETRIABLE] recording_id=%s has retriable failed job(s)",
                            rec.id,
                        )
                        continue
                    else:
                        should_purge = True
                        purge_reason = "associated_job_failed_exhausted"
            else:
                # ── Step 2: No Explicit Job Link Found ────────────────────────────
                # Inspect other recordings in the same meeting
                sibling_recordings = (
                    db.query(MeetingRecording)
                    .filter(
                        MeetingRecording.meeting_id == rec.meeting_id,
                        MeetingRecording.id != rec.id,
                        MeetingRecording.deleted_at.is_(None),
                    )
                    .all()
                )

                if sibling_recordings:
                    # Multiple recordings in meeting: NEVER assume a meeting-level job belongs to this recording
                    if rec.processing_status == RecordingProcessingStatus.FAILED.value:
                        should_purge = True
                        purge_reason = "recording_status_failed_no_job"
                    else:
                        stats["skipped_ambiguous"] += 1
                        logger.warning(
                            "[ORPHAN_RECONCILE_SKIP_AMBIGUOUS] recording_id=%s meeting_id=%s has %d sibling recordings and no explicit AIJob link",
                            rec.id,
                            rec.meeting_id,
                            len(sibling_recordings),
                        )
                        continue
                else:
                    # Single recording in meeting with no explicit job link
                    # Check if there is an active meeting-level job
                    meeting_active_jobs = (
                        db.query(AIJob)
                        .filter(
                            AIJob.meeting_id == rec.meeting_id,
                            AIJob.status.in_(["QUEUED", "RUNNING", "PROCESSING"]),
                        )
                        .all()
                    )
                    if meeting_active_jobs:
                        stats["skipped_active"] += 1
                        logger.info(
                            "[ORPHAN_RECONCILE_SKIP_MEETING_ACTIVE_JOB] recording_id=%s meeting_id=%s has active meeting job",
                            rec.id,
                            rec.meeting_id,
                        )
                        continue

                    if rec.processing_status in (
                        RecordingProcessingStatus.COMPLETED.value,
                        RecordingProcessingStatus.FAILED.value,
                    ):
                        should_purge = True
                        purge_reason = f"recording_status_{rec.processing_status.lower()}"
                    elif rec_created and rec_created <= threshold:
                        should_purge = True
                        purge_reason = "stalled_abandoned_orphan"
                    else:
                        stats["skipped_active"] += 1
                        continue

            if should_purge:
                logger.info(
                    "[ORPHAN_RECONCILE_PURGE] recording_id=%s meeting_id=%s tenant=%s reason=%s path=%s",
                    rec.id,
                    rec.meeting_id,
                    rec.company_id or "personal",
                    purge_reason,
                    _sanitize_storage_path(rec.storage_path),
                )
                success = purge_recording_audio(db, rec, storage)
                if success:
                    stats["purged"] += 1
                else:
                    stats["failed"] += 1

        return stats


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


def retrieve_egress_media(file_info: dict) -> tuple[bytes, str]:
    """
    Retrieve egress output media using the configured output mechanism.
    Supports:
      1. In-memory / direct payload content (file_bytes or content) for testing & direct workers.
      2. Local filesystem path if location or filename exists on disk.
      3. Secure HTTP/HTTPS download if location is an explicit pre-signed/cloud URL provided by egress.
      4. S3 object retrieval if location starts with s3:// or if S3_BUCKET is configured.
    Never assumes filename is a publicly accessible URL or invents endpoints.
    """
    # 1. Direct content provided (e.g. testing or multipart injection)
    if "content" in file_info and isinstance(file_info["content"], bytes) and len(file_info["content"]) > 0:
        content_type = "video/mp4" if str(file_info.get("filename", "")).endswith(".mp4") else "audio/webm"
        return file_info["content"], content_type
    if "file_bytes" in file_info and isinstance(file_info["file_bytes"], bytes) and len(file_info["file_bytes"]) > 0:
        content_type = "video/mp4" if str(file_info.get("filename", "")).endswith(".mp4") else "audio/webm"
        return file_info["file_bytes"], content_type

    filename = str(file_info.get("filename") or "").strip()
    location = str(file_info.get("location") or "").strip()
    content_type = "video/mp4" if filename.endswith(".mp4") or location.endswith(".mp4") else "audio/webm"

    # 2. Local filesystem check
    for cand in (location, filename):
        if cand:
            try:
                p = Path(cand)
                if p.is_file():
                    data = p.read_bytes()
                    if data:
                        return data, content_type
            except Exception:
                pass

    # 3. Explicit HTTP / HTTPS pre-signed cloud URL provided by LiveKit/cloud storage in location
    if location.startswith("http://") or location.startswith("https://"):
        try:
            resp = httpx.get(location, timeout=120)
            resp.raise_for_status()
            if resp.content:
                return resp.content, content_type
        except Exception as exc:
            raise RuntimeError(f"Failed downloading egress media from location URL: {exc}") from exc

    # 4. S3 URI or configured S3 bucket
    s3_bucket = None
    s3_key = None
    if location.startswith("s3://"):
        parts = location[5:].split("/", 1)
        s3_bucket = parts[0]
        s3_key = parts[1] if len(parts) > 1 else ""
    elif settings.S3_BUCKET and filename:
        s3_bucket = settings.S3_BUCKET
        s3_key = filename

    if s3_bucket and s3_key:
        try:
            import boto3

            boto_kwargs = {}
            if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
                boto_kwargs["aws_access_key_id"] = settings.AWS_ACCESS_KEY_ID
                boto_kwargs["aws_secret_access_key"] = settings.AWS_SECRET_ACCESS_KEY
            if settings.AWS_REGION:
                boto_kwargs["region_name"] = settings.AWS_REGION

            s3_client = boto3.client("s3", **boto_kwargs)
            obj = s3_client.get_object(Bucket=s3_bucket, Key=s3_key)
            data = obj["Body"].read()
            if data:
                return data, content_type
        except Exception as exc:
            raise RuntimeError(f"Failed retrieving egress media from S3 (bucket={s3_bucket}, key={s3_key}): {exc}") from exc

    raise FileNotFoundError(
        f"Egress output media could not be located via configured output mechanisms (filename='{filename}', location='{location}')"
    )


async def handle_livekit_webhook_event(
    db: Session,
    event_payload: dict,
    storage: StorageService,
) -> dict:
    """
    Handle verified LiveKit webhook events (egress_ended, room_finished, etc.).
    Automatically finalizes egress recording artifacts, uploads to private storage,
    persists storage_path, and dispatches AI jobs safely.
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

        # Idempotency check: duplicate webhook events
        if (
            recording.processing_status in [
                RecordingProcessingStatus.QUEUED.value,
                RecordingProcessingStatus.PROCESSING.value,
                RecordingProcessingStatus.COMPLETED.value,
            ]
            and (recording.storage_path or recording.is_audio_purged)
        ):
            logger.info(
                "[LIVEKIT_WEBHOOK_DUPLICATE_IGNORED] egress_id=%s already finalized with status=%s storage_path=%s purged=%s",
                egress_id,
                recording.processing_status,
                recording.storage_path,
                recording.is_audio_purged,
            )
            return {
                "status": "already_processed",
                "recording_id": str(recording.id),
                "storage_path": recording.storage_path,
            }

        # Check if egress execution failed
        if status_val in ("EGRESS_FAILED", "FAILED", 3):
            recording.processing_status = RecordingProcessingStatus.FAILED.value
            recording.processing_error = error_msg or "LiveKit egress execution failed"
            if meeting:
                meeting.transcription_status = "failed"
                meeting.transcription_error = recording.processing_error
            db.commit()
            logger.error("[LIVEKIT_EGRESS_FAILED] egress_id=%s error=%s", egress_id, recording.processing_error)
            return {"status": "failed", "recording_id": str(recording.id), "error": recording.processing_error}

        file_results = egress_info.get("file_results") or []
        if not file_results:
            recording.processing_status = RecordingProcessingStatus.FAILED.value
            recording.processing_error = "LiveKit egress completed but produced no output files"
            if meeting:
                meeting.transcription_status = "failed"
                meeting.transcription_error = recording.processing_error
            db.commit()
            logger.error("[LIVEKIT_EGRESS_NO_FILES] egress_id=%s", egress_id)
            return {"status": "failed", "recording_id": str(recording.id), "error": recording.processing_error}

        first_file = file_results[0]
        filename = first_file.get("filename") or f"meeting-{recording.meeting_id}.mp4"
        duration = first_file.get("duration") or egress_info.get("duration")
        duration_seconds = int(duration / 1_000_000_000) if duration and duration > 1000000 else (duration or None)

        # Retrieve egress output media from configured output mechanism
        try:
            content_bytes, content_type = retrieve_egress_media(first_file)
        except Exception as exc:
            recording.processing_status = RecordingProcessingStatus.FAILED.value
            recording.processing_error = f"Egress media retrieval failed: {exc}"
            if meeting:
                meeting.transcription_status = "failed"
                meeting.transcription_error = recording.processing_error
            db.commit()
            logger.error("[LIVEKIT_EGRESS_RETRIEVAL_FAILED] egress_id=%s error=%s", egress_id, exc)
            return {"status": "failed", "recording_id": str(recording.id), "error": recording.processing_error}

        # Upload audio to private storage
        uploader = db.query(User).filter(User.public_id == recording.uploaded_by_user_id).first()
        uploader_ref = uploader or User(public_id="system")
        storage_path = _recording_storage_path(
            meeting or Meeting(public_id=recording.meeting_id),
            uploader_ref,
            filename,
        )

        try:
            stored = storage.upload_private_file(
                path=storage_path,
                content=content_bytes,
                content_type=content_type,
            )
        except Exception as exc:
            recording.processing_status = RecordingProcessingStatus.FAILED.value
            recording.processing_error = f"Private storage upload failed: {exc}"
            if meeting:
                meeting.transcription_status = "failed"
                meeting.transcription_error = recording.processing_error
            db.commit()
            logger.error("[LIVEKIT_EGRESS_STORAGE_FAILED] egress_id=%s error=%s", egress_id, exc)
            return {"status": "failed", "recording_id": str(recording.id), "error": recording.processing_error}

        # Persist storage path and finalized recording metadata
        recording.storage_backend = stored.backend
        recording.storage_bucket = stored.bucket
        recording.storage_path = stored.path
        recording.original_filename = filename
        recording.file_type = content_type
        recording.duration_seconds = duration_seconds
        recording.file_size_bytes = len(content_bytes)
        recording.processing_status = RecordingProcessingStatus.QUEUED.value
        recording.processing_error = None

        if meeting:
            meeting.recording_url = stored.path
            meeting.transcription_status = "queued"
            meeting.analysis_status = "queued"

        db.commit()
        db.refresh(recording)

        # Enqueue AI Job ONLY after storage_path is committed
        if uploader:
            try:
                job = get_or_create_recording_ai_job(
                    db,
                    recording=recording,
                    requested_by=uploader,
                    provider=settings.LLM_PROVIDER,
                )
                db.commit()
                _enqueue_ai_job(db, job.public_id)
                logger.info(
                    "[LIVEKIT_EGRESS_FINALIZED_AND_DISPATCHED] recording_id=%s ai_job_id=%s storage_path=%s",
                    recording.id,
                    job.public_id,
                    recording.storage_path,
                )
            except Exception as exc:
                logger.error(
                    "[LIVEKIT_EGRESS_DISPATCH_FAILED] Failed to enqueue AI job for recording_id=%s: %s. Initiating emergency audio purge.",
                    recording.id,
                    exc,
                )
                recording.processing_status = RecordingProcessingStatus.FAILED.value
                recording.processing_error = f"AI job dispatch failed: {exc}"
                if meeting:
                    meeting.transcription_status = "failed"
                    meeting.transcription_error = recording.processing_error
                db.commit()
                purge_recording_audio(db, recording, storage)
                return {
                    "status": "failed",
                    "recording_id": str(recording.id),
                    "error": recording.processing_error,
                }
        else:
            logger.error("[LIVEKIT_EGRESS_NO_UPLOADER] Cannot dispatch AI job without uploader for recording_id=%s", recording.id)
            recording.processing_status = RecordingProcessingStatus.FAILED.value
            recording.processing_error = "Recording uploader user not found, cannot dispatch AI job"
            if meeting:
                meeting.transcription_status = "failed"
                meeting.transcription_error = recording.processing_error
            db.commit()
            purge_recording_audio(db, recording, storage)
            return {
                "status": "failed",
                "recording_id": str(recording.id),
                "error": recording.processing_error,
            }

        return {"status": "processed", "recording_id": str(recording.id), "storage_path": stored.path}

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

