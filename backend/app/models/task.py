from sqlalchemy import Column, String, Text, DateTime, Float
from sqlalchemy.orm import relationship
from .base import Base


class Task(Base):
    __tablename__ = 'tasks'
    
    company_id = Column(String, nullable=False, index=True)
    meeting_id = Column(String, nullable=False, index=True)
    assignee_id = Column(String, nullable=True, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String, nullable=False, default='open')
    due_date = Column(DateTime(timezone=True), nullable=True)
    
    # Task details
    project_id = Column(String, nullable=True, index=True)
    priority = Column(String, nullable=True)  # high, medium, low
    deadline = Column(DateTime(timezone=True), nullable=True)
    estimated_hours = Column(String, nullable=True)
    
    # Evidence & AI extraction metadata
    source_segment_id = Column(String, nullable=True, index=True)
    source_start_ms = Column(Float, nullable=True)
    source_end_ms = Column(Float, nullable=True)
    speaker_label = Column(String, nullable=True)
    extracted_by = Column(String, nullable=True)
    extraction_confidence = Column(String, nullable=True)
