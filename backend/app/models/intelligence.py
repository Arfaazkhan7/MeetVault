from sqlalchemy import Column, String, Text, DateTime, Float, ForeignKey
from sqlalchemy.orm import relationship
from .base import Base

class Question(Base):
    __tablename__ = 'questions'
    
    meeting_id = Column(String, nullable=False, index=True)
    project_id = Column(String, nullable=True, index=True)
    
    question = Column(Text, nullable=False)
    asked_by_participant_id = Column(String, nullable=True, index=True)
    mentioned_to_participant_id = Column(String, nullable=True, index=True)
    
    status = Column(String, nullable=False, default='OPEN') # OPEN, ANSWERED, DEFERRED, CANCELLED
    answer = Column(Text, nullable=True)
    answered_by_participant_id = Column(String, nullable=True)
    
    # Evidence
    source_segment_id = Column(String, nullable=True, index=True)
    source_start_ms = Column(Float, nullable=True)
    source_end_ms = Column(Float, nullable=True)
    confidence = Column(String, nullable=True)


class Risk(Base):
    __tablename__ = 'risks'
    
    meeting_id = Column(String, nullable=False, index=True)
    project_id = Column(String, nullable=True, index=True)
    
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    severity = Column(String, nullable=True) # high, medium, low
    probability = Column(String, nullable=True) # high, medium, low
    
    owner_participant_id = Column(String, nullable=True, index=True)
    status = Column(String, nullable=False, default='OPEN') # OPEN, MITIGATED, ACCEPTED, CLOSED
    
    # Evidence
    source_segment_id = Column(String, nullable=True, index=True)
    source_start_ms = Column(Float, nullable=True)
    source_end_ms = Column(Float, nullable=True)
    confidence = Column(String, nullable=True)


class UnresolvedIssue(Base):
    __tablename__ = 'unresolved_issues'
    
    project_id = Column(String, nullable=False, index=True)
    first_detected_meeting_id = Column(String, nullable=False)
    latest_meeting_id = Column(String, nullable=False, index=True)
    
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String, nullable=False, default='OPEN') # OPEN, RESOLVED
    priority = Column(String, nullable=True)
    
    related_meetings = Column(Text, nullable=True) # JSON array of meeting IDs


class Commitment(Base):
    __tablename__ = 'commitments'
    
    meeting_id = Column(String, nullable=False, index=True)
    project_id = Column(String, nullable=True, index=True)
    
    person = Column(String, nullable=False) # Extracted name or speaker label
    participant_id = Column(String, nullable=True, index=True) # Mapped identity
    
    commitment = Column(Text, nullable=False)
    due_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String, nullable=False, default='OPEN') # OPEN, FULFILLED
    
    # Evidence
    source_segment_id = Column(String, nullable=True, index=True)
    source_start_ms = Column(Float, nullable=True)
    source_end_ms = Column(Float, nullable=True)
    confidence = Column(String, nullable=True)


class Reminder(Base):
    __tablename__ = 'reminders'
    
    user_id = Column(String, nullable=False, index=True)
    action_item_id = Column(String, nullable=True, index=True) # links to Task.public_id
    commitment_id = Column(String, nullable=True, index=True)
    
    remind_at = Column(DateTime(timezone=True), nullable=False)
    status = Column(String, nullable=False, default='SCHEDULED') # SCHEDULED, SENT, CANCELLED, FAILED
    sent_at = Column(DateTime(timezone=True), nullable=True)
