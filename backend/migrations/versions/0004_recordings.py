"""recordings: whole-exam video pieces stored on disk, deleted after the exam's retention days

Revision ID: 0004
Revises: 0003
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "recordings",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("attempt_id", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=12), nullable=False),
        sa.Column("part", sa.String(length=24), nullable=False),
        sa.Column("path", sa.String(length=400), nullable=False),
        sa.Column("bytes", sa.Integer(), nullable=False),
        sa.Column("pieces", sa.Integer(), nullable=False),
        sa.Column("gaps", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expired", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["attempt_id"], ["attempts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("attempt_id", "kind", "part", name="uq_recording_part"),
    )
    op.create_index(op.f("ix_recordings_attempt_id"), "recordings", ["attempt_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_recordings_attempt_id"), table_name="recordings")
    op.drop_table("recordings")
