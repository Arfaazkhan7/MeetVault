from sqlalchemy import Column, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from .base import Base


class Topic(Base):
    __tablename__ = 'topics'
    
    company_id = Column(String, nullable=False, index=True)
    meeting_id = Column(String, nullable=True, index=True)
    name = Column(String, nullable=False, index=True)
    description = Column(Text, nullable=True)
    importance = Column(String, nullable=True)  # high, medium, low
    
    # AI extraction metadata
    extracted_by = Column(String, nullable=True)
    extraction_confidence = Column(String, nullable=True)


class MeetingTopic(Base):
    __tablename__ = 'meeting_topics'
    __table_args__ = (
        UniqueConstraint("meeting_id", "topic_id", name="uq_meeting_topic"),
    )

    company_id = Column(String, nullable=False, index=True)
    meeting_id = Column(String, nullable=False, index=True)
    topic_id = Column(String, nullable=False, index=True)
