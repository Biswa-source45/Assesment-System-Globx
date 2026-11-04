"""archived exams remember the status they had, so restoring puts them back exactly as they were

Revision ID: 0005
Revises: 0004
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tests", sa.Column("archived_from", sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column("tests", "archived_from")
