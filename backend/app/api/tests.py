"""Tests, sections, items, publish; invites, candidates, actions; analytics, exports, plagiarism."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.deps import AUTHOR, RECRUIT, SUPER, VIEW, audit, same_org
from app.core.paging import limit_q, offset_q, page_rows
from app.core.security import hash_password
from app.db import get_db
from app.api.library import q_out
from app.models import (Assignment, Attempt, Department, PlagiarismMatch, Question, QuestionGroup, Section, SectionItem, Test,
                        User, AttemptQuestion, CodeSubmission, Answer, aware, now, uid)
from app.services import invites as inv
from app.services import login_mail, reports
from app.services.analytics import exam_analytics
from app.services.mail import queue_mail
from app.services.report_card import is_real_email
from app.services.attempts import retime_open_attempts
from app.services.populate import pick_questions
from app.services.sanitize import sanitize_html

router = APIRouter(tags=["tests"])


class TestIn(BaseModel):
    department_id: Optional[str] = None
    title: str
    description: str = ""
    instructions: str = ""
    duration_min: int = 60
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    access_enabled: bool = True
    cutoff: float = 0
    shuffle_questions: bool = True
    shuffle_options: bool = True
    settings: Dict[str, Any] = {}


class SectionIn(BaseModel):
    title: str
    order: Optional[int] = None
    timer_min: Optional[int] = None
    shuffle: bool = True
    lock_nav: bool = False
    min_score: Optional[float] = None
    allow_negative: bool = False


class ItemIn(BaseModel):
    kind: str = "question"
    question_id: Optional[str] = None
    group_id: Optional[str] = None
    pool: Optional[Dict[str, Any]] = None
    marks_override: Optional[float] = None
    negative_override: Optional[float] = None


class InviteIn(BaseModel):
    text: Optional[str] = None
    rows: Optional[List[Dict[str, Any]]] = None
    expires_at: Optional[datetime] = None
    schedule_at: Optional[datetime] = None
    extra_time_min: int = 0


class ActionIn(BaseModel):
    action: str  # shortlist|archive|extend|terminate|reset|cancel|remind|resend
    minutes: int = 0
    reason: str = ""


def _test(db: Session, tid: str, user: User) -> Test:
    t = db.get(Test, tid)
    if not t:
        raise HTTPException(404, "Test not found")
    same_org(user, t.org_id)
    if t.status == "archived" and not user.has("super_admin"):  # an archived exam exists only for the Super Admin, even by its direct address
        raise HTTPException(404, "Test not found")
    return t


def _draft(t: Test) -> None:
    """Sections and questions of a published exam are frozen: candidates may be taking it."""
    if t.status != "draft":
        raise HTTPException(409, "Unpublish the exam before changing its sections or questions")


def _iso(d):
    return aware(d).isoformat() if d else None


def item_out(db: Session, it: SectionItem) -> dict:
    d = {"id": it.id, "kind": it.kind, "marks_override": it.marks_override, "negative_override": it.negative_override,
         "order": it.order, "pool": it.pool}
    if it.question_id:
        q = db.get(Question, it.question_id)
        d["question"] = {"id": q.id, "title": q.title, "type": q.type, "marks": q.marks, "negative_marks": q.negative_marks,
                         "difficulty": q.difficulty, "status": q.status, "validated": bool((q.config or {}).get("validated"))} if q else None
    if it.group_id:
        g = db.get(QuestionGroup, it.group_id)
        d["group"] = {"id": g.id, "title": g.title, "count": len([q for q in g.questions if q.status != "archived"]),
                      "marks": sum(q.marks for q in g.questions if q.status != "archived")} if g else None
    return d


def _item_marks(db: Session, it: SectionItem) -> tuple:
    if it.kind == "question" and it.question_id:
        q = db.get(Question, it.question_id)
        return 1, float(it.marks_override if it.marks_override is not None else (q.marks if q else 0))
    if it.kind == "group" and it.group_id:
        g = db.get(QuestionGroup, it.group_id)
        qs = [q for q in (g.questions if g else []) if q.status != "archived"]
        return len(qs), sum(float(it.marks_override if it.marks_override is not None else q.marks) for q in qs)
    if it.kind == "pool" and it.pool:
        n = int(it.pool.get("draw") or 0)
        m = it.marks_override
        if m is None:
            m = float(it.pool.get("marks_each") or 1)
        return n, n * float(m)
    return 0, 0.0


def test_out(db: Session, t: Test, full: bool = True) -> dict:
    n_q, marks = 0, 0.0
    secs = []
    for s in t.sections:
        sq, sm = 0, 0.0
        for it in s.items:
            a, b = _item_marks(db, it)
            sq += a
            sm += b
        n_q += sq
        marks += sm
        if full:
            secs.append({"id": s.id, "title": s.title, "order": s.order, "timer_min": s.timer_min, "shuffle": s.shuffle,
                         "lock_nav": s.lock_nav, "min_score": s.min_score, "allow_negative": s.allow_negative,
                         "question_count": sq, "marks": round(sm, 2), "items": [item_out(db, it) for it in s.items]})
    asgs = db.scalars(select(Assignment).where(Assignment.test_id == t.id)).all()
    d = {"id": t.id, "department_id": t.department_id, "title": t.title, "status": t.status, "duration_min": t.duration_min,
         "starts_at": _iso(t.starts_at), "ends_at": _iso(t.ends_at), "cutoff": t.cutoff,
         "question_count": n_q, "total_marks": round(marks, 2), "section_count": len(t.sections),
         "invited": len(asgs), "taking": sum(1 for a in asgs if a.status == "in_progress"), "taken": sum(1 for a in asgs if a.status not in ("invited", "expired", "cancelled", "in_progress")),
         "updated_at": _iso(t.updated_at)}
    if full:
        d.update({"description": t.description, "instructions": t.instructions, "access_enabled": t.access_enabled,
                  "shuffle_questions": t.shuffle_questions, "shuffle_options": t.shuffle_options,
                  "settings": t.settings or {}, "sections": secs})
    return d


@router.get("/tests")
def list_tests(archived: bool = False, user: User = Depends(VIEW), db: Session = Depends(get_db)):
    """The exams, or with ?archived=true the archived ones (Super Admin only)."""
    if archived and not user.has("super_admin"):
        raise HTTPException(403, "You do not have permission for this action")
    where = Test.status == "archived" if archived else Test.status != "archived"
    ts = db.scalars(select(Test).where(Test.org_id == user.org_id, where).order_by(Test.updated_at.desc())).all()
    return [test_out(db, t, full=False) for t in ts]


@router.post("/tests")
def create_test(body: TestIn, request: Request, user: User = Depends(AUTHOR), db: Session = Depends(get_db)):
    t = Test(id=uid(), org_id=user.org_id, created_by=user.id)
    _apply_test(db, user, t, body)
    db.add(t)
    audit(db, user, "create", "test", t.id, request=request)
    db.commit()
    return test_out(db, t)


def _apply_test(db: Session, user: User, t: Test, body: TestIn) -> None:
    dept = db.get(Department, body.department_id or "")
    if not dept or dept.org_id != user.org_id:
        raise HTTPException(422, "Choose the department this exam is for")
    t.department_id = dept.id
    if body.duration_min < 1 or body.duration_min > 600:
        raise HTTPException(422, "Duration must be 1-600 minutes")
    if body.starts_at and body.ends_at and body.ends_at <= body.starts_at:
        raise HTTPException(422, "End must be after start")
    t.title, t.description = body.title.strip(), body.description
    t.instructions = sanitize_html(body.instructions)
    t.duration_min, t.starts_at, t.ends_at = body.duration_min, body.starts_at, body.ends_at
    t.access_enabled, t.cutoff = body.access_enabled, body.cutoff
    t.shuffle_questions, t.shuffle_options = body.shuffle_questions, body.shuffle_options
    t.settings = body.settings or {}


@router.get("/tests/{tid}")
def get_test(tid: str, user: User = Depends(VIEW), db: Session = Depends(get_db)):
    return test_out(db, _test(db, tid, user))


@router.put("/tests/{tid}")
def update_test(tid: str, body: TestIn, request: Request, user: User = Depends(AUTHOR), db: Session = Depends(get_db)):
    t = _test(db, tid, user)
    old_end = aware(t.ends_at)
    _apply_test(db, user, t, body)
    if aware(t.ends_at) != old_end:  # a new closing time reaches the people taking the exam now, and an exam that is open again is not "calculated"
        retime_open_attempts(db, t)
        if not t.ends_at or aware(t.ends_at) > now():
            t.calculated_at = None
    audit(db, user, "update", "test", t.id, request=request)
    db.commit()
    return test_out(db, t)


@router.delete("/tests/{tid}")
def archive_test(tid: str, request: Request, user: User = Depends(SUPER), db: Session = Depends(get_db)):
    """Nothing is deleted: the exam, its candidates and their results stay, and restoring puts the exam back as it was."""
    t = _test(db, tid, user)
    if t.status == "archived":
        raise HTTPException(409, "This exam is already archived")
    if db.scalar(select(Attempt.id).where(Attempt.test_id == t.id, Attempt.status == "in_progress")):
        raise HTTPException(409, "Candidates are taking this exam right now. End their exams first.")
    t.archived_from, t.status = t.status, "archived"
    audit(db, user, "archive", "test", t.id, request=request)
    db.commit()
    return {"ok": True}


@router.post("/tests/{tid}/restore")
def restore_test(tid: str, request: Request, user: User = Depends(SUPER), db: Session = Depends(get_db)):
    t = _test(db, tid, user)
    if t.status != "archived":
        raise HTTPException(409, "This exam is not archived")
    t.status, t.archived_from = t.archived_from or "draft", None
    audit(db, user, "restore", "test", t.id, request=request)
    db.commit()
    return test_out(db, t)


@router.post("/tests/{tid}/clone")
def clone_test(tid: str, request: Request, user: User = Depends(AUTHOR), db: Session = Depends(get_db)):
    t = _test(db, tid, user)
    n = Test(id=uid(), org_id=t.org_id, department_id=t.department_id, title=t.title + " (copy)", description=t.description, instructions=t.instructions,
             duration_min=t.duration_min, cutoff=t.cutoff, shuffle_questions=t.shuffle_questions,
             shuffle_options=t.shuffle_options, settings=dict(t.settings or {}), created_by=user.id)
    for s in t.sections:
        ns = Section(id=uid(), title=s.title, order=s.order, timer_min=s.timer_min, shuffle=s.shuffle, lock_nav=s.lock_nav,
                     min_score=s.min_score, allow_negative=s.allow_negative)
        for it in s.items:
            ns.items.append(SectionItem(id=uid(), kind=it.kind, question_id=it.question_id, group_id=it.group_id,
                                        pool=it.pool, marks_override=it.marks_override,
                                        negative_override=it.negative_override, order=it.order))
        n.sections.append(ns)
    db.add(n)
    audit(db, user, "clone", "test", n.id, {"from": t.id}, request)
    db.commit()
    return test_out(db, n)


def publish_errors(db: Session, t: Test) -> List[str]:
    errs = []
    if not t.sections:
        errs.append("Add at least one section")
    for s in t.sections:
        if not s.items:
            errs.append(f"Section '{s.title}' has no questions")
        for it in s.items:
            qs: List[Question] = []
            if it.kind == "question":
                q = db.get(Question, it.question_id)
                qs = [q] if q else []
            elif it.kind == "group":
                g = db.get(QuestionGroup, it.group_id)
                qs = [q for q in (g.questions if g else []) if q.status != "archived"]
                if not qs:
                    errs.append(f"Linked group in '{s.title}' has no questions")
            elif it.kind == "pool":
                p = it.pool or {}
                flt = p.get("filter") or {}
                stmt = select(Question).where(Question.org_id == t.org_id, Question.status == "approved",
                                              Question.group_id.is_(None))
                if flt.get("types"):
                    stmt = stmt.where(Question.type.in_(flt["types"]))
                cand = db.scalars(stmt).all()
                if flt.get("skills"):
                    cand = [q for q in cand if set(flt["skills"]) & set(q.skills or [])]
                if int(p.get("draw") or 0) < 1:
                    errs.append(f"Pool in '{s.title}' must draw at least 1 question")
                elif len(cand) < int(p.get("draw")):
                    errs.append(f"Pool in '{s.title}' wants {p.get('draw')} questions but only {len(cand)} match")
                for diff, n in (p.get("mix") or {}).items():
                    have = sum(1 for q in cand if q.difficulty == diff)
                    if have < int(n):
                        errs.append(f"Pool in '{s.title}' wants {n} {diff} questions but only {have} exist")
            for q in qs:
                if q.status != "approved":
                    errs.append(f"'{q.title}' is not approved")
                if q.type in ("coding", "sql") and not (q.config or {}).get("validated"):
                    errs.append(f"'{q.title}': its reference solution does not pass every test case. Open it in the question bank, fix it and save.")
    return errs


@router.post("/tests/{tid}/publish")
def publish(tid: str, request: Request, user: User = Depends(AUTHOR), db: Session = Depends(get_db)):
    t = _test(db, tid, user)
    errs = publish_errors(db, t)
    if errs:
        raise HTTPException(422, {"errors": errs})
    t.status = "published"
    audit(db, user, "publish", "test", t.id, request=request)
    db.commit()
    return test_out(db, t)


@router.post("/tests/{tid}/unpublish")
def unpublish(tid: str, request: Request, user: User = Depends(AUTHOR), db: Session = Depends(get_db)):
    t = _test(db, tid, user)
    if db.scalar(select(Attempt.id).where(Attempt.test_id == t.id, Attempt.status == "in_progress")):
        raise HTTPException(409, "Candidates are taking this exam right now. End their exams first.")
    t.status = "draft"
    audit(db, user, "unpublish", "test", t.id, request=request)
    db.commit()
    return test_out(db, t)


# ------------------------------------------------------------------ sections & items
class PopulateIn(BaseModel):
    department_id: Optional[str] = None
    types: List[str] = []
    easy: int = 0
    medium: int = 0
    hard: int = 0
    skills: List[str] = []


@router.post("/tests/{tid}/auto-populate")
def auto_populate(tid: str, body: PopulateIn, user: User = Depends(AUTHOR), db: Session = Depends(get_db)):
    """Pick random questions for a section from the bank. Nothing is saved: the admin reviews the pick (and can pick again),
    then adds the questions with POST /sections/{id}/items. `short` says what the bank could not supply."""
    t = _test(db, tid, user)
    _draft(t)
    mix = {"easy": body.easy, "medium": body.medium, "hard": body.hard}
    if any(n < 0 for n in mix.values()) or not 1 <= sum(mix.values()) <= 50:
        raise HTTPException(422, "Ask for between 1 and 50 questions in total")
    if body.department_id:
        d = db.get(Department, body.department_id)
        if not d or d.org_id != user.org_id:
            raise HTTPException(422, "Unknown department")
    picked, short = pick_questions(db, t, mix, body.department_id, body.types, body.skills)
    return {"questions": [q_out(q, full=False) for q in picked], "short": short}


@router.post("/tests/{tid}/sections")
def add_section(tid: str, body: SectionIn, user: User = Depends(AUTHOR), db: Session = Depends(get_db)):
    t = _test(db, tid, user)
    _draft(t)
    s = Section(id=uid(), title=body.title, order=body.order if body.order is not None else len(t.sections),
                timer_min=body.timer_min or None, shuffle=body.shuffle, lock_nav=body.lock_nav,
                min_score=body.min_score, allow_negative=body.allow_negative)
    t.sections.append(s)
    db.commit()
    return test_out(db, t)


def _section(db: Session, sid: str, user: User) -> tuple:
    s = db.get(Section, sid)
    if not s:
        raise HTTPException(404, "Section not found")
    t = _test(db, s.test_id, user)
    return s, t


@router.put("/sections/{sid}")
def update_section(sid: str, body: SectionIn, user: User = Depends(AUTHOR), db: Session = Depends(get_db)):
    s, t = _section(db, sid, user)
    _draft(t)
    s.title, s.timer_min, s.shuffle, s.lock_nav = body.title, body.timer_min or None, body.shuffle, body.lock_nav
    s.min_score, s.allow_negative = body.min_score, body.allow_negative
    if body.order is not None:
        s.order = body.order
    db.commit()
    return test_out(db, t)


@router.delete("/sections/{sid}")
def delete_section(sid: str, user: User = Depends(AUTHOR), db: Session = Depends(get_db)):
    s, t = _section(db, sid, user)
    _draft(t)
    t.sections.remove(s)
    db.delete(s)
    db.commit()
    return test_out(db, t)


@router.post("/sections/{sid}/items")
def add_item(sid: str, body: ItemIn, user: User = Depends(AUTHOR), db: Session = Depends(get_db)):
    s, t = _section(db, sid, user)
    _draft(t)
    if body.kind == "question":
        q = db.get(Question, body.question_id or "")
        if not q:
            raise HTTPException(404, "Question not found")
        same_org(user, q.org_id)
        if any(it.question_id == q.id for sec in t.sections for it in sec.items):
            raise HTTPException(409, "This question is already in the test")
    elif body.kind == "group":
        g = db.get(QuestionGroup, body.group_id or "")
        if not g:
            raise HTTPException(404, "Group not found")
    elif body.kind == "pool":
        if not body.pool or int(body.pool.get("draw") or 0) < 1:
            raise HTTPException(422, "Pool needs draw >= 1")
    else:
        raise HTTPException(422, "kind must be question, group or pool")
    s.items.append(SectionItem(id=uid(), kind=body.kind, question_id=body.question_id if body.kind == "question" else None,
                               group_id=body.group_id if body.kind == "group" else None,
                               pool=body.pool if body.kind == "pool" else None, marks_override=body.marks_override,
                               negative_override=body.negative_override, order=len(s.items)))
    db.commit()
    return test_out(db, t)


@router.put("/items/{iid}")
def update_item(iid: str, body: ItemIn, user: User = Depends(AUTHOR), db: Session = Depends(get_db)):
    it = db.get(SectionItem, iid)
    if not it:
        raise HTTPException(404, "Item not found")
    s, t = _section(db, it.section_id, user)
    _draft(t)
    it.marks_override, it.negative_override = body.marks_override, body.negative_override
    if it.kind == "pool" and body.pool:
        it.pool = body.pool
    db.commit()
    return test_out(db, t)


@router.delete("/items/{iid}")
def delete_item(iid: str, user: User = Depends(AUTHOR), db: Session = Depends(get_db)):
    it = db.get(SectionItem, iid)
    if not it:
        raise HTTPException(404, "Item not found")
    s, t = _section(db, it.section_id, user)
    _draft(t)
    s.items.remove(it)
    db.delete(it)
    db.commit()
    return test_out(db, t)


# ------------------------------------------------------------------ invites & candidates
@router.post("/tests/{tid}/invites/preview")
async def invite_preview(tid: str, file: Optional[UploadFile] = File(None), text: Optional[str] = Form(None),
                         user: User = Depends(RECRUIT), db: Session = Depends(get_db)):
    _test(db, tid, user)
    if file is not None:
        data = await file.read()
        rows = inv.parse_rows(filename=file.filename or "", data=data)
    else:
        rows = inv.parse_rows(text=text or "")
    limit = 50000 if file is not None and (file.filename or "").lower().endswith(".xlsx") else (20000 if file is not None else 1000)
    if len(rows) > limit:
        raise HTTPException(422, f"Too many rows ({len(rows)}); the limit is {limit}. Split the file.")
    return {"rows": rows, "valid": sum(1 for r in rows if r["status"] == "valid"),
            "flagged": sum(1 for r in rows if r["status"] != "valid")}


@router.post("/tests/{tid}/invites")
def invite(tid: str, body: InviteIn, request: Request, user: User = Depends(RECRUIT), db: Session = Depends(get_db)):
    t = _test(db, tid, user)
    if t.status != "published":
        raise HTTPException(422, "Publish the test before inviting candidates")
    rows = body.rows if body.rows is not None else inv.parse_rows(text=body.text or "")
    if body.schedule_at:
        delta = (aware(body.schedule_at) - now()).total_seconds()
        if delta < 3600 - 60 or delta > 60 * 86400:
            raise HTTPException(422, "Schedule must be between 1 hour and 60 days from now")
    res = inv.create_invites(db, t, rows, body.expires_at, body.schedule_at, body.extra_time_min)
    audit(db, user, "invite", "test", t.id, {"created": res["created"], "skipped": res["skipped"]}, request)
    db.commit()
    return res


class ParticipantEditIn(BaseModel):
    name: str
    email: str


class SendLoginsIn(BaseModel):
    again: bool = False  # also mail people who already got a mail (their earlier password then stops working)


class ParticipantsIn(BaseModel):
    names: List[str]
    email_required: bool = False  # the screen always asks for "Name, email"; scripts may still send a name alone


@router.post("/tests/{tid}/participants")
def add_participants(tid: str, body: ParticipantsIn, request: Request, user: User = Depends(RECRUIT),
                     db: Session = Depends(get_db)):
    """Create exam logins. The response is the only time the passwords are visible."""
    t = _test(db, tid, user)
    if t.status == "archived":
        raise HTTPException(422, "This test is archived")
    if not 0 < sum(1 for x in body.names if x.strip()) <= 200:
        raise HTTPException(422, "Give between 1 and 200 names")
    res = inv.create_participants(db, t, inv.parse_participants(db, t.org_id, body.names, body.email_required, t))  # each line: "Name" or "Name, email"
    audit(db, user, "participants_create", "test", t.id, {"count": len(res)}, request)
    db.commit()
    return {"participants": res}


@router.post("/tests/{tid}/participants/sheet")
async def read_participants_sheet(tid: str, file: UploadFile = File(...), user: User = Depends(RECRUIT), db: Session = Depends(get_db)):
    """Read a student sheet (CSV or Excel: Full name, Email) into lines for the participants box. Nothing is created: the examiner reviews the lines first."""
    _test(db, tid, user)
    data = await file.read(2_000_001)
    if len(data) > 2_000_000:
        raise HTTPException(422, "The sheet is too large (the limit is 2 MB)")
    return inv.parse_sheet(data, file.filename or "")


@router.put("/assignments/{aid}/participant")
def edit_participant(aid: str, body: ParticipantEditIn, request: Request, user: User = Depends(RECRUIT), db: Session = Depends(get_db)):
    """Correct a participant's name and email. Nothing is mailed: the examiner sends the login when they choose."""
    a = db.get(Assignment, aid)
    if not a:
        raise HTTPException(404, "Assignment not found")
    t = _test(db, a.test_id, user)
    if t.status == "archived":
        raise HTTPException(422, "This test is archived")
    old = a.candidate.email
    inv.edit_participant(db, a, body.name, body.email)
    audit(db, user, "participant_edit", "assignment", a.id, {"old_email": old, "new_email": a.candidate.email}, request)
    db.commit()
    return {"name": a.candidate.name, "email": a.candidate.email}


@router.get("/assignments/{aid}/login-mails")
def login_mail_history(aid: str, user: User = Depends(VIEW), db: Session = Depends(get_db)):
    """Every login mail sent to this person, newest first: the address, when, whether the mail server accepted it, and the reason when not."""
    a = db.get(Assignment, aid)
    if not a:
        raise HTTPException(404, "Assignment not found")
    _test(db, a.test_id, user)
    return {"email": a.candidate.email if is_real_email(a.candidate.email) else "", "mails": login_mail.history(login_mail.mails_of(db, [a.id]).get(a.id, []))}


def _can_mail(t: Test) -> None:
    """Logins are mailed only for a published exam and only when the server can send mail; otherwise nothing at all is changed (no password either)."""
    if t.status != "published":
        raise HTTPException(422, "Publish the exam first. Logins can be e-mailed only for a published exam.")
    if not get_settings().smtp_host:
        raise HTTPException(422, "E-mail is not set up on this server (the mail server setting is empty). Nothing was sent and no password was changed. Ask IT to set it up.")


def _mail_login(db: Session, t: Test, a: Assignment) -> dict:
    """A new password for this person, mailed to them with the exam details. Returns the login row (the one time the password is shown here)."""
    row = _fresh_login(a)
    subject, text, page = login_mail.exam_login_mail(t, a.candidate.name, row["username"], row["password"])
    queue_mail(db, a.candidate.email, subject, text, login_mail.KIND, t.org_id, html=page).attach = a.id
    return row


def _busy(db: Session, asgs: List[Assignment]) -> set:
    """The people among these who are taking an exam right now (a new password could lock them out)."""
    ids = [a.candidate_id for a in asgs]
    return set(db.scalars(select(Attempt.candidate_id).where(Attempt.status == "in_progress", Attempt.candidate_id.in_(ids)))) if ids else set()


@router.post("/tests/{tid}/send-logins")
def send_logins(tid: str, body: SendLoginsIn, request: Request, user: User = Depends(RECRUIT), db: Session = Depends(get_db)):
    """E-mail every waiting participant a fresh login (and the exam details). Waiting = has not started, has an email, and has not been mailed at
    that address (or the mail failed). People already mailed keep their password unless `again` is set."""
    t = _test(db, tid, user)
    _can_mail(t)
    asgs = [a for a in db.scalars(select(Assignment).where(Assignment.test_id == t.id, Assignment.status == "invited")).all() if a.candidate.username]
    mails = login_mail.mails_of(db, [a.id for a in asgs])
    states = {a.id: login_mail.mail_state(a.candidate.email, mails.get(a.id, []))["state"] for a in asgs}
    no_email = sum(1 for s in states.values() if s == "no_email")
    wanted = [a for a in asgs if states[a.id] != "no_email" and (body.again or states[a.id] in login_mail.WAITING)]
    busy = _busy(db, wanted)
    todo = [a for a in wanted if a.candidate_id not in busy]
    batch = todo[:200]  # the password check takes a moment each: a click does at most 200, the screen says how many are left
    rows = [_mail_login(db, t, a) for a in batch]
    audit(db, user, "logins_sent", "test", t.id, {"count": len(rows), "again": body.again}, request)
    db.commit()
    return {"queued": len(rows), "no_email": no_email, "busy": len(wanted) - len(todo), "remaining": len(todo) - len(batch), "participants": rows}


@router.post("/assignments/{aid}/send-login")
def send_login(aid: str, request: Request, user: User = Depends(RECRUIT), db: Session = Depends(get_db)):
    """E-mail one person a fresh login (a failed mail, or an email that was corrected)."""
    a = db.get(Assignment, aid)
    if not a:
        raise HTTPException(404, "Assignment not found")
    t = _test(db, a.test_id, user)
    _can_mail(t)
    if a.status != "invited" or not a.candidate.username:
        raise HTTPException(422, "A login can be mailed only to a person who has not started the exam")
    if not is_real_email(a.candidate.email):
        raise HTTPException(422, "This person has no email. Open Edit details and add one first")
    if _busy(db, [a]):
        raise HTTPException(409, "This person is taking another exam right now. Try again after it ends")
    row = _mail_login(db, t, a)
    audit(db, user, "login_sent", "assignment", a.id, request=request)
    db.commit()
    return {"participant": row}


def _fresh_login(a: Assignment) -> dict:
    """A new password for this person (the old one stops working). Only its hash is stored, so this is the one time it can be shown."""
    pw = inv.login_password(a.candidate.name)
    a.candidate.password_hash, a.candidate.failed_logins = hash_password(pw), 0
    return {"assignment_id": a.id, "name": a.candidate.name, "username": a.candidate.username or a.candidate.email, "password": pw}


@router.post("/assignments/{aid}/password")
def reset_password(aid: str, request: Request, user: User = Depends(RECRUIT), db: Session = Depends(get_db)):
    a = db.get(Assignment, aid)
    if not a:
        raise HTTPException(404, "Assignment not found")
    _test(db, a.test_id, user)
    out = _fresh_login(a)
    audit(db, user, "password_reset", "assignment", a.id, request=request)
    db.commit()
    return out


@router.post("/tests/{tid}/passwords")
def fresh_login_sheet(tid: str, request: Request, user: User = Depends(RECRUIT), db: Session = Depends(get_db)):
    """The whole login sheet again: new passwords for everyone who has not started yet (people already taking or finished keep theirs)."""
    t = _test(db, tid, user)
    rows = [_fresh_login(a) for a in db.scalars(select(Assignment).where(Assignment.test_id == t.id, Assignment.status == "invited")).all() if a.candidate.username]
    audit(db, user, "passwords_reset_all", "test", t.id, {"count": len(rows)}, request)
    db.commit()
    return {"participants": rows}


@router.get("/tests/{tid}/candidates")
def candidates(tid: str, status: str = "", q: Optional[str] = None, limit: Optional[int] = Depends(limit_q), offset: int = Depends(offset_q),
               user: User = Depends(VIEW), db: Session = Depends(get_db)):
    """The people of an exam. `counts` always covers everyone; `rows` is the whole table, or with ?limit=&offset= (and q to search) one page, `total` the rows that match."""
    t = _test(db, tid, user)
    rows = reports.candidates_table(db, t)
    mails = login_mail.mails_of(db, [r["assignment_id"] for r in rows])  # one query for everyone
    counts: Dict[str, int] = {}
    logins = {"waiting": 0, "queued": 0, "sent": 0, "failed": 0, "changed": 0, "no_email": 0}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
        r["login_mail"] = lm = login_mail.mail_state(r["email"], mails.get(r["assignment_id"], []))
        key = "changed" if lm["state"] == "email_changed" else lm["state"]
        if key in logins:
            logins[key] += 1
        if r["status"] == "invited" and lm["state"] in login_mail.WAITING:
            logins["waiting"] += 1
    if status:
        rows = [r for r in rows if r["status"] == status]
    page, total = page_rows(rows, q, limit, offset)
    return {"rows": page, "counts": counts, "total": total, "logins": logins}


@router.get("/tests/{tid}/monitor")
def monitor(tid: str, user: User = Depends(VIEW), db: Session = Depends(get_db)):
    return reports.monitor_rows(db, _test(db, tid, user))


@router.post("/assignments/{aid}/action")
def assignment_action(aid: str, body: ActionIn, request: Request, user: User = Depends(RECRUIT), db: Session = Depends(get_db)):
    from app.services.mail import queue_mail
    a = db.get(Assignment, aid)
    if not a:
        raise HTTPException(404, "Assignment not found")
    t = _test(db, a.test_id, user)
    at = db.scalar(select(Attempt).where(Attempt.assignment_id == a.id).order_by(Attempt.started_at.desc()))
    act = body.action
    if act == "shortlist":
        a.status = "shortlisted"
        queue_mail(db, a.candidate.email, f"Update on {t.title}", f"Dear {a.candidate.name or a.candidate.email},\n\n"
                   "Congratulations - you have been shortlisted for the next round. The recruiter will contact you.\n\nKAUTILYA by GLOBX",
                   "shortlist", t.org_id)
    elif act == "archive":
        a.status = "archived"
    elif act == "cancel":
        a.status = "cancelled"
    elif act == "extend":
        if body.minutes <= 0 or body.minutes > 240:
            raise HTTPException(422, "Minutes must be 1-240")
        if not body.reason:
            raise HTTPException(422, "A reason is required")
        a.extra_time_min += body.minutes
        if at and at.status == "in_progress":
            at.deadline_at = aware(at.deadline_at) + timedelta(minutes=body.minutes)
    elif act == "terminate":  # end a running exam now; the candidate's browser notices within seconds
        if not body.reason:
            raise HTTPException(422, "A reason is required")
        if not at or at.status != "in_progress":
            raise HTTPException(409, "This candidate is not taking the exam right now")
        from app.services import attempts as attempts_svc, jobs
        attempts_svc.terminate_attempt(db, at, "admin_ended")
        audit(db, user, "assignment_terminate", "assignment", a.id, {"reason": body.reason}, request)
        db.commit()
        jobs.finalize_async(at.id, "admin_ended")
        return {"ok": True, "status": a.status}
    elif act == "reset":
        if not body.reason:
            raise HTTPException(422, "A reason is required")
        if t.results_declared_at:
            raise HTTPException(409, "The results of this exam are declared. Withdraw them before re-opening an exam.")
        t.calculated_at = None  # the exam must be calculated again
        if at:
            at.status = "reset"
        token = None
        from app.core.security import new_token, sha256
        token = new_token(32)
        a.token_hash = sha256(token)
        a.status = "invited"
        inv.send_invite_mail(db, a, token)
    elif act in ("remind", "resend"):
        from app.core.security import new_token, sha256
        token = new_token(32)
        a.token_hash = sha256(token)
        inv.send_invite_mail(db, a, token)
    else:
        raise HTTPException(422, "Unknown action")
    audit(db, user, f"assignment_{act}", "assignment", a.id, {"minutes": body.minutes, "reason": body.reason}, request)
    db.commit()
    return {"ok": True, "status": a.status}


# ------------------------------------------------------------------ analytics / export / plagiarism
@router.get("/tests/{tid}/analytics")
def analytics(tid: str, user: User = Depends(VIEW), db: Session = Depends(get_db)):
    return exam_analytics(db, _test(db, tid, user))


@router.get("/tests/{tid}/export")
def export(tid: str, format: str = "csv", user: User = Depends(RECRUIT), db: Session = Depends(get_db)):
    t = _test(db, tid, user)
    rows = reports.export_rows(db, t)
    safe = "".join(ch for ch in t.title if ch.isalnum() or ch in " -_")[:40].strip().replace(" ", "_") or "results"
    if format == "xlsx":
        return Response(reports.to_xlsx(rows), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="{safe}.xlsx"'})
    return Response(reports.to_csv(rows), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{safe}.csv"'})


@router.post("/tests/{tid}/plagiarism/run")
def plagiarism_run(tid: str, user: User = Depends(VIEW), db: Session = Depends(get_db)):
    from app.services.plagiarism import run_for_test
    t = _test(db, tid, user)
    return run_for_test(db, t.id)


@router.get("/tests/{tid}/plagiarism")
def plagiarism_list(tid: str, user: User = Depends(VIEW), db: Session = Depends(get_db)):
    t = _test(db, tid, user)
    ms = db.scalars(select(PlagiarismMatch).where(PlagiarismMatch.test_id == t.id).order_by(PlagiarismMatch.similarity.desc())).all()
    names = {}

    def who(aid):
        if aid not in names:
            at = db.get(Attempt, aid)
            u = db.get(User, at.candidate_id) if at else None
            names[aid] = {"attempt_id": aid, "name": u.name if u else "", "email": u.email if u else "",
                          "risk_level": at.risk_level if at else ""}
        return names[aid]
    out = []
    for m in ms:
        q = db.get(Question, m.question_id)
        out.append({"id": m.id, "question": {"id": q.id, "title": q.title, "type": q.type} if q else None,
                    "a": who(m.attempt_a), "b": who(m.attempt_b), "similarity": m.similarity, "longest_run": m.longest_run,
                    "level": m.level, "decision": m.decision})
    return out


def _source_of(db: Session, attempt_id: str, question_id: str) -> dict:
    a = db.scalar(select(Answer).where(Answer.attempt_id == attempt_id, Answer.question_id == question_id))
    r = (a.response if a else {}) or {}
    sub = db.get(CodeSubmission, r.get("best_submission_id")) if r.get("best_submission_id") else None
    at = db.get(Attempt, attempt_id)
    return {"text": sub.source if sub else (r.get("html") or r.get("text") or r.get("source") or ""), "language": sub.language if sub else "",
            "submitted_at": _iso(sub.created_at) if sub else None, "ip": at.ip if at else ""}


@router.get("/plagiarism/{mid}")
def plagiarism_detail(mid: str, user: User = Depends(VIEW), db: Session = Depends(get_db)):
    m = db.get(PlagiarismMatch, mid)
    if not m:
        raise HTTPException(404, "Not found")
    _test(db, m.test_id, user)
    return {"id": m.id, "similarity": m.similarity, "level": m.level, "longest_run": m.longest_run, "decision": m.decision,
            "a": _source_of(db, m.attempt_a, m.question_id), "b": _source_of(db, m.attempt_b, m.question_id)}


@router.post("/plagiarism/{mid}/decision")
def plagiarism_decision(mid: str, body: dict, request: Request, user: User = Depends(VIEW), db: Session = Depends(get_db)):
    m = db.get(PlagiarismMatch, mid)
    if not m:
        raise HTTPException(404, "Not found")
    _test(db, m.test_id, user)
    d = body.get("decision", "")
    if d not in ("false_positive", "confirmed", "review", ""):
        raise HTTPException(422, "decision must be false_positive, confirmed or review")
    m.decision = d
    audit(db, user, "plagiarism_decision", "plagiarism", m.id, {"decision": d, "reason": body.get("reason", "")}, request)
    db.commit()
    return {"ok": True}
