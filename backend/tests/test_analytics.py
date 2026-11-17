"""Analytics: the small statistics rules, the exam as a whole (staff), one candidate against the class (candidate-safe, no answer key) and the progress over exams.
Shares its fixture and helpers with test_results."""
import pytest
from test_exam_rules import DEPT, PW, _login, _start, client  # noqa: F401  (client is a fixture)
from test_results import _answer, _results, _submit_and_wait, _wait

from app.db import SessionLocal
from app.models import Assignment, Test, uid
from app.services.analytics import _health, beat_percent, discrimination, histogram

API = "/api/v1"
RIGHT, WRONG = "Zebra-right", "Yak-wrong"  # option texts that must never reach a candidate


# ---------------------------------------------------------------- the small rules
def test_histogram_puts_every_score_in_one_of_ten_bins():
    assert histogram([0, 9.99, 10, 55, 99.9, 100, 140, -5]) == [3, 1, 0, 0, 0, 1, 0, 0, 0, 3]  # 100 and more in the last bin, a negative score in the first
    assert histogram([]) == [0] * 10


def test_beat_percent_is_the_share_of_the_others_you_are_strictly_above():
    assert beat_percent([50], 50) is None                    # nobody else finished
    assert beat_percent([90, 50, 10], 90) == 100 and beat_percent([90, 50, 10], 10) == 0 and beat_percent([90, 50, 10], 50) == 50
    assert beat_percent([60, 60, 60, 20], 60) == 33          # a tie is not beaten


def test_discrimination_compares_the_strong_with_the_weak():
    strong_right = [(90, 1), (80, 1), (70, 1), (40, 0), (30, 0), (20, 0)]
    assert discrimination(strong_right) == 1.0
    assert discrimination([(t, 1 - r) for t, r in strong_right]) == -1.0   # the weak did better: often a wrong key
    assert discrimination(strong_right[:5]) is None                          # too few candidates
    assert discrimination([(50, 1)] * 3 + [(50, 0)] * 3) is None             # everyone has the same total


def test_a_question_is_only_judged_when_enough_candidates_answered_it():
    assert _health(4, 100, 0, None) == "few answers"
    assert _health(10, 95, 0, 0.1) == "too easy" and _health(10, 5, 0, 0.1) == "too hard" and _health(10, 50, 40, 0.3) == "often skipped"
    assert _health(10, 50, 0, -0.5) == "check the key" and _health(10, 50, 0, 0.5) == "good"


# ---------------------------------------------------------------- a finished exam with known numbers
def _exam(client, h, title, cutoff=3, sections=None):
    """Sections of (title, [(question title, marks, difficulty, skills)]); every question is single choice and the key is always option a."""
    sections = sections or [("Part A", [(f"{title} Q1", 2, "easy", ["python"]), (f"{title} Q2", 3, "hard", ["python", "sql"])]), ("Part B", [(f"{title} Q3", 1, "medium", ["sql"])])]
    t = client.post(f"{API}/tests", headers=h, json={"department_id": DEPT["Technical"], "title": title, "duration_min": 30, "cutoff": cutoff,
                                                     "shuffle_questions": False, "shuffle_options": False}).json()
    ids = []
    for sec, qs in sections:
        sid = client.post(f"{API}/tests/{t['id']}/sections", headers=h, json={"title": sec}).json()["sections"][-1]["id"]
        for qt, marks, level, skills in qs:
            q = client.post(f"{API}/questions", headers=h, json={"department_id": DEPT["Technical"], "body": "<p>x</p>", "type": "mcq_single", "title": qt, "marks": marks,
                                                                 "difficulty": level, "skills": skills,
                                                                 "config": {"options": [{"id": "a", "text": RIGHT, "correct": True}, {"id": "b", "text": WRONG, "correct": False}]}}).json()
            assert client.post(f"{API}/sections/{sid}/items", headers=h, json={"kind": "question", "question_id": q["id"]}).status_code == 200
            ids.append(q["id"])
    assert client.post(f"{API}/tests/{t['id']}/publish", headers=h).status_code == 200
    return t["id"], ids


def _person(client, staff, tid, name):
    p = client.post(f"{API}/tests/{tid}/participants", headers=staff, json={"names": [name]}).json()["participants"][0]
    return _login(client, p["username"], p["password"]), p["assignment_id"]


def _sit(client, staff, tid, qids, name, picks):
    """picks: one of 'a', 'b' or None (left blank) per question. Returns (candidate headers, attempt id)."""
    cand, asg = _person(client, staff, tid, name)
    at = _start(client, cand, asg)
    for qid, pick in zip(qids, picks):
        if pick:
            _answer(client, cand, at, qid, {"selected": [pick]})
    _submit_and_wait(client, cand, at)
    return cand, at


def _calculate(client, evaluator, tid):
    assert client.post(f"{API}/tests/{tid}/calculate", headers=evaluator).status_code == 200
    _wait(lambda: _results(client, evaluator, tid)["calculated_at"], "the calculation")


# Q1 is worth 2 marks, Q2 3 and Q3 1 (6 in all). Q3 has a bad key: the strong candidates answer b, the weak ones a.
CLASS = [("Cand P1", "aab"), ("Cand P2", "aab"), ("Cand P3", "abb"), ("Cand P4", "abb"), ("Cand P5", "bab"), ("Cand P6", "bba"), ("Cand P7", "bba"), ("Cand P8", "   ")]
# totals: P1 5, P2 5, P3 2, P4 2, P5 3 (only Q2 right), P6 1, P7 1, P8 0 (blank paper)


@pytest.fixture(scope="module")
def exam(client):
    creator = _login(client, "creator@globx.co.in", PW["creator@globx.co.in"])
    recruiter = _login(client, "recruiter@globx.co.in", PW["recruiter@globx.co.in"])
    evaluator = _login(client, "evaluator@globx.co.in", PW["evaluator@globx.co.in"])
    tid, qids = _exam(client, creator, "Analytics Exam")
    people = {}
    for name, picks in CLASS:
        people[name] = _sit(client, recruiter, tid, qids, name, [p if p in "ab" else None for p in picks])
    _person(client, recruiter, tid, "Cand Absent")  # invited, never came
    before = client.get(f"{API}/tests/{tid}/analytics", headers=creator).json()
    _calculate(client, evaluator, tid)
    return {"tid": tid, "qids": qids, "creator": creator, "recruiter": recruiter, "evaluator": evaluator, "people": people, "before": before}


def _declare(client, exam, on=True):
    r = client.post(f"{API}/tests/{exam['tid']}/declare", headers=exam["evaluator"], json={"declared": on})
    assert r.status_code == 200, r.text


def test_the_exam_numbers(client, exam):
    assert exam["before"]["calculated"] is False and exam["before"]["funnel"]["completed"] == 8      # readable before the results are calculated
    d = client.get(f"{API}/tests/{exam['tid']}/analytics", headers=exam["creator"]).json()
    assert d["calculated"] is True and d["declared"] is False and d["pending_review"] == 0
    assert d["funnel"] == {"invited": 9, "started": 8, "completed": 8, "cleared_cutoff": 3, "shortlisted": 0}   # the absent person is invited only
    s = d["scores"]
    assert s["n"] == 8 and s["mean"] == pytest.approx(39.6, abs=0.1) and s["median"] == 33.3 and s["min"] == 0 and s["max"] == 83.3
    assert s["std"] == pytest.approx(28.8, abs=0.2) and s["q1"] == pytest.approx(16.7, abs=0.1) and s["q3"] == pytest.approx(58.3, abs=0.1)
    assert s["pass_rate"] == 38 and s["pass_mark_percent"] == 50.0                                        # 3 of 8 passed; 3 marks of 6
    assert d["score_distribution"] == [1, 2, 0, 2, 0, 1, 0, 0, 2, 0] and sum(d["score_distribution"]) == 8
    assert d["results"] == {"passed": 3, "not_passed": 4, "not_attempted": 1}
    assert d["time_distribution"][0] == 8 and sum(d["time_distribution"]) == 8                              # all finished in the first tenth of the time
    assert len(d["points"]) == 8 and {p["name"] for p in d["points"]} == {n for n, _ in CLASS}

    a, b = d["sections"]
    assert (a["title"], a["max"], a["mean"], a["best"], a["worst"], a["below_min"]) == ("Part A", 5, 42.5, 100, 0, 0)
    assert (b["title"], b["max"], b["mean"], b["best"], b["worst"]) == ("Part B", 1, 25.0, 100, 0)
    assert d["kinds"] == [{"name": "Choice", "percent": 39.6, "n": 3}]
    assert d["difficulty"] == [{"name": "easy", "percent": 50.0, "n": 1}, {"name": "medium", "percent": 25.0, "n": 1}, {"name": "hard", "percent": 37.5, "n": 1}]
    assert {r["name"]: (r["percent"], r["n"]) for r in d["skills"]} == {"python": (42.5, 2), "sql": (34.4, 2)}
    assert d["marking"] == {"machine": 24, "ai": 0, "ai_changed": 0, "person": 0}


def test_each_question_is_judged_with_its_options_and_a_bad_key_is_found(client, exam):
    q1, q2, q3 = client.get(f"{API}/tests/{exam['tid']}/analytics", headers=exam["creator"]).json()["questions"]   # in the order of the exam
    assert [q["title"] for q in (q1, q2, q3)] == ["Analytics Exam Q1", "Analytics Exam Q2", "Analytics Exam Q3"]
    assert (q1["attempts"], q1["full_marks_pct"], q1["avg_percent"], q1["skipped"], q1["skipped_pct"]) == (8, 50.0, 50.0, 1, 12.5)
    assert q1["discrimination"] == 1.0 and q1["health"] == "good" and q1["difficulty"] == "easy" and q1["marks"] == 2
    assert [(o["label"], o["text"], o["correct"], o["chosen"]) for o in q1["options"]] == [("A", RIGHT, True, 4), ("B", WRONG, False, 3)]
    assert (q2["full_marks_pct"], q2["discrimination"], q2["health"]) == (37.5, 1.0, "good")
    assert (q3["full_marks_pct"], q3["discrimination"], q3["health"]) == (25.0, -0.5, "check the key")           # the strong did worse than the weak
    assert [o["chosen"] for o in q3["options"]] == [2, 5]


def test_who_may_open_the_exam_analytics(client, exam):
    url = f"{API}/tests/{exam['tid']}/analytics"
    assert client.get(url, headers=exam["recruiter"]).status_code == 200 and client.get(url, headers=exam["evaluator"]).status_code == 200
    cand = exam["people"]["Cand P5"][0]
    assert client.get(url, headers=cand).status_code == 403
    assert client.get(url).status_code in (401, 403)


def test_a_candidate_sees_their_own_analytics_against_the_class_and_never_the_key(client, exam):
    cand, at = exam["people"]["Cand P5"]
    url = f"{API}/attempts/{at}/analytics"
    assert client.get(url, headers=cand).status_code == 409                       # not declared yet
    assert client.get(url, headers=exam["creator"]).status_code == 200            # staff may look before
    _declare(client, exam)
    r = client.get(url, headers=cand)
    assert r.status_code == 200
    d = r.json()
    assert d["candidate"]["name"] == "Cand P5" and d["exam"] == {"title": "Analytics Exam", "declared": True}
    assert d["score"] == {"score": 3, "max": 6, "percent": 50.0, "result": "passed", "result_label": "Passed"}
    assert d["rank"] == 3 and d["of"] == 8 and d["beat_percent"] == 71                                     # 5 of the other 7 scored lower
    assert d["class"] == {"n": 8, "mean": pytest.approx(39.6, abs=0.1), "median": 33.3, "highest": 83.3}
    assert d["histogram"] == [1, 2, 0, 2, 0, 1, 0, 0, 2, 0] and d["you_bin"] == 5
    assert [(s["title"], s["you"], s["class"], s["best"]) for s in d["sections"]] == [("Part A", 60.0, 42.5, 100), ("Part B", 0.0, 25.0, 100)]
    assert d["kinds"] == [{"name": "Choice", "you": 50.0, "class": 39.6, "n": 3}]
    assert [(x["n"], x["status"], x["score"], x["class_correct"]) for x in d["questions"]] == [(1, "Incorrect", 0, 50), (2, "Correct", 3, 38), (3, "Incorrect", 0, 25)]
    assert d["highlights"][0].startswith("Best against the class: Part A") and d["highlights"][1].startswith("Most to improve: Part B")
    assert d["time"]["allowed"] == 30 and d["time"]["taken"] is not None and d["time"]["class_average"] is not None
    text = r.text
    assert RIGHT not in text and WRONG not in text and '"options"' not in text and '"correct"' not in text and "model_answer" not in text
    assert not any(n in text for n, _ in CLASS if n != "Cand P5")                                          # nobody else's name
    assert "risk" not in text and "proctoring" not in text


def test_the_candidate_gate_is_the_report_card_gate(client, exam):
    cand, at = exam["people"]["Cand P5"]
    other, _ = exam["people"]["Cand P1"]
    url = f"{API}/attempts/{at}/analytics"
    _declare(client, exam)
    assert client.get(url, headers=other).status_code == 404                      # someone else's result
    assert client.get(url).status_code in (401, 403)
    assert client.get(f"{API}/attempts/nope/analytics", headers=cand).status_code == 404
    with SessionLocal() as db:                                                    # the exam is not shared with candidates
        t = db.get(Test, exam["tid"])
        t.settings = {**(t.settings or {}), "show_result_to_candidate": False}
        db.commit()
    assert client.get(url, headers=cand).status_code == 409
    assert client.get(url, headers=exam["creator"]).status_code == 200            # staff still can
    with SessionLocal() as db:
        t = db.get(Test, exam["tid"])
        t.settings = {**(t.settings or {}), "show_result_to_candidate": True}
        db.commit()
    assert client.get(url, headers=cand).status_code == 200
    _declare(client, exam, on=False)                                              # withdrawn
    assert client.get(url, headers=cand).status_code == 409


def test_the_report_card_numbers_questions_in_the_order_of_the_exam_across_sections(client, exam):
    card = client.get(f"{API}/attempts/{exam['people']['Cand P5'][1]}/report-card", headers=exam["creator"]).json()
    assert [[q["n"] for q in s["questions"]] for s in card["sections"]] == [[1, 2], [3]]      # the order of a question restarts in each section


def test_a_blank_paper_and_a_top_paper_have_sensible_numbers(client, exam):
    _declare(client, exam)
    blank = client.get(f"{API}/attempts/{exam['people']['Cand P8'][1]}/analytics", headers=exam["creator"]).json()
    assert blank["score"]["percent"] == 0 and blank["score"]["result"] == "not_attempted" and blank["beat_percent"] == 0 and blank["you_bin"] == 0
    assert [x["status"] for x in blank["questions"]] == ["Not answered"] * 3
    top = client.get(f"{API}/attempts/{exam['people']['Cand P1'][1]}/analytics", headers=exam["creator"]).json()
    assert top["rank"] in (1, 2) and top["beat_percent"] in (86, 100) and top["you_bin"] == 8       # the other top paper has the same score: a tie is not beaten


def test_progress_over_the_exams_a_candidate_has_taken(client, exam):
    cand, at = exam["people"]["Cand P5"]
    mine = client.get(f"{API}/me/progress", headers=cand)
    assert mine.status_code == 200
    _declare(client, exam, on=False)
    assert client.get(f"{API}/me/progress", headers=cand).json() == []              # withdrawn: nothing to show
    _declare(client, exam)
    first = client.get(f"{API}/me/progress", headers=cand).json()
    assert len(first) == 1 and first[0]["attempt_id"] == at and first[0]["title"] == "Analytics Exam"
    assert first[0]["percent"] == 50.0 and first[0]["rank"] == 3 and first[0]["of"] == 8 and first[0]["result"] == "passed"
    assert first[0]["class_average"] == pytest.approx(39.6, abs=0.1)

    # the same person sits a second exam: both show, oldest first, and an archived one is left out
    me = client.get(f"{API}/auth/me", headers=cand).json()["id"]
    tid2, q2 = _exam(client, exam["creator"], "Analytics Exam Two")
    with SessionLocal() as db:
        asg = Assignment(test_id=tid2, candidate_id=me, token_hash=uid())
        db.add(asg)
        db.commit()
        asg2 = asg.id
    at2 = _start(client, cand, asg2)
    for qid in q2:
        _answer(client, cand, at2, qid, {"selected": ["a"]})
    _submit_and_wait(client, cand, at2)
    _calculate(client, exam["evaluator"], tid2)
    assert client.post(f"{API}/tests/{tid2}/declare", headers=exam["evaluator"], json={"declared": True}).status_code == 200
    two = client.get(f"{API}/me/progress", headers=cand).json()
    assert [p["title"] for p in two] == ["Analytics Exam", "Analytics Exam Two"] and two[1]["percent"] == 100.0 and two[1]["of"] == 1
    assert client.get(f"{API}/me/progress").status_code in (401, 403)
    _declare(client, exam, on=False)


# ---------------------------------------------------------------- awkward exams
def test_an_exam_nobody_has_finished_gives_empty_numbers_not_an_error(client):
    creator = _login(client, "creator@globx.co.in", PW["creator@globx.co.in"])
    recruiter = _login(client, "recruiter@globx.co.in", PW["recruiter@globx.co.in"])
    tid, qids = _exam(client, creator, "Analytics Empty")
    d = client.get(f"{API}/tests/{tid}/analytics", headers=creator).json()
    assert d["funnel"]["completed"] == 0 and d["scores"]["n"] == 0 and d["scores"]["mean"] is None and d["scores"]["pass_rate"] is None
    assert d["score_distribution"] == [0] * 10 and d["questions"] == [] and d["sections"] == [] and d["points"] == [] and d["time_minutes"] == {"min": 0, "max": 0, "avg": 0}
    cand, asg = _person(client, recruiter, tid, "Cand Still Writing")
    at = _start(client, cand, asg)                                                   # started, not finished: still not counted
    d = client.get(f"{API}/tests/{tid}/analytics", headers=creator).json()
    assert d["funnel"]["started"] == 1 and d["funnel"]["completed"] == 0 and d["scores"]["n"] == 0
    assert client.get(f"{API}/attempts/{at}/analytics", headers=creator).status_code == 409      # no result yet


def test_one_finished_candidate_and_an_exam_with_no_pass_mark(client):
    creator = _login(client, "creator@globx.co.in", PW["creator@globx.co.in"])
    recruiter = _login(client, "recruiter@globx.co.in", PW["recruiter@globx.co.in"])
    tid, qids = _exam(client, creator, "Analytics Alone", cutoff=0)
    _, at = _sit(client, recruiter, tid, qids, "Cand Alone", ["a", "a", "b"])
    d = client.get(f"{API}/tests/{tid}/analytics", headers=creator).json()
    assert d["scores"]["n"] == 1 and d["scores"]["std"] == 0 and d["scores"]["median"] == 83.3 and d["scores"]["q1"] == d["scores"]["q3"] == 83.3
    assert d["scores"]["pass_rate"] is None and d["scores"]["pass_mark_percent"] is None and d["funnel"]["cleared_cutoff"] == 0     # no pass mark: no verdict
    assert all(q["discrimination"] is None and q["health"] == "few answers" for q in d["questions"])
    me = client.get(f"{API}/attempts/{at}/analytics", headers=creator).json()
    assert me["rank"] == 1 and me["of"] == 1 and me["beat_percent"] is None and me["highlights"] == [] and all(q["class_correct"] is None for q in me["questions"])
    assert me["score"]["result"] == "no_pass_mark"


def test_an_exam_where_everyone_has_the_same_score(client):
    creator = _login(client, "creator@globx.co.in", PW["creator@globx.co.in"])
    recruiter = _login(client, "recruiter@globx.co.in", PW["recruiter@globx.co.in"])
    tid, qids = _exam(client, creator, "Analytics Same")
    for i in range(6):
        _sit(client, recruiter, tid, qids, f"Cand Same {i}", ["a", "b", "a"])
    d = client.get(f"{API}/tests/{tid}/analytics", headers=creator).json()
    assert d["scores"]["std"] == 0 and d["scores"]["mean"] == d["scores"]["median"] and sum(d["score_distribution"]) == 6
    assert all(q["discrimination"] is None for q in d["questions"])                  # nobody to tell apart
