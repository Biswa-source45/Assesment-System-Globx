"""Write or change one question with AI (POST /questions/ai-draft). The AI is replaced by a stand-in that answers from a script, so no network and no cost;
the platform's own checks (the library's rules, the judge, the SQL engine) are the real ones."""
import copy
import json

import pytest
from fastapi import HTTPException
from test_exam_pack import _bank_count, _creator
from test_exam_rules import DEPT, PW, _login, client  # noqa: F401  (client is a fixture)
from test_paper import data_uri, png

from app.api import exam_pack
from app.api.exam_pack import EXAMPLES

API = "/api/v1"
MCQ = {"type": "mcq_single", "title": "Capital of Japan", "statement": "What is the capital of Japan?", "options": ["Osaka", "Tokyo", "Kyoto", "Nagoya"],
       "correct": ["b"], "marks": 1, "difficulty": "easy"}
SUM_CODE = "a, b = map(int, input().split())\nprint(a + b)\n"


def _pack(*items, changes=("Made the question.",), notes=()):
    return {"request_ok": True, "changes": list(changes), "notes": list(notes), "question": items[0] if len(items) == 1 else list(items)}


class Script:
    """The stand-in AI. `main` is the reply (or a list of replies, one per call) to the question-writing call; the second-opinion calls have their own."""

    def __init__(self, monkeypatch, main, blind=None, code=None, sql=None):
        self.main, self.blind, self.code, self.sql = main if isinstance(main, list) else [main], blind, code, sql
        self.calls, self.second = [], []
        monkeypatch.setattr(exam_pack, "ask_ai_for_pack", self)

    def __call__(self, system, msg, pics):
        if system.startswith("You answer a multiple choice"):
            self.second.append((system, msg, pics))
            reply = self.blind if self.blind is not None else {"answer": ["b"]}
        elif system.startswith("You write a correct Python 3"):
            self.second.append((system, msg, pics))
            reply = self.code or {"source": SUM_CODE}
        elif system.startswith("You write one correct SQLite"):
            self.second.append((system, msg, pics))
            reply = self.sql or {"sql": EXAMPLES["sql"]["reference_sql"]}
        else:
            self.calls.append((system, msg, pics))
            reply = self.main[min(len(self.calls), len(self.main)) - 1]
            if isinstance(reply, Exception):
                raise reply
        return json.dumps(reply), "stop"


def _ask(client, h, dept="Technical", **kw):
    return client.post(f"{API}/questions/ai-draft", headers=h, json={"department_id": DEPT[dept], "prompt": "make a question", **kw})


def _current(**over):
    base = {"department_id": DEPT["Technical"], "type": "mcq_single", "title": "Capital of Japan", "body": "<p>What is the capital of Japan?</p>", "difficulty": "easy",
            "skills": ["geography"], "marks": 1, "negative_marks": 0, "status": "approved",
            "config": {"options": [{"id": "x1", "text": "Osaka", "correct": False}, {"id": "x2", "text": "Tokyo", "correct": True},
                                   {"id": "x3", "text": "Kyoto", "correct": False}, {"id": "x4", "text": "Nagoya", "correct": False}], "partial": True}}
    return {**base, **over}


def _code_item(**over):
    it = copy.deepcopy(EXAMPLES["coding"])
    it.pop("starter")
    return {**it, **over}


def test_a_prompt_makes_a_question_in_the_editors_shape_and_nothing_is_saved(client, monkeypatch):
    h = _creator(client)
    before = _bank_count(client, h, "Capital of Japan")
    ai = Script(monkeypatch, _pack(MCQ, changes=["Wrote a question about the capital of Japan."]))
    r = _ask(client, h, prompt="One easy question: capital of Japan", type="mcq_single")
    assert r.status_code == 200, r.text
    out = r.json()
    q = out["question"]
    assert q["type"] == "mcq_single" and q["title"] == "Capital of Japan" and q["difficulty"] == "easy" and q["marks"] == 1
    assert [o["text"] for o in q["config"]["options"]] == MCQ["options"] and [o["correct"] for o in q["config"]["options"]] == [False, True, False, False]
    assert "What is the capital of Japan?" in q["body"] and q["department_id"] == DEPT["Technical"]
    assert out["changes"] == ["Wrote a question about the capital of Japan."] and out["warnings"] == []   # the second opinion agrees
    assert _bank_count(client, h, "Capital of Japan") == before                                              # nothing was saved
    system, msg, pics = ai.calls[0]
    assert "Technical" in system and 'must be of type "mcq_single"' in system and "One easy question: capital of Japan" in msg and "THE QUESTION AS IT IS NOW" not in msg
    assert '"starter"' not in system.split("FORMAT")[1]                                                       # the starter rule is left out for one question
    assert len(ai.second) == 1                                                                                # the independent answer was asked once
    # what comes back can be saved by the ordinary route
    save = {k: q[k] for k in ("department_id", "type", "title", "body", "difficulty", "skills", "marks", "negative_marks", "config")}
    assert client.post(f"{API}/questions", headers=h, json={**save, "status": "approved"}).status_code == 200


def test_a_picture_is_read_by_the_ai_and_kept_in_the_question_only_where_the_ai_puts_it(client, monkeypatch):
    h = _creator(client)
    pic, option_pic = data_uri(png(120, 90, "blue")), data_uri(png(100, 100, "green"))
    ai = Script(monkeypatch, _pack({"type": "mcq_single", "title": "Speed from the graph", "statement": "What is the speed at 2 seconds? [[IMAGE 1]]",
                                    "options": ["10 km/h", "A [[IMAGE 2]]"], "correct": ["a"]}))
    out = _ask(client, h, prompt="", images=[pic, option_pic]).json()
    q = out["question"]
    assert pic in q["body"] and "[[IMAGE" not in q["body"]
    assert q["config"]["options"][1]["image"] == option_pic and q["config"]["options"][1]["text"] == "A"
    assert [(p[0], p[1], p[2]) for p in ai.calls[0][2]] == [("IMAGE 1", pic, "high"), ("IMAGE 2", option_pic, "high")]
    assert "(none: make the question the picture shows)" in ai.calls[0][1]
    assert [p[1] for p in ai.second[0][2]] == [pic, option_pic]            # the independent answer sees the pictures too


def test_a_picture_that_only_shows_text_is_not_attached(client, monkeypatch):
    h = _creator(client)
    Script(monkeypatch, _pack(MCQ))
    q = _ask(client, h, prompt="turn this photo into a question", images=[data_uri()]).json()["question"]
    assert "<img" not in q["body"]


def test_a_change_sends_the_current_question_and_keeps_what_the_ai_leaves_alone(client, monkeypatch):
    h = _creator(client)
    cur_pic = data_uri(png(80, 60, "red"))
    cur = _current(body=f'<p>Which city is shown?</p><p><img src="{cur_pic}" alt="Picture 1"></p>')
    changed = {**MCQ, "title": "Capital of Japan", "statement": "Which city is shown? [[IMAGE 1]]", "options": ["Osaka", "Tokyo", "Kyoto", "Nagoya", "Sapporo"], "correct": ["b"]}
    ai = Script(monkeypatch, _pack(changed, changes=["Added a fifth option, Sapporo."]))
    out = _ask(client, h, prompt="add a fifth option", current=cur).json()
    q = out["question"]
    assert [o["text"] for o in q["config"]["options"]][-1] == "Sapporo" and len(q["config"]["options"]) == 5 and out["changes"] == ["Added a fifth option, Sapporo."]
    assert cur_pic in q["body"]                                                                   # the question's own picture survived
    system, msg, pics = ai.calls[0]
    assert "CHANGING" in system and "THE QUESTION AS IT IS NOW" in msg and "[[IMAGE 1]]" in msg and "add a fifth option" in msg and "Osaka" in msg
    assert pics[0][1] == cur_pic and cur_pic not in msg                                          # the AI is shown the picture, never the raw data in the text
    assert len(ai.second) == 1                                                                   # an option was added, so the answer was checked again


def test_a_picture_that_goes_missing_in_a_change_is_said(client, monkeypatch):
    h = _creator(client)
    cur = _current(body=f'<p>What is the capital of Japan?</p><p><img src="{data_uri()}" alt="Picture 1"></p>')
    Script(monkeypatch, _pack(MCQ))                                                              # the AI returns the question without the marker
    out = _ask(client, h, prompt="make it worth 2 marks", current=cur).json()
    assert "<img" not in out["question"]["body"] and any("1 picture fewer" in n for n in out["notes"])


def test_a_change_that_does_not_touch_the_answer_is_not_checked_again(client, monkeypatch):
    h = _creator(client)
    ai = Script(monkeypatch, _pack({**MCQ, "marks": 3}, changes=["Marks are now 3."]))
    out = _ask(client, h, prompt="make it worth 3 marks", current=_current()).json()
    assert out["question"]["marks"] == 3 and out["warnings"] == [] and ai.second == []


def test_a_question_the_platform_refuses_is_sent_back_once_with_the_reasons(client, monkeypatch):
    h = _creator(client)
    ai = Script(monkeypatch, [_pack({**MCQ, "correct": ["z"]}), _pack(MCQ)])
    r = _ask(client, h)
    assert r.status_code == 200 and len(ai.calls) == 2
    assert "REFUSED" in ai.calls[1][1] and "correct answer 'z' is not one of the options" in ai.calls[1][1]
    ai = Script(monkeypatch, _pack({**MCQ, "correct": ["z"]}))                                    # still wrong the second time
    r = _ask(client, h)
    assert r.status_code == 422 and "could not make a valid question" in r.json()["detail"]["errors"][0] and len(ai.calls) == 2


def test_the_type_of_an_existing_question_cannot_be_changed_by_the_ai(client, monkeypatch):
    h = _creator(client)
    ai = Script(monkeypatch, _pack({"type": "short", "title": "Capital", "statement": "Name the capital of Japan.", "model_answer": "Tokyo"}))
    r = _ask(client, h, prompt="make it a written question", current=_current())
    assert r.status_code == 422 and 'must be of type "mcq_single", not "short"' in r.json()["detail"]["errors"][0] and len(ai.calls) == 2


def test_a_request_that_is_not_a_question_gets_the_ais_reason(client, monkeypatch):
    h = _creator(client)
    Script(monkeypatch, {"request_ok": False, "notes": ["The request is not about a question."], "question": MCQ})      # a question written anyway is not used
    r = _ask(client, h, prompt="what is the weather")
    assert r.status_code == 422 and r.json()["detail"]["errors"] == ["The request is not about a question."]
    Script(monkeypatch, {"sections": [], "notes": ["Cannot be done."], "changes": []})
    assert _ask(client, h).json()["detail"]["errors"] == ["Cannot be done."]


def test_an_ai_that_answers_in_the_paper_upload_format_or_garbles_its_end_is_still_understood(client, monkeypatch):
    h = _creator(client)
    Script(monkeypatch, {"sections": [{"title": "Draft", "questions": [MCQ]}], "changes": ["Made it."]})
    assert _ask(client, h).json()["question"]["title"] == "Capital of Japan"
    garbled = json.dumps({"request_ok": True, "changes": ["Made it."], "notes": [], "question": MCQ})[:-1] + ', "request_ok�: true, '   # the real model does this
    monkeypatch.setattr(exam_pack, "ask_ai_for_pack", lambda s, m, p: ((garbled, "stop") if s.startswith("You write ONE") else (json.dumps({"answer": ["b"]}), "stop")))
    out = _ask(client, h)
    assert out.status_code == 200 and out.json()["question"]["title"] == "Capital of Japan"


def test_a_second_question_from_the_ai_is_ignored_with_a_note(client, monkeypatch):
    h = _creator(client)
    Script(monkeypatch, _pack(MCQ, {**MCQ, "title": "Other"}))
    out = _ask(client, h).json()
    assert out["question"]["title"] == "Capital of Japan" and any("more than one" in n for n in out["notes"])


def test_requests_that_cannot_be_served_are_refused_with_a_plain_reason(client, monkeypatch):
    h = _creator(client)
    ai = Script(monkeypatch, _pack(MCQ))
    for kw, words in [({"prompt": ""}, "Write what the question should be"), ({"prompt": "x" * 4001}, "at most 4000"), ({"images": [data_uri()] * 5}, "At most 4 pictures"),
                      ({"images": ["data:image/png;base64,AAAA"]}, "Picture 1"), ({"type": "puzzle"}, "Unknown question type"),
                      ({"type": "coding"}, None), ({"prompt": "", "current": _current()}, "Tell the AI what to change")]:
        dept = "HR" if kw.get("type") == "coding" else "Technical"
        r = _ask(client, h, dept=dept, **kw)
        assert r.status_code == 422, kw
        if words:
            assert words in json.dumps(r.json()), kw
        else:
            assert "does not offer coding" in json.dumps(r.json())
    assert client.post(f"{API}/questions/ai-draft", headers=h, json={"department_id": "nope", "prompt": "x"}).status_code == 422
    assert ai.calls == []                                                                           # none of them cost an AI call


def test_when_the_ai_is_off_the_author_is_told_so(client, monkeypatch):
    h = _creator(client)
    r = _ask(client, h)                                                  # the test server has no AI: the paper upload's own words ("the JSON steps below") do not apply here
    assert r.status_code == 503 and "JSON steps" not in r.text and "switched on" in r.text


def test_only_authors_may_use_it(client, monkeypatch):
    Script(monkeypatch, _pack(MCQ))
    for who in ("recruiter@globx.co.in", "evaluator@globx.co.in"):
        assert _ask(client, _login(client, who, PW[who])).status_code == 403, who


def test_a_second_opinion_that_disagrees_is_a_warning_and_one_that_cannot_run_is_said(client, monkeypatch):
    h = _creator(client)
    Script(monkeypatch, _pack(MCQ), blind={"answer": ["a"]})
    out = _ask(client, h).json()
    assert out["question"] and len(out["warnings"]) == 1 and "chose a, the key says b" in out["warnings"][0]
    Script(monkeypatch, _pack({**MCQ, "answer_from_ai": True}), blind="not an object")
    w = _ask(client, h).json()["warnings"]
    assert any("worked out the answer itself" in x for x in w)
    monkeypatch.setattr(exam_pack, "ask_ai_for_pack", lambda s, m, p: (_ for _ in ()).throw(HTTPException(502, "x")) if s.startswith("You answer") else (json.dumps(_pack(MCQ)), "stop"))
    assert "could not be run" in _ask(client, h).json()["warnings"][0]


def test_a_coding_question_gets_its_expected_outputs_from_the_reference_and_is_cross_checked(client, monkeypatch):
    h = _creator(client)
    Script(monkeypatch, _pack(_code_item()))
    out = _ask(client, h, type="coding").json()
    q = out["question"]
    assert q["type"] == "coding" and out["warnings"] == [] and q["case_count"] == 4
    assert [c["expected"].strip() for c in q["cases"]] == ["5", "0", "0", "2000000000"] and q["config"]["reference"]["source"] == SUM_CODE
    assert {c["visibility"] for c in q["cases"]} == {"open", "hidden"} and not q["config"].get("starter")
    Script(monkeypatch, _pack(_code_item()), code={"source": "a, b = map(int, input().split())\nprint(a * b)\n"})   # a second solution that disagrees
    w = _ask(client, h, type="coding").json()["warnings"]
    assert len(w) == 1 and "different output on test case" in w[0]


def test_changing_a_coding_question_keeps_its_cases_and_constraints_and_drops_a_starter_that_no_longer_fits(client, monkeypatch):
    h = _creator(client)
    starter = "a, b = map(int, input().split())\n# TODO\n"
    cases = [{"ordinal": 1, "visibility": "open", "input": "2 3\n", "expected": "5\n", "weight": 1, "purpose": "sample"},
             {"ordinal": 2, "visibility": "hidden", "input": "7 8\n", "expected": "15\n", "weight": 1, "purpose": "hidden"}]
    cur = _current(type="coding", title="Sum", body="<p>Read two integers and print their sum.</p>", cases=cases, negative_marks=0, marks=10,
                   config={"languages": ["python"], "time_limit_ms": 2000, "memory_mb": 256, "constraints": "|a|,|b| <= 10", "comparator": "trim", "starter": {"python": starter},
                           "reference": {"language": "python", "source": SUM_CODE}})
    product = {"type": "coding", "title": "Product", "statement": "<p>Read two integers and print their product.</p>", "marks": 10, "languages": ["python"],
               "reference": {"language": "python", "source": "a, b = map(int, input().split())\nprint(a * b)\n"}}   # no test_cases: the current ones are kept
    ai = Script(monkeypatch, _pack(product, changes=["Now multiplies."]), code={"source": "a, b = map(int, input().split())\nprint(a * b)\n"})
    out = _ask(client, h, prompt="multiply instead of add", current=cur).json()
    q = out["question"]
    assert [c["input"].strip() for c in q["cases"]] == ["2 3", "7 8"] and [c["expected"].strip() for c in q["cases"]] == ["6", "56"]   # same inputs, new outputs from the new reference
    assert q["config"]["constraints"] == "|a|,|b| <= 10" and not q["config"].get("starter") and any("starter code was removed" in n for n in out["notes"])
    assert '"test_cases"' in ai.calls[0][1] and "2 3" in ai.calls[0][1]
    assert out["warnings"] == []
    same = {**product, "statement": "<p>Read two integers and print their sum.</p>", "reference": {"language": "python", "source": SUM_CODE}}  # only the marks change: the starter stays
    Script(monkeypatch, _pack({**same, "marks": 6}))
    out = _ask(client, h, prompt="6 marks", current=cur).json()
    assert out["question"]["config"]["starter"]["python"] == starter and out["question"]["marks"] == 6 and out["warnings"] == []


def test_a_case_too_large_to_show_is_never_shown_to_the_ai_and_is_kept(client, monkeypatch):
    h = _creator(client)
    big = "1 " + "2" * 2000 + "\n"
    cur = _current(type="coding", title="Sum", body="<p>Read two integers and print their sum.</p>", marks=10,
                   cases=[{"visibility": "open", "input": "2 3\n", "expected": "5\n"}, {"visibility": "hidden", "input": big, "expected": ""}],
                   config={"languages": ["python"], "time_limit_ms": 2000, "memory_mb": 256, "comparator": "trim", "reference": {"language": "python", "source": SUM_CODE}})
    ai = Script(monkeypatch, _pack({"type": "coding", "title": "Sum", "statement": "<p>Read two integers and print their sum.</p>", "marks": 12, "languages": ["python"],
                                    "reference": {"language": "python", "source": SUM_CODE}}))
    out = _ask(client, h, prompt="12 marks", current=cur)
    assert "too large to show" in ai.calls[0][1] and big not in ai.calls[0][1]
    assert out.status_code == 200, out.text
    assert [c["input"] for c in out.json()["question"]["cases"]] == ["2 3\n", big]


def test_an_sql_question_is_checked_by_the_engine_and_a_second_query(client, monkeypatch):
    h = _creator(client)
    Script(monkeypatch, _pack(copy.deepcopy(EXAMPLES["sql"])))
    out = _ask(client, h, type="sql").json()
    q = out["question"]
    assert q["type"] == "sql" and out["warnings"] == [] and len(q["cases"]) == 2 and q["sql_tables"][0][0]["name"] == "employees"
    assert json.loads(q["cases"][0]["expected"])["rows"] == [["Asha"], ["Chen"]]
    Script(monkeypatch, _pack(copy.deepcopy(EXAMPLES["sql"])), sql={"sql": "SELECT name FROM employees WHERE salary > 40000 ORDER BY name"})
    w = _ask(client, h, type="sql").json()["warnings"]
    assert len(w) == 1 and "different result on dataset" in w[0]
    broken = copy.deepcopy(EXAMPLES["sql"])
    for d in broken["datasets"]:
        d["data"] = "INSERT INTO nothing VALUES (1);"                                               # data the schema rejects
    Script(monkeypatch, _pack(broken))
    assert _ask(client, h, type="sql").status_code == 422


def test_a_written_question_is_made_and_the_author_is_told_it_is_not_checked_by_a_second_answer(client, monkeypatch):
    h = _creator(client)
    ai = Script(monkeypatch, _pack(copy.deepcopy(EXAMPLES["long"])))
    out = _ask(client, h, type="long").json()
    assert out["question"]["type"] == "long" and out["question"]["config"]["model_answer"] and ai.second == [] and any("model answer" in n for n in out["notes"])
    no_rubric = copy.deepcopy(EXAMPLES["long"])
    no_rubric.pop("rubric")
    Script(monkeypatch, _pack(no_rubric))
    assert _ask(client, h, type="long").status_code == 200                                         # a missing rubric is no reason to refuse


@pytest.mark.parametrize("raw", ["not json at all", '{"nothing": 1}'])
def test_an_unusable_ai_reply_is_a_plain_refusal(client, monkeypatch, raw):
    h = _creator(client)
    monkeypatch.setattr(exam_pack, "ask_ai_for_pack", lambda s, m, p: (raw, "stop"))
    r = _ask(client, h)
    assert r.status_code == 422 and r.json()["detail"]["errors"]
