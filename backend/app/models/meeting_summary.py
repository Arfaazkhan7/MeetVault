from sqlalchemy import Column, String, Text
from sqlalchemy.orm import relationship
from .base import Base


class MeetingSummary(Base):
    __tablename__ = 'meeting_summaries'
    
    meeting_id = Column(String, nullable=False, index=True, unique=True)
    company_id = Column(String, nullable=False, index=True)
    
    # Summary content
    summary_text = Column(Text, nullable=False)
    key_takeaways = Column(Text, nullable=True)  # JSON array of key points
    
    # AI extraction metadata
    extracted_by = Column(String, nullable=True)
    extraction_confidence = Column(String, nullable=True)
    extraction_metadata = Column(Text, nullable=True)  # JSON string