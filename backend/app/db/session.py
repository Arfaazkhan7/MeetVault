import logging
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker, Session
from typing import Generator

from app.core.config import settings
from app.core.runtime import IS_WORKERS
from sqlalchemy.pool import NullPool


def _worker_connect():
    """Open a request-owned connection; Hyperdrive owns the upstream pool."""
    import pg8000.dbapi
    from workers import env

    hd = getattr(env, "HYPERDRIVE", None)
    if hd is None:
        raise RuntimeError("HYPERDRIVE binding is not configured")
    return pg8000.dbapi.connect(
        host=hd.host, port=int(hd.port), user=hd.user,
        password=hd.password, database=hd.database, ssl_context=False,
    )


def _raise_database_connection_error(exc: Exception) -> None:
    message = str(exc)
    if "tenant/user" in message and "pooler.supabase.com" in message:
        raise RuntimeError(
            "Supabase pooler rejected DATABASE_URL: tenant/user was not found. "
            "Open Supabase Dashboard -> Connect -> Session pooler or Transaction pooler, "
            "copy the entire PostgreSQL URI exactly, replace only the password, and set that "
            "same value as DATABASE_URL on Render for meetvault-api. Shared pooler URLs must "
            "use the copied pooler host and username like postgres.<project-ref>; direct URLs "
            "use host db.<project-ref>.supabase.co with username postgres."
        ) from exc
    raise exc

# Engine creation with PostgreSQL / SQLite fallback
try:
    if IS_WORKERS:
        # Import/snapshot must not perform I/O. Connections are created inside
        # requests and closed after each session; never reuse sockets in isolates.
        engine = create_engine(
            "postgresql+pg8000://", creator=_worker_connect, poolclass=NullPool,
        )
    elif "sqlite" in settings.DATABASE_URL:
        logging.info("Connecting to SQLite database")
        engine = create_engine(settings.DATABASE_URL, connect_args={"check_same_thread": False})
    else:
        logging.info("Connecting to Cloud PostgreSQL database (Supabase / Render)")
        engine = create_engine(
            settings.DATABASE_URL,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
            echo=(settings.ENVIRONMENT == "development"),
        )
        # Test the connection. Production schema creation is handled by
        # scripts/bootstrap_db.py so extension fallbacks run first.
        try:
            with engine.connect() as conn:
                pass
        except OperationalError as exc:
            _raise_database_connection_error(exc)
        if settings.ENVIRONMENT != "production":
            from app.models.base import Base
            import app.models  # noqa: F401
            Base.metadata.create_all(bind=engine)
except Exception as e:
    if IS_WORKERS or settings.ENVIRONMENT == "production":
        logging.exception("Production database connection failed")
        raise
    logging.warning(f"PostgreSQL connection failed ({e}). Falling back to local SQLite database.")
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
            ("users", "firebase_uid", "VARCHAR"),
            ("companies", "workspace_code", "VARCHAR"),
            ("tasks", "project_id", "VARCHAR"),
            ("tasks", "source_segment_id", "VARCHAR"),
            ("tasks", "source_start_ms", "FLOAT"),
            ("tasks", "source_end_ms", "FLOAT"),
            ("tasks", "speaker_label", "VARCHAR"),
            ("decisions", "source_segment_id", "VARCHAR"),
            ("decisions", "source_start_ms", "FLOAT"),
            ("decisions", "source_end_ms", "FLOAT"),
            ("decisions", "speaker_label", "VARCHAR"),
            ("evidence", "question_id", "VARCHAR"),
            ("evidence", "risk_id", "VARCHAR"),
            ("evidence", "commitment_id", "VARCHAR"),
            ("evidence", "unresolved_issue_id", "VARCHAR"),
            ("transcript_segments", "recording_id", "VARCHAR"),
            ("transcript_segments", "segment_id", "VARCHAR"),
            ("transcript_segments", "translated_text", "VARCHAR"),
            ("transcript_segments", "words", "JSON"),
            ("transcript_segments", "speaker_user_id", "VARCHAR"),
            ("transcript_segments", "participant_id", "CHAR(36)"),
            ("transcript_segments", "attribution_status", "VARCHAR NOT NULL DEFAULT 'unknown'"),
            ("transcript_segments", "processing_metadata", "JSON"),
            ("meeting_participants", "livekit_identity", "VARCHAR"),
            ("meeting_participants", "identity_mapping_status", "VARCHAR NOT NULL DEFAULT 'unmapped'"),
            ("meeting_participants", "is_guest", "BOOLEAN NOT NULL DEFAULT 0"),
            ("meeting_participants", "display_name", "VARCHAR"),
            ("meeting_recordings", "is_audio_purged", "BOOLEAN NOT NULL DEFAULT 0"),
            ("meeting_recordings", "audio_purged_at", "DATETIME"),
            ("meeting_recordings", "retention_policy", "VARCHAR DEFAULT 'ephemeral_transcript_only'"),
            ("meeting_recordings", "cleanup_error", "TEXT"),
            ("meeting_recordings", "cleanup_retry_count", "INTEGER NOT NULL DEFAULT 0"),
            ("ai_jobs", "current_stage", "VARCHAR NOT NULL DEFAULT 'QUEUED'"),
        ):
            columns = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
            if column not in columns:
                conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

        for index_sql in (
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_transcript_segment_meeting_segid ON transcript_segments(meeting_id, segment_id)",
            "CREATE INDEX IF NOT EXISTS ix_transcript_segments_meeting_start ON transcript_segments(meeting_id, start_time)",
            "CREATE INDEX IF NOT EXISTS ix_transcript_segments_speaker_user ON transcript_segments(meeting_id, speaker_user_id)",
            "CREATE INDEX IF NOT EXISTS ix_transcript_segments_participant ON transcript_segments(meeting_id, participant_id)",
        ):
            try:
                conn.exec_driver_sql(index_sql)
            except Exception:
                pass


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that provides a database session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

