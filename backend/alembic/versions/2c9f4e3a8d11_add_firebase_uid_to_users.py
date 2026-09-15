"""Add Firebase UID used to link Google accounts."""
from alembic import op
import sqlalchemy as sa


revision = "2c9f4e3a8d11"
down_revision = "1ba80ec4c563"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("users")}
    if "firebase_uid" not in columns:
        op.add_column("users", sa.Column("firebase_uid", sa.String(), nullable=True))
        op.create_index("ix_users_firebase_uid", "users", ["firebase_uid"], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("users")}
    if "firebase_uid" in columns:
        op.drop_index("ix_users_firebase_uid", table_name="users")
        op.drop_column("users", "firebase_uid")
