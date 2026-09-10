from sqlalchemy import Column, String, Text, DateTime
from sqlalchemy.orm import relationship
from .base import Base


class Decision(Base):
    __tablename__ = 'decisions'
    
    company_id = Column(String, nullable=False, index=True)
    meeting_id = Column(String, nullable=False, index=True)
    project_id = Column(String, nullable=True, index=True)
    
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String, nullable=False, default='proposed')
    
    # Decision details
    decision_type = Column(String, nullable=True)  # agreement, disagreement, proposal, concern
    proposer_id = Column(String, nullable=True, index=True)  # user who proposed
    confidence_level = Column(String, nullable=True)  # high, medium, low
    
    # Evolution fields
    original_proposal = Column(Text, nullable=True)
    reason = Column(Text, nullable=True)
    
    # AI extraction metadata
    extracted_by = Column(String, nullable=True)
    extraction_confidence = Column(String, nullable=True)


class DecisionHistory(Base):
    __tablename__ = 'decision_history'
    
    public_id = Column(String, unique=True, index=True, nullable=True)
    decision_id = Column(String, nullable=False, index=True)
    meeting_id = Column(String, nullable=False, index=True)
    
    stage = Column(String, nullable=False, default='STATUS_CHANGE')  # PROPOSAL, CONCERN, ALTERNATIVE, FINAL_DECISION, STATUS_CHANGE
    previous_status = Column(String, nullable=True)
    new_status = Column(String, nullable=False)
    
    notes = Column(Text, nullable=True)
    evidence_text = Column(Text, nullable=True)
    reason = Column(Text, nullable=True)
    speaker_label = Column(String, nullable=True)
    changed_by = Column(String, nullable=True)  # user who made the change
    timestamp = Column(DateTime(timezone=True), nullable=True)

