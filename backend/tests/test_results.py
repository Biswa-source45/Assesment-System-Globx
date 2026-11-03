"""Results of an exam: calculated once after the end time, reviewed, declared. Shares its fixture and helpers with test_exam_rules."""
import time
from datetime import timedelta

import pytest
from test_exam_rules import DEPT, PW, _coding, _event, _login, _start, client  # noqa: F401  (client is a fixture)

from app.db import SessionLocal
from app.models import Attempt, Test, now
from app.services import ai
from app.services.jobs import sweep_once

API = "/api/v1"
GOOD = "n=int(input())\nprint(2*n)"  # what _coding's reference solution does


@pytest.fixture()
def ai_calls(monkeypatch):
    """A pretend AI that counts its calls: 'unsure' answers get a low confidence, 'boom' answers make it fail."""
    calls = {"short": 0, "long": 0}

    def semantic(question, model_answer, answer):
        calls["short"] += 1
        return {"similarity": 1.0, "confidence": 0.3 if "unsure" in answer else 0.9, "rationale": "stub"}

    def rubric(question, model_answer, rub, answer):
        calls["long"] += 1
        if "boom" in answer:
            raise RuntimeError("AI is down")
        return {"scores": [{"id": c["id"], "score": c["max"]} for c in rub], "rationale": "stub", "confidence": 0.9, "provider": "stub"}

    monkeypatch.setattr(ai, "llm_enabled", lambda: True)
    monkeypatch.setattr(ai, "ai_semantic_similarity", semantic)
    monkeypatch.setattr(ai, "ai_rubric_score", rubric)
    return calls


def _wait(check, what, tries=120):
    for _ in range(tries):
        if check():
            return
        time.sleep(0.25)
    raise AssertionError("timed out waiting for " + what)


def _exam(client, h, title, cutoff=8):
    mk = lambda body: client.post(f"{API}/questions", headers=h, json={"department_id": DEPT["Technical"], "body": "<p>x</p>", **body}).json()
    qs = {
        "mcq": mk({"type": "mcq_single", "title": f"{title} mcq", "marks": 1, "config": {"options": [{"id": "a", "text": "A", "correct": True}, {"id": "b", "text": "B", "correct": False}]}}),
        "short": mk({"type": "short", "title": f"{title} short", "marks": 2, "config": {"model_answer": "alpha is first", "keywords": ["alpha"], "max_words": 100}}),
        "long": mk({"type": "long", "title": f"{title} long", "marks": 5, "config": {"model_answer": "a full explanation", "rubric": [
            {"id": "r1", "name": "Content", "max": 3}, {"id": "r2", "name": "Clarity", "max": 2}]}}),
        "code": client.post(f"{API}/questions", headers=h, json=_coding(f"{title} code", "6")).json(),
    }
    t = client.post(f"{API}/tests", headers=h, json={"department_id": DEPT["Technical"], "title": title, "duration_min": 30, "cutoff": cutoff,
                                                      "shuffle_questions": False, "shuffle_options": False}).json()
    sid = client.post(f"{API}/tests/{t['id']}/sections", headers=h, json={"title": "All"}).json()["sections"][0]["id"]
    for q in qs.values():
        assert client.post(f"{API}/sections/{sid}/items", headers=h, json={"kind": "question", "question_id": q["id"]}).status_code == 200
    assert client.post(f"{API}/tests/{t['id']}/publish", headers=h).status_code == 200
    return t["id"], {k: v["id"] for k, v in qs.items()}


def _person(client, staff, tid, name):
    p = client.post(f"{API}/tests/{tid}/participants", headers=staff, json={"names": [name]}).json()["participants"][0]
    return _login(client, p["username"], p["password"]), p["assignment_id"]


def _answer(client, cand, at, qid, response, seq=1):
    r = client.put(f"{API}/attempts/{at}/answers/{qid}", headers=cand, json={"response": response, "flagged": False, "seq": seq})
    assert r.status_code == 200, r.text


def _finished(client, cand, at):
    return client.get(f"{API}/attempts/{at}", headers=cand).json()["attempt"]["status"] in ("review_pending", "evaluated")


def _results(client, h, tid):
    return client.get(f"{API}/tests/{tid}/results", headers=h).json()


def _row(res, name):
    return next(r for r in res["rows"] if r["name"] == name)


def _answers(client, h, at):
    return {q["title"].rsplit(" ", 1)[-1]: q for q in client.get(f"{API}/reports/attempts/{at}", headers=h).json()["questions"]}


def _mine(client, cand, aid):
    return next(a for a in client.get(f"{API}/me/assignments", headers=cand).json() if a["assignment_id"] == aid)


def test_the_exam_is_calculated_after_its_end_time_then_reviewed_and_declared(client, ai_calls):
    creator = _login(client, "creator@globx.co.in", PW["creator@globx.co.in"])
    staff = _login(client, "evaluator@globx.co.in", PW["evaluator@globx.co.in"])
    recruiter = _login(client, "recruiter@globx.co.in", PW["recruiter@globx.co.in"])
    tid, q = _exam(client, creator, "Results exam")
    asha, a_asg = _person(client, recruiter, tid, "Asha Finisher")
    bala, b_asg = _person(client, recruiter, tid, "Bala Terminated")
    _, c_asg = _person(client, recruiter, tid, "Chitra Absent")
    dev, d_asg = _person(client, recruiter, tid, "Dev Timeover")

    # Asha finishes properly: right MCQ, a sure short answer, an explained answer, a program sent with Submit
    at_a = _start(client, asha, a_asg)
    _answer(client, asha, at_a, q["mcq"], {"selected": ["a"]})
    _answer(client, asha, at_a, q["short"], {"html": "<p>alpha beta</p>"})
    _answer(client, asha, at_a, q["long"], {"html": "<p>a clear explanation</p>"})
    sub = client.post(f"{API}/attempts/{at_a}/code/{q['code']}/submit", headers=asha, json={"language": "python", "source": GOOD}).json()["submission_id"]
    _wait(lambda: client.get(f"{API}/submissions/{sub}", headers=asha).json()["status"] == "done", "the judge")
    assert client.post(f"{API}/attempts/{at_a}/submit", headers=asha, json={}).status_code == 200
    _wait(lambda: _finished(client, asha, at_a), "Asha's submission")
    assert ai_calls == {"short": 0, "long": 0}                      # nothing is sent to the AI at submit time
    assert _answers(client, creator, at_a)["mcq"]["score"] == 1 and _answers(client, creator, at_a)["code"]["score"] == 10  # MCQ and the program are marked at once

    # Bala answers badly, saves a program but never presses Submit, then leaves the window too often and is ended
    at_b = _start(client, bala, b_asg)
    _answer(client, bala, at_b, q["mcq"], {"selected": ["b"]})
    _answer(client, bala, at_b, q["short"], {"html": "<p>unsure about it</p>"})
    _answer(client, bala, at_b, q["long"], {"html": "<p>boom</p>"})
    _answer(client, bala, at_b, q["code"], {"language": "python", "source": GOOD})
    for _ in range(3):
        _event(client, bala, at_b, type="tab_blur", duration_ms=2000)
    assert _event(client, bala, at_b, type="tab_blur", duration_ms=2000)["action"] == "force_submit"
    _wait(lambda: _finished(client, bala, at_b), "Bala's submission")
    assert _answers(client, creator, at_b)["code"]["score"] == 10   # the saved program was judged at the end, not thrown away

    # Dev is still working when the end time passes
    at_d = _start(client, dev, d_asg)
    with SessionLocal() as db:
        db.get(Test, tid).ends_at = now() - timedelta(minutes=1)
        db.commit()
    sweep_once()
    time.sleep(1)
    assert _results(client, creator, tid)["state"] == "calculating" and ai_calls == {"short": 0, "long": 0}  # closed, but Dev is still in: not calculated yet
    with SessionLocal() as db:
        db.get(Attempt, at_d).deadline_at = now() - timedelta(minutes=2)
        db.commit()
    sweep_once()                                                    # Dev's time is over: submitted and graded by the sweeper
    _wait(lambda: _finished(client, dev, at_d), "Dev's time-over submission")
    for _ in range(40):                                             # then the exam is calculated by itself
        sweep_once()
        if _results(client, creator, tid)["calculated_at"]:
            break
        time.sleep(0.5)
    res = _results(client, creator, tid)
    assert res["calculated_at"] and res["state"] == "needs_attention"
    assert ai_calls == {"short": 2, "long": 2}                      # one call per text answer: Asha's two and Bala's two. Not for MCQ, programs or Dev's blank answers

    # who is in the table, and why
    assert [(r["name"], r["outcome"]) for r in sorted(res["rows"], key=lambda r: r["name"])] == [
        ("Asha Finisher", "submitted"), ("Bala Terminated", "violation_limit"), ("Chitra Absent", "absent"), ("Dev Timeover", "time_over")]
    assert _row(res, "Bala Terminated")["outcome_label"] == "Ended: left the window too often" and _row(res, "Chitra Absent")["outcome_label"] == "Did not attend"
    assert res["summary"]["assigned"] == 4 and res["summary"]["appeared"] == 3 and res["summary"]["absent"] == 1 and res["summary"]["ended_early"] == 1
    asha_row = _row(res, "Asha Finisher")
    assert asha_row["score"] == 1 + 2 + 5 + 10 and asha_row["rank"] == 1 and asha_row["result"] == "passed"   # AI was sure about both of Asha's text answers
    assert _row(res, "Dev Timeover")["score"] == 0 and _row(res, "Dev Timeover")["result"] == "not_attempted"   # Dev answered nothing: never a pass
    assert res["attention"] == 2 and _row(res, "Bala Terminated")["attention"] == 2   # an unsure AI mark and a failed AI call wait for a person
    assert [r["rank"] for r in res["rows"]][:3] == [1, 2, 3] and _row(res, "Chitra Absent")["rank"] is None

    # declaring is blocked until a person has looked
    r = client.post(f"{API}/tests/{tid}/declare", headers=staff, json={"declared": True})
    assert r.status_code == 409 and "2 answer(s)" in r.text
    assert client.post(f"{API}/tests/{tid}/calculate", headers=staff).status_code == 200      # run again: only the failed AI call is repeated
    _wait(lambda: ai_calls["long"] == 3, "the retry")
    time.sleep(1)
    assert ai_calls == {"short": 2, "long": 3}
    accepted = client.post(f"{API}/tests/{tid}/accept-ai", headers=staff).json()["accepted"]
    assert accepted == 1                                              # the unsure short answer takes its suggested mark; the failed one has none
    assert _results(client, creator, tid)["attention"] == 1
    assert client.post(f"{API}/tests/{tid}/declare", headers=staff, json={"declared": True}).status_code == 409
    long_b = _answers(client, creator, at_b)["long"]
    r = client.post(f"{API}/answers/{long_b['answer_id']}/evaluate", headers=staff, json={"final_score": 1.5})
    assert r.status_code == 200, r.text
    assert _results(client, creator, tid)["attention"] == 0 and _results(client, creator, tid)["state"] == "ready"

    # until declared nobody sees a result; then they do, and an override afterwards reaches them
    assert _mine(client, asha, a_asg)["result"] is None
    assert client.post(f"{API}/tests/{tid}/declare", headers=staff, json={"declared": True}).status_code == 200
    mine = _mine(client, asha, a_asg)["result"]
    assert mine["score"] == 18 and mine["percent"] == 100 and mine["result"] == "passed" and mine["sections"] == [{"title": "All", "score": 18.0, "max": 18.0}]
    assert _mine(client, bala, b_asg)["result"]["reason"] == "violation_limit"
    assert _mine(client, dev, d_asg)["result"]["result"] == "not_attempted"
    assert _mine(client, bala, b_asg)["result"]["result"] == "passed"   # Bala was ended early but his saved program alone (10) is over the pass mark of 8
    long_a = _answers(client, creator, at_a)["long"]
    assert client.post(f"{API}/answers/{long_a['answer_id']}/evaluate", headers=staff, json={"final_score": 3, "override_reason": "missed the main point"}).status_code == 200
    assert _mine(client, asha, a_asg)["result"]["score"] == 16
    assert client.post(f"{API}/assignments/{d_asg}/action", headers=recruiter, json={"action": "reset", "reason": "x"}).status_code == 409   # declared: no re-opening
    assert client.post(f"{API}/assignments/{c_asg}/start", headers=_login(client, *_credentials(client, recruiter, tid, "Chitra Absent")), json={"consent": {"accepted": True}, "system_check": {}}).status_code == 403
    assert client.post(f"{API}/tests/{tid}/declare", headers=staff, json={"declared": False}).status_code == 200
    assert _mine(client, asha, a_asg)["result"] is None               # withdrawn: hidden again

    # the export says what happened to each person
    csv = client.get(f"{API}/tests/{tid}/export", headers=recruiter).text
    assert "Outcome" in csv.splitlines()[0] and "Did not attend" in csv and "Ended: left the window too often" in csv
    assert "Result" in csv.splitlines()[0] and "Did not attempt" in csv and "Passed" in csv

    # who may do what
    for who, path, body in [(recruiter, "calculate", None), (recruiter, "accept-ai", None), (recruiter, "declare", {"declared": True})]:
        assert client.post(f"{API}/tests/{tid}/{path}", headers=who, json=body).status_code == 403
    assert client.get(f"{API}/tests/{tid}/results", headers=recruiter).status_code == 200
    assert client.get(f"{API}/tests/{tid}/results", headers=asha).status_code == 403


def _credentials(client, recruiter, tid, name):
    """A fresh password for someone who has not started, to log in as them."""
    rows = client.get(f"{API}/tests/{tid}/candidates", headers=recruiter).json()["rows"]
    row = next(r for r in rows if r["name"] == name)
    out = client.post(f"{API}/assignments/{row['assignment_id']}/password", headers=recruiter).json()
    return out["username"], out["password"]


def test_calculating_again_regrades_machine_marked_answers_and_keeps_hand_marks(client, ai_calls):
    creator = _login(client, "creator@globx.co.in", PW["creator@globx.co.in"])
    evaluator = _login(client, "evaluator@globx.co.in", PW["evaluator@globx.co.in"])
    recruiter = _login(client, "recruiter@globx.co.in", PW["recruiter@globx.co.in"])
    tid, q = _exam(client, creator, "Regrade exam")
    one, one_asg = _person(client, recruiter, tid, "Eka Regrade")
    two, two_asg = _person(client, recruiter, tid, "Fatima Handmarked")
    ats = {}
    for name, cand, asg in (("one", one, one_asg), ("two", two, two_asg)):
        ats[name] = _start(client, cand, asg)
        _answer(client, cand, ats[name], q["mcq"], {"selected": ["a"]})
        assert client.post(f"{API}/attempts/{ats[name]}/submit", headers=cand, json={}).status_code == 200
        _wait(lambda: _finished(client, cand, ats[name]), "submission")
    hand = _answers(client, creator, ats["two"])["mcq"]["answer_id"]
    assert client.post(f"{API}/answers/{hand}/evaluate", headers=evaluator, json={"final_score": 1, "override_reason": "agreed after a discussion"}).status_code == 200

    # the author finds the answer key was wrong while the exam is still on, and fixes it
    fixed = {"department_id": DEPT["Technical"], "type": "mcq_single", "title": "Regrade exam mcq", "body": "<p>x</p>", "marks": 1,
             "config": {"options": [{"id": "a", "text": "A", "correct": False}, {"id": "b", "text": "B", "correct": True}]}}
    assert client.put(f"{API}/questions/{q['mcq']}", headers=creator, json=fixed).status_code == 200
    assert _answers(client, creator, ats["one"])["mcq"]["score"] == 1  # nothing changes until the exam is calculated
    client.post(f"{API}/tests/{tid}/calculate", headers=evaluator)
    _wait(lambda: _results(client, creator, tid)["calculated_at"], "the calculation")
    assert _answers(client, creator, ats["one"])["mcq"]["score"] == 0   # re-marked with the corrected key
    assert _answers(client, creator, ats["two"])["mcq"]["score"] == 1   # the hand mark stays
    assert ai_calls == {"short": 0, "long": 0}


def _submit_and_wait(client, cand, at):
    assert client.post(f"{API}/attempts/{at}/submit", headers=cand, json={}).status_code == 200
    _wait(lambda: _finished(client, cand, at), "a submission")


def test_a_blank_paper_is_never_passed_and_an_exam_without_a_pass_mark_gives_no_verdict(client, ai_calls):
    creator = _login(client, "creator@globx.co.in", PW["creator@globx.co.in"])
    recruiter = _login(client, "recruiter@globx.co.in", PW["recruiter@globx.co.in"])

    # no pass mark (0): a score but no verdict; a blank paper is still "did not attempt", not a pass
    tid0, q0 = _exam(client, creator, "No pass mark exam", cutoff=0)
    blank, blank_asg = _person(client, recruiter, tid0, "Blank Paper")
    some, some_asg = _person(client, recruiter, tid0, "Some Answers")
    at_blank, at_some = _start(client, blank, blank_asg), _start(client, some, some_asg)
    _answer(client, some, at_some, q0["mcq"], {"selected": ["a"]})
    _submit_and_wait(client, blank, at_blank)
    _submit_and_wait(client, some, at_some)
    rows = _results(client, creator, tid0)
    assert _row(rows, "Blank Paper")["score"] == 0 and _row(rows, "Blank Paper")["result"] == "not_attempted"
    assert _row(rows, "Some Answers")["score"] == 1 and _row(rows, "Some Answers")["result"] == "no_pass_mark"
    review = client.get(f"{API}/reports/attempts/{at_blank}", headers=creator).json()["attempt"]
    assert review["result"] == "not_attempted" and review["attempted"] == 0 and "below_cutoff" not in review
    assert rows["summary"]["passed"] == 0 and rows["summary"]["failed"] == 0 and rows["summary"]["not_attempted"] == 1

    # a pass mark of 1: the right answer passes, the wrong one does not, the blank paper did not attempt
    tid1, q1 = _exam(client, creator, "Pass mark one exam", cutoff=1)
    people = {}
    for name, pick in (("Right One", ["a"]), ("Wrong One", ["b"]), ("Empty One", None)):
        cand, asg = _person(client, recruiter, tid1, name)
        at = _start(client, cand, asg)
        if pick:
            _answer(client, cand, at, q1["mcq"], {"selected": pick})
        _submit_and_wait(client, cand, at)
    rows = _results(client, creator, tid1)
    assert {r["name"]: r["result"] for r in rows["rows"]} == {"Right One": "passed", "Wrong One": "not_passed", "Empty One": "not_attempted"}
    assert (rows["summary"]["passed"], rows["summary"]["failed"], rows["summary"]["not_attempted"]) == (1, 1, 1)
    assert client.get(f"{API}/tests/{tid1}/analytics", headers=creator).json()["funnel"]["cleared_cutoff"] == 1   # only the person who really passed
    assert client.get(f"{API}/dashboard", headers=creator).json()["cleared"] >= 1
