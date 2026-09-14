from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from sqlalchemy.orm import Session

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
    list_meeting_recordings,
    update_recording_status,
)
from app.services.storage_service import StorageService, get_storage_service


router = APIRouter(prefix="/meetings/{meeting_id}/recordings", tags=["recordings"])


from fastapi import BackgroundTasks

@router.post("", response_model=RecordingUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_meeting_recording(
    background_tasks: BackgroundTasks,
    duration_seconds: int | None = Form(default=None),
    file: UploadFile = File(...),
    meeting: Meeting = Depends(require_meeting_host),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    storage: StorageService = Depends(get_storage_service),
):
    response = await create_recording_from_upload(
        db,
        meeting=meeting,
        current_user=current_user,
        upload=file,
        duration_seconds=duration_seconds,
        storage=storage,
    )
    
    # Enqueue the meeting intelligence job
    from ai_worker.tasks.pipeline import process_meeting_intelligence
    background_tasks.add_task(process_meeting_intelligence, meeting.public_id)
    
    return response


@router.get("", response_model=list[RecordingResponse])
def get_meeting_recordings(
    meeting: Meeting = Depends(get_meeting_and_authorize),
    db: Session = Depends(get_db),
):
    return list_meeting_recordings(db, meeting)


@router.post("/{recording_id}/signed-url", response_model=SignedRecordingUrlResponse)
def get_recording_signed_url(
    recording_id: str,
    meeting: Meeting = Depends(get_meeting_and_authorize),
    db: Session = Depends(get_db),
    storage: StorageService = Depends(get_storage_service),
):
    return create_recording_signed_url(
        db,
        meeting=meeting,
        recording_id=recording_id,
        storage=storage,
    )


@router.patch("/{recording_id}/status", response_model=RecordingResponse)
def update_meeting_recording_status(
    recording_id: str,
    payload: RecordingStatusUpdateRequest,
    meeting: Meeting = Depends(require_meeting_host),
    db: Session = Depends(get_db),
):
    return update_recording_status(
        db,
        meeting=meeting,
        recording_id=recording_id,
        processing_status=payload.processing_status,
        processing_error=payload.processing_error,
    )
