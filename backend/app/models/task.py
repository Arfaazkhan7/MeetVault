from sqlalchemy import Column, String, Text, DateTime
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
    priority = Column(String, nullable=True)  # high, medium, low
    deadline = Column(DateTime(timezone=True), nullable=True)
    estimated_hours = Column(String, nullable=True)
    
    # AI extraction metadata
    extracted_by = Column(String, nullable=True)
    extraction_confidence = Column(String, nullable=True)
