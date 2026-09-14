"""Add current_stage to ai_jobs

Revision ID: 1ba80ec4c563
Revises: add_ai_jobs
Create Date: 2026-09-14 18:26:34.036363

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1ba80ec4c563'
down_revision: Union[str, Sequence[str], None] = 'add_ai_jobs'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('ai_jobs', sa.Column('current_stage', sa.String(), server_default='QUEUED', nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('ai_jobs', 'current_stage')
