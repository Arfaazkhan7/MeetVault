from sqlalchemy import Column, String, Integer, DateTime, Text, UniqueConstraint

from app.models.base import Base


class AIJob(Base):
    __tablename__ = "ai_jobs"
    __table_args__ = (
        UniqueConstraint("recording_id", "job_type", name="uq_ai_job_recording_type"),
    )

    public_id = Column(String, unique=True, index=True, nullable=False)
    meeting_id = Column(String, nullable=False, index=True)
    recording_id = Column(String, nullable=False, index=True)
    company_id = Column(String, nullable=True, index=True)
    requested_by_user_id = Column(String, nullable=False, index=True)
    job_type = Column(String, nullable=False, default="MEETING_AI_PIPELINE")
    status = Column(String, nullable=False, default="QUEUED", index=True)
    retry_count = Column(Integer, nullable=False, default=0)
    max_retries = Column(Integer, nullable=False, default=3)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    failed_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
    provider = Column(String, nullable=True)
