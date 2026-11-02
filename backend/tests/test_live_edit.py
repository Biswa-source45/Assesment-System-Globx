"""Editing a question while its exam is live. Shares its fixture and helpers with test_exam_rules (seeded database, staff logins)."""
from test_exam_rules import DEPT, PW, _coding, _login, _start, client  # noqa: F401  (client is a fixture)

API = "/api/v1"


def _mcq(title, options="ab", correct="a", marks=1):
    """options: the ids to offer, as letters; each option's text is its id in capitals (ids stay put when one is removed, as in the editor)."""
    return {"department_id": DEPT["Technical"], "type": "mcq_single", "title": title, "body": "<p>x</p>", "marks": marks,
            "config": {"options": [{"id": i, "text": i.upper(), "correct": i == correct} for i in options]}}


def _state(client, cand, at):
    sec = client.get(f"{API}/attempts/{at}", headers=cand).json()
    return sec, {q["id"]: q for s in sec["sections"] for q in s["questions"]}


def test_editing_a_question_reaches_candidates_taking_the_exam(client):
    h = _login(client, "creator@globx.co.in", PW["creator@globx.co.in"])
    staff = _login(client, "recruiter@globx.co.in", PW["recruiter@globx.co.in"])
    q1 = client.post(f"{API}/questions", headers=h, json=_mcq("Live one")).json()
    q2 = client.post(f"{API}/questions", headers=h, json=_mcq("Live two", marks=2)).json()
    code = client.post(f"{API}/questions", headers=h, json=_coding("Live code", "6")).json()
    t = client.post(f"{API}/tests", headers=h, json={"department_id": DEPT["Technical"], "title": "Live edit exam", "duration_min": 30}).json()
    sid = client.post(f"{API}/tests/{t['id']}/sections", headers=h, json={"title": "All"}).json()["sections"][0]["id"]
    for q, override in ((q1, None), (q2, 5), (code, None)):
        r = client.post(f"{API}/sections/{sid}/items", headers=h, json={"kind": "question", "question_id": q["id"], "marks_override": override})
        assert r.status_code == 200, r.text
    assert client.post(f"{API}/tests/{t['id']}/publish", headers=h).status_code == 200
    p = client.post(f"{API}/tests/{t['id']}/participants", headers=staff, json={"names": ["Live Tester"]}).json()["participants"][0]
    cand = _login(client, p["username"], p["password"])
    at = _start(client, cand, p["assignment_id"])

    st0, qs = _state(client, cand, at)
    v0 = st0["attempt"]["content_version"]
    assert st0["attempt"]["max_score"] == 1 + 5 + 10 and qs[q1["id"]]["marks"] == 1 and [o["text"] for o in qs[q1["id"]]["options"]] in (["A", "B"], ["B", "A"])
    assert client.get(f"{API}/attempts/{at}/clock", headers=cand).json()["content_version"] == v0
    assert client.get(f"{API}/tests/{t['id']}", headers=h).json()["taking"] == 1

    # the admin edits question one while the candidate is in the exam: new text, a third option, more marks
    r = client.put(f"{API}/questions/{q1['id']}", headers=h, json=_mcq("Live one, reworded", "abc", correct="c", marks=3))
    assert r.status_code == 200, r.text
    st1, qs = _state(client, cand, at)
    one = qs[q1["id"]]
    assert one["title"] == "Live one, reworded" and one["marks"] == 3
    assert sorted(o["text"] for o in one["options"]) == ["A", "B", "C"] and one["options"][-1]["text"] == "C"  # the new option goes last, the order of the others is kept
    assert st1["attempt"]["max_score"] == 3 + 5 + 10                                                             # the total follows
    v1 = client.get(f"{API}/attempts/{at}/clock", headers=cand).json()["content_version"]
    assert v1 > v0 and v1 == st1["attempt"]["content_version"]                                                   # the exam page notices this and reloads

    # an option can be removed; the exam's own marks override still wins over the question's marks
    client.put(f"{API}/questions/{q1['id']}", headers=h, json=_mcq("Live one, reworded", "ac", correct="c", marks=3))
    client.put(f"{API}/questions/{q2['id']}", headers=h, json=_mcq("Live two", marks=9))
    _, qs = _state(client, cand, at)
    assert sorted(o["id"] for o in qs[q1["id"]]["options"]) == ["a", "c"] and qs[q2["id"]]["marks"] == 5

    # a question of a published exam must stay publishable: breaking the reference solution is refused, with the question left as it was
    broken = client.put(f"{API}/questions/{code['id']}", headers=h, json=_coding("Live code", "7"))
    assert broken.status_code == 422 and "published exam" in broken.text
    assert client.get(f"{API}/questions/{code['id']}", headers=h).json()["validated"] is True
    assert client.put(f"{API}/questions/{code['id']}", headers=h, json=_coding("Live code, renamed", "6")).status_code == 200

    # the type of a question that is in an exam cannot change
    as_short = {"department_id": DEPT["Technical"], "type": "short", "title": "Now short", "body": "<p>x</p>", "marks": 2, "config": {"model_answer": "x"}}
    r = client.put(f"{API}/questions/{q1['id']}", headers=h, json=as_short)
    assert r.status_code == 422 and "cannot change" in r.text

    # a finished attempt keeps the marks it was graded with
    assert client.post(f"{API}/attempts/{at}/submit", headers=cand, json={"reason": "submitted"}).status_code == 200
    client.put(f"{API}/questions/{q1['id']}", headers=h, json=_mcq("Live one, reworded", "ac", correct="c", marks=4))
    assert client.get(f"{API}/attempts/{at}", headers=cand).json()["attempt"]["max_score"] == 3 + 5 + 10
