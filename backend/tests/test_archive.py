"""Archiving an exam: only the Super Admin can do it and see archived exams; nothing is deleted, results stay readable, restoring puts the exam back as it was."""
from test_exam_pack import _exam as _draft_exam
from test_exam_rules import DEPT, PW, _login, _start, client  # noqa: F401  (client is a fixture)
from test_results import _person

API = "/api/v1"


def _people(client):
    return {r: _login(client, f"{r}@globx.co.in", PW[f"{r}@globx.co.in"]) for r in ("superadmin", "creator", "recruiter", "evaluator")}


def _published(client, h, title):
    q = client.post(f"{API}/questions", headers=h, json={"department_id": DEPT["Technical"], "type": "mcq_single", "title": f"{title} q", "body": "<p>x</p>", "marks": 1,
                                                        "config": {"options": [{"id": "a", "text": "A", "correct": True}, {"id": "b", "text": "B", "correct": False}]}}).json()
    t = client.post(f"{API}/tests", headers=h, json={"department_id": DEPT["Technical"], "title": title, "duration_min": 30}).json()
    sid = client.post(f"{API}/tests/{t['id']}/sections", headers=h, json={"title": "All"}).json()["sections"][0]["id"]
    assert client.post(f"{API}/sections/{sid}/items", headers=h, json={"kind": "question", "question_id": q["id"]}).status_code == 200
    assert client.post(f"{API}/tests/{t['id']}/publish", headers=h).status_code == 200
    return t["id"]


def _titles(client, h, archived=False):
    r = client.get(f"{API}/tests", headers=h, params={"archived": "true"} if archived else None)
    assert r.status_code == 200, r.text
    return [t["title"] for t in r.json()]


def test_only_the_super_admin_archives_and_sees_archived_exams_and_nothing_is_lost(client):
    who = _people(client)
    sa, creator, recruiter = who["superadmin"], who["creator"], who["recruiter"]
    tid = _published(client, creator, "Archive me ZZ")
    cand, aid = _person(client, recruiter, tid, "Archive Candidate")
    assert "Archive me ZZ" in _titles(client, creator) and "Archive me ZZ" in _titles(client, recruiter)

    for h in (creator, recruiter, who["evaluator"]):                                  # nobody but the Super Admin may archive
        assert client.delete(f"{API}/tests/{tid}", headers=h).status_code == 403
    assert client.delete(f"{API}/tests/{tid}", headers=sa).status_code == 200
    assert client.delete(f"{API}/tests/{tid}", headers=sa).status_code == 409         # already archived

    for h in (sa, creator, recruiter):                                                # gone from every normal list
        assert "Archive me ZZ" not in _titles(client, h)
    assert "Archive me ZZ" in _titles(client, sa, archived=True)                      # the Archived window belongs to the Super Admin
    for h in (creator, recruiter):
        assert client.get(f"{API}/tests", headers=h, params={"archived": "true"}).status_code == 403
        assert client.get(f"{API}/tests/{tid}", headers=h).status_code == 404         # not even by its direct address
        assert client.get(f"{API}/tests/{tid}/results", headers=h).status_code == 404

    res = client.get(f"{API}/tests/{tid}/results", headers=sa)                        # the student data is still there for the Super Admin
    assert res.status_code == 200 and [r["name"] for r in res.json()["rows"]] == ["Archive Candidate"]
    mine = client.get(f"{API}/me/assignments", headers=cand).json()
    assert all(a["assignment_id"] != aid for a in mine)                               # the candidate no longer sees it...
    assert client.post(f"{API}/assignments/{aid}/start", headers=cand, json={"consent": {"accepted": True}, "system_check": {}}).status_code != 200  # ...nor can start it

    assert client.post(f"{API}/tests/{tid}/restore", headers=creator).status_code == 403
    back = client.post(f"{API}/tests/{tid}/restore", headers=sa)
    assert back.status_code == 200 and back.json()["status"] == "published"           # exactly as it was
    assert client.post(f"{API}/tests/{tid}/restore", headers=sa).status_code == 409   # not archived any more
    assert "Archive me ZZ" in _titles(client, recruiter) and "Archive me ZZ" not in _titles(client, sa, archived=True)
    again = next(a for a in client.get(f"{API}/me/assignments", headers=cand).json() if a["assignment_id"] == aid)
    assert again["can_start"] is True                                                 # the candidate can take it again


def test_a_draft_goes_back_to_a_draft_and_an_exam_being_taken_is_not_archived(client):
    who = _people(client)
    sa, creator = who["superadmin"], who["creator"]
    d = _draft_exam(client, creator, title="Draft archive ZZ")
    assert client.delete(f"{API}/tests/{d['id']}", headers=sa).status_code == 200
    assert client.post(f"{API}/tests/{d['id']}/restore", headers=sa).json()["status"] == "draft"

    tid = _published(client, creator, "Busy exam ZZ")
    cand, aid = _person(client, creator, tid, "Busy Candidate")
    _start(client, cand, aid)
    busy = client.delete(f"{API}/tests/{tid}", headers=sa)
    assert busy.status_code == 409 and "taking this exam" in busy.text
    assert "Busy exam ZZ" in _titles(client, sa) and "Busy exam ZZ" not in _titles(client, sa, archived=True)
