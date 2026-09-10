"""Add transcription fields to meetings table

Revision ID: add_transcription_fields
Revises: 0f8de96e1991
Create Date: 2026-09-06 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_transcription_fields'
down_revision: Union[str, Sequence[str], None] = '0f8de96e1991'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('meetings', sa.Column('transcription_status', sa.String(), nullable=False, server_default='pending'))
    op.add_column('meetings', sa.Column('transcription_error', sa.Text(), nullable=True))
    op.add_column('meetings', sa.Column('recording_url', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('meetings', 'recording_url')
    op.drop_column('meetings', 'transcription_error')
    op.drop_column('meetings', 'transcription_status')