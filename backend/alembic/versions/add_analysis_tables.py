"""Add analysis tables and fields

Revision ID: add_analysis_tables
Revises: add_transcription_fields
Create Date: 2026-09-06 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_analysis_tables'
down_revision: Union[str, Sequence[str], None] = 'add_transcription_fields'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    
    # Add analysis status to meetings table
    op.add_column('meetings', sa.Column('analysis_status', sa.String(), nullable=False, server_default='pending'))
    op.add_column('meetings', sa.Column('analysis_error', sa.Text(), nullable=True))
    
    # Create meeting_summaries table
    op.create_table(
        'meeting_summaries',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('meeting_id', sa.String(), nullable=False),
        sa.Column('company_id', sa.String(), nullable=False),
        sa.Column('summary_text', sa.Text(), nullable=False),
        sa.Column('key_takeaways', sa.Text(), nullable=True),
        sa.Column('questions', sa.Text(), nullable=True),
        sa.Column('answers', sa.Text(), nullable=True),
        sa.Column('suggestions', sa.Text(), nullable=True),
        sa.Column('proposals', sa.Text(), nullable=True),
        sa.Column('concerns', sa.Text(), nullable=True),
        sa.Column('agreements', sa.Text(), nullable=True),
        sa.Column('disagreements', sa.Text(), nullable=True),
        sa.Column('extracted_by', sa.String(), nullable=True),
        sa.Column('extraction_confidence', sa.String(), nullable=True),
        sa.Column('extraction_metadata', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('meeting_id')
    )
    op.create_index(op.f('ix_meeting_summaries_meeting_id'), 'meeting_summaries', ['meeting_id'], unique=True)
    op.create_index(op.f('ix_meeting_summaries_company_id'), 'meeting_summaries', ['company_id'], unique=False)
    
    # Update topics table to include meeting_id
    # First make it nullable to avoid constraint issues
    op.add_column('topics', sa.Column('meeting_id', sa.String(), nullable=True))
    op.add_column('topics', sa.Column('importance', sa.String(), nullable=True))
    op.add_column('topics', sa.Column('extracted_by', sa.String(), nullable=True))
    op.add_column('topics', sa.Column('extraction_confidence', sa.String(), nullable=True))
    
    # Update decisions table
    op.add_column('decisions', sa.Column('decision_type', sa.String(), nullable=True))
    op.add_column('decisions', sa.Column('proposer_id', sa.String(), nullable=True))
    op.add_column('decisions', sa.Column('confidence_level', sa.String(), nullable=True))
    op.add_column('decisions', sa.Column('extracted_by', sa.String(), nullable=True))
    op.add_column('decisions', sa.Column('extraction_confidence', sa.String(), nullable=True))
    
    # Update tasks table
    op.add_column('tasks', sa.Column('priority', sa.String(), nullable=True))
    op.add_column('tasks', sa.Column('deadline', sa.DateTime(timezone=True), nullable=True))
    op.add_column('tasks', sa.Column('estimated_hours', sa.String(), nullable=True))
    op.add_column('tasks', sa.Column('extracted_by', sa.String(), nullable=True))
    op.add_column('tasks', sa.Column('extraction_confidence', sa.String(), nullable=True))
    
    # Create evidence table
    op.create_table(
        'evidence',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('meeting_id', sa.String(), nullable=False),
        sa.Column('transcript_segment_id', sa.String(), nullable=True),
        sa.Column('timestamp', sa.Float(), nullable=True),
        sa.Column('speaker_label', sa.String(), nullable=True),
        sa.Column('user_id', sa.String(), nullable=True),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('context', sa.Text(), nullable=True),
        sa.Column('evidence_type', sa.String(), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('topic_id', sa.String(), nullable=True),
        sa.Column('decision_id', sa.String(), nullable=True),
        sa.Column('task_id', sa.String(), nullable=True),
        sa.Column('extracted_by', sa.String(), nullable=True),
        sa.Column('extraction_metadata', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_evidence_meeting_id'), 'evidence', ['meeting_id'], unique=False)
    op.create_index(op.f('ix_evidence_transcript_segment_id'), 'evidence', ['transcript_segment_id'], unique=False)
    op.create_index(op.f('ix_evidence_user_id'), 'evidence', ['user_id'], unique=False)
    op.create_index(op.f('ix_evidence_evidence_type'), 'evidence', ['evidence_type'], unique=False)
    op.create_index(op.f('ix_evidence_topic_id'), 'evidence', ['topic_id'], unique=False)
    op.create_index(op.f('ix_evidence_decision_id'), 'evidence', ['decision_id'], unique=False)
    op.create_index(op.f('ix_evidence_task_id'), 'evidence', ['task_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    
    # Drop evidence table
    op.drop_index(op.f('ix_evidence_task_id'), table_name='evidence')
    op.drop_index(op.f('ix_evidence_decision_id'), table_name='evidence')
    op.drop_index(op.f('ix_evidence_topic_id'), table_name='evidence')
    op.drop_index(op.f('ix_evidence_evidence_type'), table_name='evidence')
    op.drop_index(op.f('ix_evidence_user_id'), table_name='evidence')
    op.drop_index(op.f('ix_evidence_transcript_segment_id'), table_name='evidence')
    op.drop_index(op.f('ix_evidence_meeting_id'), table_name='evidence')
    op.drop_table('evidence')
    
    # Remove columns from tasks table
    op.drop_column('tasks', 'extraction_confidence')
    op.drop_column('tasks', 'extracted_by')
    op.drop_column('tasks', 'estimated_hours')
    op.drop_column('tasks', 'deadline')
    op.drop_column('tasks', 'priority')
    
    # Remove columns from decisions table
    op.drop_column('decisions', 'extraction_confidence')
    op.drop_column('decisions', 'extracted_by')
    op.drop_column('decisions', 'confidence_level')
    op.drop_column('decisions', 'proposer_id')
    op.drop_column('decisions', 'decision_type')
    
    # Remove columns from topics table
    op.drop_column('topics', 'extraction_confidence')
    op.drop_column('topics', 'extracted_by')
    op.drop_column('topics', 'importance')
    op.drop_column('topics', 'meeting_id')
    
    # Drop meeting_summaries table
    op.drop_index(op.f('ix_meeting_summaries_company_id'), table_name='meeting_summaries')
    op.drop_index(op.f('ix_meeting_summaries_meeting_id'), table_name='meeting_summaries')
    op.drop_table('meeting_summaries')
    
    # Remove analysis status from meetings table
    op.drop_column('meetings', 'analysis_error')
    op.drop_column('meetings', 'analysis_status')