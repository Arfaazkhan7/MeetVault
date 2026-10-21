from sqlalchemy import Column, String, Integer, BigInteger, DateTime, Text, Index, Boolean
from sqlalchemy.orm import relationship

from app.models.base import Base


class MeetingRecording(Base):
    __tablename__ = "meeting_recordings"

    meeting_id = Column(String, nullable=False, index=True)
    company_id = Column(String, nullable=True, index=True)
    uploaded_by_user_id = Column(String, nullable=False, index=True)

    session_id = Column(String, nullable=True, index=True)
    egress_id = Column(String, nullable=True, index=True)
    source = Column(String, nullable=True, default="client_mixed_audio")
    ai_job_id = Column(String, nullable=True, index=True)

    storage_backend = Column(String, nullable=False, default="supabase")
    storage_bucket = Column(String, nullable=True)
    storage_path = Column(String, nullable=True, unique=True, index=True)

    original_filename = Column(String, nullable=True)
    file_type = Column(String, nullable=True)
    file_size_bytes = Column(BigInteger, nullable=True, default=0)
    duration_seconds = Column(Integer, nullable=True)
    processing_status = Column(String, nullable=False, default="RECORDING", index=True)
    processing_error = Column(Text, nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True, index=True)
    is_audio_purged = Column(Boolean, nullable=False, default=False)
    audio_purged_at = Column(DateTime(timezone=True), nullable=True)
    retention_policy = Column(String, nullable=True, default="ephemeral_transcript_only")
    cleanup_error = Column(Text, nullable=True)
    cleanup_retry_count = Column(Integer, nullable=False, default=0)

    meeting = relationship(
        "Meeting",
        primaryjoin="foreign(MeetingRecording.meeting_id) == Meeting.public_id",
        back_populates="recordings",
    )
    uploader = relationship(
        "User",
        primaryjoin="foreign(MeetingRecording.uploaded_by_user_id) == User.public_id",
    )
    ai_job = relationship(
        "AIJob",
        primaryjoin="foreign(MeetingRecording.ai_job_id) == AIJob.public_id",
        uselist=False,
    )


Index("ix_meeting_recordings_company_meeting", MeetingRecording.company_id, MeetingRecording.meeting_id)
