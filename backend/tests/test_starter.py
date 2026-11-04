"""Starter code: a coding question never reaches a candidate with an empty editor, and a starter is checked when the question is saved.
Shares its fixture and helpers with test_exam_rules / test_exam_pack."""
from test_exam_pack import _creator, _exam, _import
from test_exam_rules import DEPT, _coding, _login, _start, client  # noqa: F401  (client is a fixture)
from test_results import _person

from app.api.exam_pack import EXAMPLES, _example_pack
from app.sandbox import remote
from app.sandbox.languages import SKELETON, STARTER_SUM

API = "/api/v1"
ALL = list(remote.language_names())  # what this machine can run: the same five as the judge in production


def _published_with(client, h, question_id, title):
    t = client.post(f"{API}/tests", headers=h, json={"department_id": DEPT["Technical"], "title": title, "duration_min": 30}).json()
    sid = client.post(f"{API}/tests/{t['id']}/sections", headers=h, json={"title": "Code"}).json()["sections"][0]["id"]
    assert client.post(f"{API}/sections/{sid}/items", headers=h, json={"kind": "question", "question_id": question_id}).status_code == 200
    assert client.post(f"{API}/tests/{t['id']}/publish", headers=h).status_code == 200
    return t["id"]


def _what_the_candidate_gets(client, h, question_id, title):
    """The coding question exactly as the exam screen receives it."""
    tid = _published_with(client, h, question_id, title)
    cand, aid = _person(client, h, tid, "Starter Candidate")
    at = _start(client, cand, aid)
    page = client.get(f"{API}/attempts/{at}", headers=cand).json()
    return next(q for s in page["sections"] for q in s["questions"] if q["id"] == question_id)


def _coding_with(starter, languages=("python",), title="Starter question"):
    body = _coding(title, "6")
    body["config"] = {**body["config"], "languages": list(languages), "starter": starter}
    return body


def test_a_question_without_starter_code_opens_with_a_template_in_every_language(client):
    h = _creator(client)
    body = _coding("No starter ZZ", "6")
    body["config"]["languages"] = ALL
    q = client.post(f"{API}/questions", headers=h, json=body)
    assert q.status_code == 200, q.text
    got = _what_the_candidate_gets(client, h, q.json()["id"], "Template exam")
    assert set(got["starter"]) == set(ALL)
    for lang in ALL:
        assert got["starter"][lang] == SKELETON[lang] and got["starter"][lang].strip(), lang  # never an empty editor
    assert "public class Main" in got["starter"]["java"] and "System.out.println" in got["starter"]["java"]


def test_a_blank_starter_is_the_same_as_none(client):
    h = _creator(client)
    q = client.post(f"{API}/questions", headers=h, json=_coding_with({"python": "   \n"}, title="Blank starter ZZ"))
    assert q.status_code == 200, q.text
    assert _what_the_candidate_gets(client, h, q.json()["id"], "Blank exam")["starter"]["python"] == SKELETON["python"]


def test_a_valid_starter_is_kept_and_given_to_the_candidate(client):
    h = _creator(client)
    mine = "n = int(input())\n# TODO: print the double of n\n"
    body = _coding_with({"python": mine, "java": "this is for a language the question does not allow"}, title="Own starter ZZ")
    q = client.post(f"{API}/questions", headers=h, json=body)
    assert q.status_code == 200, q.text
    assert client.get(f"{API}/questions/{q.json()['id']}", headers=h).json()["config"]["starter"] == {"python": mine}  # the disallowed language is dropped
    assert _what_the_candidate_gets(client, h, q.json()["id"], "Own exam")["starter"] == {"python": mine}


def test_a_starter_that_cannot_help_the_candidate_is_refused_and_nothing_is_saved(client):
    h = _creator(client)
    before = len(client.get(f"{API}/questions", headers=h, params={"q": "Bad starter"}).json())
    bad = {
        "does not compile": ("def (:\n", "Starter code for Python 3 does not compile"),
        "crashes on the first sample": ("n = int(input())\nprint(1 / 0)\n", "stops with an error on the first sample"),
        "already solves the question": ("n = int(input())\nprint(2 * n)\n", "already solves the question"),
    }
    for why, (code, message) in bad.items():
        r = client.post(f"{API}/questions", headers=h, json=_coding_with({"python": code}, title=f"Bad starter {why}"))
        assert r.status_code == 422 and message in r.text, (why, r.text)
    assert len(client.get(f"{API}/questions", headers=h, params={"q": "Bad starter"}).json()) == before


def test_the_ai_pack_asks_for_starters_and_the_imported_question_carries_them(client):
    h = _creator(client)
    t = _exam(client, h, title="Starter pack")
    prompt = client.post(f"{API}/tests/{t['id']}/question-prompt", headers=h, json={"coding": 1}).json()["prompt"]
    for part in ('"starter"', "Input format", "Output format", "Constraints", "must not solve the problem", "public class Main", "TODO"):
        assert part in prompt, part
    assert EXAMPLES["coding"]["starter"] == STARTER_SUM                       # the example the AI copies is a working starter

    pack = _example_pack(["coding"])
    out = _import(client, h, t["id"], pack, dry_run=False)
    assert out.status_code == 200, out.text
    item = out.json()["sections"][0]["items"][0]["question"]
    assert client.get(f"{API}/questions/{item['id']}", headers=h).json()["config"]["starter"] == STARTER_SUM

    # an AI that forgets the starters still gives a usable question (the template), and one that sends rubbish is told
    plain = {k: v for k, v in EXAMPLES["coding"].items() if k != "starter"}
    plain["title"] = "Pack without starter ZZ"
    ok = _import(client, h, t["id"], {"sections": [{"title": "Plain", "questions": [plain]}]})
    assert ok.json()["ok"], ok.text
    wrong = _import(client, h, t["id"], {"sections": [{"title": "Wrong", "questions": [{**plain, "starter": "print('hi')"}]}]}).json()
    assert not wrong["ok"] and "'starter' must be an object" in " ".join(wrong["errors"])
    solved = _import(client, h, t["id"], {"sections": [{"title": "Solved", "questions": [{**plain, "starter": {"python": EXAMPLES["coding"]["reference"]["source"]}}]}]}).json()
    assert not solved["ok"] and "already solves the question" in " ".join(solved["errors"])
