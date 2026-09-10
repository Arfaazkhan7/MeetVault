from sqlalchemy import Column, String, Boolean, Text
from .base import Base


class SpeakerMapping(Base):
    __tablename__ = 'speaker_mappings'
    
    meeting_id = Column(String, nullable=False, index=True)
    speaker_label = Column(String, nullable=False, index=True)  # SPEAKER_00, SPEAKER_01, etc.
    user_id = Column(String, nullable=True, index=True)  # USR-XXXX or None if unmapped
    is_confirmed = Column(Boolean, nullable=False, default=False)  # Whether mapping is confirmed
    confidence = Column(String, nullable=True)  # high/medium/low for AI confidence
    notes = Column(Text, nullable=True)  # Additional notes about the mapping