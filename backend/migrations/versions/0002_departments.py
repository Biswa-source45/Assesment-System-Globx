"""departments: who an exam is for, and which question types each department offers

Everything that exists before this migration is technical content, so every organisation gets the default
departments and its existing questions and exams are filed under "Technical".

Revision ID: 0002
Revises: 0001
"""
import uuid
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

PEOPLE = ["mcq_single", "mcq_multi", "short", "long"]
DEFAULTS = [("Technical", PEOPLE + ["coding", "sql"]), ("HR", PEOPLE), ("Finance", PEOPLE), ("Operations", PEOPLE), ("General", PEOPLE)]


def upgrade() -> None:
    departments = op.create_table(
        "departments",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("org_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("question_types", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "name", name="uq_department_org_name"),
    )
    op.create_index(op.f("ix_departments_org_id"), "departments", ["org_id"], unique=False)
    for table in ("questions", "tests"):
        op.add_column(table, sa.Column("department_id", sa.String(length=32), nullable=True))
        op.create_index(op.f(f"ix_{table}_department_id"), table, ["department_id"], unique=False)
        op.create_foreign_key(f"fk_{table}_department", table, "departments", ["department_id"], ["id"])

    bind = op.get_bind()
    now = datetime.now(timezone.utc)
    for (org_id,) in bind.execute(sa.text("SELECT id FROM organizations")).fetchall():
        op.bulk_insert(departments, [{"id": uuid.uuid4().hex, "org_id": org_id, "name": name, "question_types": types,
                                      "created_at": now + timedelta(milliseconds=i)}  # staggered: the list is sorted by creation time
                                     for i, (name, types) in enumerate(DEFAULTS)])
    for table in ("questions", "tests"):
        bind.execute(sa.text(
            f"UPDATE {table} SET department_id = (SELECT d.id FROM departments d "
            f"WHERE d.org_id = {table}.org_id AND d.name = 'Technical')"))


def downgrade() -> None:
    for table in ("tests", "questions"):
        op.drop_constraint(f"fk_{table}_department", table, type_="foreignkey")
        op.drop_index(op.f(f"ix_{table}_department_id"), table_name=table)
        op.drop_column(table, "department_id")
    op.drop_index(op.f("ix_departments_org_id"), table_name="departments")
    op.drop_table("departments")
