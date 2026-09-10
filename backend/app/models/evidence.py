from sqlalchemy import Column, String, Float, Text
from sqlalchemy.orm import relationship
from .base import Base


class Evidence(Base):
    __tablename__ = 'evidence'
    
    # Source information
    meeting_id = Column(String, nullable=False, index=True)
    transcript_segment_id = Column(String, nullable=True, index=True)
    timestamp = Column(Float, nullable=True)
    speaker_label = Column(String, nullable=True)
    user_id = Column(String, nullable=True, index=True)
    
    # Evidence content
    content = Column(Text, nullable=False)
    context = Column(Text, nullable=True)
    
    # Evidence classification
    evidence_type = Column(String, nullable=False, index=True)  # summary, topic, decision, task, etc.
    confidence = Column(Float, nullable=True)
    
    # Relationships to analyzed entities
    topic_id = Column(String, nullable=True, index=True)
    decision_id = Column(String, nullable=True, index=True)
    task_id = Column(String, nullable=True, index=True)
    
    # Metadata
    extracted_by = Column(String, nullable=True)  # AI model identifier
    extraction_metadata = Column(Text, nullable=True)  # JSON string for additional metadata