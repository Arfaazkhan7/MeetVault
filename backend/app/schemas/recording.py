from datetime import datetime
from typing import Optional

from pydantic import BaseModel, field_validator


class RecordingUploadResponse(BaseModel):
    id: str
    meeting_id: str
    company_id: Optional[str] = None
    uploaded_by_user_id: str
    storage_backend: str = "supabase"
    storage_bucket: Optional[str] = None
    storage_path: Optional[str] = None
    original_filename: Optional[str] = None
    file_type: Optional[str] = None
    file_size_bytes: Optional[int] = 0
    duration_seconds: Optional[int] = None
    processing_status: str
    ai_job_id: Optional[str] = None
    session_id: Optional[str] = None
    egress_id: Optional[str] = None
    source: Optional[str] = None
    is_audio_purged: bool = False
    audio_purged_at: Optional[datetime] = None
    retention_policy: Optional[str] = "ephemeral_transcript_only"
    created_at: datetime
    model_config = {"from_attributes": True}


class RecordingResponse(RecordingUploadResponse):
    processing_error: Optional[str] = None


class SignedRecordingUrlResponse(BaseModel):
    recording_id: str
    url: str
    expires_in_seconds: int


class RecordingStatusUpdateRequest(BaseModel):
    processing_status: str
    processing_error: Optional[str] = None

    @field_validator("processing_status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        allowed = {"STARTING", "RECORDING", "FINALIZING", "UPLOADED", "QUEUED", "PROCESSING", "COMPLETED", "FAILED"}
        if value not in allowed:
            raise ValueError("Invalid processing status")
        return value
