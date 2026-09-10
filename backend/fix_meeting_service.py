import re

with open('app/services/meeting_service.py', 'r') as f:
    text = f.read()

# Let's find the FIRST def join_meeting_by_invite_code
idx = text.find('def join_meeting_by_invite_code')
clean_text = text[:idx]

clean_text += '''def join_meeting_by_invite_code(
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

    # Check company membership
    from app.models.company import CompanyMember
    membership = db.query(CompanyMember).filter(
        CompanyMember.user_id == user.public_id,
        CompanyMember.company_id == meeting.company_id,
    ).first()
    if not membership:
        raise HTTPException(status_code=403, detail="You are not a member of this company")

    # Check if participant already exists
    participant = db.query(MeetingParticipant).filter(
        MeetingParticipant.user_id == user.public_id,
        MeetingParticipant.meeting_id == meeting.public_id,
    ).first()

    if not participant:
        # Create new participant record
        participant = MeetingParticipant(
            user_id=user.public_id,
            meeting_id=meeting.public_id,
            role=MeetingRole.ATTENDEE.value,
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
            p.attendance_duration_seconds = int((now - join_time).total_seconds())

    db.commit()
    db.refresh(meeting)
    return meeting
'''

with open('app/services/meeting_service.py', 'w') as f:
    f.write(clean_text)
