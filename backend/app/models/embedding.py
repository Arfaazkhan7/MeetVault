from sqlalchemy import Column, String, Text
from app.models.base import Base

# pgvector is only available when running against PostgreSQL.
# For testing (SQLite) we fall back to Text so the schema still creates cleanly.
try:
    from pgvector.sqlalchemy import Vector as _Vector
    _VECTOR_COL = lambda: Column(_Vector(1536), nullable=True)  # noqa: E731
except Exception:
    _VECTOR_COL = lambda: Column(Text, nullable=True)  # noqa: E731


class Embedding(Base):
    __tablename__ = "embeddings"

    public_id = Column(String, unique=True, index=True, nullable=True)
    company_id = Column(String, nullable=False, index=True)
    project_id = Column(String, nullable=True, index=True)
    meeting_id = Column(String, nullable=True, index=True)

    # 'transcript_segment' | 'meeting_summary' | 'topic' | 'decision' | 'document_page'
    source_type = Column(String, nullable=False, index=True)
    source_id = Column(String, nullable=False, index=True)

    content_text = Column(Text, nullable=True)
    speaker_label = Column(String, nullable=True)
    participant_id = Column(String, nullable=True, index=True)

    embedding = _VECTOR_COL()
    vector_data = Column(Text, nullable=True)  # JSON string array of floats for cross-db similarity math

