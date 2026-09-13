import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from typing import Generator

from app.core.config import settings

# Engine creation with PostgreSQL / SQLite fallback
try:
    if "sqlite" in settings.DATABASE_URL:
        engine = create_engine(settings.DATABASE_URL, connect_args={"check_same_thread": False})
    else:
        engine = create_engine(
            settings.DATABASE_URL,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
            echo=(settings.ENVIRONMENT == "development"),
        )
        # Test connection
        with engine.connect() as conn:
            pass
except Exception as e:
    if settings.ENVIRONMENT == "production":
        logging.exception("Production database connection failed")
        raise
    logging.warning(f"PostgreSQL connection failed ({e}). Falling back to SQLite local database.")
    sqlite_url = "sqlite:///./meetingdb.db"
    engine = create_engine(sqlite_url, connect_args={"check_same_thread": False})
    from app.models.base import Base
    import app.models  # noqa: F401
    Base.metadata.create_all(bind=engine)

    # SQLite create_all() does not alter an existing local database. Keep
    # older developer databases usable after model additions.
    with engine.begin() as conn:
        for table, column, definition in (
            ("users", "account_type", "VARCHAR NOT NULL DEFAULT 'personal'"),
            ("companies", "workspace_code", "VARCHAR"),
        ):
            columns = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
            if column not in columns:
                conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that provides a database session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
