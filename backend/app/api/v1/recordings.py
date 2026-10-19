from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile, status
from sqlalchemy.orm import Session
from typing import Optional

from app.core.dependencies import get_current_user
from app.core.meeting_dependencies import get_meeting_and_authorize, require_meeting_host
from app.db.session import get_db
from app.models.meeting import Meeting
from app.models.user import User
from app.schemas.recording import (
    RecordingResponse,
    RecordingStatusUpdateRequest,
    RecordingUploadResponse,
    SignedRecordingUrlResponse,
)
from app.services.recording_service import (
    create_recording_from_upload,
    create_recording_signed_url,
    handle_livekit_webhook_event,
    list_meeting_recordings,
    start_automatic_recording_session,
    stop_automatic_recording_session,
    update_recording_status,
)
from app.services.storage_service import StorageService, get_storage_service
from app.services.livekit_service import verify_livekit_webhook

router = APIRouter(tags=["recordings"])


# ── Automatic Recording Lifecycle Endpoints ──────────────────────────────

@router.post("/meetings/{meeting_id}/recordings/auto/start", response_model=RecordingUploadResponse, status_code=status.HTTP_200_OK)
async def start_auto_recording(
    meeting: Meeting = Depends(require_meeting_host),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Start automatic recording session for a meeting (Host only).
    Idempotent: returns existing active recording if already recording.
    """
    return await start_automatic_recording_session(
        db,
        meeting=meeting,
        current_user=current_user,
    )


@router.post("/meetings/{meeting_id}/recordings/auto/stop", response_model=RecordingUploadResponse)
async def stop_auto_recording(
    session_id: Optional[str] = None,
    meeting: Meeting = Depends(require_meeting_host),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Stop automatic recording session and transition to FINALIZING (Host only).
    """
    return await stop_automatic_recording_session(
        db,
        meeting=meeting,
        current_user=current_user,
        session_id=session_id,
    )


# ── Recording Upload & Finalization ──────────────────────────────────────

@router.post("/meetings/{meeting_id}/recordings", response_model=RecordingUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_meeting_recording(
    duration_seconds: int | None = Form(default=None),
    session_id: str | None = Form(default=None),
    file: UploadFile = File(...),
    meeting: Meeting = Depends(require_meeting_host),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    storage: StorageService = Depends(get_storage_service),
):
    """
    Finalize meeting recording from captured audio/video media (Host only).
    Durably uploads to private storage, validates media, and automatically dispatches AI transcription.
    """
    response = await create_recording_from_upload(
        db,
        meeting=meeting,
        current_user=current_user,
        upload=file,
        duration_seconds=duration_seconds,
        storage=storage,
        session_id=session_id,
    )
    return response


@router.get("/meetings/{meeting_id}/recordings", response_model=list[RecordingResponse])
def get_meeting_recordings(
    meeting: Meeting = Depends(get_meeting_and_authorize),
    db: Session = Depends(get_db),
):
    """List recordings associated with a meeting (authorized participants only)."""
    return list_meeting_recordings(db, meeting)


@router.post("/meetings/{meeting_id}/recordings/{recording_id}/signed-url", response_model=SignedRecordingUrlResponse)
def get_recording_signed_url(
    recording_id: str,
    meeting: Meeting = Depends(get_meeting_and_authorize),
    db: Session = Depends(get_db),
    storage: StorageService = Depends(get_storage_service),
):
    """Generate time-limited signed URL for playback/download (authorized participants only)."""
    return create_recording_signed_url(
        db,
        meeting=meeting,
        recording_id=recording_id,
        storage=storage,
    )


@router.patch("/meetings/{meeting_id}/recordings/{recording_id}/status", response_model=RecordingResponse)
def update_meeting_recording_status(
    recording_id: str,
    payload: RecordingStatusUpdateRequest,
    meeting: Meeting = Depends(require_meeting_host),
    db: Session = Depends(get_db),
):
    """Update recording processing status (Host only)."""
    return update_recording_status(
        db,
        meeting=meeting,
        recording_id=recording_id,
        processing_status=payload.processing_status,
        processing_error=payload.processing_error,
    )


# ── LiveKit Server-Side Webhook ──────────────────────────────────────────

@router.post("/recordings/livekit-webhook")
async def livekit_webhook(
    request: Request,
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
    storage: StorageService = Depends(get_storage_service),
):
    """
    LiveKit webhook receiver for egress and room events.
    Verifies cryptographic signature using LIVEKIT_API_KEY and LIVEKIT_API_SECRET.
    """
    body_bytes = await request.body()
    try:
        event = verify_livekit_webhook(body_bytes, authorization or "")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid webhook signature: {exc}",
        )

    # Convert event object to dictionary if it's a LiveKit WebhookEvent protobuf/class
    event_dict = {}
    if hasattr(event, "event"):
        event_dict["event"] = getattr(event, "event", "")
    if hasattr(event, "egress_info"):
        e_info = getattr(event, "egress_info")
        event_dict["egress_info"] = {
            "egress_id": getattr(e_info, "egress_id", ""),
            "status": str(getattr(e_info, "status", "")),
            "error": getattr(e_info, "error", None),
        }
    if hasattr(event, "room"):
        rm = getattr(event, "room")
        event_dict["room"] = {"name": getattr(rm, "name", "")}

    return await handle_livekit_webhook_event(db, event_dict, storage)
