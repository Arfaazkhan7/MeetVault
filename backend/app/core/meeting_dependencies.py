from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.dependencies import get_current_user, get_membership
from app.models.user import User
from app.models.meeting import Meeting, MeetingParticipant


def get_meeting_and_authorize(
    meeting_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Meeting:
    """
    Fetch meeting by ID, ensure user is authorized to access it:
    - If PERSONAL meeting: user is owner or participant.
    - If WORKSPACE meeting: user is a member of the workspace company.
    """
    meeting = db.query(Meeting).filter(Meeting.public_id == meeting_id, Meeting.deleted_at.is_(None)).first()
    if not meeting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")

    if meeting.meeting_type == "PERSONAL" or not meeting.company_id:
        if meeting.owner_id == current_user.public_id:
            return meeting
        participant = db.query(MeetingParticipant).filter(
            MeetingParticipant.meeting_id == meeting.public_id,
            MeetingParticipant.user_id == current_user.public_id,
        ).first()
        if not participant:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not authorized to access this personal meeting",
            )
        return meeting

    # Workspace meeting: user must be a member of the company
    get_membership(db, current_user.public_id, meeting.company_id)
    return meeting


def require_meeting_host(
    meeting: Meeting = Depends(get_meeting_and_authorize),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Meeting:
    """
    Ensure user is HOST of the meeting (or owner of personal meeting).
    """
    if meeting.owner_id and meeting.owner_id == current_user.public_id:
        return meeting

    participant = db.query(MeetingParticipant).filter(
        MeetingParticipant.meeting_id == meeting.public_id,
        MeetingParticipant.user_id == current_user.public_id
    ).first()

    if not participant or participant.role != "HOST":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Requires meeting host privileges")

    return meeting
