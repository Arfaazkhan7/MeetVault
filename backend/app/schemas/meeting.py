from pydantic import BaseModel, field_validator
from typing import Optional
from datetime import datetime
from app.core.enums import MeetingStatus, ParticipantStatus, MeetingRole, MeetingType


class CreateMeetingRequest(BaseModel):
    title: str
    description: Optional[str] = None
    project_id: Optional[str] = None
    scheduled_start_time: Optional[datetime] = None

    @field_validator("title")
    @classmethod
    def title_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Meeting title cannot be blank")
        return v


class CreatePersonalMeetingRequest(BaseModel):
    title: str
    description: Optional[str] = None

    @field_validator("title")
    @classmethod
    def title_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Meeting title cannot be blank")
        return v


class UpdateMeetingRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[MeetingStatus] = None
    scheduled_start_time: Optional[datetime] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None


class MeetingResponse(BaseModel):
    public_id: str
    company_id: Optional[str] = None
    project_id: Optional[str] = None
    owner_id: Optional[str] = None
    meeting_type: str = "WORKSPACE"
    title: str
    description: Optional[str] = None
    status: str
    invite_code: Optional[str] = None
    scheduled_start_time: Optional[datetime] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    model_config = {"from_attributes": True}


class InviteParticipantRequest(BaseModel):
    user_public_id: str
    role: MeetingRole = MeetingRole.ATTENDEE


class UpdateParticipantStatusRequest(BaseModel):
    status: ParticipantStatus
    join_time: Optional[datetime] = None
    leave_time: Optional[datetime] = None


class MeetingParticipantResponse(BaseModel):
    user_public_id: str
    meeting_id: str
    role: str
    status: str
    join_time: Optional[datetime] = None
    leave_time: Optional[datetime] = None
    attendance_duration_seconds: Optional[int] = None

    # Joined fields
    email: Optional[str] = None
    full_name: Optional[str] = None
    model_config = {"from_attributes": True}


class JoinByInviteCodeRequest(BaseModel):
    invite_code: str


class MeetingStartResponse(BaseModel):
    public_id: str
    status: str
    start_time: Optional[datetime] = None
    model_config = {"from_attributes": True}


class MeetingConnectionResponse(BaseModel):
    meeting_id: str
    meeting_title: str
    room_name: str
    livekit_url: str
    token: str
    token_expires_at: datetime
    participant: MeetingParticipantResponse


class MeetingHistoryItemResponse(BaseModel):
    meeting_id: str
    title: str
    description: Optional[str] = None
    meeting_code: Optional[str] = None
    meeting_type: str = "PERSONAL"
    status: str
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    my_role: str = "ATTENDEE"
    my_join_time: Optional[datetime] = None
    my_leave_time: Optional[datetime] = None
    my_duration_seconds: Optional[int] = None
    participants: list[MeetingParticipantResponse] = []
    model_config = {"from_attributes": True}
