from sqlalchemy import Column, String, Float, Boolean, JSON, Index, UniqueConstraint
from sqlalchemy.orm import relationship
from .base import Base

class TranscriptSegment(Base):
    __tablename__ = 'transcript_segments'
    __table_args__ = (
        UniqueConstraint("meeting_id", "segment_id", name="uq_transcript_segment_meeting_segid"),
        Index("ix_transcript_segments_meeting_start", "meeting_id", "start_time"),
    )

    meeting_id = Column(String, nullable=False, index=True)
    recording_id = Column(String, nullable=True, index=True)
    segment_id = Column(String, nullable=True, index=True)
    speaker_label = Column(String, nullable=False)  # SPEAKER_00, SPEAKER_01, etc.
    user_id = Column(String, nullable=True, index=True)  # Mapped user ID
    speaker_confirmed = Column(Boolean, nullable=False, default=False)  # Whether speaker mapping is confirmed
    start_time = Column(Float, nullable=False)
    end_time = Column(Float, nullable=False)
    text = Column(String, nullable=False)
    translated_text = Column(String, nullable=True)
    language = Column(String, nullable=True)
    confidence = Column(Float, nullable=True)
    words = Column(JSON, nullable=True)

    meeting = relationship(
        "Meeting",
        primaryjoin="foreign(TranscriptSegment.meeting_id) == Meeting.public_id",
        back_populates="transcripts",
        foreign_keys="TranscriptSegment.meeting_id",
    )
    user = relationship(
        "User",
        primaryjoin="foreign(TranscriptSegment.user_id) == User.public_id",
    )

