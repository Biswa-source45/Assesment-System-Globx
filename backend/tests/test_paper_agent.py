"""The paper reader and the analysing pass: layouts the rules now read (a marking scheme on page 1, options side by side, "Model answer", marks with a
negative-marking note, multi-line and request test cases, a schema given once for a section), and the plan the AI makes first."""
import json

from test_exam_pack import _creator, _exam
from test_exam_rules import client  # noqa: F401  (client is a fixture)
from test_paper import _understand

from app.api import exam_pack
from app.api.exam_pack import _clean_plan, _paper_facts, _plan_hint, _spans
from app.services.paper_parse import clean_pages, parse_paper, read_code_block, tidy_paper

API = "/api/v1"
PAD = "Time allowed: 100 minutes. Total marks: 50. Every wrong answer loses 0.5 marks and the score of one question never goes below 0. " * 3


def _read(text):
    body, key, _ = _paper_facts(tidy_paper(clean_pages(text)))
    body = clean_pages(body)
    return body, key, parse_paper(body, clean_pages(key), _spans(body))


def _items(res):
    return [it for s in res["sections"] for it in s["items"]]


def test_a_marking_scheme_on_page_one_is_not_the_answer_key_and_one_line_options_are_read():
    paper = (f"Screening Test\nMarking scheme\n{PAD}\nSection A: Aptitude (3 marks)\n"
             "Q1. What is 2 + 2? [1 mark; 0.5 off for a wrong answer]\n(a) 3 (b) 4 (c) 5 (d) 6 (e) 7\nModel answer: (b).\nThe sum is four.\n"
             "Q2. Which are even? [2 marks; 0.5 off for a wrong\nanswer]\n(a) 2 (b) 3 (c) 4 (d) 5\nModel answer: (a), (c).\n"
             "Q3. Capital of France? [1 mark]\n(a) Rome\n(b) Paris\nAnswer: (b)\n")
    body, key, res = _read(paper)
    assert key == "" and res["exact"] == 3                                                                     # "Marking scheme" is the paper's own rules, not the key
    q1, q2, q3 = (i["question"] for i in _items(res))
    assert [o["text"] for o in q1["options"]] == ["3", "4", "5", "6", "7"] and q1["correct"] == ["b"] and q1["marks"] == 1 and q1["negative_marks"] == 0.5
    assert q2["type"] == "mcq_multi" and q2["correct"] == ["a", "c"] and q2["marks"] == 2 and q2["negative_marks"] == 0.5     # the note wrapped over two lines
    assert "negative_marks" not in q3 and q3["correct"] == ["b"]                                               # options already one per line are left as they are
    with_key = paper + "Answer Key and Solutions\nFor the examiner only.\nQ1 (b)\n"
    assert _read(with_key)[1].startswith("Answer Key and Solutions")                                           # a real key after the questions is still found


def test_options_wrapped_over_lines_and_a_marker_only_option_are_rebuilt_one_per_line():
    text = "Q1. Pick one [1 mark]\n(a) first option (b) second option wraps\nonto a second line (c) third\n(d) fourth\nAnswer: (b)\nQ2. Next [1 mark]\n(a) x\n(b) y\nAnswer: (a)\n"
    res = parse_paper(*_read(text)[::2][:1], "", [])
    qs = [i["question"] for i in _items(res)]
    assert [o["text"] for o in qs[0]["options"]] == ["first option", "second option wraps onto a second line", "third", "fourth"] and qs[0]["correct"] == ["b"]
    assert [o["text"] for o in qs[1]["options"]] == ["x", "y"]


BACKEND = """Q21. Course Seats API [10 marks]
Build the back end only. GET /api/courses lists the courses. POST /api/courses/{id}/register frees a seat or fails with 400 or 404.
Starting data: course 1 DBMS has 2 seats, course 2 OOP has 0 seats.
Model answer (Flask):
from flask import Flask, jsonify
app = Flask(__name__)
@app.route("/api/courses")
def listing():
    return jsonify([])
Test cases:
open:
GET /api/courses
POST /api/courses/1/register
hidden:
POST /api/courses/99/register
hidden: GET /api/courses
"""


def test_a_backend_question_with_requests_as_test_cases_is_read_as_a_flask_coding_question():
    q = read_code_block(21, BACKEND, "")
    assert q["type"] == "coding" and q["reference"]["language"] == "flask" and q["languages"] == ["flask"] and q["time_limit_ms"] == 5000
    assert "app = Flask(__name__)" in q["reference"]["source"] and "    return jsonify([])" in q["reference"]["source"]       # indentation kept, the test cases are not part of the code
    assert [(c["visibility"], c["input"]) for c in q["test_cases"]] == [("open", "GET /api/courses\nPOST /api/courses/1/register"), ("hidden", "POST /api/courses/99/register"),
                                                                           ("hidden", "GET /api/courses")]


def test_tests_that_are_only_described_are_left_to_the_ai_and_a_written_model_answer_is_not_code():
    described = BACKEND.split("Test cases:")[0] + "Tests (auto-evaluated) - 2 open + 1 hidden:\nopen 1: GET /api/courses -> 200 both courses\nhidden 1: POST /x -> 404\n"
    assert read_code_block(21, described, "") is None
    case_study = "Q14. Design a system [5 marks]\nDescribe the modules.\nModel answer (indicative):\nModules - a registration service and a catalogue service.\n"
    assert read_code_block(14, case_study, "") is None


SQL_PAPER = ("Section D: SQL (6 marks)\nSchema (shared by all questions):\nCREATE TABLE courses (\n  course_id INTEGER PRIMARY KEY,\n  course_name TEXT\n);\n"
             "INSERT INTO courses VALUES (10,'DBMS'),(11,'OOP');\n"
             "Q15. Write ONE SQL query that lists the course names. [2 marks]\nModel answer:\nSELECT course_name FROM courses ORDER BY course_name;\n"
             "Q16. Add a column credits to courses. [2 marks]\nModel answer:\nALTER TABLE courses ADD COLUMN credits INTEGER;\n"
             "Q17. Which course has the lowest id? [2 marks]\nModel answer:\nSELECT course_name FROM courses ORDER BY course_id LIMIT 1;\n")


def test_a_schema_written_once_for_a_section_reaches_its_questions_and_ddl_is_never_taken_for_a_query():
    _, _, res = _read("Intro\nQ0. Warm up\n(a) x\n(b) y\nAnswer: (a)\n" + SQL_PAPER)
    items = {i["number"]: i for i in _items(res)}
    q15, q17 = items[15]["question"], items[17]["question"]
    assert items[15]["kind"] == "code" and q15["type"] == "sql" and "CREATE TABLE courses" in q15["schema"] and "INSERT INTO courses" in q15["datasets"][0]["data"]
    assert q15["reference_sql"] == "SELECT course_name FROM courses ORDER BY course_name" and "Model answer" not in q15["statement"]
    assert items[17]["kind"] == "code" and q17["reference_sql"].startswith("SELECT course_name")
    assert items[16]["kind"] == "block" and "CREATE TABLE courses" in items[16]["context"]                    # ALTER is not one query: the AI makes it a script question, with the schema as context


def test_a_language_line_a_script_question_with_checks_and_hidden_data_written_in_the_paper_are_read_without_the_ai():
    paper = ("Section C: Code (4 marks)\n"
             "Q1. Echo [2 marks]\nPrint the input.\nLanguage: Python / Java / C++ or JavaScript (Node.js), TypeScript\nSample answer (Python):\nprint(input())\nTest cases:\nopen: a\nhidden: b\n"
             "Section D: SQL (2 marks)\nOne table for all questions.\nCREATE TABLE t (id INTEGER, qty INTEGER);\nINSERT INTO t VALUES (1,0),(2,5);\n"
             "Q2. Remove zero rows [1 mark]\nDelete the rows with quantity 0.\nAnswer:\nDELETE FROM t WHERE qty = 0;\nChecks:\nSELECT id FROM t ORDER BY id\nSELECT COUNT(*) FROM t\n"
             "Hidden data: several zeros\nINSERT INTO t VALUES (1,0),(2,0),(3,4);\nHidden data: none to delete\nINSERT INTO t VALUES (1,1);\n"
             "Q3. Big rows [1 mark]\nList the ids with qty above 3.\nAnswer:\nSELECT id FROM t WHERE qty > 3;\nHidden data:\nINSERT INTO t VALUES (7,9);\n")
    res = _read(paper)[2]
    q1, q2, q3 = (i["question"] for i in _items(res))
    assert res["exact"] == 3 and q1["languages"] == ["python", "java", "cpp", "javascript"] and "Language" not in q1["statement"]   # the languages the paper allows (TypeScript is not a platform language)
    assert q2["type"] == "sql" and q2["reference_sql"] == "DELETE FROM t WHERE qty = 0;" and q2["checks"] == ["SELECT id FROM t ORDER BY id", "SELECT COUNT(*) FROM t"]
    assert [d["visibility"] for d in q2["datasets"]] == ["open", "hidden", "hidden"] and "(2,5)" in q2["datasets"][0]["data"] and "(3,4)" not in q2["datasets"][0]["data"]
    assert q2["datasets"][1]["data"] == "INSERT INTO t VALUES (1,0),(2,0),(3,4);" and q2["datasets"][2]["data"] == "INSERT INTO t VALUES (1,1);"
    assert q3["reference_sql"] == "SELECT id FROM t WHERE qty > 3" and "checks" not in q3 and [d["visibility"] for d in q3["datasets"]] == ["open", "hidden"]


def test_starter_code_written_in_the_paper_is_read_per_language_and_a_page_break_never_cuts_a_query():
    paper = ("Section C: Code (3 marks)\n"
             "Q1. Echo [2 marks]\nPrint the input.\nLanguage: Python / JavaScript\n"
             "Starter code (Python):\nimport sys\ndef solve(x):\n    # write your code here\n    return 0\nprint(solve(sys.stdin.read()))\n"
             "Starter code (JavaScript):\nconst input = require('fs').readFileSync(0, 'utf8');\nconsole.log(0);\n"
             "Sample answer (Python):\nprint(input())\nTest cases:\nopen: a\nhidden: b\n"
             "Section D: SQL (2 marks)\nCREATE TABLE t (id INTEGER, qty INTEGER);\nINSERT INTO t VALUES (1,0),(2,5);\n"
             "Q2. Ids with stock [1 mark]\nList the ids.\nAnswer:\nSELECT id\n\n--- Page 3 ---\nFROM t\nWHERE qty > 0;\n"
             "Q3. Another [1 mark]\nList all ids.\nAnswer:\nSELECT id FROM t;\n")
    res = _read(paper)[2]
    q1, q2, _ = (i["question"] for i in _items(res))
    assert set(q1["starter"]) == {"python", "javascript"}
    assert "def solve(x):\n    # write your code here\n    return 0" in q1["starter"]["python"] and "console.log(0);" in q1["starter"]["javascript"]
    assert "Starter" not in q1["statement"] and q1["reference"]["source"] == "print(input())"    # the starters are neither the statement nor the sample answer
    assert q2["reference_sql"] == "SELECT id\nFROM t\nWHERE qty > 0"                               # the page break left no blank line in the query


def test_a_sample_answer_with_a_variable_called_test_is_not_cut_short_and_rules_is_a_label():
    paper = ("Section C: Code (2 marks)\nQ1. Echo [2 marks]\nRules\n1. Print the input.\n2. Nothing else.\n"
             "Sample answer (Python):\ntest = []\ntest += [input()]\ntests = test\nprint(tests[0])\nTest cases:\nopen: a\nhidden: b\n"
             "Q2. Another [1 mark]\nSay hi.\nSample answer (Python):\nprint('hi')\nTest cases:\nopen: x\nhidden: y\n")
    q1 = _items(_read(paper)[2])[0]["question"]
    assert q1["reference"]["source"] == "test = []\ntest += [input()]\ntests = test\nprint(tests[0])"
    assert [c["input"] for c in q1["test_cases"]] == ["a", "b"] and "Rules\n1. Print the input." in q1["statement"]    # "Rules" stays a line of its own above the list


def test_open_and_hidden_datasets_in_the_paper_keep_their_visibility_and_order():
    paper = ("Section D: SQL (2 marks)\nCREATE TABLE t (id INTEGER, qty INTEGER);\nINSERT INTO t VALUES (1,5);\n"
             "Q1. Ids [1 mark]\nList the ids.\nAnswer:\nSELECT id FROM t;\n"
             "Open data: none at all\nINSERT INTO t VALUES (9,9);\nHidden data: one more\nINSERT INTO t VALUES (2,2);\nOpen data: a last sample\nINSERT INTO t VALUES (3,3);\n"
             "Q2. Quantities [1 mark]\nList the quantities.\nAnswer:\nSELECT qty FROM t;\n")
    q1 = _items(_read(paper)[2])[0]["question"]
    assert [(d["visibility"], d["data"]) for d in q1["datasets"]] == [("open", "INSERT INTO t VALUES (1,5);"), ("open", "INSERT INTO t VALUES (9,9);"),
                                                                      ("hidden", "INSERT INTO t VALUES (2,2);"), ("open", "INSERT INTO t VALUES (3,3);")]


def test_a_long_question_text_keeps_its_numbered_rules_bullets_and_code_words():
    from app.api.exam_pack import _structure
    text = "Check `payload` in this order:\n1. First rule, return (400, 'x').\n2. Second rule.\n- one more thing\nInput format\nOne line with `s`."
    assert _structure(text, "coding") == ("<p>Check <code>payload</code> in this order:</p><ol><li>First rule, return (400, 'x').</li><li>Second rule.</li></ol>"
                                          "<ul><li>one more thing</li></ul><p><b>Input format</b></p><p>One line with <code>s</code>.</p>")


# ---------------------------------------------------------------- the plan
PLAN_REPLY = {"questions": [{"number": 16, "type": "sql_script", "marks": 2, "negative_marks": None}, {"number": "17", "type": "sql", "marks": 2}, {"number": 18, "type": "nonsense"}],
              "shared_context": [{"applies_to": [16, 17], "text": "CREATE TABLE courses (\n  course_id INTEGER PRIMARY KEY,\n  course_name TEXT\n);"},
                                 {"applies_to": [16], "text": "a schema the paper never contained"}],
              "marking_rules": "Two marks each."}


def test_the_plan_keeps_only_what_can_be_trusted_and_turns_into_a_hint_for_the_ai():
    text = clean_pages(SQL_PAPER)
    plan = _clean_plan(PLAN_REPLY, text)
    assert sorted(plan["questions"]) == [16, 17] and plan["questions"][16]["type"] == "sql_script" and plan["questions"][17]["marks"] == 2.0   # a made-up type is dropped, "17" is a number
    assert len(plan["shared"]) == 1                                                                              # a shared text that is not in the paper is dropped
    hint = _plan_hint(plan, text, 16)
    assert 'Question 16: SQL script (type "sql" with "checks"), 2 marks' in hint and "CREATE TABLE courses" in hint and "Two marks each." in hint
    assert _plan_hint({}, text, 16) == "" and _clean_plan("junk", text) == {} and _clean_plan({"questions": "x"}, text) == {}
    assert exam_pack.ask_ai_for_plan(text) == {}                                                                  # the test server has the AI off: no plan, nothing breaks


def test_the_plan_reaches_the_ai_with_the_question_and_fills_in_what_the_ai_left_out(client, monkeypatch):
    h = _creator(client)
    t = _exam(client, h, "Technical", "Plan exam")
    seen = []

    def fake(system, msg, pictures):
        seen.append((system, msg))
        q = {"type": "sql", "title": "Add credits", "statement": "Add a column credits to courses.", "schema": "CREATE TABLE courses (course_id INTEGER PRIMARY KEY, course_name TEXT);",
             "reference_sql": "ALTER TABLE courses ADD COLUMN credits INTEGER;\nALTER TABLE courses ADD COLUMN x INTEGER;", "checks": ["SELECT name FROM pragma_table_info('courses') ORDER BY cid"],
             "datasets": [{"data": "INSERT INTO courses VALUES (1,'A');", "visibility": "open"}, {"data": "INSERT INTO courses VALUES (2,'B');", "visibility": "hidden"}]}
        return json.dumps({"sections": [{"title": "S", "questions": [q]}]}), "stop"
    monkeypatch.setattr(exam_pack, "ask_ai_for_pack", fake)
    monkeypatch.setattr(exam_pack, "ask_ai_for_plan", lambda text: _clean_plan(PLAN_REPLY, text))
    paper = "Intro\nQ0. Warm up\n(a) x\n(b) y\nAnswer: (a)\n" + SQL_PAPER
    got = _understand(client, h, t["id"], paper).json()
    system, msg = seen[0]
    assert "conversion agent" in system and "SQL SCRIPT question" in system and "BACKEND API question" in system and "negative_marks" in system     # the agent's instructions
    assert 'PLAN (made by reading the whole paper first; follow it)' in msg and 'Question 16: SQL script' in msg and "SHARED CONTEXT" in msg
    script = next(q for s in got["pack"]["sections"] for q in s["questions"] if q.get("checks"))
    assert script["marks"] == 2.0 and script["reference_sql"].count("ALTER TABLE") == 2                            # the plan's marks, the whole script kept
    rep = client.post(f"{API}/tests/{t['id']}/import-questions", headers=h, json={"pack": got["pack"], "dry_run": True, "detail": True}).json()
    assert not [e for e in rep["errors"] if "credits" in e], rep["errors"]       # the script question itself is valid (the plain SQL ones lack hidden data: the AI is off here)


def test_the_paper_s_own_schema_and_rows_are_used_when_the_ai_leaves_them_out_or_misplaces_the_checks():
    context = "CREATE TABLE t (x INTEGER);\nINSERT INTO t VALUES (1);"
    q = {"type": "sql", "schema": "", "datasets": [{"data": "INSERT INTO member VALUES (1, 'A');", "visibility": "open"},            # a check statement, into a table that does not exist yet
                                                     {"data": "INSERT INTO t VALUES (2);", "visibility": "hidden"},                  # real hidden data for this schema: kept
                                                     {"data": "INSERT INTO t VALUES (3); DELETE FROM t;", "visibility": "hidden"}]}  # not only INSERT lines: dropped
    exam_pack._shared_database(q, context)
    assert q["schema"] == "CREATE TABLE t (x INTEGER);"
    assert [(d["visibility"], d["data"]) for d in q["datasets"]] == [("open", "INSERT INTO t VALUES (1);"), ("hidden", "INSERT INTO t VALUES (2);")]
    other = {"type": "sql", "schema": "CREATE TABLE u (y INTEGER);", "datasets": []}
    exam_pack._shared_database(other, "")                                                                                         # no shared context: nothing is touched
    assert other == {"type": "sql", "schema": "CREATE TABLE u (y INTEGER);", "datasets": []}


def test_checks_written_with_descriptions_or_as_one_text_are_accepted_as_plain_statements():
    described = exam_pack._loosen({"checks": [{"statement": "SELECT 1", "description": "one"}, {"sql": "SELECT 2"}, "SELECT 3"]})
    assert described["checks"] == ["SELECT 1", "SELECT 2", "SELECT 3"]
    assert exam_pack._loosen({"checks": "SELECT 1\n\nSELECT 2\n"})["checks"] == ["SELECT 1", "SELECT 2"]
