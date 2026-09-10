from sqlalchemy import Column, String, Float, Boolean
from sqlalchemy.orm import relationship
from .base import Base

class TranscriptSegment(Base):
    __tablename__ = 'transcript_segments'
    meeting_id = Column(String, nullable=False, index=True)
    speaker_label = Column(String, nullable=False)  # SPEAKER_00, SPEAKER_01, etc.
    user_id = Column(String, nullable=True, index=True)  # Mapped user ID
    speaker_confirmed = Column(Boolean, nullable=False, default=False)  # Whether speaker mapping is confirmed
    start_time = Column(Float, nullable=False)
    end_time = Column(Float, nullable=False)
    text = Column(String, nullable=False)
    language = Column(String, nullable=True)
    confidence = Column(Float, nullable=True)

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
