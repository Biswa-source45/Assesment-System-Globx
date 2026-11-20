"""a mail can carry a formatted (HTML) version beside its plain text (the exam login mail)

Revision ID: 0008
Revises: 0007
"""
import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("mail_outbox", sa.Column("body_html", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("mail_outbox", "body_html")
