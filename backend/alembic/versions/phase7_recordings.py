"""Add meeting recordings

Revision ID: phase7_recordings
Revises: add_transcription_fields
Create Date: 2026-09-06 15:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "phase7_recordings"
down_revision: Union[str, Sequence[str], None] = "add_transcription_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "meeting_topics",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("company_id", sa.String(), nullable=False),
        sa.Column("meeting_id", sa.String(), nullable=False),
        sa.Column("topic_id", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("meeting_id", "topic_id", name="uq_meeting_topic"),
    )
    op.create_index("ix_meeting_topics_id", "meeting_topics", ["id"])
    op.create_index("ix_meeting_topics_company_id", "meeting_topics", ["company_id"])
    op.create_index("ix_meeting_topics_meeting_id", "meeting_topics", ["meeting_id"])
    op.create_index("ix_meeting_topics_topic_id", "meeting_topics", ["topic_id"])

    op.create_table(
        "meeting_recordings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("meeting_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.String(), nullable=False),
        sa.Column("uploaded_by_user_id", sa.String(), nullable=False),
        sa.Column("storage_backend", sa.String(), nullable=False),
        sa.Column("storage_bucket", sa.String(), nullable=False),
        sa.Column("storage_path", sa.String(), nullable=False),
        sa.Column("original_filename", sa.String(), nullable=False),
        sa.Column("file_type", sa.String(), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("processing_status", sa.String(), nullable=False),
        sa.Column("processing_error", sa.Text(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_path"),
    )
    op.create_index("ix_meeting_recordings_id", "meeting_recordings", ["id"])
    op.create_index("ix_meeting_recordings_meeting_id", "meeting_recordings", ["meeting_id"])
    op.create_index("ix_meeting_recordings_company_id", "meeting_recordings", ["company_id"])
    op.create_index("ix_meeting_recordings_uploaded_by_user_id", "meeting_recordings", ["uploaded_by_user_id"])
    op.create_index("ix_meeting_recordings_processing_status", "meeting_recordings", ["processing_status"])
    op.create_index("ix_meeting_recordings_deleted_at", "meeting_recordings", ["deleted_at"])
    op.create_index("ix_meeting_recordings_storage_path", "meeting_recordings", ["storage_path"])
    op.create_index("ix_meeting_recordings_company_meeting", "meeting_recordings", ["company_id", "meeting_id"])


def downgrade() -> None:
    op.drop_index("ix_meeting_recordings_company_meeting", table_name="meeting_recordings")
    op.drop_index("ix_meeting_recordings_storage_path", table_name="meeting_recordings")
    op.drop_index("ix_meeting_recordings_deleted_at", table_name="meeting_recordings")
    op.drop_index("ix_meeting_recordings_processing_status", table_name="meeting_recordings")
    op.drop_index("ix_meeting_recordings_uploaded_by_user_id", table_name="meeting_recordings")
    op.drop_index("ix_meeting_recordings_company_id", table_name="meeting_recordings")
    op.drop_index("ix_meeting_recordings_meeting_id", table_name="meeting_recordings")
    op.drop_index("ix_meeting_recordings_id", table_name="meeting_recordings")
    op.drop_table("meeting_recordings")
    op.drop_index("ix_meeting_topics_topic_id", table_name="meeting_topics")
    op.drop_index("ix_meeting_topics_meeting_id", table_name="meeting_topics")
    op.drop_index("ix_meeting_topics_company_id", table_name="meeting_topics")
    op.drop_index("ix_meeting_topics_id", table_name="meeting_topics")
    op.drop_table("meeting_topics")
