from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from datetime import datetime, timezone
from typing import Optional
import secrets
import string

from app.models.meeting import Meeting, MeetingParticipant
from app.models.project import Project
from app.models.user import User
from app.core.enums import MeetingStatus, ParticipantStatus, MeetingRole, MeetingType


def _next_meeting_id(db: Session) -> str:
    count = db.query(Meeting).count() + 1
    return f"MTG-{count:04d}"


def _generate_invite_code(db: Session) -> str:
    """Generate a unique, non-sequential invite code."""
    alphabet = string.ascii_uppercase + string.digits
    # Remove confusing characters: 0, O, 1, I, 8, B
    alphabet = ''.join(c for c in alphabet if c not in '0O1I8B')
    while True:
        code = ''.join(secrets.choice(alphabet) for _ in range(6))
        invite_code = f"MTG-{code}"
        existing = db.query(Meeting).filter(Meeting.invite_code == invite_code).first()
        if not existing:
            return invite_code


def create_meeting(
    db: Session, 
    company_id: str, 
    project_id: str, 
    title: str, 
    description: str | None, 
    scheduled_start_time: datetime | None,
    creator: User
) -> Meeting:
    # Validate project belongs to company
    project = db.query(Project).filter(Project.public_id == project_id, Project.company_id == company_id).first()
    if not project:
        raise HTTPException(status_code=400, detail="Project not found in this company")

    meeting = Meeting(
        public_id=_next_meeting_id(db),
        company_id=company_id,
        project_id=project_id,
        owner_id=creator.public_id,
        meeting_type=MeetingType.WORKSPACE.value,
        title=title.strip(),
        description=description.strip() if description else None,
        scheduled_start_time=scheduled_start_time,
        status=MeetingStatus.SCHEDULED.value,
        invite_code=_generate_invite_code(db),
    )
    db.add(meeting)
    db.flush()

    # Creator becomes HOST
    member = MeetingParticipant(
        user_id=creator.public_id,
        meeting_id=meeting.public_id,
        role=MeetingRole.HOST.value,
        status=ParticipantStatus.INVITED.value,
    )
    db.add(member)
    db.commit()
    db.refresh(meeting)
    return meeting


def create_personal_meeting(
    db: Session,
    title: str,
    description: str | None,
    creator: User,
) -> Meeting:
    """Create a Personal meeting (type=PERSONAL, company_id=None, project_id=None)."""
    meeting = Meeting(
        public_id=_next_meeting_id(db),
        company_id=None,
        project_id=None,
        owner_id=creator.public_id,
        meeting_type=MeetingType.PERSONAL.value,
        title=title.strip(),
        description=description.strip() if description else None,
        status=MeetingStatus.SCHEDULED.value,
        invite_code=_generate_invite_code(db),
    )
    db.add(meeting)
    db.flush()

    # Creator becomes HOST
    member = MeetingParticipant(
        user_id=creator.public_id,
        meeting_id=meeting.public_id,
        role=MeetingRole.HOST.value,
        status=ParticipantStatus.INVITED.value,
    )
    db.add(member)
    db.commit()
    db.refresh(meeting)
    return meeting


def list_personal_meetings_for_user(db: Session, user_public_id: str) -> list[Meeting]:
    """Return all personal meetings owned or joined by the user."""
    # Find meetings owned by user or where user is a participant
    participant_meetings = (
        db.query(MeetingParticipant.meeting_id)
        .filter(MeetingParticipant.user_id == user_public_id)
        .all()
    )
    part_meeting_ids = [m[0] for m in participant_meetings]

    return (
        db.query(Meeting)
        .filter(
            Meeting.meeting_type == MeetingType.PERSONAL.value,
            (Meeting.owner_id == user_public_id) | (Meeting.public_id.in_(part_meeting_ids)),
            Meeting.deleted_at.is_(None),
        )
        .all()
    )


def list_meetings_for_company(db: Session, company_id: str) -> list[Meeting]:
    return db.query(Meeting).filter(
        Meeting.company_id == company_id,
        Meeting.deleted_at.is_(None)
    ).all()


def list_meetings_for_project(db: Session, project_id: str) -> list[Meeting]:
    return db.query(Meeting).filter(
        Meeting.project_id == project_id,
        Meeting.deleted_at.is_(None)
    ).all()

def update_meeting(db: Session, meeting: Meeting, data: dict) -> Meeting:
    for k, v in data.items():
        if v is not None:
            setattr(meeting, k, v.value if hasattr(v, 'value') else v)
    db.commit()
    db.refresh(meeting)
    return meeting

def invite_participant(db: Session, meeting: Meeting, user_public_id: str, role: MeetingRole) -> MeetingParticipant:
    existing = db.query(MeetingParticipant).filter(
        MeetingParticipant.user_id == user_public_id,
        MeetingParticipant.meeting_id == meeting.public_id
    ).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User already in meeting")

    member = MeetingParticipant(
        user_id=user_public_id,
        meeting_id=meeting.public_id,
        role=role.value,
        status=ParticipantStatus.INVITED.value
    )
    db.add(member)
    db.commit()
    db.refresh(member)
    return member

def update_participant_status(
    db: Session, 
    meeting: Meeting, 
    user_public_id: str, 
    status_val: ParticipantStatus,
    join_time: datetime | None,
    leave_time: datetime | None
) -> MeetingParticipant:
    participant = db.query(MeetingParticipant).filter(
        MeetingParticipant.user_id == user_public_id,
        MeetingParticipant.meeting_id == meeting.public_id
    ).first()

    if not participant:
        raise HTTPException(status_code=404, detail="Participant not found")

    participant.status = status_val.value
    if join_time:
        participant.join_time = join_time
    if leave_time:
        participant.leave_time = leave_time

    # Calculate duration if both are present
    if participant.join_time and participant.leave_time:
        diff = participant.leave_time - participant.join_time
        participant.attendance_duration_seconds = int(diff.total_seconds())

    db.commit()
    db.refresh(participant)
    return participant

def list_meeting_participants(db: Session, meeting_id: str) -> list[dict]:
    members = db.query(MeetingParticipant).filter(MeetingParticipant.meeting_id == meeting_id).all()
    user_ids = [m.user_id for m in members]
    users = db.query(User).filter(User.public_id.in_(user_ids)).all()
    user_map = {u.public_id: u for u in users}

    now = datetime.now(timezone.utc)
    res = []
    for m in members:
        u = user_map.get(m.user_id)
        dur = m.attendance_duration_seconds
        if dur is None and m.join_time:
            jt = m.join_time if m.join_time.tzinfo else m.join_time.replace(tzinfo=timezone.utc)
            if m.leave_time:
                lt = m.leave_time if m.leave_time.tzinfo else m.leave_time.replace(tzinfo=timezone.utc)
                dur = max(0, int((lt - jt).total_seconds()))
            else:
                dur = max(0, int((now - jt).total_seconds()))

        res.append({
            "user_public_id": m.user_id,
            "meeting_id": m.meeting_id,
            "role": m.role,
            "status": m.status,
            "join_time": m.join_time,
            "leave_time": m.leave_time,
            "attendance_duration_seconds": dur,
            "email": u.email if u else None,
            "full_name": u.full_name if u else (u.email.split('@')[0] if u and u.email else 'User'),
        })
    return res


def get_meeting_participant(
    db: Session,
    meeting: Meeting,
    user_public_id: str,
) -> MeetingParticipant:
    participant = db.query(MeetingParticipant).filter(
        MeetingParticipant.user_id == user_public_id,
        MeetingParticipant.meeting_id == meeting.public_id,
    ).first()
    if not participant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not a participant in this meeting",
        )
    return participant


def record_participant_join(
    db: Session,
    meeting: Meeting,
    user_public_id: str,
) -> MeetingParticipant:
    participant = db.query(MeetingParticipant).filter(
        MeetingParticipant.user_id == user_public_id,
        MeetingParticipant.meeting_id == meeting.public_id,
    ).first()
    if not participant:
        role = MeetingRole.HOST.value if meeting.owner_id == user_public_id else MeetingRole.ATTENDEE.value
        participant = MeetingParticipant(
            user_id=user_public_id,
            meeting_id=meeting.public_id,
            role=role,
            status=ParticipantStatus.INVITED.value,
        )
        db.add(participant)
        db.flush()
    now = datetime.now(timezone.utc)
    if not participant.join_time or participant.status == ParticipantStatus.LEFT.value:
        participant.join_time = now
        participant.leave_time = None
        participant.attendance_duration_seconds = None
    participant.status = ParticipantStatus.JOINED.value
    if meeting.status == MeetingStatus.SCHEDULED.value:
        meeting.status = MeetingStatus.LIVE.value
        meeting.start_time = meeting.start_time or now
    db.commit()
    db.refresh(participant)
    return participant


def record_participant_leave(
    db: Session,
    meeting: Meeting,
    user_public_id: str,
) -> MeetingParticipant:
    participant = get_meeting_participant(db, meeting, user_public_id)
    now = datetime.now(timezone.utc)
    participant.leave_time = now
    participant.status = ParticipantStatus.LEFT.value
    if participant.join_time:
        join_time = participant.join_time
        if join_time.tzinfo is None:
            join_time = join_time.replace(tzinfo=timezone.utc)
        participant.attendance_duration_seconds = max(0, int(
            (participant.leave_time - join_time).total_seconds()
        ))
    db.commit()
    db.refresh(participant)
    return participant


def get_meeting_by_public_id(db: Session, public_id: str) -> Optional[Meeting]:
    """Get meeting by public ID."""
    return db.query(Meeting).filter(Meeting.public_id == public_id).first()


def get_meeting_by_invite_code(db: Session, invite_code: str) -> Optional[Meeting]:
    """Get meeting by invite code."""
    return db.query(Meeting).filter(Meeting.invite_code == invite_code.upper()).first()


def get_meeting_by_id(db: Session, meeting_id: int) -> Optional[Meeting]:
    """Get meeting by database ID."""
    return db.query(Meeting).filter(Meeting.id == meeting_id).first()


def join_meeting_by_invite_code(
    db: Session,
    invite_code: str,
    user: User,
) -> tuple[Meeting, MeetingParticipant]:
    """Join a meeting using an invite code. Returns the meeting and participant record."""
    meeting = get_meeting_by_invite_code(db, invite_code)
    if not meeting:
        raise HTTPException(status_code=404, detail="Invalid invite code")

    # Check meeting status
    if meeting.status == MeetingStatus.CANCELLED.value:
        raise HTTPException(status_code=400, detail="Meeting has been cancelled")
    if meeting.status == MeetingStatus.COMPLETED.value:
        raise HTTPException(status_code=400, detail="Meeting has already ended")

    # Check company membership for workspace meetings; auto-grant member role if invited via code
    if meeting.meeting_type == MeetingType.WORKSPACE.value and meeting.company_id:
        from app.models.company import CompanyMember
        from app.core.roles import Role
        membership = db.query(CompanyMember).filter(
            CompanyMember.user_id == user.public_id,
            CompanyMember.company_id == meeting.company_id,
        ).first()
        if not membership:
            membership = CompanyMember(
                user_id=user.public_id,
                company_id=meeting.company_id,
                role=Role.MEMBER.value,
            )
            db.add(membership)
            db.commit()

    # Check if participant already exists
    participant = db.query(MeetingParticipant).filter(
        MeetingParticipant.user_id == user.public_id,
        MeetingParticipant.meeting_id == meeting.public_id,
    ).first()

    if not participant:
        # Create new participant record
        role = MeetingRole.HOST.value if meeting.owner_id == user.public_id else MeetingRole.ATTENDEE.value
        participant = MeetingParticipant(
            user_id=user.public_id,
            meeting_id=meeting.public_id,
            role=role,
            status=ParticipantStatus.INVITED.value,
        )
        db.add(participant)
        db.commit()
        db.refresh(participant)
    else:
        # Update status if they were previously LEFT or ABSENT
        if participant.status in [ParticipantStatus.LEFT.value, ParticipantStatus.ABSENT.value]:
            participant.status = ParticipantStatus.INVITED.value
            db.commit()
            db.refresh(participant)

    return meeting, participant


def start_meeting(db: Session, meeting: Meeting, user: User) -> Meeting:
    # Ensure user is host
    participant = get_meeting_participant(db, meeting, user.public_id)
    if participant.role != MeetingRole.HOST.value:
        raise HTTPException(status_code=403, detail="Only the host can start the meeting")

    if meeting.status != MeetingStatus.SCHEDULED.value:
        raise HTTPException(status_code=400, detail="Meeting is not in SCHEDULED state")

    meeting.status = MeetingStatus.LIVE.value
    meeting.start_time = datetime.now(timezone.utc)
    db.commit()
    db.refresh(meeting)
    return meeting


def end_meeting(db: Session, meeting: Meeting, user: User) -> Meeting:
    # Ensure user is host
    participant = get_meeting_participant(db, meeting, user.public_id)
    if participant.role != MeetingRole.HOST.value:
        raise HTTPException(status_code=403, detail="Only the host can end the meeting")

    if meeting.status != MeetingStatus.LIVE.value:
        raise HTTPException(status_code=400, detail="Meeting is not LIVE")

    now = datetime.now(timezone.utc)
    meeting.status = MeetingStatus.COMPLETED.value
    meeting.end_time = now
    
    if meeting.start_time:
        st = meeting.start_time
        if st.tzinfo is None:
            st = st.replace(tzinfo=timezone.utc)
        meeting.duration_seconds = max(0, int((now - st).total_seconds()))
    
    # Mark all joined participants as left
    active_participants = db.query(MeetingParticipant).filter(
        MeetingParticipant.meeting_id == meeting.public_id,
        MeetingParticipant.status == ParticipantStatus.JOINED.value
    ).all()

    for p in active_participants:
        p.status = ParticipantStatus.LEFT.value
        p.leave_time = now
        if p.join_time:
            join_time = p.join_time
            if join_time.tzinfo is None:
                join_time = join_time.replace(tzinfo=timezone.utc)
            p.attendance_duration_seconds = max(0, int((now - join_time).total_seconds()))

    db.commit()
    db.refresh(meeting)
    return meeting


def get_user_meeting_history(db: Session, user_public_id: str) -> list[dict]:
    """
    Fetch complete cloud meeting history for the authenticated user.
    Returns meetings where the user was HOST or ATTENDEE, or member of workspace company,
    including start/end times, meeting codes, total duration, my role, real participant lists,
    and transcription/recording status.
    """
    from app.models.company import CompanyMember
    from sqlalchemy import or_

    part_records = (
        db.query(MeetingParticipant)
        .filter(MeetingParticipant.user_id == user_public_id)
        .all()
    )
    part_map = {p.meeting_id: p for p in part_records}

    user_companies = db.query(CompanyMember.company_id).filter(CompanyMember.user_id == user_public_id).all()
    company_ids = [c[0] for c in user_companies if c[0]]

    access_conditions = [Meeting.owner_id == user_public_id]
    if part_map:
        access_conditions.append(Meeting.public_id.in_(list(part_map.keys())))
    if company_ids:
        access_conditions.append(
            (Meeting.company_id.in_(company_ids)) & (Meeting.meeting_type == MeetingType.WORKSPACE.value)
        )

    meetings = (
        db.query(Meeting)
        .filter(
            or_(*access_conditions),
            Meeting.deleted_at.is_(None),
        )
        .order_by(Meeting.created_at.desc())
        .all()
    )

    now = datetime.now(timezone.utc)
    history = []
    for m in meetings:
        my_part = part_map.get(m.public_id)
        if m.owner_id == user_public_id:
            my_role = MeetingRole.HOST.value
        elif my_part:
            my_role = my_part.role
        else:
            my_role = MeetingRole.ATTENDEE.value

        duration = m.duration_seconds
        if duration is None:
            if m.start_time and m.end_time:
                st = m.start_time if m.start_time.tzinfo else m.start_time.replace(tzinfo=timezone.utc)
                et = m.end_time if m.end_time.tzinfo else m.end_time.replace(tzinfo=timezone.utc)
                duration = max(0, int((et - st).total_seconds()))
            elif m.start_time:
                st = m.start_time if m.start_time.tzinfo else m.start_time.replace(tzinfo=timezone.utc)
                duration = max(0, int((now - st).total_seconds()))

        my_dur = my_part.attendance_duration_seconds if my_part else None
        if my_dur is None and my_part and my_part.join_time:
            jt = my_part.join_time if my_part.join_time.tzinfo else my_part.join_time.replace(tzinfo=timezone.utc)
            if my_part.leave_time:
                lt = my_part.leave_time if my_part.leave_time.tzinfo else my_part.leave_time.replace(tzinfo=timezone.utc)
                my_dur = max(0, int((lt - jt).total_seconds()))
            elif m.end_time:
                et = m.end_time if m.end_time.tzinfo else m.end_time.replace(tzinfo=timezone.utc)
                my_dur = max(0, int((et - jt).total_seconds()))
            else:
                my_dur = max(0, int((now - jt).total_seconds()))

        participants_data = list_meeting_participants(db, m.public_id)

        history.append({
            "meeting_id": m.public_id,
            "title": m.title,
            "description": m.description,
            "meeting_code": m.invite_code,
            "meeting_type": m.meeting_type,
            "status": m.status,
            "started_at": m.start_time or m.created_at,
            "ended_at": m.end_time,
            "duration_seconds": duration,
            "my_role": my_role,
            "my_join_time": my_part.join_time if my_part else None,
            "my_leave_time": my_part.leave_time if my_part else None,
            "my_duration_seconds": my_dur,
            "participants": participants_data,
            "transcription_status": m.transcription_status,
            "transcription_error": m.transcription_error,
            "recording_url": m.recording_url,
        })

    return history
