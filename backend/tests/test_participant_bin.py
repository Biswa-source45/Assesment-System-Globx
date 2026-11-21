"""Deleting a participant: first into the bin (out of every list, count, rank and export), then restored or deleted for good."""
import io
import os
import zipfile
from datetime import timedelta

from sqlalchemy import select
from test_exam_rules import DEPT, PW, _login, _start, client  # noqa: F401  (client is a fixture)
from test_results import _answer, _finished, _person, _results, _wait

from app.core.config import get_settings
from app.db import SessionLocal
from app.models import Assignment, Attempt, AuditLog, MailOutbox, PlagiarismMatch, Test, User, now
from app.services import login_mail
from app.services.jobs import sweep_once

API = "/api/v1"


def _exam(client, h, title):
    """One multiple-choice question, published: 'a' is right."""
    q = client.post(f"{API}/questions", headers=h, json={"department_id": DEPT["Technical"], "body": "<p>x</p>", "type": "mcq_single", "title": f"{title} q", "marks": 4,
                                                          "config": {"options": [{"id": "a", "text": "A", "correct": True}, {"id": "b", "text": "B", "correct": False}]}}).json()
    t = client.post(f"{API}/tests", headers=h, json={"department_id": DEPT["Technical"], "title": title, "duration_min": 30, "cutoff": 2,
                                                      "shuffle_questions": False, "shuffle_options": False}).json()
    sid = client.post(f"{API}/tests/{t['id']}/sections", headers=h, json={"title": "Part one"}).json()["sections"][0]["id"]
    assert client.post(f"{API}/sections/{sid}/items", headers=h, json={"kind": "question", "question_id": q["id"]}).status_code == 200
    assert client.post(f"{API}/tests/{t['id']}/publish", headers=h).status_code == 200
    return t["id"], q["id"]


def _sit(client, cand, aid, qid, pick):
    at = _start(client, cand, aid)
    _answer(client, cand, at, qid, {"selected": [pick]})
    assert client.post(f"{API}/attempts/{at}/submit", headers=cand, json={}).status_code == 200
    _wait(lambda: _finished(client, cand, at), "the submission")
    return at


def _names(rows):
    return sorted(r["name"] for r in rows)


def _staff(client):
    return (_login(client, "recruiter@globx.co.in", PW["recruiter@globx.co.in"]), _login(client, "creator@globx.co.in", PW["creator@globx.co.in"]),
            _login(client, "evaluator@globx.co.in", PW["evaluator@globx.co.in"]))


def test_a_binned_person_is_in_no_list_count_rank_or_export_until_restored(client):
    rec, creator, evaluator = _staff(client)
    tid, q = _exam(client, creator, "Bin exam")
    asha, a_asg = _person(client, rec, tid, "Asha Topper")
    bala, b_asg = _person(client, rec, tid, "Bala Second")
    _, c_asg = _person(client, rec, tid, "Chitra Absent")
    dev, d_asg = _person(client, rec, tid, "Dev Waiting")
    at_a = _sit(client, asha, a_asg, q, "a")   # 4 marks
    _sit(client, bala, b_asg, q, "b")          # 0 marks
    before = client.get(f"{API}/dashboard", headers=rec).json()
    res = _results(client, creator, tid)
    assert [(r["name"], r["rank"]) for r in res["rows"][:2]] == [("Asha Topper", 1), ("Bala Second", 2)]
    assert [s["title"] for s in res["sections"]] == ["Part one"]                       # the Compare table needs the section names
    assert client.get(f"{API}/tests/{tid}/analytics", headers=creator).json()["scores"]["n"] == 2

    # who may bin: the person who manages participants, not an evaluator
    assert client.delete(f"{API}/assignments/{a_asg}", headers=evaluator).status_code == 403
    assert client.delete(f"{API}/assignments/{a_asg}", headers=rec).status_code == 200
    assert client.delete(f"{API}/assignments/{a_asg}", headers=rec).status_code == 404   # already in the bin: gone from the normal list

    # out of every list and count
    cands = client.get(f"{API}/tests/{tid}/candidates", headers=rec).json()
    assert _names(cands["rows"]) == ["Bala Second", "Chitra Absent", "Dev Waiting"] and cands["binned"] == 1 and "Asha Topper" not in str(cands["counts"])
    res = _results(client, creator, tid)
    assert _names(res["rows"]) == ["Bala Second", "Chitra Absent", "Dev Waiting"]
    assert res["summary"]["assigned"] == 3 and res["summary"]["appeared"] == 1 and res["summary"]["highest"] == 0
    assert next(r for r in res["rows"] if r["name"] == "Bala Second")["rank"] == 1       # nobody is ranked against the binned person
    assert client.get(f"{API}/tests/{tid}/analytics", headers=creator).json()["scores"]["n"] == 1
    for fmt in ("csv", "xlsx"):
        out = client.get(f"{API}/tests/{tid}/export?format={fmt}", headers=rec)
        assert out.status_code == 200 and (b"Asha" not in out.content if fmt == "csv" else True)
    zipped = zipfile.ZipFile(io.BytesIO(client.get(f"{API}/tests/{tid}/report-cards.zip", headers=rec).content)).namelist()
    assert len(zipped) == 1 and "Asha" not in zipped[0]
    after = client.get(f"{API}/dashboard", headers=rec).json()
    assert (before["invited"] - after["invited"], before["attempted"] - after["attempted"]) == (1, 1)
    assert [r["name"] for r in client.get(f"{API}/tests/{tid}/monitor", headers=rec).json()["rows"] if r["name"].startswith("Asha")] == []
    assert next(t for t in client.get(f"{API}/tests", headers=creator).json() if t["id"] == tid)["invited"] == 3

    # the person cannot reach the exam, the result or the report card any more
    assert client.get(f"{API}/me/assignments", headers=asha).json() == []
    assert client.post(f"{API}/assignments/{a_asg}/start", headers=asha, json={"consent": {"accepted": True}, "system_check": {}}).status_code == 404
    assert client.get(f"{API}/attempts/{at_a}/report-card", headers=asha).status_code == 404
    # nothing else can be done to them from the lists
    assert client.post(f"{API}/assignments/{a_asg}/password", headers=rec).status_code == 404
    assert client.put(f"{API}/assignments/{a_asg}/participant", headers=rec, json={"name": "X", "email": "x@example.com"}).status_code == 404
    assert client.post(f"{API}/assignments/{a_asg}/action", headers=rec, json={"action": "cancel"}).status_code == 404
    sheet = client.post(f"{API}/tests/{tid}/passwords", headers=rec).json()["participants"]
    assert sorted(p["name"] for p in sheet) == ["Chitra Absent", "Dev Waiting"]         # the fresh login sheet skips the binned person

    # the bin lists them (with what they had), and only them
    bin_ = client.get(f"{API}/tests/{tid}/candidates?deleted=true", headers=rec).json()
    assert bin_["total"] == 1 and bin_["rows"][0]["name"] == "Asha Topper" and bin_["rows"][0]["score"] == 4 and bin_["rows"][0]["deleted_at"]
    assert client.get(f"{API}/tests/{tid}/candidates?deleted=true&q=nobody", headers=rec).json()["total"] == 0
    # restore: everything is back, as it was
    assert client.post(f"{API}/assignments/{a_asg}/restore", headers=rec).status_code == 200
    assert client.post(f"{API}/assignments/{a_asg}/restore", headers=rec).status_code == 409
    res = _results(client, creator, tid)
    assert _names(res["rows"]) == ["Asha Topper", "Bala Second", "Chitra Absent", "Dev Waiting"] and res["summary"]["assigned"] == 4
    assert next(r for r in res["rows"] if r["name"] == "Asha Topper")["rank"] == 1
    assert [m["assignment_id"] for m in client.get(f"{API}/me/assignments", headers=asha).json()] == [a_asg]
    assert client.get(f"{API}/tests/{tid}/candidates?deleted=true", headers=rec).json()["total"] == 0


def test_a_person_taking_the_exam_cannot_be_binned_and_the_bin_has_its_own_rules(client):
    rec, creator, _ = _staff(client)
    tid, q = _exam(client, creator, "Bin rules")
    asha, a_asg = _person(client, rec, tid, "Asha Busy")
    at = _start(client, asha, a_asg)
    r = client.delete(f"{API}/assignments/{a_asg}", headers=rec)
    assert r.status_code == 409 and "taking the exam" in r.text                          # a running exam is never pulled from under a person
    _answer(client, asha, at, q, {"selected": ["a"]})
    assert client.post(f"{API}/attempts/{at}/submit", headers=asha, json={}).status_code == 200
    _wait(lambda: _finished(client, asha, at), "the submission")
    # deleting for good needs the bin first
    r = client.delete(f"{API}/assignments/{a_asg}/permanent", headers=rec)
    assert r.status_code == 409 and "not in the bin" in r.text
    assert client.post(f"{API}/assignments/{a_asg}/restore", headers=rec).status_code == 409
    assert client.delete(f"{API}/assignments/nope", headers=rec).status_code == 404
    assert client.delete(f"{API}/assignments/{a_asg}", headers=rec).status_code == 200
    # a queued login mail to a binned person is not sent
    with SessionLocal() as db:
        db.add(MailOutbox(to="a@example.com", subject="s", body="b", kind=login_mail.KIND, attach=a_asg, status="queued"))
        db.commit()
    other, o_asg = _person(client, rec, tid, "Omar Mail")
    with SessionLocal() as db:
        db.add(MailOutbox(id="m" * 32, to="o@example.com", subject="s", body="b", kind=login_mail.KIND, attach=o_asg, status="queued"))
        db.commit()
    assert client.delete(f"{API}/assignments/{o_asg}", headers=rec).status_code == 200
    with SessionLocal() as db:
        m = db.get(MailOutbox, "m" * 32)
        assert m.status == "failed" and "deleted" in m.error
    with SessionLocal() as db:
        assert db.scalars(select(AuditLog.action).where(AuditLog.entity_id == o_asg)).all() == ["participant_binned"]


def test_an_address_in_the_bin_cannot_be_added_again_but_says_where_it_is(client):
    rec, creator, _ = _staff(client)
    tid, _ = _exam(client, creator, "Readd exam")
    out = client.post(f"{API}/tests/{tid}/participants", headers=rec, json={"names": ["Eve Mail, eve.readd@example.com"], "email_required": True}).json()["participants"][0]
    assert client.delete(f"{API}/assignments/{out['assignment_id']}", headers=rec).status_code == 200
    r = client.post(f"{API}/tests/{tid}/participants", headers=rec, json={"names": ["Eve Again, eve.readd@example.com"], "email_required": True})
    assert r.status_code == 422 and "bin" in r.text
    assert client.post(f"{API}/assignments/{out['assignment_id']}/restore", headers=rec).status_code == 200
    r = client.post(f"{API}/tests/{tid}/participants", headers=rec, json={"names": ["Eve Again, eve.readd@example.com"], "email_required": True})
    assert r.status_code == 422 and "already in this exam" in r.text


def test_deleting_for_good_removes_the_person_and_everything_of_theirs(client):
    rec, creator, evaluator = _staff(client)
    tid, q = _exam(client, creator, "Gone exam")
    tid2, _ = _exam(client, creator, "Other exam")
    asha, a_asg = _person(client, rec, tid, "Asha Gone")
    bala, b_asg = _person(client, rec, tid, "Bala Gone")
    at_a, at_b = _sit(client, asha, a_asg, q, "a"), _sit(client, bala, b_asg, q, "b")
    # Bala is also in another exam (same login): his login must survive, Asha's must not
    with SessionLocal() as db:
        bala_user = db.get(Assignment, b_asg).candidate
        bala_user.email = "bala.gone@example.com"
        asha_user_id = db.get(Assignment, a_asg).candidate_id
        bala_user_id = bala_user.id
        db.commit()
    assert client.post(f"{API}/tests/{tid2}/participants", headers=rec, json={"names": ["Bala Gone, bala.gone@example.com"]}).status_code == 200
    folder = os.path.join(get_settings().storage_dir, "proctor", at_a)
    os.makedirs(folder, exist_ok=True)
    open(os.path.join(folder, "pic.jpg"), "wb").write(b"x")
    os.makedirs(os.path.join(get_settings().storage_dir, "uploads", at_a), exist_ok=True)
    with SessionLocal() as db:
        db.add(PlagiarismMatch(test_id=tid, question_id=q, attempt_a=at_a, attempt_b=at_b, similarity=0.9, level="high"))
        db.add(MailOutbox(to="x@example.com", subject="s", body="b", kind="report_card", attach=at_a, status="sent"))
        db.add(MailOutbox(to="x@example.com", subject="s", body="b", kind=login_mail.KIND, attach=a_asg, status="sent"))
        db.commit()
    assert client.delete(f"{API}/assignments/{a_asg}", headers=rec).status_code == 200
    assert client.delete(f"{API}/assignments/{a_asg}/permanent", headers=evaluator).status_code == 403
    assert client.delete(f"{API}/assignments/{a_asg}/permanent", headers=rec).status_code == 200
    with SessionLocal() as db:
        assert db.get(Assignment, a_asg) is None and db.get(Attempt, at_a) is None and db.get(User, asha_user_id) is None
        assert db.scalars(select(PlagiarismMatch)).all() == [] and not db.scalars(select(MailOutbox).where(MailOutbox.attach.in_([a_asg, at_a]))).all()
        assert db.get(Attempt, at_b) is not None                                           # nobody else is touched
    assert not os.path.exists(folder) and not os.path.exists(os.path.join(get_settings().storage_dir, "uploads", at_a))
    assert client.get(f"{API}/tests/{tid}/candidates?deleted=true", headers=rec).json()["total"] == 0
    assert _names(_results(client, creator, tid)["rows"]) == ["Bala Gone"]
    assert client.post(f"{API}/auth/login", json={"email": "asha", "password": "x"}).status_code in (400, 401, 403, 422)
    # Bala: bin and delete for good in this exam; his login stays for the other exam
    assert client.delete(f"{API}/assignments/{b_asg}", headers=rec).status_code == 200
    assert client.delete(f"{API}/assignments/{b_asg}/permanent", headers=rec).status_code == 200
    with SessionLocal() as db:
        assert db.get(User, bala_user_id) is not None and db.get(Assignment, b_asg) is None
        assert db.scalar(select(Assignment.id).where(Assignment.test_id == tid2, Assignment.candidate_id == bala_user_id))


def test_a_binned_person_gets_no_reminder(client):
    rec, creator, _ = _staff(client)
    tid, _ = _exam(client, creator, "Reminder exam")
    _, a_asg = _person(client, rec, tid, "Asha Reminder")
    _, b_asg = _person(client, rec, tid, "Bala Reminder")
    with SessionLocal() as db:
        for aid in (a_asg, b_asg):
            a = db.get(Assignment, aid)
            a.sent_at, a.expires_at = now(), now() + timedelta(hours=5)
        db.commit()
    assert client.delete(f"{API}/assignments/{a_asg}", headers=rec).status_code == 200
    sweep_once()
    with SessionLocal() as db:
        assert db.get(Assignment, a_asg).reminders_sent == 0 and db.get(Assignment, b_asg).reminders_sent == 1


def test_the_login_mail_says_to_use_chrome_or_edge_only(client):
    rec, creator, _ = _staff(client)
    tid, _ = _exam(client, creator, "Browser exam")
    with SessionLocal() as db:
        _, text, page = login_mail.exam_login_mail(db.get(Test, tid), "Asha", "asha1", "pw")
    for body in (text, page):
        assert "Google Chrome or Microsoft Edge only" in body and "Firefox" in body and "Brave" in body
