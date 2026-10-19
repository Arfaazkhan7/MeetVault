"""Add recording_id, segment_id, translated_text, words to transcript_segments.

Revision ID: 4e9b2a1f8c33
Revises: 3d8a1f7e9b22
Create Date: 2026-10-19 22:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "4e9b2a1f8c33"
down_revision: Union[str, Sequence[str], None] = "3d8a1f7e9b22"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    if "transcript_segments" in tables:
        columns = {col["name"] for col in inspector.get_columns("transcript_segments")}

        if "recording_id" not in columns:
            op.add_column("transcript_segments", sa.Column("recording_id", sa.String(), nullable=True))
            op.create_index("ix_transcript_segments_recording_id", "transcript_segments", ["recording_id"])

        if "segment_id" not in columns:
            op.add_column("transcript_segments", sa.Column("segment_id", sa.String(), nullable=True))
            op.create_index("ix_transcript_segments_segment_id", "transcript_segments", ["segment_id"])

        if "translated_text" not in columns:
            op.add_column("transcript_segments", sa.Column("translated_text", sa.String(), nullable=True))

        if "words" not in columns:
            op.add_column("transcript_segments", sa.Column("words", sa.JSON(), nullable=True))

        # Check existing unique constraints before creating
        constraints = {c["name"] for c in inspector.get_unique_constraints("transcript_segments")}
        if "uq_transcript_segment_meeting_segid" not in constraints:
            op.create_unique_constraint(
                "uq_transcript_segment_meeting_segid",
                "transcript_segments",
                ["meeting_id", "segment_id"]
            )

        indexes = {idx["name"] for idx in inspector.get_indexes("transcript_segments")}
        if "ix_transcript_segments_meeting_start" not in indexes:
            op.create_index(
                "ix_transcript_segments_meeting_start",
                "transcript_segments",
                ["meeting_id", "start_time"]
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    if "transcript_segments" in tables:
        indexes = {idx["name"] for idx in inspector.get_indexes("transcript_segments")}
        if "ix_transcript_segments_meeting_start" in indexes:
            op.drop_index("ix_transcript_segments_meeting_start", table_name="transcript_segments")

        constraints = {c["name"] for c in inspector.get_unique_constraints("transcript_segments")}
        if "uq_transcript_segment_meeting_segid" in constraints:
            op.drop_constraint("uq_transcript_segment_meeting_segid", "transcript_segments", type_="unique")

        columns = {col["name"] for col in inspector.get_columns("transcript_segments")}
        if "words" in columns:
            op.drop_column("transcript_segments", "words")
        if "translated_text" in columns:
            op.drop_column("transcript_segments", "translated_text")
        if "segment_id" in columns:
            if "ix_transcript_segments_segment_id" in indexes:
                op.drop_index("ix_transcript_segments_segment_id", table_name="transcript_segments")
            op.drop_column("transcript_segments", "segment_id")
        if "recording_id" in columns:
            if "ix_transcript_segments_recording_id" in indexes:
                op.drop_index("ix_transcript_segments_recording_id", table_name="transcript_segments")
            op.drop_column("transcript_segments", "recording_id")
