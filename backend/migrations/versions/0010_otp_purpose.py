"""a one-time code says what it is for (candidate sign-in, or a staff user changing their e-mail) and, for the e-mail change, which new address it is good for

Revision ID: 0010
Revises: 0009
"""
import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("otp_codes", sa.Column("purpose", sa.String(20), nullable=False, server_default="login"))
    op.add_column("otp_codes", sa.Column("payload", sa.String(255), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("otp_codes", "payload")
    op.drop_column("otp_codes", "purpose")
