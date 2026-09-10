from datetime import datetime
from typing import Optional

from pydantic import BaseModel, field_validator


class RecordingUploadResponse(BaseModel):
    id: str
    meeting_id: str
    company_id: str
    uploaded_by_user_id: str
    storage_backend: str
    storage_bucket: str
    storage_path: str
    original_filename: str
    file_type: str
    file_size_bytes: int
    duration_seconds: Optional[int]
    processing_status: str
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
        allowed = {"UPLOADED", "QUEUED", "PROCESSING", "COMPLETED", "FAILED"}
        if value not in allowed:
            raise ValueError("Invalid processing status")
        return value
