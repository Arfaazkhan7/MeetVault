"""Add multi-participant, provider identity, and speaker attribution architecture.

Revision ID: 5f0c3d2e1a44
Revises: 4e9b2a1f8c33
Create Date: 2026-10-20 22:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "5f0c3d2e1a44"
down_revision: Union[str, Sequence[str], None] = "4e9b2a1f8c33"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()
    is_pg = bind.dialect.name == "postgresql"

    # 1. Update meeting_participants table
    if "meeting_participants" in tables:
        columns = {col["name"] for col in inspector.get_columns("meeting_participants")}

        if "livekit_identity" not in columns:
            op.add_column("meeting_participants", sa.Column("livekit_identity", sa.String(), nullable=True))
            op.create_index("ix_meeting_participants_livekit_identity", "meeting_participants", ["livekit_identity"])

        if "identity_mapping_status" not in columns:
            op.add_column(
                "meeting_participants",
                sa.Column("identity_mapping_status", sa.String(), nullable=False, server_default="unmapped")
            )

        if "is_guest" not in columns:
            default_val = sa.text("false" if is_pg else "0")
            op.add_column(
                "meeting_participants",
                sa.Column("is_guest", sa.Boolean(), nullable=False, server_default=default_val)
            )

        if "display_name" not in columns:
            op.add_column("meeting_participants", sa.Column("display_name", sa.String(), nullable=True))

        indexes = {idx["name"] for idx in inspector.get_indexes("meeting_participants")}
        if "ix_meeting_participants_meeting_livekit" not in indexes:
            op.create_index(
                "ix_meeting_participants_meeting_livekit",
                "meeting_participants",
                ["meeting_id", "livekit_identity"]
            )

    # 2. Update transcript_segments table
    if "transcript_segments" in tables:
        columns = {col["name"] for col in inspector.get_columns("transcript_segments")}

        if "speaker_user_id" not in columns:
            op.add_column("transcript_segments", sa.Column("speaker_user_id", sa.String(), nullable=True))
            op.create_index("ix_transcript_segments_speaker_user_id", "transcript_segments", ["speaker_user_id"])

        if "participant_id" not in columns:
            uuid_type = postgresql.UUID(as_uuid=True) if is_pg else sa.CHAR(36)
            op.add_column("transcript_segments", sa.Column("participant_id", uuid_type, nullable=True))
            op.create_index("ix_transcript_segments_participant_id", "transcript_segments", ["participant_id"])

        if "attribution_status" not in columns:
            op.add_column(
                "transcript_segments",
                sa.Column("attribution_status", sa.String(), nullable=False, server_default="unknown")
            )

        if "processing_metadata" not in columns:
            op.add_column("transcript_segments", sa.Column("processing_metadata", sa.JSON(), nullable=True))

        indexes = {idx["name"] for idx in inspector.get_indexes("transcript_segments")}
        if "ix_transcript_segments_speaker_user" not in indexes:
            op.create_index(
                "ix_transcript_segments_speaker_user",
                "transcript_segments",
                ["meeting_id", "speaker_user_id"]
            )

        if "ix_transcript_segments_participant" not in indexes:
            op.create_index(
                "ix_transcript_segments_participant",
                "transcript_segments",
                ["meeting_id", "participant_id"]
            )

    # 3. Update meeting_recordings table
    if "meeting_recordings" in tables:
        rec_cols = {col["name"] for col in inspector.get_columns("meeting_recordings")}
        if "is_audio_purged" not in rec_cols:
            default_val = sa.text("false" if is_pg else "0")
            op.add_column("meeting_recordings", sa.Column("is_audio_purged", sa.Boolean(), nullable=False, server_default=default_val))
        if "audio_purged_at" not in rec_cols:
            op.add_column("meeting_recordings", sa.Column("audio_purged_at", sa.DateTime(timezone=True), nullable=True))
        if "retention_policy" not in rec_cols:
            op.add_column("meeting_recordings", sa.Column("retention_policy", sa.String(), nullable=True, server_default="ephemeral_transcript_only"))

    # 4. Repeatable Data Migration / Backfill
    try:
        confirmed_cond = "true" if is_pg else "1"
        unconfirmed_cond = "false" if is_pg else "0"
        bind.execute(
            sa.text("UPDATE transcript_segments SET speaker_user_id = user_id WHERE user_id IS NOT NULL AND (speaker_user_id IS NULL OR speaker_user_id = '')")
        )
        bind.execute(
            sa.text(f"UPDATE transcript_segments SET attribution_status = 'confirmed' WHERE speaker_confirmed = {confirmed_cond}")
        )
        bind.execute(
            sa.text(f"UPDATE transcript_segments SET attribution_status = 'unconfirmed' WHERE speaker_confirmed = {unconfirmed_cond} AND user_id IS NOT NULL")
        )
    except Exception:
        pass


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    if "transcript_segments" in tables:
        indexes = {idx["name"] for idx in inspector.get_indexes("transcript_segments")}
        for idx in ("ix_transcript_segments_participant", "ix_transcript_segments_speaker_user", "ix_transcript_segments_participant_id", "ix_transcript_segments_speaker_user_id"):
            if idx in indexes:
                op.drop_index(idx, table_name="transcript_segments")

        columns = {col["name"] for col in inspector.get_columns("transcript_segments")}
        for col in ("processing_metadata", "attribution_status", "participant_id", "speaker_user_id"):
            if col in columns:
                op.drop_column("transcript_segments", col)

    if "meeting_participants" in tables:
        indexes = {idx["name"] for idx in inspector.get_indexes("meeting_participants")}
        for idx in ("ix_meeting_participants_meeting_livekit", "ix_meeting_participants_livekit_identity"):
            if idx in indexes:
                op.drop_index(idx, table_name="meeting_participants")

        columns = {col["name"] for col in inspector.get_columns("meeting_participants")}
        for col in ("display_name", "is_guest", "identity_mapping_status", "livekit_identity"):
            if col in columns:
                op.drop_column("meeting_participants", col)
