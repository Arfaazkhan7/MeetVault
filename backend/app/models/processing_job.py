from sqlalchemy import Column, String, Integer, DateTime, Text
from .base import Base
from datetime import datetime, timezone

class ProcessingJob(Base):
    __tablename__ = 'processing_jobs'
    
    meeting_id = Column(String, nullable=False, index=True)
    job_type = Column(String, nullable=False, default="MEETING_INTELLIGENCE")
    status = Column(String, nullable=False, default="QUEUED", index=True)
    current_stage = Column(String, nullable=False, default="QUEUED")
    attempt_count = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=3)
    
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(Text, nullable=True)
