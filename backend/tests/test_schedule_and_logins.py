"""The exam window follows the admin's dates; the login sheet can be had again; the review page gets what it needs to show right and wrong."""
from datetime import datetime, timedelta

from sqlalchemy import select
from test_exam_rules import PW, _login, _start, client  # noqa: F401  (client is a fixture)
from test_results import _answer, _exam, _finished, _person, _wait

from app.db import SessionLocal
from app.models import Assignment, Test, User, now

API = "/api/v1"
ISO = lambda dt: dt.isoformat()


def _put_end(client, h, tid, end):
    t = client.get(f"{API}/tests/{tid}", headers=h).json()
    body = {k: t[k] for k in ("department_id", "title", "duration_min", "cutoff", "shuffle_questions", "shuffle_options")}
    r = client.put(f"{API}/tests/{tid}", headers=h, json={**body, "ends_at": ISO(end) if end else None})
    assert r.status_code == 200, r.text


def _deadline(client, cand, at):
    return datetime.fromisoformat(client.get(f"{API}/attempts/{at}/clock", headers=cand).json()["deadline_at"])


def _near(a, b, secs=3):
    return abs((a - b).total_seconds()) <= secs


def test_changing_the_closing_time_reaches_people_taking_the_exam_and_reopens_the_exam(client):
    creator = _login(client, "creator@globx.co.in", PW["creator@globx.co.in"])
    recruiter = _login(client, "recruiter@globx.co.in", PW["recruiter@globx.co.in"])
    tid, _ = _exam(client, creator, "Schedule exam")
    amit, a_asg = _person(client, recruiter, tid, "Amit Window")
    at = _start(client, amit, a_asg)
    started = datetime.fromisoformat(client.get(f"{API}/attempts/{at}", headers=amit).json()["attempt"]["started_at"])
    own_time = started + timedelta(minutes=30)
    assert _near(_deadline(client, amit, at), own_time)                      # no closing time: their own 30 minutes

    _put_end(client, creator, tid, now() + timedelta(minutes=10))             # the exam will close sooner: they follow it
    assert _near(_deadline(client, amit, at), now() + timedelta(minutes=10))
    _put_end(client, creator, tid, now() + timedelta(hours=3))                # it is moved later: back to their own 30 minutes
    assert _near(_deadline(client, amit, at), own_time)

    row = next(r for r in client.get(f"{API}/tests/{tid}/candidates", headers=recruiter).json()["rows"] if r["name"] == "Amit Window")
    assert client.post(f"{API}/assignments/{row['assignment_id']}/action", headers=recruiter, json={"action": "extend", "minutes": 15, "reason": "slow"}).status_code == 200
    _put_end(client, creator, tid, now() + timedelta(hours=4))                # a new closing time keeps the extension they were given
    assert _near(_deadline(client, amit, at), own_time + timedelta(minutes=15))

    # closed: nobody new can start; opened again (a later closing time): they can
    bea, b_asg = _person(client, recruiter, tid, "Bea Latecomer")
    _put_end(client, creator, tid, now() - timedelta(minutes=5))
    r = client.post(f"{API}/assignments/{b_asg}/start", headers=bea, json={"consent": {"accepted": True}, "system_check": {}})
    assert r.status_code == 403 and "closed" in r.text
    assert _deadline(client, amit, at) < now()                                # and Amit's time ran out with it
    _put_end(client, creator, tid, now() + timedelta(days=2))
    assert client.post(f"{API}/assignments/{b_asg}/start", headers=bea, json={"consent": {"accepted": True}, "system_check": {}}).status_code == 200

    # an exam that had been calculated is open again when its closing time moves into the future
    with SessionLocal() as db:
        db.get(Test, tid).calculated_at = now()
        db.commit()
    _put_end(client, creator, tid, now() + timedelta(days=3))
    assert client.get(f"{API}/tests/{tid}/results", headers=creator).json()["calculated_at"] is None


def test_seeded_logins_have_no_expiry_of_their_own(client):
    """Only the exam's window decides, so moving its closing date later cannot leave seeded candidates with 'invitation expired'."""
    with SessionLocal() as db:
        rows = db.scalars(select(Assignment).join(User, User.id == Assignment.candidate_id).where(User.username.in_(["rahul", "sneha", "amit"]))).all()
        assert rows and all(a.expires_at is None for a in rows)


def test_the_login_sheet_can_be_had_again_for_everyone_who_has_not_started(client):
    creator = _login(client, "creator@globx.co.in", PW["creator@globx.co.in"])
    recruiter = _login(client, "recruiter@globx.co.in", PW["recruiter@globx.co.in"])
    evaluator = _login(client, "evaluator@globx.co.in", PW["evaluator@globx.co.in"])
    tid, _ = _exam(client, creator, "Sheet exam")
    made = [client.post(f"{API}/tests/{tid}/participants", headers=recruiter, json={"names": [n]}).json()["participants"][0] for n in ("Ila One", "Jai Two", "Kia Three")]
    login = lambda p, pw: client.post(f"{API}/auth/login", json={"email": p["username"], "password": pw})
    started = _login(client, made[0]["username"], made[0]["password"])
    _start(client, started, made[0]["assignment_id"])                          # Ila is already taking the exam

    r = client.post(f"{API}/tests/{tid}/passwords", headers=recruiter)
    assert r.status_code == 200, r.text
    sheet = {p["username"]: p for p in r.json()["participants"]}
    assert set(sheet) == {made[1]["username"], made[2]["username"]}           # everyone who has not started, and nobody who has
    assert [p["name"] for p in sorted(sheet.values(), key=lambda p: p["name"])] == ["Jai Two", "Kia Three"]
    for p in made[1:]:
        assert login(p, p["password"]).status_code == 401                       # the old password stops working
        assert login(p, sheet[p["username"]]["password"]).status_code == 200    # the sheet's works
    assert login(made[0], made[0]["password"]).status_code == 200               # the one who started keeps theirs

    assert client.post(f"{API}/tests/{tid}/passwords", headers=evaluator).status_code == 403
    assert client.post(f"{API}/tests/{tid}/passwords", headers=started).status_code == 403


def test_the_review_gets_every_option_with_what_is_right_and_what_was_ticked(client):
    creator = _login(client, "creator@globx.co.in", PW["creator@globx.co.in"])
    recruiter = _login(client, "recruiter@globx.co.in", PW["recruiter@globx.co.in"])
    tid, q = _exam(client, creator, "Review exam")
    cand, asg = _person(client, recruiter, tid, "Mina Wrong")
    at = _start(client, cand, asg)
    _answer(client, cand, at, q["mcq"], {"selected": ["b"]})                    # the wrong one
    _answer(client, cand, at, q["short"], {"html": "<p>no idea</p>"})
    assert client.post(f"{API}/attempts/{at}/submit", headers=cand, json={}).status_code == 200
    _wait(lambda: _finished(client, cand, at), "the submission")
    items = {i["title"].rsplit(" ", 1)[-1]: i for i in client.get(f"{API}/reports/attempts/{at}", headers=creator).json()["questions"]}
    assert items["mcq"]["options"] == [{"text": "A", "correct": True, "chosen": False}, {"text": "B", "correct": False, "chosen": True}]
    assert items["short"]["model_answer"] == "alpha is first" and items["short"]["keywords"] == ["alpha"]
