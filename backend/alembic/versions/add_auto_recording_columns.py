"""Add session_id, egress_id, and source to meeting_recordings for automatic recording lifecycle."""
from alembic import op
import sqlalchemy as sa


revision = "3d8a1f7e9b22"
down_revision = "2c9f4e3a8d11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()
    if "meeting_recordings" in tables:
        columns = {column["name"] for column in inspector.get_columns("meeting_recordings")}
        if "session_id" not in columns:
            op.add_column("meeting_recordings", sa.Column("session_id", sa.String(), nullable=True))
            op.create_index("ix_meeting_recordings_session_id", "meeting_recordings", ["session_id"])
        if "egress_id" not in columns:
            op.add_column("meeting_recordings", sa.Column("egress_id", sa.String(), nullable=True))
            op.create_index("ix_meeting_recordings_egress_id", "meeting_recordings", ["egress_id"])
        if "source" not in columns:
            op.add_column("meeting_recordings", sa.Column("source", sa.String(), nullable=True, server_default="client_mixed_audio"))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()
    if "meeting_recordings" in tables:
        columns = {column["name"] for column in inspector.get_columns("meeting_recordings")}
        if "session_id" in columns:
            op.drop_index("ix_meeting_recordings_session_id", table_name="meeting_recordings")
            op.drop_column("meeting_recordings", "session_id")
        if "egress_id" in columns:
            op.drop_index("ix_meeting_recordings_egress_id", table_name="meeting_recordings")
            op.drop_column("meeting_recordings", "egress_id")
        if "source" in columns:
            op.drop_column("meeting_recordings", "source")
