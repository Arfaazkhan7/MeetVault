"""Create the current schema on a fresh database before starting the API."""
from sqlalchemy import Text, text

from app.db.session import engine
from app.models.base import Base
import app.models  # noqa: F401,E402


if engine.dialect.name == "postgresql":
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    except Exception:
        # Render/Postgres plans may not permit extensions. The application also
        # stores JSON vectors in vector_data for portable similarity search.
        from app.models.embedding import Embedding

        Embedding.__table__.c.embedding.type = Text()

Base.metadata.create_all(bind=engine)
