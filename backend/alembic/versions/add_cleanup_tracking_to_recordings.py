"""Add cleanup_error and cleanup_retry_count to meeting_recordings.

Revision ID: 6b2e1f4a9c33
Revises: 5f0c3d2e1a44
Create Date: 2026-10-21 09:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "6b2e1f4a9c33"
down_revision: Union[str, Sequence[str], None] = "5f0c3d2e1a44"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    if "meeting_recordings" in tables:
        columns = {col["name"] for col in inspector.get_columns("meeting_recordings")}
        if "cleanup_error" not in columns:
            op.add_column("meeting_recordings", sa.Column("cleanup_error", sa.Text(), nullable=True))
        if "cleanup_retry_count" not in columns:
            op.add_column(
                "meeting_recordings",
                sa.Column("cleanup_retry_count", sa.Integer(), nullable=False, server_default="0"),
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    if "meeting_recordings" in tables:
        columns = {col["name"] for col in inspector.get_columns("meeting_recordings")}
        if "cleanup_retry_count" in columns:
            op.drop_column("meeting_recordings", "cleanup_retry_count")
        if "cleanup_error" in columns:
            op.drop_column("meeting_recordings", "cleanup_error")
