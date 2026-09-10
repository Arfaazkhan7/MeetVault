from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Optional

from app.db.session import get_db
from app.core.dependencies import get_current_user, require_role, get_membership
from app.core.meeting_dependencies import get_meeting_and_authorize, require_meeting_host
from app.core.roles import Role
from app.models.user import User
from app.models.meeting import Meeting
from app.models.company import CompanyMember
from app.schemas.meeting import (
    CreateMeetingRequest,
    CreatePersonalMeetingRequest,
    UpdateMeetingRequest,
    MeetingResponse,
    InviteParticipantRequest,
    UpdateParticipantStatusRequest,
    MeetingParticipantResponse,
    MeetingConnectionResponse,
    JoinByInviteCodeRequest,
    MeetingStartResponse,
)
from app.services.meeting_service import (
    create_meeting,
    create_personal_meeting,
    list_personal_meetings_for_user,
    list_meetings_for_company,
    list_meetings_for_project,
    update_meeting,
    invite_participant,
    update_participant_status,
    list_meeting_participants,
    get_meeting_participant,
    record_participant_join,
    record_participant_leave,
    join_meeting_by_invite_code,
    get_meeting_by_invite_code,
    start_meeting,
    end_meeting,
)
from app.services.livekit_service import generate_meeting_token, room_name_for_meeting
from app.core.config import settings

router = APIRouter(tags=["meetings"])


# ── Personal Meetings ───────────────────────────────────────────────────
@router.post("/meetings/personal", response_model=MeetingResponse, status_code=status.HTTP_201_CREATED)
def create_new_personal_meeting(
    payload: CreatePersonalMeetingRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a Personal meeting (type=PERSONAL, company_id=None, project_id=None)."""
    return create_personal_meeting(db, payload.title, payload.description, current_user)


@router.get("/meetings/personal", response_model=list[MeetingResponse])
def list_personal_meetings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List personal meetings for current authenticated user."""
    return list_personal_meetings_for_user(db, current_user.public_id)


# ── Meeting CRUD ─────────────────────────────────────────────────────────
@router.post("/companies/{company_id}/meetings", response_model=MeetingResponse, status_code=status.HTTP_201_CREATED)
def create_new_meeting(
    company_id: str,
    payload: CreateMeetingRequest,
    current_user: User = Depends(get_current_user),
    membership: CompanyMember = Depends(require_role(Role.MEMBER)),
    db: Session = Depends(get_db),
):
    return create_meeting(
        db,
        company_id,
        payload.project_id,
        payload.title,
        payload.description,
        payload.scheduled_start_time,
        current_user,
    )


@router.get("/companies/{company_id}/meetings", response_model=list[MeetingResponse])
def get_company_meetings(
    company_id: str,
    membership: CompanyMember = Depends(require_role(Role.MEMBER)),
    db: Session = Depends(get_db),
):
    return list_meetings_for_company(db, company_id)


@router.get("/projects/{project_id}/meetings", response_model=list[MeetingResponse])
def get_project_meetings(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_meetings_for_project(db, project_id)


# CRITICAL ROUTE FIX: Must be defined BEFORE /meetings/{meeting_id} to avoid matching "join" as meeting_id
@router.post("/meetings/join", response_model=MeetingConnectionResponse)
def join_meeting_by_code(
    payload: JoinByInviteCodeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Join a meeting by invite code (e.g. MTG-XXXXXX). Works for both Personal and Workspace meetings."""
    invite_code = payload.invite_code.strip().upper()
    meeting, participant = join_meeting_by_invite_code(db, invite_code, current_user)

    token, expires_at = generate_meeting_token(meeting, current_user, participant)
    participant_data = MeetingParticipantResponse(
        user_public_id=participant.user_id,
        meeting_id=participant.meeting_id,
        role=participant.role,
        status=participant.status,
        join_time=participant.join_time,
        leave_time=participant.leave_time,
        attendance_duration_seconds=participant.attendance_duration_seconds,
        email=current_user.email,
        full_name=current_user.full_name,
    )

    return {
        "meeting_id": meeting.public_id,
        "room_name": room_name_for_meeting(meeting),
        "livekit_url": settings.LIVEKIT_URL,
        "token": token,
        "token_expires_at": expires_at,
        "participant": participant_data,
    }


@router.get("/meetings/{meeting_id}", response_model=MeetingResponse)
def get_meeting_details(
    meeting: Meeting = Depends(get_meeting_and_authorize),
):
    return meeting


@router.patch("/meetings/{meeting_id}", response_model=MeetingResponse)
def update_meeting_details(
    payload: UpdateMeetingRequest,
    meeting: Meeting = Depends(require_meeting_host),
    db: Session = Depends(get_db),
):
    update_data = payload.model_dump(exclude_unset=True)
    return update_meeting(db, meeting, update_data)


@router.post("/meetings/{meeting_id}/start", response_model=MeetingStartResponse)
def start_meeting_endpoint(
    meeting: Meeting = Depends(require_meeting_host),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Host manually starts the meeting (transitions SCHEDULED -> LIVE)."""
    return start_meeting(db, meeting, current_user)


@router.post("/meetings/{meeting_id}/end", response_model=MeetingResponse)
def end_meeting_endpoint(
    meeting: Meeting = Depends(require_meeting_host),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Host manually ends the meeting (transitions LIVE -> COMPLETED)."""
    return end_meeting(db, meeting, current_user)


# ── Participant Endpoints ─────────────────────────────────────────────────
@router.get("/meetings/{meeting_id}/participants", response_model=list[MeetingParticipantResponse])
def get_participants(
    meeting: Meeting = Depends(get_meeting_and_authorize),
    db: Session = Depends(get_db),
):
    return list_meeting_participants(db, meeting.public_id)


@router.post("/meetings/{meeting_id}/participants", response_model=MeetingParticipantResponse, status_code=status.HTTP_201_CREATED)
def invite_user_to_meeting(
    payload: InviteParticipantRequest,
    meeting: Meeting = Depends(require_meeting_host),
    db: Session = Depends(get_db),
):
    participant = invite_participant(db, meeting, payload.user_public_id, payload.role)
    invited_user = db.query(User).filter(User.public_id == payload.user_public_id).first()
    return MeetingParticipantResponse(
        user_public_id=participant.user_id,
        meeting_id=participant.meeting_id,
        role=participant.role,
        status=participant.status,
        join_time=participant.join_time,
        leave_time=participant.leave_time,
        attendance_duration_seconds=participant.attendance_duration_seconds,
        email=invited_user.email if invited_user else None,
        full_name=invited_user.full_name if invited_user else None,
    )


@router.patch("/meetings/{meeting_id}/participants/{user_public_id}", response_model=MeetingParticipantResponse)
def update_participant(
    user_public_id: str,
    payload: UpdateParticipantStatusRequest,
    meeting: Meeting = Depends(get_meeting_and_authorize),
    db: Session = Depends(get_db),
):
    participant = update_participant_status(
        db,
        meeting,
        user_public_id,
        payload.status,
        payload.join_time,
        payload.leave_time,
    )
    user_obj = db.query(User).filter(User.public_id == user_public_id).first()
    return MeetingParticipantResponse(
        user_public_id=participant.user_id,
        meeting_id=participant.meeting_id,
        role=participant.role,
        status=participant.status,
        join_time=participant.join_time,
        leave_time=participant.leave_time,
        attendance_duration_seconds=participant.attendance_duration_seconds,
        email=user_obj.email if user_obj else None,
        full_name=user_obj.full_name if user_obj else None,
    )


# ── LiveKit Room Connection Endpoints ─────────────────────────────────────
@router.post("/meetings/{meeting_id}/room/connect", response_model=MeetingConnectionResponse)
def get_meeting_room_connection(
    meeting_id: str,
    meeting: Meeting = Depends(get_meeting_and_authorize),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generate a LiveKit JWT token for entering the meeting room."""
    participant = get_meeting_participant(db, meeting, current_user.public_id)
    token, expires_at = generate_meeting_token(meeting, current_user, participant)
    participant = get_meeting_participant(db, meeting, current_user.public_id)

    participant_data = MeetingParticipantResponse(
        user_public_id=participant.user_id,
        meeting_id=participant.meeting_id,
        role=participant.role,
        status=participant.status,
        join_time=participant.join_time,
        leave_time=participant.leave_time,
        attendance_duration_seconds=participant.attendance_duration_seconds,
        email=current_user.email,
        full_name=current_user.full_name,
    )

    return {
        "meeting_id": meeting.public_id,
        "room_name": room_name_for_meeting(meeting),
        "livekit_url": settings.LIVEKIT_URL,
        "token": token,
        "token_expires_at": expires_at,
        "participant": participant_data,
    }


@router.post("/meetings/{meeting_id}/room/join", response_model=MeetingParticipantResponse)
def join_meeting_room(
    meeting_id: str,
    meeting: Meeting = Depends(get_meeting_and_authorize),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Record participant join timestamp when connecting to LiveKit room."""
    participant = record_participant_join(db, meeting, current_user.public_id)
    return MeetingParticipantResponse(
        user_public_id=participant.user_id,
        meeting_id=participant.meeting_id,
        role=participant.role,
        status=participant.status,
        join_time=participant.join_time,
        leave_time=participant.leave_time,
        attendance_duration_seconds=participant.attendance_duration_seconds,
        email=current_user.email,
        full_name=current_user.full_name,
    )


@router.post("/meetings/{meeting_id}/room/leave", response_model=MeetingParticipantResponse)
def leave_meeting_room(
    meeting_id: str,
    meeting: Meeting = Depends(get_meeting_and_authorize),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Record participant leave timestamp and attendance duration."""
    participant = record_participant_leave(db, meeting, current_user.public_id)
    return MeetingParticipantResponse(
        user_public_id=participant.user_id,
        meeting_id=participant.meeting_id,
        role=participant.role,
        status=participant.status,
        join_time=participant.join_time,
        leave_time=participant.leave_time,
        attendance_duration_seconds=participant.attendance_duration_seconds,
        email=current_user.email,
        full_name=current_user.full_name,
    )
