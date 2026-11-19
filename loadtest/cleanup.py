"""Erases everything one load-test run made, and nothing else. It runs INSIDE the exam server's container, fed through standard input
(nothing is added to the image). It first only COUNTS what it would erase; set YES=1 to erase.

  docker compose exec -T -e RUN=LT-20261120-2100 api python - < cleanup.py                (counts only)
  docker compose exec -T -e RUN=LT-20261120-2100 -e YES=1 api python - < cleanup.py       (erases; add -e FULL=1 to also return the disk space, in quiet hours)
On the office PC (PowerShell):  Get-Content -Raw cleanup.py | docker compose exec -T -e RUN=LT-... -e YES=1 api python -

What belongs to a run: every test, department, question and person whose name starts with the run id and a space (the setup script names everything that way);
the attempts and answers, pictures, events, recordings and code runs of those tests (they go with the test); their picture/video/upload folders; the audit entries
about them. The Super Admin's own sign-ins stay (they are real activity)."""
import json
import os
import re
import shutil
import sys

sys.path.insert(0, os.getcwd())
from sqlalchemy import text  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402

RUN = os.environ.get("RUN", "")
YES = os.environ.get("YES") == "1"
if not re.fullmatch(r"LT-[0-9A-Za-z-]{3,40}", RUN):
    sys.exit("Set RUN to the run id, for example RUN=LT-20261120-2100")
LIKE = RUN + " %"
MID = "% " + RUN + " %"   # the fake candidates are named "lt00001 <run id> Candidate"

with SessionLocal() as db:
    one = lambda sql, **p: db.scalar(text(sql), {"like": LIKE, **p} if ":like" in sql else p)
    tests = [r[0] for r in db.execute(text("select id from tests where title like :like"), {"like": LIKE})]
    users = [r[0] for r in db.execute(text("select id from users where name like :like or name like :mid"), {"like": LIKE, "mid": MID})]
    plan = {
        "tests": len(tests), "departments": one("select count(*) from departments where name like :like"),
        "questions": one("select count(*) from questions where title like :like"), "people": len(users),
        "attempts": one("select count(*) from attempts where test_id = any(:t)", t=tests),
        "answers": one("select count(*) from answers where attempt_id in (select id from attempts where test_id = any(:t))", t=tests),
        "pictures": one("select count(*) from proctor_snapshots where attempt_id in (select id from attempts where test_id = any(:t))", t=tests),
        "events": one("select count(*) from proctor_events where attempt_id in (select id from attempts where test_id = any(:t))", t=tests),
        "code runs": one("select count(*) from code_submissions where attempt_id in (select id from attempts where test_id = any(:t))", t=tests),
        "mails": one("select count(*) from mail_outbox where subject like :sub", sub="%" + RUN + "%"),   # submission receipts and the like, named after the exam
    }
    print("This run would erase:", json.dumps(plan))
    if len(tests) > 5 or len(users) > 200000:
        sys.exit("That is more than a load test makes: stopping. Check RUN.")
    if not YES:
        print("Counted only. Add YES=1 to erase.")
        sys.exit(0)

    attempts = [r[0] for r in db.execute(text("select id from attempts where test_id = any(:t)"), {"t": tests})]
    ids = set(tests) | set(attempts) | set(users)
    ids |= {r[0] for r in db.execute(text("select id from questions where title like :like"), {"like": LIKE})}
    ids |= {r[0] for r in db.execute(text("select id from departments where name like :like"), {"like": LIKE})}
    ids |= {r[0] for r in db.execute(text("select id from assignments where test_id = any(:t)"), {"t": tests})}
    recs = [r[0] for r in db.execute(text("select path from recordings where attempt_id = any(:a)"), {"a": attempts})]
    snaps = [r[0] for r in db.execute(text("select path from proctor_snapshots where attempt_id = any(:a)"), {"a": attempts})]

    # children first, in one transaction: either everything goes or nothing
    db.execute(text("delete from attempts where test_id = any(:t)"), {"t": tests})   # answers, pictures, events, recordings, code runs, evaluations follow
    db.execute(text("delete from tests where id = any(:t)"), {"t": tests})           # sections, items, assignments follow
    db.execute(text("delete from questions where title like :like"), {"like": LIKE})  # test cases follow
    db.execute(text("delete from departments where name like :like"), {"like": LIKE})
    db.execute(text("delete from mail_outbox where subject like :sub"), {"sub": "%" + RUN + "%"})
    db.execute(text("delete from users where name like :like or name like :mid"), {"like": LIKE, "mid": MID})      # roles and sign-in tokens follow
    for chunk in range(0, len(ids), 5000):
        part = list(ids)[chunk:chunk + 5000]
        db.execute(text("delete from audit_logs where entity_id = any(:i) or actor_id = any(:i)"), {"i": part})
    db.commit()

root = os.path.realpath(get_settings().storage_dir)
removed = 0
for a in attempts:
    for sub in ("proctor", "uploads", "recordings"):
        folder = os.path.realpath(os.path.join(root, sub, a))
        if os.path.commonpath([root, folder]) == root and os.path.isdir(folder):
            shutil.rmtree(folder, ignore_errors=True)
            removed += 1
for rel in recs + snaps:
    p = os.path.realpath(os.path.join(root, rel))
    if os.path.commonpath([root, p]) == root and os.path.isfile(p):
        os.remove(p)
        removed += 1
print(f"Erased. {removed} folders/files removed from storage.")
# give the space back: VACUUM makes it reusable; FULL=1 (quiet hours: it locks a table while it rewrites it) also returns it to the disk
from sqlalchemy import create_engine  # noqa: E402
with create_engine(get_settings().database_url, isolation_level="AUTOCOMMIT").connect() as c:
    for t in ("answers", "attempt_questions", "attempts", "proctor_snapshots", "proctor_events", "code_submissions", "questions", "test_cases", "users", "user_roles",
              "assignments", "audit_logs", "mail_outbox", "refresh_tokens", "tests", "sections", "section_items", "departments"):
        c.execute(text(f'VACUUM {"FULL " if os.environ.get("FULL") == "1" else ""}ANALYZE "{t}"'))
print("Space given back" + (" to the disk (VACUUM FULL)." if os.environ.get("FULL") == "1" else " for reuse (VACUUM). Add FULL=1 in quiet hours to return it to the disk."))
with SessionLocal() as db:
    left = {"tests": db.scalar(text("select count(*) from tests where title like :l"), {"l": LIKE}), "people": db.scalar(text("select count(*) from users where name like :l or name like :m"), {"l": LIKE, "m": MID}),
            "questions": db.scalar(text("select count(*) from questions where title like :l"), {"l": LIKE})}
print("Left of this run:", json.dumps(left))
