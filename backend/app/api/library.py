"""Question library: CRUD for all six types, Linked MCQ groups, bulk MCQ import, reference validation."""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import audit, require, same_org
from app.db import get_db
from app.models import QTYPES, Department, Question, QuestionGroup, TestCase, User, aware, uid
from app.sandbox.judge import judge_code, run_reference, sql_expected_for
from app.sandbox.languages import REGISTRY
from app.sandbox.sql import describe_tables
from app.services import ai
from app.services.sanitize import sanitize_html

router = APIRouter(tags=["library"])
AUTHOR = require("test_creator", "org_admin")
READ = require("test_creator", "org_admin", "recruiter", "evaluator")


class CaseIn(BaseModel):
    ordinal: Optional[int] = None
    visibility: str = "open"
    input: str = ""
    expected: str = ""
    weight: float = 1
    purpose: str = ""


class QuestionIn(BaseModel):
    department_id: Optional[str] = None
    type: str
    title: str
    body: str = ""
    difficulty: str = "medium"
    skills: List[str] = []
    marks: float = 1
    negative_marks: float = 0
    group_id: Optional[str] = None
    config: Dict[str, Any] = {}
    status: str = "approved"
    cases: Optional[List[CaseIn]] = None


class GroupIn(BaseModel):
    title: str
    stimulus: str = ""
    skills: List[str] = []


def q_out(q: Question, full: bool = True) -> dict:
    d = {"id": q.id, "department_id": q.department_id, "type": q.type, "title": q.title, "difficulty": q.difficulty, "skills": q.skills,
         "marks": q.marks, "negative_marks": q.negative_marks, "group_id": q.group_id, "status": q.status,
         "version": q.version, "updated_at": aware(q.updated_at).isoformat() if q.updated_at else None,
         "validated": bool((q.config or {}).get("validated")), "case_count": len(q.cases)}
    if full:
        d.update({"body": q.body, "config": q.config,
                  "cases": [{"id": c.id, "ordinal": c.ordinal, "visibility": c.visibility, "input": c.input,
                             "expected": c.expected, "weight": c.weight, "purpose": c.purpose} for c in q.cases]})
        if q.type == "sql":  # the table builder shows each dataset as editable tables
            cfg = q.config or {}
            d["sql_tables"] = [describe_tables(cfg.get("schema", ""), cfg.get("seed", ""), c.input, limit=500) for c in q.cases]
    return d


def validate_question(body: QuestionIn, strict: bool) -> List[str]:
    errs: List[str] = []
    c = body.config or {}
    if body.type not in QTYPES:
        errs.append(f"type must be one of {', '.join(QTYPES)}")
        return errs
    if not body.title.strip():
        errs.append("Title is required")
    if body.marks <= 0:
        errs.append("Marks must be positive")
    if body.negative_marks < 0:
        errs.append("Negative marks cannot be below 0 (enter 0.5 for -0.5)")
    if body.type.startswith("mcq"):
        opts = c.get("options") or []
        if not (2 <= len(opts) <= 8):
            errs.append("MCQ needs 2 to 8 options")
        ncor = sum(1 for o in opts if o.get("correct"))
        if body.type == "mcq_single" and ncor != 1:
            errs.append("Single-correct MCQ needs exactly one correct option")
        if body.type == "mcq_multi" and ncor < 1:
            errs.append("Mark at least one correct option")
        if len({o.get("id") for o in opts}) != len(opts):
            errs.append("Option ids must be unique")
    if body.type == "long" and strict:
        rub = c.get("rubric") or []
        if rub and abs(sum(float(r.get("max", 0)) for r in rub) - body.marks) > 1e-6:
            errs.append("Rubric criteria must add up to the question marks")
    if body.type in ("coding", "sql") and strict:
        cases = body.cases or []
        n_open = sum(1 for x in cases if x.visibility == "open")
        n_hid = sum(1 for x in cases if x.visibility == "hidden")
        if n_open < 1 or n_hid < 1:
            errs.append("Add at least 1 sample (open) test case and 1 hidden test case")
    if body.type == "coding":
        langs = c.get("languages") or []
        bad = [l for l in langs if l not in REGISTRY]
        if not langs or bad:
            errs.append(f"Choose languages from: {', '.join(REGISTRY)}")
        if not (100 <= int(c.get("time_limit_ms", 2000)) <= 10000):
            errs.append("Time limit must be 100 - 10000 ms")
        if not (32 <= int(c.get("memory_mb", 256)) <= 1024):
            errs.append("Memory limit must be 32 - 1024 MB")
    if body.type == "sql":
        if not (c.get("schema") or "").strip():
            errs.append("SQL schema (CREATE TABLE ...) is required")
        if not (c.get("reference_sql") or "").strip():
            errs.append("Reference query is required")
    return errs


def _normalise_weights(q: Question) -> None:
    """Case weights are relative; scale them so they add up to the question's marks."""
    total = sum(float(c.weight) for c in q.cases)
    if q.type not in ("coding", "sql") or total <= 0:
        return
    ws = [round(float(q.marks) * float(c.weight) / total, 2) for c in q.cases]
    ws[-1] = round(float(q.marks) - sum(ws[:-1]), 2)
    for c, w in zip(q.cases, ws):
        c.weight = w


def _check_on_save(q: Question) -> None:
    """Decide from the saved data whether the question can go into a published exam, never from a flag the client sends.
    SQL: the expected output is computed from the solution query, so it matches by construction.
    Coding: the reference solution must pass every test case."""
    cfg = dict(q.config or {})
    if q.type == "sql":
        for i, c in enumerate(q.cases):
            try:
                c.expected = json.dumps(sql_expected_for(cfg, c.input))
            except ValueError as e:
                raise HTTPException(422, {"errors": [f"Dataset {i + 1}: {e}"]})
        cfg["validated"] = bool(q.cases)
    elif q.type == "coding":
        ref = cfg.get("reference") or {}
        cases = [{"ordinal": c.ordinal, "visibility": c.visibility, "input": c.input, "expected": c.expected,
                  "weight": float(c.weight)} for c in q.cases]
        ok = False
        if (ref.get("source") or "").strip() and cases:
            res = judge_code(cfg, cases, ref.get("language", "python"), ref["source"], "validate")
            ok = res.get("status") == "done" and res.get("total", 0) > 0 and res.get("passed") == res.get("total")
        cfg["validated"] = ok
    else:
        return
    q.config = cfg


TYPE_NAME = {"mcq_single": "multiple choice", "mcq_multi": "multiple answer", "short": "short answer", "long": "explained answer",
             "coding": "coding", "sql": "SQL"}


def _department(db: Session, user: User, body: QuestionIn, current_type: Optional[str] = None) -> Department:
    """The question's department must be one of the organisation's, and must offer this type of question.
    A question that already exists keeps its type even if the department no longer offers it."""
    d = db.get(Department, body.department_id or "")
    if not d or d.org_id != user.org_id:
        raise HTTPException(422, {"errors": ["Choose a department"]})
    if body.type not in (d.question_types or []) and body.type != current_type:
        raise HTTPException(422, {"errors": [f"The {d.name} department does not offer {TYPE_NAME.get(body.type, body.type)} questions"]})
    return d


def _apply(q: Question, body: QuestionIn) -> None:
    q.department_id = body.department_id
    q.type, q.title, q.difficulty = body.type, body.title.strip(), body.difficulty
    q.body = sanitize_html(body.body)
    q.skills = [s.strip() for s in body.skills if s.strip()]
    q.marks, q.negative_marks, q.group_id = body.marks, body.negative_marks, body.group_id or None
    cfg = dict(body.config or {})
    cfg.pop("validated", None)
    q.config = cfg
    q.status = body.status if body.status in ("draft", "approved", "archived") else "draft"
    if body.cases is not None:
        q.cases.clear()
        for i, c in enumerate(body.cases):
            q.cases.append(TestCase(id=uid(), ordinal=c.ordinal or i + 1, visibility=c.visibility if c.visibility in ("open", "hidden") else "open",
                                    input=c.input, expected=c.expected, weight=c.weight, purpose=c.purpose))
    _normalise_weights(q)


@router.get("/questions")
def list_questions(type: Optional[str] = None, department_id: Optional[str] = None, skill: Optional[str] = None, difficulty: Optional[str] = None,
                   q: Optional[str] = None, status: Optional[str] = None, group_id: Optional[str] = None,
                   standalone: bool = False, user: User = Depends(READ), db: Session = Depends(get_db)):
    stmt = select(Question).where(Question.org_id == user.org_id)
    if type:
        stmt = stmt.where(Question.type == type)
    if department_id:
        stmt = stmt.where(Question.department_id == department_id)
    if difficulty:
        stmt = stmt.where(Question.difficulty == difficulty)
    if status:
        stmt = stmt.where(Question.status == status)
    else:
        stmt = stmt.where(Question.status != "archived")
    if group_id:
        stmt = stmt.where(Question.group_id == group_id)
    if standalone:
        stmt = stmt.where(Question.group_id.is_(None))
    rows = db.scalars(stmt.order_by(Question.updated_at.desc())).all()
    if skill:
        rows = [r for r in rows if skill.lower() in [s.lower() for s in r.skills or []]]
    if q:
        rows = [r for r in rows if q.lower() in r.title.lower()]
    return [q_out(r, full=False) for r in rows]


@router.post("/questions")
def create_question(body: QuestionIn, request: Request, user: User = Depends(AUTHOR), db: Session = Depends(get_db)):
    errs = validate_question(body, strict=body.status == "approved")
    if errs:
        raise HTTPException(422, {"errors": errs})
    _department(db, user, body)
    q = Question(id=uid(), org_id=user.org_id, created_by=user.id)
    _apply(q, body)
    _check_on_save(q)
    db.add(q)
    audit(db, user, "create", "question", q.id, {"type": q.type}, request)
    db.commit()
    return q_out(q)


@router.get("/questions/{qid}")
def get_question(qid: str, user: User = Depends(READ), db: Session = Depends(get_db)):
    q = db.get(Question, qid)
    if not q:
        raise HTTPException(404, "Question not found")
    same_org(user, q.org_id)
    return q_out(q)


@router.put("/questions/{qid}")
def update_question(qid: str, body: QuestionIn, request: Request, user: User = Depends(AUTHOR), db: Session = Depends(get_db)):
    q = db.get(Question, qid)
    if not q:
        raise HTTPException(404, "Question not found")
    same_org(user, q.org_id)
    errs = validate_question(body, strict=body.status == "approved")
    if errs:
        raise HTTPException(422, {"errors": errs})
    _department(db, user, body, current_type=q.type)
    _apply(q, body)
    _check_on_save(q)
    q.version += 1
    audit(db, user, "update", "question", q.id, {"version": q.version}, request)
    db.commit()
    return q_out(q)


@router.delete("/questions/{qid}")
def archive_question(qid: str, request: Request, user: User = Depends(AUTHOR), db: Session = Depends(get_db)):
    q = db.get(Question, qid)
    if not q:
        raise HTTPException(404, "Question not found")
    same_org(user, q.org_id)
    q.status = "archived"
    audit(db, user, "archive", "question", q.id, request=request)
    db.commit()
    return {"ok": True}


def keep_same_shape(proposed: List[Dict], examples: List[str]) -> tuple:
    """When every example input has the same number of lines, drop generated inputs with a different line count:
    the model sometimes invents inputs outside the problem's format, which the reference solution would silently accept."""
    lines = lambda t: len(t.strip().splitlines())
    shapes = {lines(e) for e in examples if e.strip()}
    if len(shapes) != 1:
        return proposed, 0
    kept = [c for c in proposed if lines(c["input"]) in shapes]
    return kept, len(proposed) - len(kept)


class RefIn(BaseModel):
    language: str = "python"
    source: str = ""


class GenerateIn(BaseModel):
    """The unsaved form: the admin can generate and check cases before saving the question."""
    count: int = 10
    statement: str = ""
    constraints: str = ""
    reference: RefIn = RefIn()
    examples: List[str] = []
    time_limit_ms: int = 2000
    memory_mb: int = 256


class CheckIn(BaseModel):
    reference: RefIn = RefIn()
    cases: List[CaseIn] = []
    time_limit_ms: int = 2000
    memory_mb: int = 256


def _need_reference(ref: RefIn) -> None:
    if not ref.source.strip():
        raise HTTPException(422, "Add a reference solution (language + source) first")


@router.post("/questions/generate-cases")
def generate_cases(body: GenerateIn, request: Request, user: User = Depends(AUTHOR), db: Session = Depends(get_db)):
    """AI proposes test inputs; the reference solution produces the expected outputs. Nothing is saved:
    the admin reviews the proposal and saves the cases they want with the question."""
    if not ai.llm_enabled():
        raise HTTPException(400, "No AI provider is configured (set LLM_PROVIDER and the API key in .env)")
    _need_reference(body.reference)
    try:
        proposed = ai.ai_generate_inputs(re.sub(r"<[^>]+>", " ", body.statement), body.constraints, body.reference.source,
                                         body.count, body.examples)
    except Exception as e:
        raise HTTPException(502, f"AI request failed: {e}")
    proposed, off_shape = keep_same_shape(proposed, body.examples)
    cfg = {"time_limit_ms": body.time_limit_ms, "memory_mb": body.memory_mb}
    try:
        ran = run_reference(cfg, body.reference.language, body.reference.source, [c["input"] for c in proposed])
    except ValueError as e:
        raise HTTPException(422, str(e))
    cases = [{"input": r["input"], "expected": r["expected"], "purpose": p["purpose"]} for r, p in zip(ran, proposed) if r["ok"]]
    audit(db, user, "generate_cases", "question", "", {"proposed": len(proposed), "kept": len(cases)}, request)
    db.commit()
    return {"cases": cases, "dropped": off_shape + len(ran) - len(cases)}


class SqlPreviewIn(BaseModel):
    ddl: str
    reference_sql: str
    datasets: List[str]


@router.post("/questions/sql-preview")
def sql_preview(body: SqlPreviewIn, user: User = Depends(AUTHOR)):
    """Run the reference query on each dataset of the unsaved form; the result is the expected output the candidate must match."""
    cfg = {"schema": body.ddl, "seed": "", "reference_sql": body.reference_sql}
    results = []
    for ds in body.datasets:
        try:
            results.append({"ok": True, **sql_expected_for(cfg, ds)})
        except ValueError as e:
            results.append({"ok": False, "error": str(e)})
    return {"results": results}


@router.post("/questions/check-reference")
def check_reference(body: CheckIn, user: User = Depends(AUTHOR)):
    """Run the reference solution against the cases in the form; one verdict per case (AC = the expected output matches)."""
    _need_reference(body.reference)
    cases = [{"ordinal": i + 1, "visibility": c.visibility, "input": c.input, "expected": c.expected, "weight": 1.0}
             for i, c in enumerate(body.cases)]
    res = judge_code({"time_limit_ms": body.time_limit_ms, "memory_mb": body.memory_mb}, cases, body.reference.language,
                     body.reference.source, "validate")
    if res.get("status") != "done":
        raise HTTPException(422, res.get("error", "The reference solution could not be run"))
    return {"passed": res["passed"], "total": res["total"], "verdicts": [c["verdict"] for c in res["cases"]],
            "message": (res.get("compile") or {}).get("message", "") if not (res.get("compile") or {}).get("ok", True) else ""}


@router.post("/questions/import")
async def import_mcqs(file: UploadFile = File(...), department_id: str = Form(...), user: User = Depends(AUTHOR), db: Session = Depends(get_db)):
    """CSV/XLSX columns: title, option_a, option_b, option_c, option_d, correct (e.g. 'a' or 'a,c'),
    marks, negative, difficulty, skills (semicolon separated)."""
    import csv
    import io
    _department(db, user, QuestionIn(department_id=department_id, type="mcq_single", title="import"))
    data = await file.read()
    rows: List[List[str]] = []
    if file.filename.lower().endswith(".xlsx"):
        import openpyxl
        ws = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True).active
        rows = [[("" if v is None else str(v)).strip() for v in r] for r in ws.iter_rows(values_only=True)]
    else:
        rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig", errors="replace"))))
    report, created = [], 0
    for i, r in enumerate(rows):
        if i == 0 and r and r[0].strip().lower() == "title":
            continue
        if not r or not r[0].strip():
            continue
        r = (r + [""] * 11)[:11]
        title, a, b, c_, d, correct, marks, neg, diff, skills = r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9]
        opts = [(k, v) for k, v in zip("abcd", (a, b, c_, d)) if v.strip()]
        cor = {x.strip().lower() for x in correct.split(",") if x.strip()}
        body = QuestionIn(department_id=department_id, type="mcq_multi" if len(cor) > 1 else "mcq_single", title=title[:250], body=f"<p>{title}</p>",
                          difficulty=diff.lower() if diff.lower() in ("easy", "medium", "hard") else "medium",
                          skills=[s for s in skills.split(";") if s.strip()], marks=float(marks or 1),
                          negative_marks=float(neg or 0),
                          config={"options": [{"id": k, "text": v, "correct": k in cor} for k, v in opts], "partial": True})
        errs = validate_question(body, strict=True)
        if errs:
            report.append({"row": i + 1, "ok": False, "errors": errs})
            continue
        qq = Question(id=uid(), org_id=user.org_id, created_by=user.id)
        _apply(qq, body)
        db.add(qq)
        created += 1
        report.append({"row": i + 1, "ok": True})
    db.commit()
    return {"created": created, "rows": report}


# ------------------------------------------------------------------ Linked MCQ groups
@router.get("/groups")
def list_groups(user: User = Depends(READ), db: Session = Depends(get_db)):
    gs = db.scalars(select(QuestionGroup).where(QuestionGroup.org_id == user.org_id).order_by(QuestionGroup.created_at.desc())).all()
    return [{"id": g.id, "title": g.title, "stimulus": g.stimulus, "skills": g.skills,
             "questions": [q_out(q, full=False) for q in g.questions if q.status != "archived"]} for g in gs]


@router.post("/groups")
def create_group(body: GroupIn, request: Request, user: User = Depends(AUTHOR), db: Session = Depends(get_db)):
    g = QuestionGroup(id=uid(), org_id=user.org_id, title=body.title, stimulus=sanitize_html(body.stimulus), skills=body.skills)
    db.add(g)
    audit(db, user, "create", "group", g.id, request=request)
    db.commit()
    return {"id": g.id, "title": g.title, "stimulus": g.stimulus, "skills": g.skills, "questions": []}


@router.put("/groups/{gid}")
def update_group(gid: str, body: GroupIn, user: User = Depends(AUTHOR), db: Session = Depends(get_db)):
    g = db.get(QuestionGroup, gid)
    if not g:
        raise HTTPException(404, "Group not found")
    same_org(user, g.org_id)
    g.title, g.stimulus, g.skills = body.title, sanitize_html(body.stimulus), body.skills
    db.commit()
    return {"ok": True}
