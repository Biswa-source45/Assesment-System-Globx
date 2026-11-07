"""What the candidate's screen really sends must show up in the review and be marked: a written answer is saved as {"text": ...}
(the older tests used {"html": ...}, so a blank review went unnoticed), and a multiple-answer question follows the strict rule.
Shares its fixture and helpers with test_exam_rules."""
import time

from test_exam_rules import DEPT, PW, _login, _start, client  # noqa: F401  (client is a fixture)

from app.api.tests import _source_of
from app.db import SessionLocal

API = "/api/v1"


def test_a_written_answer_is_shown_in_the_review_and_multiple_answer_is_marked_strictly(client):
    creator = _login(client, "creator@globx.co.in", PW["creator@globx.co.in"])
    recruiter = _login(client, "recruiter@globx.co.in", PW["recruiter@globx.co.in"])
    mk = lambda body: client.post(f"{API}/questions", headers=creator, json={"department_id": DEPT["General"], "body": "<p>x</p>", **body}).json()
    opts = [{"id": k, "text": k.upper(), "correct": k in "abc"} for k in "abcde"]  # three right of five
    multi = mk({"type": "mcq_multi", "title": "Review multi", "marks": 3, "negative_marks": 0, "config": {"options": opts, "partial": True}})
    long = mk({"type": "long", "title": "Review long", "marks": 4, "config": {"model_answer": "plan, tell, help", "rubric": [{"id": "r1", "name": "All", "max": 4}]}})
    t = client.post(f"{API}/tests", headers=creator, json={"department_id": DEPT["General"], "title": "Review exam", "duration_min": 30, "shuffle_questions": False, "shuffle_options": False}).json()
    sid = client.post(f"{API}/tests/{t['id']}/sections", headers=creator, json={"title": "All"}).json()["sections"][0]["id"]
    for q in (multi, long):
        assert client.post(f"{API}/sections/{sid}/items", headers=creator, json={"kind": "question", "question_id": q["id"]}).status_code == 200
    assert client.post(f"{API}/tests/{t['id']}/publish", headers=creator).status_code == 200

    def sit(name, picked, answer):
        p = client.post(f"{API}/tests/{t['id']}/participants", headers=recruiter, json={"names": [name]}).json()["participants"][0]
        cand = _login(client, p["username"], p["password"])
        at = _start(client, cand, p["assignment_id"])
        put = lambda q, response: client.put(f"{API}/attempts/{at}/answers/{q['id']}", headers=cand, json={"response": response, "flagged": False, "seq": 1})
        assert put(multi, {"selected": picked}).status_code == 200
        assert put(long, {"text": answer}).status_code == 200  # the shape the candidate's text box sends
        assert client.post(f"{API}/attempts/{at}/submit", headers=cand, json={}).status_code == 200
        for _ in range(120):
            if client.get(f"{API}/attempts/{at}", headers=cand).json()["attempt"]["status"] in ("review_pending", "evaluated"):
                break
            time.sleep(0.25)
        rep = client.get(f"{API}/reports/attempts/{at}", headers=creator).json()
        return at, {q["title"]: q for q in rep["questions"]}

    at, qs = sit("Rina Exact", list("abc"), "I would list my tasks, tell my manager and offer help later.")
    assert qs["Review long"]["answer_html"] == "I would list my tasks, tell my manager and offer help later."  # shown, not "No answer"
    assert qs["Review multi"]["score"] == 3.0
    with SessionLocal() as db:
        assert _source_of(db, at, long["id"])["text"].startswith("I would list")  # the plagiarism compare shows it too

    assert sit("Rita Extra", list("abcd"), "x")[1]["Review multi"]["score"] == 2.75   # all right + one wrong: 0.25 off
    assert sit("Rani Every", list("abcde"), "x")[1]["Review multi"]["score"] == 0.0   # ticking everything does not win
    assert sit("Ravi Wrong", list("de"), "x")[1]["Review multi"]["score"] == 0.0      # never below zero
