from alembic import command
from alembic.config import Config
from sqlalchemy import text


def _config():
    from app.core.config import BACKEND_DIR
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return cfg


def test_a_database_from_before_migrations_is_adopted_and_keeps_its_data():
    from app.db import engine, migrate, reset_schema
    from app.models import Organization, Question, Test
    reset_schema()
    command.upgrade(_config(), "0001")  # the schema as it was before departments existed...
    with engine.begin() as c:
        c.execute(text("DROP TABLE alembic_version"))  # ...with no migration history, like a database from the old days
        c.execute(Organization.__table__.insert().values(id="o1", name="Old Co", slug="old-co"))
        c.execute(Question.__table__.insert().values(id="q1", org_id="o1", type="mcq_single", title="Old question"))
        c.execute(Test.__table__.insert().values(id="t1", org_id="o1", title="Old exam"))
    migrate()
    with engine.connect() as c:
        assert [r[0] for r in c.execute(text("SELECT name FROM departments ORDER BY name"))] == ["Finance", "General", "HR", "Operations", "Technical"]
        for table in ("questions", "tests"):  # all old content is technical
            assert c.execute(text(f"SELECT d.name FROM {table} x JOIN departments d ON d.id = x.department_id")).scalar() == "Technical"
    migrate()  # starting again changes nothing


def test_the_models_and_the_migrations_agree():
    """Fails if someone edits app/models.py without writing a migration (alembic revision --autogenerate)."""
    from app.db import migrate, reset_schema
    reset_schema()
    migrate()
    command.check(_config())
