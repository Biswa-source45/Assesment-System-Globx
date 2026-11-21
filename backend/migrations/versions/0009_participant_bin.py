"""a deleted participant goes to the bin first: the assignment keeps the moment it was binned, empty for everyone else

Revision ID: 0009
Revises: 0008
"""
import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("assignments", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("assignments", "deleted_at")
