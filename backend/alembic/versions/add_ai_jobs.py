"""Add durable AI jobs

Revision ID: add_ai_jobs
Revises: phase7_recordings, add_speaker_diarization
Create Date: 2026-09-13 08:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "add_ai_jobs"
down_revision: Union[str, Sequence[str], None] = ("phase7_recordings", "add_speaker_diarization")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("meeting_recordings", "company_id", existing_type=sa.String(), nullable=True)
    op.create_table(
        "ai_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("public_id", sa.String(), nullable=False),
        sa.Column("meeting_id", sa.String(), nullable=False),
        sa.Column("recording_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.String(), nullable=True),
        sa.Column("requested_by_user_id", sa.String(), nullable=False),
        sa.Column("job_type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("max_retries", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("provider", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
        sa.UniqueConstraint("recording_id", "job_type", name="uq_ai_job_recording_type"),
    )
    op.create_index("ix_ai_jobs_id", "ai_jobs", ["id"])
    op.create_index("ix_ai_jobs_public_id", "ai_jobs", ["public_id"])
    op.create_index("ix_ai_jobs_meeting_id", "ai_jobs", ["meeting_id"])
    op.create_index("ix_ai_jobs_recording_id", "ai_jobs", ["recording_id"])
    op.create_index("ix_ai_jobs_company_id", "ai_jobs", ["company_id"])
    op.create_index("ix_ai_jobs_requested_by_user_id", "ai_jobs", ["requested_by_user_id"])
    op.create_index("ix_ai_jobs_status", "ai_jobs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_ai_jobs_status", table_name="ai_jobs")
    op.drop_index("ix_ai_jobs_requested_by_user_id", table_name="ai_jobs")
    op.drop_index("ix_ai_jobs_company_id", table_name="ai_jobs")
    op.drop_index("ix_ai_jobs_recording_id", table_name="ai_jobs")
    op.drop_index("ix_ai_jobs_meeting_id", table_name="ai_jobs")
    op.drop_index("ix_ai_jobs_public_id", table_name="ai_jobs")
    op.drop_index("ix_ai_jobs_id", table_name="ai_jobs")
    op.drop_table("ai_jobs")
    op.alter_column("meeting_recordings", "company_id", existing_type=sa.String(), nullable=False)
