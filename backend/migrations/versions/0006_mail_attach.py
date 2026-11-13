"""a mail can carry an attachment that is made when it is sent (the candidate's report card), named by this reference

Revision ID: 0006
Revises: 0005
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("mail_outbox", sa.Column("attach", sa.String(length=64), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("mail_outbox", "attach")
