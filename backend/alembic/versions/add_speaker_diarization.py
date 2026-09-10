"""Add speaker diarization tables and fields

Revision ID: add_speaker_diarization
Revises: add_analysis_tables
Create Date: 2026-09-06 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_speaker_diarization'
down_revision: Union[str, Sequence[str], None] = 'add_analysis_tables'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    
    # Add speaker fields to transcript_segments table
    op.add_column('transcript_segments', sa.Column('speaker_confirmed', sa.Boolean(), nullable=False, server_default='false'))
    
    # Create speaker_mappings table
    op.create_table(
        'speaker_mappings',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('meeting_id', sa.String(), nullable=False),
        sa.Column('speaker_label', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=True),
        sa.Column('is_confirmed', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('confidence', sa.String(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_speaker_mappings_meeting_id'), 'speaker_mappings', ['meeting_id'], unique=False)
    op.create_index(op.f('ix_speaker_mappings_speaker_label'), 'speaker_mappings', ['speaker_label'], unique=False)
    op.create_index(op.f('ix_speaker_mappings_user_id'), 'speaker_mappings', ['user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    
    # Drop speaker_mappings table
    op.drop_index(op.f('ix_speaker_mappings_user_id'), table_name='speaker_mappings')
    op.drop_index(op.f('ix_speaker_mappings_speaker_label'), table_name='speaker_mappings')
    op.drop_index(op.f('ix_speaker_mappings_meeting_id'), table_name='speaker_mappings')
    op.drop_table('speaker_mappings')
    
    # Remove speaker fields from transcript_segments table
    op.drop_column('transcript_segments', 'speaker_confirmed')