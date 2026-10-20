from typing import Optional, List, Any, Dict
from pydantic import BaseModel, Field


class TranscriptSegmentResponse(BaseModel):
    id: Optional[str] = None
    segment_id: Optional[str] = None
    recording_id: Optional[str] = None
    speaker_label: str
    speaker_user_id: Optional[str] = None
    user_id: Optional[str] = None
    participant_id: Optional[str] = None
    attribution_status: str = "unknown"
    start_time: float
    end_time: float
    text: str
    translated_text: Optional[str] = None
    language: Optional[str] = None
    confidence: Optional[float] = None
    words: Optional[List[Dict[str, Any]]] = None
    user_name: Optional[str] = None
    speaker_confirmed: bool = False
    processing_metadata: Optional[Dict[str, Any]] = None

    model_config = {"from_attributes": True}


class MeetingTranscriptResponse(BaseModel):
    meeting_id: str
    total_segments: int
    segments: List[TranscriptSegmentResponse] = Field(default_factory=list)
    speakers: List[str] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class TranscriptionStatusResponse(BaseModel):
    status: str
    error: Optional[str] = None
    segment_count: int = 0
    speaker_count: int = 0

    model_config = {"from_attributes": True}
