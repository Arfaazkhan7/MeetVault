from sqlalchemy import Column, String, DateTime, Text, Integer, UniqueConstraint
from sqlalchemy.orm import relationship

from app.models.base import Base


class Meeting(Base):
    __tablename__ = "meetings"

    public_id = Column(String, unique=True, index=True, nullable=False)
    company_id = Column(String, nullable=True, index=True)
    project_id = Column(String, nullable=True, index=True)
    owner_id = Column(String, nullable=True, index=True)
    title = Column(String, nullable=False)
    description = Column(String, nullable=True)

    meeting_type = Column(String, nullable=False, default="WORKSPACE")
    status = Column(String, nullable=False, default="SCHEDULED")

    scheduled_start_time = Column(DateTime(timezone=True), nullable=True)
    start_time = Column(DateTime(timezone=True), nullable=True)
    end_time = Column(DateTime(timezone=True), nullable=True)

    deleted_at = Column(DateTime(timezone=True), nullable=True)

    # Invite code for joining meetings
    invite_code = Column(String, unique=True, index=True, nullable=True)

    # Transcription status
    transcription_status = Column(String, nullable=False, default='pending')
    transcription_error = Column(Text, nullable=True)
    recording_url = Column(String, nullable=True)
    
    # Analysis status
    analysis_status = Column(String, nullable=False, default='pending')
    analysis_error = Column(Text, nullable=True)

    company = relationship(
        "Company",
        primaryjoin="foreign(Meeting.company_id) == Company.public_id",
        viewonly=True,
    )
    project = relationship(
        "Project",
        primaryjoin="foreign(Meeting.project_id) == Project.public_id",
        back_populates="meetings",
    )
    participants = relationship(
        "MeetingParticipant",
        primaryjoin="Meeting.public_id == foreign(MeetingParticipant.meeting_id)",
        back_populates="meeting",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    transcripts = relationship(
        "TranscriptSegment",
        primaryjoin="foreign(TranscriptSegment.meeting_id) == Meeting.public_id",
        back_populates="meeting",
    )
    recordings = relationship(
        "MeetingRecording",
        primaryjoin="Meeting.public_id == foreign(MeetingRecording.meeting_id)",
        back_populates="meeting",
        cascade="all, delete-orphan",
    )
    documents = relationship(
        "Document",
        primaryjoin="Meeting.public_id == foreign(Document.meeting_id)",
        back_populates="meeting",
    )


class MeetingParticipant(Base):
    __tablename__ = "meeting_participants"

    __table_args__ = (
        UniqueConstraint("user_id", "meeting_id", name="uq_participant_meeting"),
    )

    user_id = Column(String, nullable=False, index=True)
    meeting_id = Column(String, nullable=False, index=True)

    role = Column(String, nullable=False, default="ATTENDEE")
    status = Column(String, nullable=False, default="INVITED")

    join_time = Column(DateTime(timezone=True), nullable=True)
    leave_time = Column(DateTime(timezone=True), nullable=True)
    attendance_duration_seconds = Column(Integer, nullable=True)

    meeting = relationship(
        "Meeting",
        primaryjoin="foreign(MeetingParticipant.meeting_id) == Meeting.public_id",
        back_populates="participants",
    )
    user = relationship(
        "User",
        primaryjoin="foreign(MeetingParticipant.user_id) == User.public_id",
    )
