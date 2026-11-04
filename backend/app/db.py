"""Database engine / session."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Iterator

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import BACKEND_DIR, get_settings

_s = get_settings()
if _s.is_sqlite:
    Path(_s.database_url.replace("sqlite:///", "")).parent.mkdir(parents=True, exist_ok=True)
engine = create_engine(_s.database_url, future=True, pool_pre_ping=True,
                       connect_args={"check_same_thread": False, "timeout": 30} if _s.is_sqlite else {})

if _s.is_sqlite:
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _):  # pragma: no cover - trivial
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def migrate() -> None:
    """Bring the database schema up to date (the app does this on start). A database created before migrations
    existed is adopted as revision 0001 first, so existing data is kept."""
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))  # works from any working directory
    tables = set(inspect(engine).get_table_names())
    if "organizations" in tables and "alembic_version" not in tables:
        command.stamp(cfg, "0001")
    command.upgrade(cfg, "head")


def reset_schema() -> None:
    """Drop every table, including the migration history. Development and tests only (seed --reset)."""
    for attempt in range(5):
        try:
            Base.metadata.drop_all(engine)  # one transaction: a failure leaves every table in place
            break
        except OperationalError as e:
            # A background job that is still finishing (grading, the sweeper) can lock tables in the opposite order; Postgres then
            # ends one of the two as the "deadlock victim" and the advice is to ask again, which works once the job's transaction is over.
            if "deadlock detected" not in str(e) or attempt == 4:
                raise
            time.sleep(1)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
