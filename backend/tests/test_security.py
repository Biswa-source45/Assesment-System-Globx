import os
import sqlite3
import tempfile

from fastapi.testclient import TestClient


def test_sql_cannot_attach_other_database():
    from app.sandbox.sql import SQL_ENGINES
    victim = os.path.join(tempfile.mkdtemp(), "victim.db")
    v = sqlite3.connect(victim)
    v.execute("CREATE TABLE users(email TEXT)")
    v.execute("INSERT INTO users VALUES ('admin@example.com')")
    v.commit()
    v.close()
    eng = SQL_ENGINES["sqlite"]
    r = eng.run("CREATE TABLE t(x INTEGER);", "", "", f"ATTACH DATABASE '{victim}' AS v")
    assert not r["ok"], "ATTACH must be denied"
    r = eng.run("CREATE TABLE t(x INTEGER);", "", "INSERT INTO t VALUES (1);", "PRAGMA query_only = OFF")
    assert not r["ok"], "PRAGMA must be denied"
    r = eng.run("CREATE TABLE t(x INTEGER);", "", "INSERT INTO t VALUES (1);", "SELECT x FROM t")
    assert r["ok"] and r["rows"] == [[1]], "ordinary SELECT still works"


def test_staff_cannot_read_other_orgs_submission():
    from sqlalchemy import select
    from app.core.security import jwt_encode
    from app.db import SessionLocal
    from app.main import app
    from app.models import CodeSubmission, Organization, Question, User, UserRole, uid
    from app.seed import seed
    seed(reset=True)
    db = SessionLocal()
    q = db.scalars(select(Question).where(Question.type == "coding")).first()
    sub = CodeSubmission(id=uid(), question_id=q.id, kind="validate", language="python", source="print(1)", status="done",
                         result={"cases": []})
    other = Organization(id=uid(), name="Other Org", slug="other-org")
    db.add_all([sub, other])
    db.flush()
    u = User(id=uid(), org_id=other.id, email="rec@other.example", password_hash="x")
    u.roles = [UserRole(role="recruiter")]
    db.add(u)
    db.commit()
    token = jwt_encode({"sub": u.id, "typ": "access"}, 600)
    own = db.scalars(select(User).where(User.email == "recruiter@globx.co.in")).first()
    own_token = jwt_encode({"sub": own.id, "typ": "access"}, 600)
    sid = sub.id
    db.close()
    with TestClient(app) as c:
        assert c.get(f"/api/v1/submissions/{sid}", headers={"Authorization": "Bearer " + token}).status_code == 404
        assert c.get(f"/api/v1/submissions/{sid}", headers={"Authorization": "Bearer " + own_token}).status_code == 200
