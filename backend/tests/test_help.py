"""The Help screen's stateless tools: the samples, a file check without an exam, and the real marking rule on a made-up answer."""
import copy

from test_exam_pack import _bank_count, _creator, _exam, _import
from test_exam_rules import DEPT, PW, _login, client  # noqa: F401  (client is a fixture)

from app.models import QTYPES

API = "/api/v1"


def _check(client, h, pack, dept="Technical"):
    return client.post(f"{API}/help/check-pack", headers=h, json={"pack": pack, "department_id": DEPT[dept]})


def test_the_samples_are_valid_for_every_type_and_check_out_as_a_whole_file(client):
    h = _creator(client)
    s = client.get(f"{API}/help/samples", headers=h).json()
    assert set(s["examples"]) == set(QTYPES) and s["format"] == "globx-exam-questions/1"
    assert len(s["pack"]["sections"]) == len(QTYPES)
    r = _check(client, h, s["pack"]).json()
    assert r["ok"] and r["errors"] == [] and r["total_questions"] == len(QTYPES)


def test_the_check_says_what_an_import_dry_run_says_and_saves_nothing(client):
    h = _creator(client)
    pack = {"format": "x", "sections": [{"title": "A", "questions": [
        {"type": "mcq_single", "title": "Help check prime", "statement": "Which is prime?", "options": ["4", "7"], "correct": ["b"]},
        {"type": "mcq_single", "title": "Help check bad letter", "statement": "Which is prime?", "options": ["4", "7"], "correct": ["z"]}]}]}
    before = _bank_count(client, h, "Help check")
    mine = _check(client, h, pack).json()
    t = _exam(client, h, title="Help parity exam")
    real = _import(client, h, t["id"], pack).json()
    assert mine == real and not mine["ok"] and "'z'" in mine["errors"][0]
    assert _bank_count(client, h, "Help check") == before  # neither the check nor the dry run created anything
    good = copy.deepcopy(pack)
    del good["sections"][0]["questions"][1]
    assert _check(client, h, good).json()["total_questions"] == 1 and _bank_count(client, h, "Help check") == before


def test_the_check_refuses_nonsense_and_other_peoples_departments(client):
    h = _creator(client)
    assert _check(client, h, ["not", "an", "object"]).json()["ok"] is False
    assert _check(client, h, {"sections": []}).json()["ok"] is False
    r = client.post(f"{API}/help/check-pack", headers=h, json={"pack": {"sections": [{"questions": [{"type": "mcq_single"}]}]}, "department_id": "nope"}).json()
    assert not r["ok"] and r["errors"]  # an unknown department is a message, not a crash
    assert client.post(f"{API}/help/check-pack", headers=h, json={"pack": "x" * 2_100_000, "department_id": DEPT["Technical"]}).status_code == 413
    assert client.post(f"{API}/help/check-pack", json={"pack": {}, "department_id": DEPT["Technical"]}).status_code in (401, 403)  # signed out


def test_who_may_use_the_tools(client):
    rec = _login(client, "recruiter@globx.co.in", PW["recruiter@globx.co.in"])
    assert client.get(f"{API}/help/samples", headers=rec).status_code == 200  # everyone who sees exams may read the help
    body = {"options": ["a", "b"], "correct": ["a"], "selected": ["a"]}
    assert client.post(f"{API}/help/try-mcq", headers=rec, json=body).status_code == 200
    assert client.post(f"{API}/help/check-pack", headers=rec, json={"pack": {}, "department_id": DEPT["Technical"]}).status_code == 403  # it runs code: authors only
    assert client.get(f"{API}/help/samples").status_code in (401, 403)


def test_try_mcq_is_the_real_marking_rule(client):
    h = _creator(client)

    def score(selected, correct, options, multi, marks=2, negative=0):
        r = client.post(f"{API}/help/try-mcq", headers=h, json={"options": options, "correct": correct, "selected": selected, "marks": marks, "negative": negative, "multi": multi})
        assert r.status_code == 200, r.text
        return r.json()["score"]

    o = ["a", "b", "c", "d"]
    assert score(["b"], ["b"], o, False, marks=1) == 1 and score(["c"], ["b"], o, False, marks=1, negative=0.5) == -0.5 and score([], ["b"], o, False) == 0
    assert score(["a", "c"], ["a", "c"], o, True) == 2                # all the right ones
    assert score(["a"], ["a", "c"], o, True) == 1                     # half of them, half the marks
    assert score(["a", "c", "d"], ["a", "c"], o, True) == 1.75        # one wrong tick takes 0.25 off
    assert score(o, ["a", "c"], o, True) == 0                         # ticking everything cannot win
    for bad in ({"options": [], "correct": [], "selected": []}, {"options": list("abcdefghi"), "correct": [], "selected": []},
                {"options": ["a"], "correct": ["a"], "selected": ["a"], "marks": 1000}, {"options": ["a"], "correct": ["a"], "selected": ["a"], "negative": -1}):
        assert client.post(f"{API}/help/try-mcq", headers=h, json=bad).status_code == 422
