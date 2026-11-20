"""SQL script questions (the candidate's statements change a throw-away database, then the author's checks are compared) and backend API questions
(a Flask or FastAPI app called in-process by a harness), both judged by the same machinery as ordinary SQL and coding questions."""
import json

import pytest
from test_exam_pack import _creator
from test_exam_rules import DEPT, client  # noqa: F401  (client is a fixture)

from app.sandbox import remote
from app.sandbox.judge import local_judge_code, local_judge_sql, local_run_reference, local_sql_expected_for, public_view
from app.sandbox.sql import run_script

API = "/api/v1"
SCHEMA = "CREATE TABLE courses (course_id INTEGER PRIMARY KEY, course_name TEXT NOT NULL, capacity INTEGER);"
DATA = "INSERT INTO courses VALUES (10,'DBMS',30),(11,'OOP',25);"
MORE = "INSERT INTO courses VALUES (12,'ML',20);"
CHECKS = ["SELECT name FROM pragma_table_info('courses') ORDER BY cid",
          "SELECT course_id, credits, enrolled FROM courses ORDER BY course_id",
          "INSERT INTO courses (course_id, course_name, capacity, enrolled) VALUES (99, 'X', 5, NULL)",
          "INSERT INTO courses (course_id, course_name) VALUES (10, 'Again')"]
REFERENCE = "ALTER TABLE courses ADD COLUMN credits INTEGER;\nALTER TABLE courses ADD COLUMN enrolled INTEGER NOT NULL DEFAULT 0;"


def _cfg(**extra):
    return {"schema": SCHEMA, "seed": "", "engines": ["sqlite"], "ordered": True, "reference_sql": REFERENCE, "checks": CHECKS, **extra}


def _cases(cfg):
    out = []
    for i, (vis, data) in enumerate((("open", DATA), ("hidden", MORE), ("hidden", ""))):
        out.append({"ordinal": i + 1, "visibility": vis, "input": data, "weight": 2.0, "expected": json.dumps(local_sql_expected_for(cfg, data))})
    return out


def _judge(script, kind="submit", cfg=None):
    cfg = cfg or _cfg()
    return local_judge_sql(cfg, _cases(cfg), "sqlite", script, kind)


# ---------------------------------------------------------------- SQL script questions
def test_the_reference_script_passes_and_a_different_correct_script_passes_too():
    assert _judge(REFERENCE)["passed"] == 3
    other = "ALTER TABLE courses ADD COLUMN enrolled INTEGER NOT NULL DEFAULT 0;\nALTER TABLE courses ADD COLUMN credits INTEGER;"   # the columns in another order: the column list differs
    assert _judge(other)["passed"] == 0
    same = "alter table courses add column credits integer;\n-- a comment\nALTER TABLE courses ADD COLUMN enrolled INTEGER NOT NULL DEFAULT 0;"
    r = _judge(same)
    assert r["passed"] == r["total"] == 3 and r["score"] == r["max_score"] == 6.0


def test_a_wrong_script_fails_and_the_open_case_shows_what_it_left_behind():
    r = _judge("ALTER TABLE courses ADD COLUMN credits INTEGER;", "run")
    assert r["total"] == 1 and r["cases"][0]["verdict"] == "WA"                                        # run: only the open case
    got, want = r["cases"][0]["result"], r["cases"][0]["expected_result"]
    assert got["columns"] == ["check", "result"] and got["rows"][1][1].startswith("error: no such column")
    assert want["rows"][1][1] == "[[10,null,0],[11,null,0]]"                                           # the checks the candidate can see, with the right outcome
    assert want["rows"][2][1] == "error: NOT NULL constraint failed" and want["rows"][3][1] == "error: UNIQUE constraint failed"   # key rules compare only the kind of error


def test_a_script_cannot_reach_outside_or_run_away():
    for script, verdict in (("PRAGMA foreign_keys=OFF;", "RE"), ("ATTACH DATABASE 'x.db' AS x;", "RE"), ("VACUUM INTO 'stolen.db';", "RE"), ("ALTER TABEL courses;", "RE"),
                            ("SELECT zeroblob(900000000);", "RE"), ("", "RE")):
        r = _judge(script)
        assert r["passed"] == 0 and {c["verdict"] for c in r["cases"]} == {verdict}, script
    slow = _judge("WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM r) SELECT count(*) FROM r;", "run")
    assert slow["cases"][0]["verdict"] == "TLE"                                                         # stopped by the time limit, the judge is not blocked
    grow = run_script(SCHEMA, "", DATA, "CREATE TABLE t(x); WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM r LIMIT 3000000) INSERT INTO t SELECT randomblob(1000) FROM r;", CHECKS)
    assert not grow["ok"] and "full" in grow["error"]                                                   # the database has a size limit


def test_hidden_cases_of_a_script_question_show_only_verdicts_to_the_candidate():
    shown = public_view(_judge(REFERENCE))
    assert shown["hidden"]["total"] == 2 and all(set(c) <= {"ordinal", "verdict", "passed", "weight", "time_ms", "memory_kb"} for c in shown["hidden"]["cases"])
    assert "expected_result" in json.dumps(shown["open"]) and "result" not in json.dumps(shown["hidden"])


def test_a_script_question_is_saved_checked_and_validated_by_the_server(client):
    h = _creator(client)
    body = {"department_id": DEPT["Technical"], "type": "sql", "title": "Add two columns", "body": "<p>Add credits and enrolled.</p>", "marks": 2, "status": "approved",
            "config": _cfg(), "cases": [{"ordinal": 1, "visibility": "open", "input": DATA, "expected": "", "weight": 1, "purpose": ""},
                                        {"ordinal": 2, "visibility": "hidden", "input": MORE, "expected": "", "weight": 1, "purpose": ""}]}
    r = client.post(f"{API}/questions", headers=h, json=body)
    assert r.status_code == 200, r.text
    q = r.json()
    assert q["config"]["validated"] is True and q["config"]["checks"] == CHECKS
    assert json.loads(next(c for c in q["cases"] if c["visibility"] == "open")["expected"])["rows"][2][1] == "error: NOT NULL constraint failed"   # computed from the reference script
    for bad, why in (({"checks": []}, "Check statements"), ({"checks": ["SELECT 1"] * 21}, "Check statements"), ({"checks": ["  "]}, "Check statements"),
                     ({"engines": ["sqlite", "postgresql"]}, "SQLite only")):
        r = client.post(f"{API}/questions", headers=h, json={**body, "config": {**_cfg(), **bad}})
        assert r.status_code == 422 and why in json.dumps(r.json()), bad
    broken = client.post(f"{API}/questions", headers=h, json={**body, "config": _cfg(reference_sql="ALTER TABEL nowhere;")})
    assert broken.status_code == 422 and "Reference query failed" in json.dumps(broken.json())          # a reference script that does not run is refused
    prev = client.post(f"{API}/questions/sql-preview", headers=h, json={"ddl": SCHEMA, "reference_sql": REFERENCE, "datasets": [DATA], "checks": CHECKS}).json()
    assert prev["results"][0]["ok"] and prev["results"][0]["columns"] == ["check", "result"]            # the editor's preview button


# ---------------------------------------------------------------- backend API questions
flask = pytest.importorskip("flask")
FLASK_APP = '''
from flask import Flask, jsonify, request
app = Flask(__name__)
courses = [{"id": 1, "name": "DBMS", "seats": 2}, {"id": 2, "name": "OOP", "seats": 0}]
print("noise from the candidate's own prints")
@app.route("/api/courses")
def listing():
    return jsonify(courses)
@app.route("/api/courses/<int:cid>/register", methods=["POST"])
def register(cid):
    for c in courses:
        if c["id"] == cid:
            if c["seats"] <= 0:
                return jsonify({"error": "course full"}), 400
            c["seats"] -= 1
            return jsonify(c)
    return jsonify({"error": "not found"}), 404
@app.route("/echo", methods=["POST"])
def echo():
    return jsonify(request.get_json())
if __name__ == "__main__":
    app.run()
'''
FASTAPI_APP = '''
from fastapi import FastAPI
app = FastAPI()
@app.get("/ping")
def ping():
    return {"pong": True}
@app.get("/boom")
def boom():
    raise RuntimeError("crash")
'''
API_CFG = {"languages": ["flask"], "time_limit_ms": 5000, "memory_mb": 256}
TEST = "GET /api/courses\nPOST /api/courses/1/register\nPOST /api/courses/1/register\nPOST /api/courses/1/register\nPOST /api/courses/2/register\nPOST /api/courses/99/register\nGET /api/courses\n"


def _reference(app, script):
    r = local_run_reference(API_CFG, "flask", app, [script])[0]
    assert r["ok"], r
    return r["expected"]


def test_an_api_question_is_judged_by_the_status_and_json_of_each_response():
    expected = _reference(FLASK_APP, TEST).split("\n")
    assert expected[0] == '200 [{"id":1,"name":"DBMS","seats":2},{"id":2,"name":"OOP","seats":0}]'    # keys sorted, no spaces: the same text however the app formats it
    assert expected[3:6] == ['400 {"error":"course full"}'] * 2 + ['404 {"error":"not found"}']
    case = [{"ordinal": 1, "visibility": "open", "input": TEST, "expected": "\n".join(expected), "weight": 5.0}]
    assert local_judge_code(API_CFG, case, "flask", FLASK_APP, "submit")["cases"][0]["verdict"] == "AC"                # (its prints and app.run() guard did no harm)
    wrong = FLASK_APP.replace('c["seats"] <= 0', 'c["seats"] < 0')                                                    # lets the seats go below zero
    assert local_judge_code(API_CFG, case, "flask", wrong, "submit")["cases"][0]["verdict"] == "WA"


def test_every_test_case_starts_a_fresh_app_and_a_post_body_reaches_the_route():
    one = _reference(FLASK_APP, "POST /api/courses/1/register")
    again = _reference(FLASK_APP, "POST /api/courses/1/register")
    assert one == again == '200 {"id":1,"name":"DBMS","seats":1}'                                                         # the second case did not see the first one's registration
    assert _reference(FLASK_APP, 'POST /echo {"b": [1, 2], "a": "x"}') == '200 {"a":"x","b":[1,2]}'


def test_fastapi_works_without_any_extra_setup_and_a_crash_is_a_500_answer():
    assert _reference(FASTAPI_APP, "GET /ping\nGET /boom\nGET /missing") == '200 {"pong":true}\n500 Internal Server Error\n404 {"detail":"Not Found"}'


def test_a_broken_api_file_stops_with_a_reason_not_a_wrong_answer():
    case = [{"ordinal": 1, "visibility": "open", "input": "GET /x", "expected": "200 {}", "weight": 1.0}]
    assert local_judge_code(API_CFG, case, "flask", "x = 1\n", "submit")["cases"][0]["verdict"] == "RE"             # no variable named app
    assert local_judge_code(API_CFG, case, "flask", "def (:\n", "submit")["compile"]["ok"] is False                   # a syntax error is reported before anything runs
    assert local_run_reference(API_CFG, "flask", FLASK_APP, ["BAD LINE"])[0]["ok"] is False                           # a request line the harness cannot read
    too_many = "GET /api/courses\n" * 201
    assert local_run_reference(API_CFG, "flask", FLASK_APP, [too_many])[0]["ok"] is False


def test_a_backend_language_is_not_offered_to_ordinary_coding_questions():
    assert "flask" in remote.language_names() and "flask" in remote.api_keys()
    assert "flask" not in remote.default_languages() and "python" in remote.default_languages()


# ---------------------------------------------------------------- a candidate takes both kinds of question
def _wait(client, path, h):
    import time
    for _ in range(120):
        r = client.get(path, headers=h).json()
        if r.get("status") in ("done", "error"):
            return r
        time.sleep(0.5)
    raise AssertionError("the judge did not answer")


def test_a_candidate_answers_a_script_question_and_an_api_question_and_is_marked(client):
    from test_exam_rules import PW, _login
    creator, recruiter = _creator(client), _login(client, "recruiter@globx.co.in", PW["recruiter@globx.co.in"])
    script = {"type": "sql", "title": "Add two columns to courses", "statement": "Add credits and enrolled.", "marks": 4, "schema": SCHEMA, "reference_sql": REFERENCE, "checks": CHECKS,
              "datasets": [{"data": DATA, "visibility": "open"}, {"data": MORE, "visibility": "hidden"}]}
    api = {"type": "coding", "title": "Course Seats API", "statement": "Back end only. Start with course 1 DBMS (2 seats) and course 2 OOP (0 seats).", "marks": 6,
           "languages": ["flask"], "time_limit_ms": 5000, "reference": {"language": "flask", "source": FLASK_APP},
           "test_cases": [{"input": "GET /api/courses\nPOST /api/courses/1/register", "visibility": "open"}, {"input": TEST, "visibility": "hidden"}]}
    t = client.post(f"{API}/tests", headers=creator, json={"department_id": DEPT["Technical"], "title": "Script and API exam", "duration_min": 30}).json()
    got = client.post(f"{API}/tests/{t['id']}/import-questions", headers=creator, json={"pack": {"format": "globx-exam-questions/1", "sections": [{"title": "All", "questions": [script, api]}]}, "dry_run": False})
    assert got.status_code == 200, got.text
    assert client.post(f"{API}/tests/{t['id']}/publish", headers=creator).status_code == 200
    p = client.post(f"{API}/tests/{t['id']}/participants", headers=recruiter, json={"names": ["Sia Script"]}).json()["participants"][0]
    cand = _login(client, p["username"], p["password"])
    at = client.post(f"{API}/assignments/{p['assignment_id']}/start", headers=cand, json={"consent": {"accepted": True}, "system_check": {}}).json()["attempt_id"]
    qs = {q["title"]: q for s in client.get(f"{API}/attempts/{at}", headers=cand).json()["sections"] for q in s["questions"]}
    sq, aq = qs["Add two columns to courses"], qs["Course Seats API"]
    assert sq["script"] is True and sq["engines"][0]["key"] == "sqlite" and "checks" not in json.dumps(sq)             # the candidate is told it is a script question, never the answer
    assert [l["api"] for l in aq["languages"]] == [True] and aq["languages"][0]["key"] == "flask" and "app = Flask(__name__)" in aq["starter"]["flask"]
    assert aq["open_cases"][0]["input"].startswith("GET /api/courses") and aq["open_cases"][0]["expected"].startswith("200 [")        # sample requests and their responses
    assert len(aq["hidden_weights"]) == 1

    def submit(q, language, source):
        sid = client.post(f"{API}/attempts/{at}/code/{q['id']}/submit", headers=cand, json={"language": language, "source": source}).json()["submission_id"]
        return _wait(client, f"/api/v1/submissions/{sid}", cand)
    wrong = submit(sq, "sqlite", "ALTER TABLE courses ADD COLUMN credits INTEGER;")
    assert wrong["score"] == 0 and wrong["result"]["hidden"]["total"] == 1 and "expected_result" not in json.dumps(wrong["result"]["hidden"])
    right = submit(sq, "sqlite", REFERENCE)
    assert right["score"] == 4.0 and right["result"]["passed"] == 2
    assert submit(aq, "flask", FLASK_APP.replace('c["seats"] <= 0', 'c["seats"] < 0'))["score"] < 6                         # lets seats go below zero: the hidden case fails
    full = submit(aq, "flask", FLASK_APP)
    assert full["score"] == 6.0 and full["result"]["passed"] == 2
    assert client.post(f"{API}/attempts/{at}/submit", headers=cand, json={}).status_code == 200
    import time
    for _ in range(120):                                                                                              # the marking runs in the background: let it finish
        if client.get(f"{API}/attempts/{at}", headers=cand).json()["attempt"]["status"] in ("review_pending", "evaluated"):
            break
        time.sleep(0.5)
    rep = client.get(f"{API}/reports/attempts/{at}", headers=creator).json()
    assert rep["attempt"]["total_score"] == 10.0                                                                      # 4 for the script question, 6 for the API question
