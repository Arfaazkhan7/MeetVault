from sqlalchemy import Column, String, Integer, BigInteger, DateTime, Text, Index
from sqlalchemy.orm import relationship

from app.models.base import Base


class MeetingRecording(Base):
    __tablename__ = "meeting_recordings"

    meeting_id = Column(String, nullable=False, index=True)
    company_id = Column(String, nullable=False, index=True)
    uploaded_by_user_id = Column(String, nullable=False, index=True)

    storage_backend = Column(String, nullable=False, default="supabase")
    storage_bucket = Column(String, nullable=False)
    storage_path = Column(String, nullable=False, unique=True, index=True)

    original_filename = Column(String, nullable=False)
    file_type = Column(String, nullable=False)
    file_size_bytes = Column(BigInteger, nullable=False)
    duration_seconds = Column(Integer, nullable=True)
    processing_status = Column(String, nullable=False, default="UPLOADED", index=True)
    processing_error = Column(Text, nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True, index=True)

    meeting = relationship(
        "Meeting",
        primaryjoin="foreign(MeetingRecording.meeting_id) == Meeting.public_id",
        back_populates="recordings",
    )
    uploader = relationship(
        "User",
        primaryjoin="foreign(MeetingRecording.uploaded_by_user_id) == User.public_id",
    )


Index("ix_meeting_recordings_company_meeting", MeetingRecording.company_id, MeetingRecording.meeting_id)
