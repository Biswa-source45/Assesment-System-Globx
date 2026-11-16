"""the server remembers when each question was first shown to a candidate (the minimum reading time survives a reload)

Revision ID: 0007
Revises: 0006
"""
import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("attempts", sa.Column("seen", sa.JSON(), nullable=False, server_default="{}"))


def downgrade() -> None:
    op.drop_column("attempts", "seen")
