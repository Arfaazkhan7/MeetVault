"""Add ai_job_id to meeting_recordings.

Revision ID: 7c3d2e1b4a55
Revises: 6b2e1f4a9c33
Create Date: 2026-10-21 14:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7c3d2e1b4a55"
down_revision: Union[str, Sequence[str], None] = "6b2e1f4a9c33"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    if "meeting_recordings" in tables:
        columns = {col["name"] for col in inspector.get_columns("meeting_recordings")}
        if "ai_job_id" not in columns:
            op.add_column("meeting_recordings", sa.Column("ai_job_id", sa.String(), nullable=True))
            op.create_index("ix_meeting_recordings_ai_job_id", "meeting_recordings", ["ai_job_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    if "meeting_recordings" in tables:
        columns = {col["name"] for col in inspector.get_columns("meeting_recordings")}
        if "ai_job_id" in columns:
            op.drop_index("ix_meeting_recordings_ai_job_id", table_name="meeting_recordings")
            op.drop_column("meeting_recordings", "ai_job_id")
