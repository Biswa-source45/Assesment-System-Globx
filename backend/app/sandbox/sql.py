"""SQL sandboxes. SQLite is always available (in-memory DB per run); PostgreSQL and MySQL are used
when a DSN is configured and the driver is installed. Each run gets a fresh schema/database, the
candidate query runs read-only with a statement timeout and a row limit."""
from __future__ import annotations

import datetime as _dt
import decimal
import re
import secrets
import sqlite3
import time
from typing import Any, Dict, List, Optional

from app.core.config import get_settings

ROW_LIMIT = 10000


def _clean_query(q: str) -> str:
    q = (q or "").strip()
    while q.endswith(";"):
        q = q[:-1].rstrip()
    return q


def _has_multiple_statements(q: str) -> bool:
    no_str = re.sub(r"'(?:''|[^'])*'", "''", q)
    no_str = re.sub(r"--.*", "", no_str)
    no_str = re.sub(r"/\*[\s\S]*?\*/", "", no_str)
    return ";" in no_str


def _norm(v: Any) -> Any:
    if isinstance(v, decimal.Decimal):
        v = float(v)
    if isinstance(v, float):
        return round(v, 6) if v != int(v) else (int(v) if abs(v) < 1e15 else v)
    if isinstance(v, (bytes, bytearray)):
        return v.hex()
    if isinstance(v, (_dt.date, _dt.datetime, _dt.time)):
        return v.isoformat()
    return v


def result_payload(columns: List[str], rows: List[tuple]) -> Dict:
    return {"columns": list(columns), "rows": [[_norm(v) for v in r] for r in rows]}


_DENIED = {sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH, sqlite3.SQLITE_PRAGMA}


def _deny_escape(action, *_):
    """ATTACH would let a candidate open the platform's own database file; PRAGMA could undo query_only."""
    return sqlite3.SQLITE_DENY if action in _DENIED else sqlite3.SQLITE_OK


class SqlEngine:
    key = ""
    name = ""

    def available(self) -> bool:
        return False

    def info(self) -> Dict:
        return {"key": self.key, "name": self.name, "available": self.available()}

    def run(self, schema: str, seed: str, dataset: str, query: str, timeout_s: float = 3.0,
            readonly: bool = True) -> Dict:
        raise NotImplementedError


class SQLiteEngine(SqlEngine):
    key, name = "sqlite", f"SQLite {sqlite3.sqlite_version}"

    def available(self):
        return True

    def run(self, schema, seed, dataset, query, timeout_s=3.0, readonly=True):
        q = _clean_query(query)
        if not q:
            return {"ok": False, "verdict": "RE", "error": "Empty query"}
        if _has_multiple_statements(q):
            return {"ok": False, "verdict": "RE", "error": "Only one SQL statement is allowed"}
        con = sqlite3.connect(":memory:")
        t0 = time.perf_counter()
        try:
            con.executescript((schema or "") + "\n" + (seed or "") + "\n" + (dataset or ""))
            if readonly:
                con.execute("PRAGMA query_only = ON")
            con.set_authorizer(_deny_escape)  # after the trusted setup scripts, before the candidate query
            deadline = time.perf_counter() + timeout_s
            con.set_progress_handler(lambda: 1 if time.perf_counter() > deadline else 0, 2000)
            cur = con.execute(q)
            cols = [d[0] for d in (cur.description or [])]
            rows = cur.fetchmany(ROW_LIMIT + 1)
            ms = int((time.perf_counter() - t0) * 1000)
            if len(rows) > ROW_LIMIT:
                return {"ok": False, "verdict": "OLE", "error": f"More than {ROW_LIMIT} rows returned", "time_ms": ms}
            return {"ok": True, **result_payload(cols, rows), "time_ms": ms}
        except sqlite3.OperationalError as e:
            ms = int((time.perf_counter() - t0) * 1000)
            if "interrupted" in str(e):
                return {"ok": False, "verdict": "TLE", "error": "Query exceeded the time limit", "time_ms": ms}
            return {"ok": False, "verdict": "RE", "error": f"{e}", "time_ms": ms}
        except sqlite3.Error as e:
            return {"ok": False, "verdict": "RE", "error": f"{e}", "time_ms": int((time.perf_counter() - t0) * 1000)}
        finally:
            con.close()


class PostgresEngine(SqlEngine):
    key, name = "postgresql", "PostgreSQL"

    def available(self):
        if not get_settings().sql_postgres_dsn:
            return False
        try:
            import psycopg  # noqa: F401
            return True
        except Exception:
            return False

    def run(self, schema, seed, dataset, query, timeout_s=3.0, readonly=True):
        import psycopg
        q = _clean_query(query)
        if _has_multiple_statements(q):
            return {"ok": False, "verdict": "RE", "error": "Only one SQL statement is allowed"}
        sch = "judge_" + secrets.token_hex(6)
        t0 = time.perf_counter()
        try:
            with psycopg.connect(get_settings().sql_postgres_dsn, autocommit=True, connect_timeout=5) as con:
                try:
                    con.execute(f'CREATE SCHEMA "{sch}"')
                    con.execute(f'SET search_path TO "{sch}"')
                    for part in (schema, seed, dataset):
                        if part and part.strip():
                            con.execute(part)
                    with con.transaction():
                        con.execute("SET TRANSACTION READ ONLY" if readonly else "SELECT 1")
                        con.execute(f"SET LOCAL statement_timeout = {int(timeout_s * 1000)}")
                        cur = con.execute(q)
                        cols = [d.name for d in (cur.description or [])]
                        rows = cur.fetchmany(ROW_LIMIT + 1)
                    ms = int((time.perf_counter() - t0) * 1000)
                    if len(rows) > ROW_LIMIT:
                        return {"ok": False, "verdict": "OLE", "error": "Row limit exceeded", "time_ms": ms}
                    return {"ok": True, **result_payload(cols, rows), "time_ms": ms}
                finally:
                    con.execute(f'DROP SCHEMA IF EXISTS "{sch}" CASCADE')
        except Exception as e:
            ms = int((time.perf_counter() - t0) * 1000)
            msg = str(e).strip()
            verdict = "TLE" if "statement timeout" in msg else "RE"
            return {"ok": False, "verdict": verdict, "error": msg[:2000], "time_ms": ms}


class MySQLEngine(SqlEngine):
    key, name = "mysql", "MySQL"

    def available(self):
        if not get_settings().sql_mysql_dsn:
            return False
        try:
            import pymysql  # noqa: F401
            return True
        except Exception:
            return False

    def _conn(self, db: Optional[str] = None):
        import pymysql
        from urllib.parse import urlparse
        u = urlparse(get_settings().sql_mysql_dsn)
        return pymysql.connect(host=u.hostname or "localhost", port=u.port or 3306, user=u.username,
                               password=u.password or "", database=db, autocommit=True,
                               client_flag=pymysql.constants.CLIENT.MULTI_STATEMENTS, connect_timeout=5)

    def run(self, schema, seed, dataset, query, timeout_s=3.0, readonly=True):
        q = _clean_query(query)
        if _has_multiple_statements(q):
            return {"ok": False, "verdict": "RE", "error": "Only one SQL statement is allowed"}
        db = "judge_" + secrets.token_hex(6)
        t0 = time.perf_counter()
        admin = None
        try:
            admin = self._conn()
            with admin.cursor() as c:
                c.execute(f"CREATE DATABASE `{db}`")
            con = self._conn(db)
            try:
                with con.cursor() as c:
                    for part in (schema, seed, dataset):
                        if part and part.strip():
                            c.execute(part)
                            while c.nextset():
                                pass
                    if readonly:
                        c.execute("SET SESSION TRANSACTION READ ONLY")
                    c.execute(f"SET SESSION max_execution_time = {int(timeout_s * 1000)}")
                    c.execute(q)
                    cols = [d[0] for d in (c.description or [])]
                    rows = c.fetchmany(ROW_LIMIT + 1)
            finally:
                con.close()
            ms = int((time.perf_counter() - t0) * 1000)
            if len(rows) > ROW_LIMIT:
                return {"ok": False, "verdict": "OLE", "error": "Row limit exceeded", "time_ms": ms}
            return {"ok": True, **result_payload(cols, list(rows)), "time_ms": ms}
        except Exception as e:
            msg = str(e)
            return {"ok": False, "verdict": "TLE" if "maximum statement execution time" in msg else "RE",
                    "error": msg[:2000], "time_ms": int((time.perf_counter() - t0) * 1000)}
        finally:
            if admin is not None:
                try:
                    with admin.cursor() as c:
                        c.execute(f"DROP DATABASE IF EXISTS `{db}`")
                    admin.close()
                except Exception:
                    pass


SQL_ENGINES: Dict[str, SqlEngine] = {e.key: e for e in (SQLiteEngine(), PostgresEngine(), MySQLEngine())}


def compare_results(actual: Dict, expected: Dict, ordered: bool) -> bool:
    ac = [c.lower() for c in actual.get("columns", [])]
    ec = [c.lower() for c in expected.get("columns", [])]
    if ac != ec:
        return False
    ar = [[_norm(v) for v in r] for r in actual.get("rows", [])]
    er = [[_norm(v) for v in r] for r in expected.get("rows", [])]
    if ordered:
        return ar == er
    key = lambda r: [repr(x) for x in r]
    return sorted(ar, key=key) == sorted(er, key=key)
