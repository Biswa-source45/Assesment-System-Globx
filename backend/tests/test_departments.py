"""Departments and auto populate. Shares its fixture and helpers with test_exam_rules (seeded database, staff logins)."""
from test_exam_rules import DEPT, EXAM, PW, _coding, _login, _new_candidate, client  # noqa: F401  (client is a fixture)


def _creator(client):
    return _login(client, "creator@globx.co.in", PW["creator@globx.co.in"])


def test_departments_decide_which_question_types_exist(client):
    creator = _creator(client)
    deps = client.get("/api/v1/departments", headers=creator).json()
    by_name = {d["name"]: d for d in deps}
    assert [d["name"] for d in deps][:5] == ["Technical", "HR", "Finance", "Operations", "General"]
    assert "coding" in by_name["Technical"]["question_types"] and "coding" not in by_name["HR"]["question_types"]

    hr_coding = {**_coding("HR coding", "6"), "department_id": DEPT["HR"]}
    r = client.post("/api/v1/questions", headers=creator, json=hr_coding)
    assert r.status_code == 422 and "HR" in r.text and "coding" in r.text
    no_dept = {k: v for k, v in _coding("No department", "6").items() if k != "department_id"}
    r = client.post("/api/v1/questions", headers=creator, json=no_dept)
    assert r.status_code == 422 and "Choose a department" in r.text
    r = client.post("/api/v1/tests", headers=creator, json={"title": "No department", "duration_min": 30})
    assert r.status_code == 422 and "department" in r.text

    new = client.post("/api/v1/departments", headers=creator, json={"name": "Legal", "question_types": ["mcq_single", "long", "coding", "nonsense"]}).json()
    assert new["question_types"] == ["mcq_single", "long", "coding"]  # canonical order, unknown types dropped
    assert client.post("/api/v1/departments", headers=creator, json={"name": "legal", "question_types": ["long"]}).status_code == 409
    assert client.post("/api/v1/departments", headers=creator, json={"name": "Empty", "question_types": []}).status_code == 422
    edited = client.put(f"/api/v1/departments/{new['id']}", headers=creator, json={"name": "Legal team", "question_types": ["mcq_single"]}).json()
    assert (edited["name"], edited["question_types"]) == ("Legal team", ["mcq_single"])
    assert client.delete(f"/api/v1/departments/{new['id']}", headers=creator).status_code == 200
    r = client.delete(f"/api/v1/departments/{DEPT['Technical']}", headers=creator)
    assert r.status_code == 409 and "used by" in r.text  # it still has questions and exams

    _, cand, _ = _new_candidate(client, "Not Staff")
    assert client.post("/api/v1/departments", headers=cand, json={"name": "Sneaky", "question_types": ["long"]}).status_code == 403


def _mcq(dept, title, difficulty, skills=()):
    return {"department_id": dept, "type": "mcq_single", "title": title, "body": "<p>x</p>", "difficulty": difficulty, "skills": list(skills),
            "marks": 1, "config": {"options": [{"id": "a", "text": "A", "correct": True}, {"id": "b", "text": "B", "correct": False}]}}


def test_auto_populate_picks_random_matching_questions_and_reports_shortfalls(client):
    creator = _creator(client)
    dept = client.post("/api/v1/departments", headers=creator, json={"name": "Pop Dept", "question_types": ["mcq_single"]}).json()["id"]
    for title, diff, skills in [("Pop E1", "easy", ["alpha"]), ("Pop E2", "easy", []), ("Pop E3", "easy", []),
                                ("Pop M1", "medium", []), ("Pop M2", "medium", []), ("Pop H1", "hard", [])]:
        assert client.post("/api/v1/questions", headers=creator, json=_mcq(dept, title, diff, skills)).status_code == 200
    client.post("/api/v1/questions", headers=creator, json=_mcq(DEPT["General"], "Pop other department", "easy"))  # must never be picked
    test = client.post("/api/v1/tests", headers=creator, json={"department_id": dept, "title": "Pop exam", "duration_min": 30}).json()
    section = client.post(f"/api/v1/tests/{test['id']}/sections", headers=creator, json={"title": "Part 1"}).json()["sections"][0]
    url = f"/api/v1/tests/{test['id']}/auto-populate"

    out = client.post(url, headers=creator, json={"department_id": dept, "easy": 2, "medium": 1, "hard": 1}).json()
    assert sorted(q["difficulty"] for q in out["questions"]) == ["easy", "easy", "hard", "medium"] and out["short"] == {}
    assert all(q["department_id"] == dept for q in out["questions"])
    assert len({q["id"] for q in out["questions"]}) == 4  # no question twice in one pick
    firsts = {client.post(url, headers=creator, json={"department_id": dept, "easy": 1}).json()["questions"][0]["id"] for _ in range(20)}
    assert len(firsts) > 1  # it really is random

    only_alpha = client.post(url, headers=creator, json={"department_id": dept, "easy": 3, "skills": ["ALPHA"]}).json()
    assert [q["title"] for q in only_alpha["questions"]] == ["Pop E1"] and only_alpha["short"] == {"easy": 2}  # skills match in any case; the shortfall is reported

    for q in out["questions"]:  # add the pick; the next pick leaves those out
        assert client.post(f"/api/v1/sections/{section['id']}/items", headers=creator, json={"kind": "question", "question_id": q["id"]}).status_code == 200
    again = client.post(url, headers=creator, json={"department_id": dept, "easy": 2}).json()
    assert len(again["questions"]) == 1 and again["short"] == {"easy": 1}  # one easy question was left

    for bad in ({}, {"easy": 51}, {"easy": -1, "medium": 3}):
        assert client.post(url, headers=creator, json=bad).status_code == 422
    published = next(t for t in client.get("/api/v1/tests", headers=creator).json() if t["title"] == EXAM)["id"]
    assert client.post(f"/api/v1/tests/{published}/auto-populate", headers=creator, json={"easy": 1}).status_code == 409  # a published exam is frozen

    # a coding question whose solution does not pass is never picked: it could not be published
    client.post("/api/v1/questions", headers=creator, json=_coding("Pop good coding", "6"))
    client.post("/api/v1/questions", headers=creator, json=_coding("Pop bad coding", "7"))
    tech = client.post("/api/v1/tests", headers=creator, json={"department_id": DEPT["Technical"], "title": "Tech pop", "duration_min": 30}).json()
    picked = client.post(f"/api/v1/tests/{tech['id']}/auto-populate", headers=creator,
                         json={"department_id": DEPT["Technical"], "types": ["coding"], "medium": 50}).json()["questions"]
    titles = [q["title"] for q in picked]
    assert "Pop good coding" in titles and "Pop bad coding" not in titles
