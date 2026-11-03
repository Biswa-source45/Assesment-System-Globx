"""Build an exam's questions from a JSON file an AI made: the prompt to give the AI, and the checked import.

The examiner copies the prompt (it holds this exam's details and how many questions of each type are needed) into ChatGPT or Claude
together with their own question set, and uploads the JSON that comes back. Nothing is saved unless the whole file is valid.
Every question goes through the same rules as a question typed into the question editor (library.validate_question, _apply, _check_on_save).
The AI never supplies computed answers: the server runs the reference solution (coding) or reference query (SQL) to get the expected output."""
from __future__ import annotations

import html
import json
import re
from datetime import timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.library import TYPE_NAME, CaseIn, QuestionIn, _apply, _check_on_save, _department, validate_question
from app.api.tests import AUTHOR, _draft, _test, test_out
from app.core.deps import audit
from app.db import get_db
from app.models import QTYPES, Department, Question, Section, SectionItem, Test, User, aware, uid
from app.sandbox.judge import run_reference
from app.sandbox import remote
from app.services.attempts import proctoring_config

router = APIRouter(tags=["exam-pack"])

FORMAT = "globx-exam-questions/1"
DEFAULT_MARKS = {"mcq_single": 1, "mcq_multi": 1, "short": 2, "long": 5, "coding": 10, "sql": 10}
MAX_SECTIONS, MAX_QUESTIONS, MAX_BYTES = 20, 200, 2_000_000

# One valid question per type. The prompt shows these to the AI, and a test imports them, so the format described to the AI cannot drift from what the server accepts.
EXAMPLES: Dict[str, Dict[str, Any]] = {
    "mcq_single": {"type": "mcq_single", "title": "Prime number", "statement": "Which of these numbers is prime?",
                   "options": ["4", "6", "7", "9"], "correct": ["c"], "marks": 1, "difficulty": "easy", "skills": ["numeracy"]},
    "mcq_multi": {"type": "mcq_multi", "title": "Even numbers", "statement": "Which of these numbers are even? Choose all that apply.",
                  "options": ["2", "3", "4", "5"], "correct": ["a", "c"], "marks": 2, "negative_marks": 0.5, "difficulty": "easy"},
    "short": {"type": "short", "title": "Primary key", "statement": "In two sentences, what is a primary key in a database table?",
              "model_answer": "A column, or set of columns, whose value is unique for every row and identifies that row. It can never be empty.",
              "keywords": ["unique", "identif|row|record"], "max_words": 100, "marks": 2},
    "long": {"type": "long", "title": "Process and thread", "statement": "Explain the difference between a process and a thread. Give one example of when you would use each.",
             "model_answer": "A process has its own memory space; threads of one process share memory. Processes are isolated (a crash stays inside), threads are cheaper to create and communicate. Use processes for isolation, threads for parallel work on shared data.",
             "rubric": [{"name": "Correct definitions", "max": 2, "descriptor": "Memory isolation versus shared memory"},
                        {"name": "Trade-offs and examples", "max": 2, "descriptor": "A sensible example for each"},
                        {"name": "Clarity", "max": 1, "descriptor": "Organised and concise"}],
             "marks": 5, "difficulty": "medium"},
    "coding": {"type": "coding", "title": "Sum of two numbers",
               "statement": "<p>Read two integers <code>a b</code> on one line and print their sum.</p><p><b>Sample input</b></p><pre>2 3</pre><p><b>Sample output</b></p><pre>5</pre>",
               "marks": 10, "difficulty": "easy", "languages": ["python", "java", "cpp", "c", "javascript"],
               "reference": {"language": "python", "source": "a, b = map(int, input().split())\nprint(a + b)\n"},
               "test_cases": [{"input": "2 3", "visibility": "open", "purpose": "sample"}, {"input": "-5 5", "visibility": "open", "purpose": "negative number"},
                              {"input": "0 0", "visibility": "hidden", "purpose": "zeros"}, {"input": "1000000000 1000000000", "visibility": "hidden", "purpose": "large values"}]},
    "sql": {"type": "sql", "title": "Well paid employees",
            "statement": "Return the names of employees who earn more than 50000, in alphabetical order. Column: name.",
            "marks": 10, "difficulty": "easy", "ordered": True,
            "schema": "CREATE TABLE employees (id INTEGER PRIMARY KEY, name TEXT, salary INTEGER);",
            "reference_sql": "SELECT name FROM employees WHERE salary > 50000 ORDER BY name",
            "datasets": [{"data": "INSERT INTO employees VALUES (1,'Asha',60000),(2,'Ben',40000),(3,'Chen',55000);", "visibility": "open"},
                         {"data": "INSERT INTO employees VALUES (1,'Zed',50000),(2,'Amy',50001);", "visibility": "hidden"}]},
}


def _plain(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def _when(d) -> str:
    return aware(d).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if d else "not set"  # the database may hand back its own zone


class PromptIn(BaseModel):
    mcq_single: int = 0
    mcq_multi: int = 0
    short: int = 0
    long: int = 0
    coding: int = 0
    sql: int = 0


def _example_pack(types: List[str]) -> Dict[str, Any]:
    return {"format": FORMAT, "sections": [{"title": f"Section {chr(65 + i)}: {TYPE_NAME[t].capitalize()}", "timer_min": None, "questions": [EXAMPLES[t]]}
                                           for i, t in enumerate(types)]}


def make_prompt(t: Test, dept: Department, counts: Dict[str, int]) -> str:
    types = [x for x in QTYPES if counts.get(x)]
    p = proctoring_config(t)
    rules = [f"camera and face check {'on' if p['webcam'] else 'off'}", f"full screen {'on' if p['fullscreen'] else 'off'}",
             f"{p['tab_switch_limit']} window leaves allowed" if p["tab_switch_limit"] else "no window-leave limit", "copy and paste blocked" if p["block_paste"] else "copy and paste allowed"]
    need = "\n".join(f"- {counts[x]} x {TYPE_NAME[x]} (\"type\": \"{x}\")" for x in types)
    return f"""You are helping an examiner prepare an exam for an online assessment platform. Produce ONE JSON document that the platform imports. Reply with the JSON only: no explanation, no markdown.

EXAM
Department: {dept.name}
Title: {t.title}
Description: {_plain(t.description) or "not set"}
Instructions shown to candidates: {_plain(t.instructions) or "not set"}
Time allowed per candidate: {t.duration_min} minutes
Opens: {_when(t.starts_at)}; closes: {_when(t.ends_at)}
Pass mark: {t.cutoff:g} marks
Rules: {", ".join(rules)}
Write questions that fit this department and exam, and that a candidate can finish within the time allowed.

QUESTIONS NEEDED ({sum(counts[x] for x in types)} in total)
{need}
Make one section per question type, in the order above, each with a short title.

SOURCE
The examiner may paste or attach their own question set after this prompt. If they do, convert those questions faithfully (keep their wording, answers and marks) and use the counts above. If the set has fewer questions of a type than needed, write the missing ones to suit the exam. If a right answer is not given, give your best answer: the examiner checks every question before publishing.

FORMAT
- Top level: {{"format": "{FORMAT}", "sections": [{{"title": "...", "timer_min": null, "questions": [ ... ]}}]}}. timer_min is a number of minutes or null.
- Every question has: "type", "title" (short), "statement" (the question text; plain text, or simple HTML using only p, pre, code, b, i, ul, li, br), and optionally "marks", "difficulty" ("easy", "medium" or "hard"), "skills" (list of short tags).
- mcq_single and mcq_multi: "options" (2 to 8 texts, without letters) and "correct" (list of letters, "a" for the first option; exactly one letter for mcq_single). Optional "negative_marks".
- short: "model_answer", optional "keywords" (list; use | between alternatives, for example "retry|retries") and "max_words".
- long: "model_answer" and "rubric": a list of {{"name", "max", "descriptor"}} whose "max" values add up to the question's marks.
- coding: "reference" ({{"language", "source"}}: a correct solution that reads standard input and prints the answer), "test_cases" (list of {{"input", "visibility": "open" or "hidden", "purpose"}}; at least one open sample and one hidden case; give inputs only, never expected outputs: the platform runs your reference solution to get them), optional "languages" (python, java, cpp, c, javascript), "time_limit_ms", "memory_mb". Put a sample input and output in the statement.
- sql (SQLite syntax): "schema" (CREATE TABLE statements), "reference_sql" (the correct query), "datasets" (list of {{"data": "INSERT statements", "visibility": "open" or "hidden"}}; at least one of each), optional "ordered" (true when row order matters). Never give expected results: the platform runs your query.
- Default marks if you leave them out: {", ".join(f"{TYPE_NAME[x]} {DEFAULT_MARKS[x]}" for x in QTYPES)}.

EXAMPLE (valid; replace its content with the real questions)
{json.dumps(_example_pack(types), indent=2)}
"""


def _num(item: dict, key: str, default: float, errs: List[str]) -> float:
    v = item.get(key, default)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        errs.append(f"'{key}' must be a number")
        return default
    return v


def _texts(item: dict, key: str, errs: List[str]) -> List[str]:
    v = item.get(key, [])
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        errs.append(f"'{key}' must be a list of texts")
        return []
    return [x.strip() for x in v if x.strip()]


def _html(text: str) -> str:
    """Plain text becomes paragraphs (the same rule as frontend/src/lib/html.js); text that already holds HTML goes on as it is and is sanitised on save."""
    if re.search(r"<[a-z][\s\S]*>", text, re.I):
        return text
    return "".join(f"<p>{html.escape(p.strip(), quote=False)}</p>".replace("\n", "<br>") for p in re.split(r"\n{2,}", text) if p.strip())


def _cases(item: dict, key: str, field: str, errs: List[str]) -> List[CaseIn]:
    raw = item.get(key)
    if not isinstance(raw, list) or not all(isinstance(c, dict) for c in raw):
        errs.append(f"'{key}' must be a list of objects with '{field}' and 'visibility'")
        return []
    out = []
    for n, c in enumerate(raw, 1):
        text, vis = c.get(field), c.get("visibility", "open")
        if not isinstance(text, str):
            errs.append(f"{key} {n}: '{field}' must be text")
        elif vis not in ("open", "hidden"):
            errs.append(f"{key} {n}: 'visibility' must be \"open\" or \"hidden\"")
        else:  # a trailing newline is what a program reading standard input expects
            out.append(CaseIn(input=text if field == "data" or text.endswith("\n") else text + "\n", visibility=vis, purpose=str(c.get("purpose") or "")))
    return out


def _body(item: Any, dept_id: str, errs: List[str]) -> Optional[QuestionIn]:
    """One pack item to the library's own QuestionIn; the library's rules then judge it."""
    if not isinstance(item, dict):
        errs.append("is not an object")
        return None
    t = item.get("type")
    if t not in QTYPES:
        errs.append(f"'type' must be one of {', '.join(QTYPES)}")
        return None
    n0 = len(errs)
    statement = item.get("statement") if isinstance(item.get("statement"), str) else ""
    if not statement.strip():
        errs.append("'statement' (the question text) is missing")
    cfg: Dict[str, Any] = {}
    cases: Optional[List[CaseIn]] = None
    if t in ("mcq_single", "mcq_multi"):
        opts, correct = item.get("options"), item.get("correct")
        if not (isinstance(opts, list) and opts and all(isinstance(o, str) and o.strip() for o in opts)):
            errs.append("'options' must be a list of texts")
            opts = []
        letters = [chr(97 + i) for i in range(len(opts))]
        right = [str(c).strip().lower() for c in correct] if isinstance(correct, list) else []
        if not right:
            errs.append("'correct' must list the letters of the right options, for example [\"b\"]")
        errs += [f"correct answer '{c}' is not one of the options ({', '.join(letters)})" for c in right if c not in letters]
        cfg = {"options": [{"id": l, "text": o.strip(), "correct": l in right} for l, o in zip(letters, opts)], "partial": True}
    elif t in ("short", "long"):
        answer = item.get("model_answer")
        if not (isinstance(answer, str) and answer.strip()):
            errs.append("'model_answer' is missing (the AI marking compares answers with it)")
        cfg = {"model_answer": answer if isinstance(answer, str) else ""}
        for k in ("max_words", "min_words"):
            if k in item:
                cfg[k] = int(_num(item, k, 0, errs))
        if t == "short":
            cfg["keywords"] = _texts(item, "keywords", errs)
        else:
            rub = item.get("rubric")
            if not (isinstance(rub, list) and rub and all(isinstance(r, dict) and str(r.get("name") or "").strip() for r in rub)):
                errs.append("'rubric' must be a list of {name, max, descriptor}")
            else:
                cfg["rubric"] = [{"id": f"r{i + 1}", "name": str(r["name"]).strip(), "max": _num(r, "max", 0, errs), "descriptor": str(r.get("descriptor") or "")}
                                 for i, r in enumerate(rub)]
    elif t == "coding":
        ref = item.get("reference")
        if not (isinstance(ref, dict) and isinstance(ref.get("source"), str) and ref["source"].strip()):
            errs.append("'reference' must be {language, source}: a correct solution")
            ref = {"language": "python", "source": ""}
        langs = _texts(item, "languages", errs) or list(remote.language_names())
        cases = _cases(item, "test_cases", "input", errs)
        cfg = {"time_limit_ms": int(_num(item, "time_limit_ms", 2000, errs)), "memory_mb": int(_num(item, "memory_mb", 256, errs)), "comparator": "trim",
               "languages": langs, "reference": {"language": str(ref.get("language") or "python"), "source": ref["source"]}}
    else:  # sql
        for k in ("schema", "reference_sql"):
            if not (isinstance(item.get(k), str) and item[k].strip()):
                errs.append(f"'{k}' is missing")
        cases = _cases(item, "datasets", "data", errs)
        cfg = {"schema": item.get("schema") or "", "seed": "", "engines": ["sqlite"], "ordered": bool(item.get("ordered", True)), "reference_sql": item.get("reference_sql") or ""}
    diff = item.get("difficulty", "medium")
    if diff not in ("easy", "medium", "hard"):
        errs.append("'difficulty' must be easy, medium or hard")
    skills = _texts(item, "skills", errs)
    marks, neg = _num(item, "marks", DEFAULT_MARKS[t], errs), _num(item, "negative_marks", 0, errs)
    if len(errs) > n0:
        return None
    title = (item.get("title") if isinstance(item.get("title"), str) else "").strip() or _plain(statement)[:80]
    return QuestionIn(department_id=dept_id, type=t, title=title[:250], body=_html(statement), difficulty=diff, skills=skills, marks=marks,
                      negative_marks=neg, config=cfg, cases=cases, status="approved")


def _msgs(x: HTTPException) -> List[str]:
    d = x.detail
    return list(d["errors"]) if isinstance(d, dict) and "errors" in d else [str(d)]


def _question(db: Session, user: User, t: Test, item: Any, errs: List[str]) -> Optional[Question]:
    body = _body(item, t.department_id, errs)
    if body is None:
        return None
    errs += validate_question(body, strict=True)
    try:
        _department(db, user, body)
    except HTTPException as x:
        errs += _msgs(x)
    if errs:
        return None
    q = Question(id=uid(), org_id=user.org_id, created_by=user.id)
    _apply(q, body)
    if q.type == "coding":  # the reference solution produces the expected outputs; the file never does
        ref = q.config["reference"]
        try:
            ran = run_reference(q.config, ref["language"], ref["source"], [c.input for c in q.cases])
        except ValueError as e:
            errs.append(str(e))
            return None
        failed = [(n, r["verdict"]) for n, r in enumerate(ran, 1) if not r["ok"]]
        if failed:  # one message per question, not one per case
            errs.append(f"the reference solution fails on {len(failed)} of {len(ran)} test cases, the first being test case {failed[0][0]} ({failed[0][1]})")
            return None
        for c, r in zip(q.cases, ran):
            c.expected = r["expected"]
    try:
        _check_on_save(q)
    except HTTPException as x:
        errs += _msgs(x)
        return None
    if q.type in ("coding", "sql") and not q.config.get("validated"):
        errs.append("the reference solution does not pass its own test cases")
        return None
    return q


Plan = List[Tuple[str, Optional[int], List[Question]]]


def build(db: Session, user: User, t: Test, pack: Any) -> Tuple[Plan, List[str]]:
    """Check the whole file; returns what would be created and every problem found (nothing is saved)."""
    secs = pack.get("sections") if isinstance(pack, dict) else None
    if not isinstance(secs, list) or not secs:
        return [], ["The file needs a 'sections' list with at least one section"]
    if len(secs) > MAX_SECTIONS:
        return [], [f"At most {MAX_SECTIONS} sections per file"]
    if sum(len(s.get("questions") or []) for s in secs if isinstance(s, dict) and isinstance(s.get("questions"), list)) > MAX_QUESTIONS:
        return [], [f"At most {MAX_QUESTIONS} questions per file"]
    plan: Plan = []
    errs: List[str] = []
    for si, sec in enumerate(secs, 1):
        items = sec.get("questions") if isinstance(sec, dict) else None
        if not isinstance(items, list) or not items:
            errs.append(f"Section {si}: needs a 'questions' list with at least one question")
            continue
        timer = sec.get("timer_min")
        if timer is not None and (isinstance(timer, bool) or not isinstance(timer, int) or timer < 1):
            errs.append(f"Section {si}: 'timer_min' must be a whole number of minutes, or null")
            timer = None
        built = []
        for qi, item in enumerate(items, 1):
            e: List[str] = []
            q = _question(db, user, t, item, e)
            name = f" ({item['title']})" if isinstance(item, dict) and isinstance(item.get("title"), str) else ""
            errs += [f"Section {si}, question {qi}{name}: {m}" for m in e]
            if q:
                built.append(q)
        plan.append((str(sec.get("title") or "").strip() or f"Section {si}", timer, built))
    return plan, errs


@router.post("/tests/{tid}/question-prompt")
def question_prompt(tid: str, body: PromptIn, user: User = Depends(AUTHOR), db: Session = Depends(get_db)):
    t = _test(db, tid, user)
    dept = db.get(Department, t.department_id)
    counts = body.model_dump()
    if any(n < 0 for n in counts.values()) or not 1 <= sum(counts.values()) <= MAX_QUESTIONS:
        raise HTTPException(422, f"Ask for between 1 and {MAX_QUESTIONS} questions in total")
    missing = [TYPE_NAME[k] for k, n in counts.items() if n and k not in (dept.question_types or [])]
    if missing:
        raise HTTPException(422, f"The {dept.name} department does not offer {', '.join(missing)} questions")
    return {"prompt": make_prompt(t, dept, counts)}


class ImportIn(BaseModel):
    pack: Any
    dry_run: bool = True


@router.post("/tests/{tid}/import-questions")
def import_questions(tid: str, body: ImportIn, request: Request, user: User = Depends(AUTHOR), db: Session = Depends(get_db)):
    """dry_run: check the file and say what it would create. Otherwise create the questions (in the question bank, in the exam's department)
    and add them to new sections at the end of the exam, in one go. An invalid file creates nothing."""
    t = _test(db, tid, user)
    _draft(t)
    if len(json.dumps(body.pack)) > MAX_BYTES:
        raise HTTPException(413, "The file is too large (2 MB at most)")
    plan, errs = build(db, user, t, body.pack)
    if body.dry_run:
        secs = [{"title": title, "timer_min": timer, "count": len(qs), "marks": round(sum(q.marks for q in qs), 2),
                 "questions": [{"title": q.title, "type": q.type, "marks": q.marks, "difficulty": q.difficulty} for q in qs]} for title, timer, qs in plan]
        return {"ok": not errs, "errors": errs, "sections": secs, "total_questions": sum(s["count"] for s in secs), "total_marks": round(sum(s["marks"] for s in secs), 2)}
    if errs:
        raise HTTPException(422, {"errors": errs})
    for title, timer, qs in plan:
        sec = Section(id=uid(), title=title, order=len(t.sections), timer_min=timer, shuffle=True, lock_nav=False, allow_negative=False)
        t.sections.append(sec)
        for q in qs:
            db.add(q)
        db.flush()  # the questions exist before the items that point at them
        for q in qs:
            sec.items.append(SectionItem(id=uid(), kind="question", question_id=q.id, order=len(sec.items)))
    audit(db, user, "import_pack", "test", t.id, {"sections": len(plan), "questions": sum(len(qs) for _, _, qs in plan)}, request)
    db.commit()
    return test_out(db, t)
