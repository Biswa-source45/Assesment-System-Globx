"""Building an exam from an AI-made JSON file. Shares its fixture and helpers with test_exam_rules (seeded database, staff logins)."""
import copy

from test_exam_rules import DEPT, PW, _login, client  # noqa: F401  (client is a fixture)

from app.api.exam_pack import EXAMPLES, _example_pack
from app.models import QTYPES

API = "/api/v1"
COUNTS = {"mcq_single": 2, "mcq_multi": 1, "short": 1, "long": 1, "coding": 2, "sql": 1}


def _creator(client):
    return _login(client, "creator@globx.co.in", PW["creator@globx.co.in"])


def _exam(client, h, dept="Technical", title="Pack exam", **extra):
    r = client.post(f"{API}/tests", headers=h, json={"department_id": DEPT[dept], "title": title, "duration_min": 45, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def _bank_count(client, h, title):
    return len(client.get(f"{API}/questions", headers=h, params={"q": title}).json())


def _import(client, h, tid, pack, dry_run=True):
    return client.post(f"{API}/tests/{tid}/import-questions", headers=h, json={"pack": pack, "dry_run": dry_run})


def test_prompt_carries_the_exams_details_and_only_what_its_department_offers(client):
    h = _creator(client)
    t = _exam(client, h, "Technical", "Prompt exam", description="Screening for backend engineers", instructions="Read each question twice.",
              cutoff=12, starts_at="2030-01-02T09:00:00Z", ends_at="2030-01-02T18:00:00Z")
    r = client.post(f"{API}/tests/{t['id']}/question-prompt", headers=h, json=COUNTS)
    assert r.status_code == 200
    p = r.json()["prompt"]
    for part in ("Technical", "Prompt exam", "Screening for backend engineers", "Read each question twice.", "45 minutes", "2030-01-02 09:00 UTC",
                 "12 marks", "2 x multiple choice", "2 x coding", "1 x SQL", "8 in total", "globx-exam-questions/1"):
        assert part in p, part
    assert '"type": "sql"' in p and '"type": "coding"' in p  # one example per requested type
    only_mcq = client.post(f"{API}/tests/{t['id']}/question-prompt", headers=h, json={"mcq_single": 3}).json()["prompt"]
    assert '"type": "coding"' not in only_mcq and '"type": "sql"' not in only_mcq

    hr = _exam(client, h, "HR", "HR prompt exam")
    r = client.post(f"{API}/tests/{hr['id']}/question-prompt", headers=h, json={"mcq_single": 2, "coding": 1})
    assert r.status_code == 422 and "HR" in r.text and "coding" in r.text
    assert client.post(f"{API}/tests/{hr['id']}/question-prompt", headers=h, json={"mcq_single": 2, "short": 1}).status_code == 200
    for bad in ({}, {"mcq_single": -1, "short": 3}, {"mcq_single": 201}):
        assert client.post(f"{API}/tests/{t['id']}/question-prompt", headers=h, json=bad).status_code == 422


def test_the_examples_in_the_prompt_import_and_the_exam_then_publishes(client):
    h = _creator(client)
    t = _exam(client, h, title="Import everything")
    pack = _example_pack(list(QTYPES))
    pack["sections"][0]["timer_min"] = 10
    before = _bank_count(client, h, "Sum of two numbers")

    preview = _import(client, h, t["id"], pack).json()  # a dry run says what would happen and saves nothing
    assert preview["ok"] and preview["errors"] == []
    assert [s["count"] for s in preview["sections"]] == [1] * 6 and preview["total_questions"] == 6
    assert preview["total_marks"] == 1 + 2 + 2 + 5 + 10 + 10
    assert client.get(f"{API}/tests/{t['id']}", headers=h).json()["sections"] == [] and _bank_count(client, h, "Sum of two numbers") == before

    out = _import(client, h, t["id"], pack, dry_run=False)
    assert out.status_code == 200, out.text
    exam = out.json()
    assert [s["title"] for s in exam["sections"]][:2] == ["Section A: Multiple choice", "Section B: Multiple answer"]
    assert exam["sections"][0]["timer_min"] == 10 and exam["question_count"] == 6 and exam["total_marks"] == 30
    assert _bank_count(client, h, "Sum of two numbers") == before + 1

    coding = next(i["question"] for s in exam["sections"] for i in s["items"] if i["question"]["type"] == "coding")
    full = client.get(f"{API}/questions/{coding['id']}", headers=h).json()
    assert full["department_id"] == DEPT["Technical"] and full["status"] == "approved" and full["validated"]
    assert [c["expected"] for c in full["cases"]] == ["5", "0", "0", "2000000000"]  # computed by running the reference solution
    assert "<p>Read two integers" in full["body"]
    pub = client.post(f"{API}/tests/{t['id']}/publish", headers=h)
    assert pub.status_code == 200, pub.text  # imported coding and SQL questions are validated, so the exam can go live


def test_a_wrong_file_creates_nothing_and_every_problem_is_listed(client):
    h = _creator(client)
    t = _exam(client, h, title="Import problems")
    bad_mcq = {**EXAMPLES["mcq_single"], "title": "Bad letter ZZ", "correct": ["e"]}                     # only a-d exist
    two_right = {**EXAMPLES["mcq_single"], "title": "Two right ZZ", "correct": ["a", "b"]}                 # single answer, two marked
    bad_rubric = {**EXAMPLES["long"], "title": "Bad rubric ZZ", "marks": 4}                                # rubric adds up to 5
    no_hidden = {**EXAMPLES["coding"], "title": "No hidden ZZ", "test_cases": [{"input": "1 2", "visibility": "open"}]}
    crashes = {**EXAMPLES["coding"], "title": "Crashing ZZ", "reference": {"language": "python", "source": "print(1/0)"}}
    bad_sql = {**EXAMPLES["sql"], "title": "Bad SQL ZZ", "reference_sql": "SELECT nope FROM employees"}
    no_text = {k: v for k, v in EXAMPLES["short"].items() if k != "statement"}
    unknown = {"type": "essay", "title": "Unknown type ZZ"}
    good = {**EXAMPLES["mcq_single"], "title": "Fine one ZZ"}
    pack = {"sections": [{"title": "A", "questions": [good, bad_mcq, two_right, bad_rubric, no_hidden]},
                         {"title": "B", "timer_min": 0, "questions": [crashes, bad_sql, no_text, unknown, "just text"]}, {"title": "C", "questions": []}]}
    r = _import(client, h, t["id"], pack)
    assert r.status_code == 200 and not r.json()["ok"]
    errs = "\n".join(r.json()["errors"])
    for part in ("Section 1, question 2 (Bad letter ZZ): correct answer 'e'", "Section 1, question 3 (Two right ZZ)", "Section 1, question 4 (Bad rubric ZZ)",
                 "Section 1, question 5 (No hidden ZZ): Add at least 1 sample", "Section 2, question 1 (Crashing ZZ): the reference solution fails on 4 of 4 test cases","Section 2, question 2 (Bad SQL ZZ)",
                 "Section 2, question 3", "'statement'", "Section 2, question 4 (Unknown type ZZ): 'type' must be one of", "Section 2, question 5: is not an object",
                 "Section 2: 'timer_min'", "Section 3: needs a 'questions' list"):
        assert part in errs, part
    assert "Fine one ZZ" not in errs  # the good question raises nothing

    real = _import(client, h, t["id"], pack, dry_run=False)
    assert real.status_code == 422 and "errors" in real.json()["detail"]
    assert client.get(f"{API}/tests/{t['id']}", headers=h).json()["sections"] == []     # nothing was added to the exam...
    assert _bank_count(client, h, "ZZ") == 0                                            # ...and nothing reached the bank, not even the good question

    for junk in ({}, {"sections": []}, {"sections": "x"}, [1, 2], {"sections": [{"questions": [good] * 201}]}):
        assert not _import(client, h, t["id"], junk).json()["ok"]


def test_the_file_never_decides_expected_outputs(client):
    h = _creator(client)
    t = _exam(client, h, title="Expected outputs")
    coding = copy.deepcopy(EXAMPLES["coding"])
    for c in coding["test_cases"]:
        c["expected"] = "999"                                   # a wrong answer smuggled into the file is ignored
    sql = {**EXAMPLES["sql"], "datasets": [{**d, "expected": "[]"} for d in EXAMPLES["sql"]["datasets"]]}
    out = _import(client, h, t["id"], {"sections": [{"title": "Code", "questions": [coding, sql]}]}, dry_run=False).json()
    items = out["sections"][0]["items"]
    cases = client.get(f"{API}/questions/{items[0]['question']['id']}", headers=h).json()["cases"]
    assert [c["expected"] for c in cases] == ["5", "0", "0", "2000000000"]
    sql_cases = client.get(f"{API}/questions/{items[1]['question']['id']}", headers=h).json()["cases"]
    assert '"Asha"' in sql_cases[0]["expected"] and '"Chen"' in sql_cases[0]["expected"]


def test_department_draft_and_permission_rules(client):
    h = _creator(client)
    hr = _exam(client, h, "HR", "HR import")
    pack = {"sections": [{"title": "Tech", "questions": [EXAMPLES["coding"]]}]}
    r = _import(client, h, hr["id"], pack).json()
    assert not r["ok"] and "does not offer coding" in " ".join(r["errors"])               # HR offers no coding

    ok = {"sections": [{"title": "Plain", "questions": [{**EXAMPLES["mcq_single"], "title": "HR plain"}, {**EXAMPLES["short"], "title": "HR short"}]}]}
    assert _import(client, h, hr["id"], ok, dry_run=False).status_code == 200
    again = _import(client, h, hr["id"], ok, dry_run=False).json()                           # a second file is added after the first one
    assert [s["title"] for s in again["sections"]] == ["Plain", "Plain"] and again["question_count"] == 4
    assert client.post(f"{API}/tests/{hr['id']}/publish", headers=h).status_code == 200
    assert _import(client, h, hr["id"], ok).status_code == 409                               # published exams are frozen, even for a dry run
    assert client.post(f"{API}/tests/{hr['id']}/question-prompt", headers=h, json={"short": 1}).status_code == 200  # the prompt is only text, still available

    staff = _login(client, "recruiter@globx.co.in", PW["recruiter@globx.co.in"])
    t = _exam(client, h, title="Who may import")
    assert _import(client, staff, t["id"], ok).status_code == 403                            # recruiters cannot author exams
    assert client.post(f"{API}/tests/{t['id']}/question-prompt", headers=staff, json={"short": 1}).status_code == 403
    assert client.post(f"{API}/tests/{t['id']}/import-questions", json={"pack": ok}).status_code in (401, 403)
