"""Paging of the long lists: ?limit=&offset= and the total in X-Total-Count. Without `limit` every list is returned whole, as before.
Shares its fixture with test_exam_rules."""
from sqlalchemy import event
from test_exam_rules import DEPT, PW, _login, client  # noqa: F401  (client is a fixture)

from app.db import engine

API = "/api/v1"


def _creator(client):
    return _login(client, "creator@globx.co.in", PW["creator@globx.co.in"])


def _admin(client):
    return _login(client, "orgadmin@globx.co.in", PW["orgadmin@globx.co.in"])


def _question(client, h, title, **kw):
    body = {"department_id": DEPT["Technical"], "type": "mcq_single", "title": title, "body": "<p>x</p>", "marks": 1,
            "config": {"options": [{"id": "a", "text": "A", "correct": True}, {"id": "b", "text": "B", "correct": False}]}, **kw}
    r = client.post(f"{API}/questions", headers=h, json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _pages(client, path, h, size, **params):
    """Every page of a list, in order, with the totals the header gave."""
    rows, totals, offset = [], set(), 0
    while True:
        r = client.get(path, headers=h, params={**params, "limit": size, "offset": offset})
        assert r.status_code == 200, r.text
        totals.add(int(r.headers["x-total-count"]))
        page = r.json()
        rows += page
        offset += size
        if len(page) < size:
            return rows, totals


def test_the_question_bank_is_paged_in_a_fixed_order_and_searched_by_the_server(client):
    h = _creator(client)
    made = [_question(client, h, f"Paging Q {i:02d}")["id"] for i in range(25)]
    rows, totals = _pages(client, f"{API}/questions", h, 10, q="Paging Q")
    assert totals == {25} and len(rows) == 25
    assert sorted(r["id"] for r in rows) == sorted(made)        # every question once: no repeat, no gap
    whole = client.get(f"{API}/questions", headers=h, params={"q": "Paging Q"})
    assert isinstance(whole.json(), list) and len(whole.json()) == 25    # an old caller (no limit) gets the plain list, as before
    assert [r["id"] for r in whole.json()] == [r["id"] for r in rows]  # and the pages are that list in the same order
    assert client.get(f"{API}/questions", headers=h, params={"q": "Paging Q", "limit": 10, "offset": 20}).json().__len__() == 5
    assert client.get(f"{API}/questions", headers=h, params={"q": "Paging Q", "limit": 10, "offset": 99}).json() == []  # past the end: an empty page
    r = client.get(f"{API}/questions", headers=h, params={"q": "Paging Q", "limit": 0})
    assert r.json() == [] and r.headers["x-total-count"] == "25"  # limit=0: only the count
    for bad in ({"limit": 501}, {"limit": -1}, {"limit": "many"}, {"offset": -5}):
        assert client.get(f"{API}/questions", headers=h, params=bad).status_code == 422
    # the filters still apply before paging
    _question(client, h, "Paging Q short", type="short", config={"model_answer": "x", "keywords": ["x"]})
    r = client.get(f"{API}/questions", headers=h, params={"q": "paging q", "type": "short", "limit": 5})  # the search ignores capitals
    assert r.headers["x-total-count"] == "1" and r.json()[0]["title"] == "Paging Q short"


def test_percent_and_underscore_in_a_search_mean_themselves(client):
    h = _creator(client)
    _question(client, h, "Wildcards 100% sure")
    _question(client, h, "Wildcards 100x sure")
    _question(client, h, "Wildcards a_b")
    _question(client, h, "Wildcards axb")
    one = lambda q: client.get(f"{API}/questions", headers=h, params={"q": q, "limit": 10}).json()
    assert [r["title"] for r in one("100%")] == ["Wildcards 100% sure"]
    assert [r["title"] for r in one("a_b")] == ["Wildcards a_b"]
    assert len(one("Wildcards")) == 4 and one("\\") == []


def test_a_skill_filter_is_paged_too(client):
    h = _creator(client)
    for i in range(7):
        _question(client, h, f"Skill Q {i}", skills=["Zebra-skill"])
    rows, totals = _pages(client, f"{API}/questions", h, 3, skill="zebra-skill")
    assert totals == {7} and len(rows) == 7


def _people(client, h, tid, names):
    return client.post(f"{API}/tests/{tid}/participants", headers=h, json={"names": names}).json()["participants"]


def _exam(client, h, title):
    q = _question(client, h, f"{title} q")
    t = client.post(f"{API}/tests", headers=h, json={"department_id": DEPT["Technical"], "title": title, "duration_min": 30}).json()
    sid = client.post(f"{API}/tests/{t['id']}/sections", headers=h, json={"title": "All"}).json()["sections"][0]["id"]
    client.post(f"{API}/sections/{sid}/items", headers=h, json={"kind": "question", "question_id": q["id"]})
    assert client.post(f"{API}/tests/{t['id']}/publish", headers=h).status_code == 200
    return t["id"]


def test_users_are_paged_and_searched_and_staff_and_candidates_stay_apart(client):
    h = _creator(client)
    tid = _exam(client, h, "Users paging exam")
    _people(client, h, tid, [f"Zed Person {i:02d}" for i in range(12)])
    admin = _admin(client)
    rows, totals = _pages(client, f"{API}/users", admin, 4, role="candidate", q="Zed Person")
    assert totals == {12} and len({r["id"] for r in rows}) == 12
    assert all(r["exams"] == ["Users paging exam"] for r in rows)      # the exams of the people on the page
    assert all("candidate" in r["roles"] for r in rows)
    r = client.get(f"{API}/users", headers=admin, params={"role": "candidate", "q": "Users paging exam", "limit": 100})  # a search finds the exam title too
    assert r.headers["x-total-count"] == "12"
    r = client.get(f"{API}/users", headers=admin, params={"role": "candidate", "q": "zed person 03", "limit": 100})
    assert r.headers["x-total-count"] == "1"
    staff = client.get(f"{API}/users", headers=admin, params={"limit": 2})
    assert int(staff.headers["x-total-count"]) >= 5 and len(staff.json()) == 2
    assert all(set(u["roles"]) - {"candidate"} for u in staff.json())  # nobody who is only a candidate
    everyone = client.get(f"{API}/users", headers=admin).json()        # no limit: the whole list, as before
    assert len(everyone) == int(staff.headers["x-total-count"])
    one_role = client.get(f"{API}/users", headers=admin, params={"role": "evaluator", "limit": 10})
    assert one_role.headers["x-total-count"] == "1" and one_role.json()[0]["email"] == "evaluator@globx.co.in"
    assert client.get(f"{API}/users", headers=h, params={"limit": 5}).status_code == 403  # a test creator may not list users


def test_the_exam_tables_page_their_rows_but_the_totals_cover_everyone(client):
    h = _creator(client)
    tid = _exam(client, h, "Rows paging exam")
    _people(client, h, tid, [f"Row Person {i:02d}" for i in range(23)])
    whole = client.get(f"{API}/tests/{tid}/results", headers=h).json()
    page = client.get(f"{API}/tests/{tid}/results", headers=h, params={"limit": 10, "offset": 20}).json()
    assert len(whole["rows"]) == 23 and whole["total"] == 23
    assert page["total"] == 23 and [r["assignment_id"] for r in page["rows"]] == [r["assignment_id"] for r in whole["rows"]][20:]
    assert page["summary"] == whole["summary"] and page["state"] == whole["state"]   # the tiles never depend on the page
    only = client.get(f"{API}/tests/{tid}/results", headers=h, params={"limit": 0}).json()
    assert only["rows"] == [] and only["total"] == 23 and only["summary"]["assigned"] == 23
    found = client.get(f"{API}/tests/{tid}/results", headers=h, params={"q": "row person 07", "limit": 50}).json()
    assert found["total"] == 1 and found["rows"][0]["name"] == "Row Person 07" and found["summary"]["assigned"] == 23
    c = client.get(f"{API}/tests/{tid}/candidates", headers=h, params={"limit": 5, "offset": 5}).json()
    assert len(c["rows"]) == 5 and c["total"] == 23 and sum(c["counts"].values()) == 23
    assert client.get(f"{API}/tests/{tid}/candidates", headers=h, params={"limit": 999}).status_code == 422
    assert len(client.get(f"{API}/tests/{tid}/candidates", headers=h).json()["rows"]) == 23


def test_the_results_table_does_not_ask_the_database_once_per_person(client):
    h = _creator(client)
    small, large = _exam(client, h, "Queries small"), _exam(client, h, "Queries large")
    _people(client, h, small, [f"Few {i}" for i in range(3)])
    _people(client, h, large, [f"Many {i}" for i in range(30)])
    counts = []

    def count(*_):
        counts[-1] += 1

    for tid in (small, large):
        counts.append(0)
        event.listen(engine, "before_cursor_execute", count)
        try:
            assert client.get(f"{API}/tests/{tid}/results", headers=h).status_code == 200
        finally:
            event.remove(engine, "before_cursor_execute", count)
    assert counts[1] <= counts[0] + 3, counts  # 30 people cost about as many queries as 3 (it used to be one more per person)
