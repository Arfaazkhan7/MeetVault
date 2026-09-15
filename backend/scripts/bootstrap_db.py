"""Create the current schema on a fresh database before starting the API."""
from sqlalchemy import Text, text

from app.db.session import engine
from app.models.base import Base
import app.models  # noqa: F401,E402


if engine.dialect.name == "postgresql":
    vector_available = False
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            vector_available = bool(
                connection.execute(
                    text("SELECT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'vector')")
                ).scalar()
            )
    except Exception:
        pass

    # Supabase projects may not have pgvector enabled. The application also
    # stores JSON vectors in vector_data for portable similarity search.
    if not vector_available:
        from app.models.embedding import Embedding
        Embedding.__table__.c.embedding.type = Text()

Base.metadata.create_all(bind=engine)

# Seed default system admin and sample workspace if they don't exist
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from seed import seed
seed()
