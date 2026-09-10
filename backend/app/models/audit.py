from sqlalchemy import Column, String, ForeignKey, JSON
from app.models.base import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    company_id = Column(ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action = Column(String, nullable=False)
    entity_type = Column(String, nullable=False)
    entity_id = Column(String, nullable=False)
    # JSON works on both PostgreSQL and SQLite (testing); JSONB cast added via migration
    details = Column(JSON, nullable=True)
