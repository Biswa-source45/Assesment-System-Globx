"""Candidate endpoints: dashboard, start, runner state, autosave, sections, code run/submit, proctoring, submit, result."""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.deps import audit, client_ip, current_user, same_org
from app.db import get_db
from app.models import (Answer, Assignment, Attempt, AttemptQuestion, CodeSubmission, Question, Test, User, aware,
                        now, uid)
from app.sandbox.judge import public_view
from app.services import attempts as svc
from app.services import jobs, proctoring
from app.services.reports import attempt_report

router = APIRouter(tags=["candidate"])


class StartIn(BaseModel):
    consent: Dict[str, Any] = {}
    system_check: Dict[str, Any] = {}


class AnswerIn(BaseModel):
    response: Dict[str, Any] = {}
    flagged: bool = False
    seq: int = 0


class CodeIn(BaseModel):
    language: str
    source: str
    custom_input: Optional[str] = None


class EventsIn(BaseModel):
    events: List[Dict[str, Any]] = []


def _my_attempt(db: Session, attempt_id: str, user: User) -> Attempt:
    at = db.get(Attempt, attempt_id)
    if not at or at.candidate_id != user.id:
        raise HTTPException(404, "Attempt not found")
    return at


def _window_error(t: Test, a: Assignment) -> Optional[str]:
    if t.status != "published":
        return "This test is not open"
    if not t.access_enabled:
        return "Access to this test is currently disabled by the organiser"
    if t.starts_at and aware(t.starts_at) > now():
        return f"The test opens at {aware(t.starts_at).strftime('%d %b %Y %H:%M UTC')}"
    if t.results_declared_at:
        return "Results for this exam have already been declared"
    if t.ends_at and aware(t.ends_at) < now():
        return "The test window has closed"
    if a.expires_at and aware(a.expires_at) < now():
        return "Your invitation has expired"
    if a.status in ("cancelled", "expired"):
        return "Your invitation is no longer valid"
    return None


@router.get("/me/assignments")
def my_assignments(user: User = Depends(current_user), db: Session = Depends(get_db)):
    out = []
    for a in db.scalars(select(Assignment).where(Assignment.candidate_id == user.id).order_by(Assignment.invited_at.desc())).all():
        t = db.get(Test, a.test_id)
        if t.status == "archived":  # taken out of use by the Super Admin: the candidate no longer sees it
            continue
        at = db.scalar(select(Attempt).where(Attempt.assignment_id == a.id, Attempt.status != "reset").order_by(Attempt.started_at.desc()))
        publish_result = bool((t.settings or {}).get("show_result_to_candidate", True))
        res = None
        if at and t.results_declared_at and at.status == "evaluated" and publish_result:
            rep = attempt_report(db, at, staff_view=False)
            res = {"score": at.total_score, "max": at.max_score, "percent": rep["attempt"]["percent"], "result": rep["attempt"]["result"],
                   "reason": at.submit_reason, "sections": [{"title": s["title"], "score": s["score"], "max": s["max"]} for s in rep["sections"]]}
        n_q = sum(len(s.items) for s in t.sections)
        out.append({"assignment_id": a.id, "status": a.status, "test": {"id": t.id, "title": t.title,
                    "description": t.description, "duration_min": t.duration_min, "instructions": t.instructions,
                    "starts_at": aware(t.starts_at).isoformat() if t.starts_at else None,
                    "ends_at": aware(t.ends_at).isoformat() if t.ends_at else None, "items": n_q,
                    "proctoring": svc.proctoring_config(t), "min_question_seconds": svc.min_question_seconds(t)},
                    "attempt": {"id": at.id, "status": at.status, "deadline_at": aware(at.deadline_at).isoformat()} if at else None,
                    "result": res, "can_start": _window_error(t, a) is None and (not at or at.status == "in_progress")
                    and a.status in ("invited", "in_progress"), "message": _window_error(t, a)})
    return out


@router.post("/assignments/{aid}/start")
def start(aid: str, body: StartIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    a = db.get(Assignment, aid)
    if not a or a.candidate_id != user.id:
        raise HTTPException(404, "Assignment not found")
    t = db.get(Test, a.test_id)
    existing = db.scalar(select(Attempt).where(Attempt.assignment_id == a.id, Attempt.status == "in_progress"))
    if existing:
        return {"attempt_id": existing.id, "resumed": True}
    done = db.scalar(select(Attempt).where(Attempt.assignment_id == a.id, Attempt.status.notin_(["reset"])))
    if done:
        raise HTTPException(409, "You have already taken this test")
    err = _window_error(t, a)
    if err:
        raise HTTPException(403, err)
    cfg = svc.proctoring_config(t)
    if cfg.get("enabled") and not body.consent.get("accepted"):
        raise HTTPException(422, "Proctoring consent is required to start this test")
    if cfg.get("block_multi_display") and body.system_check.get("displays", 1) > 1:
        raise HTTPException(422, "Disconnect additional displays before starting")
    body.consent["at"] = now().isoformat()
    body.consent["version"] = "2026-10"
    at = svc.start_attempt(db, a, t, client_ip(request), request.headers.get("user-agent", ""), body.consent, body.system_check)
    sc = body.system_check or {}
    flags = []
    if sc.get("vm_suspected"):
        flags.append({"type": "vm_detected", "payload": {"renderer": sc.get("renderer", "")}})
    if sc.get("displays", 1) > 1:
        flags.append({"type": "multi_display", "payload": {"displays": sc.get("displays")}})
    if cfg.get("webcam") and not sc.get("camera"):
        flags.append({"type": "webcam_denied"})
    if flags:
        proctoring.ingest_events(db, at, flags)
    audit(db, user, "attempt_start", "attempt", at.id, request=request, org_id=t.org_id)
    db.commit()
    return {"attempt_id": at.id, "resumed": False}


@router.get("/attempts/{atid}")
def state(atid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    at = _my_attempt(db, atid, user)
    return svc.attempt_state(db, at, db.get(Test, at.test_id))


@router.get("/attempts/{atid}/clock")
def clock(atid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """The server's view of the deadline, polled by the exam page so that an extension or an ended exam is noticed quickly."""
    at = _my_attempt(db, atid, user)
    return {"status": at.status, "deadline_at": aware(at.deadline_at).isoformat(), "server_time": now().isoformat(),
            "reason": at.submit_reason, "content_version": svc.content_version(db, at)}


@router.post("/attempts/{atid}/sections/{sid}/enter")
def enter(atid: str, sid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    at = _my_attempt(db, atid, user)
    st = svc.enter_section(db, at, db.get(Test, at.test_id), sid)
    db.commit()
    return {"section_state": at.section_state, "current": st}


@router.put("/attempts/{atid}/answers/{qid}")
def save(atid: str, qid: str, body: AnswerIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    at = _my_attempt(db, atid, user)
    a = svc.save_answer(db, at, qid, body.response, body.flagged, body.seq)
    db.commit()
    left = int((aware(at.deadline_at) - now()).total_seconds())
    return {"saved_at": aware(a.saved_at).isoformat(), "seq": a.seq, "time_left_s": max(0, left)}


@router.post("/attempts/{atid}/answers/{qid}/file")
async def upload_answer_file(atid: str, qid: str, file: UploadFile = File(...), user: User = Depends(current_user),
                             db: Session = Depends(get_db)):
    at = _my_attempt(db, atid, user)
    svc.ensure_active(at)
    data = await file.read()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(413, "File is larger than 10 MB")
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in (".pdf", ".png", ".jpg", ".jpeg", ".docx", ".txt"):
        raise HTTPException(415, "Allowed: PDF, PNG, JPG, DOCX, TXT")
    folder = os.path.join(get_settings().storage_dir, "uploads", at.id)
    os.makedirs(folder, exist_ok=True)
    fid = uid()
    with open(os.path.join(folder, fid + ext), "wb") as f:
        f.write(data)
    a = db.scalar(select(Answer).where(Answer.attempt_id == at.id, Answer.question_id == qid))
    if not a:
        a = svc.save_answer(db, at, qid, {}, False, 0)
    r = dict(a.response or {})
    r["files"] = (r.get("files") or []) + [{"id": fid + ext, "name": (file.filename or "file")[:120], "size": len(data)}]
    a.response = r
    db.commit()
    return {"files": r["files"]}


# ------------------------------------------------------------------ code / SQL
def _code_submit(db: Session, at: Attempt, qid: str, body: CodeIn, kind: str) -> CodeSubmission:
    svc.ensure_active(at)
    aq = db.scalar(select(AttemptQuestion).where(AttemptQuestion.attempt_id == at.id, AttemptQuestion.question_id == qid))
    if not aq or aq.question.type not in ("coding", "sql"):
        raise HTTPException(404, "Programming question not found in this attempt")
    s = get_settings()
    limit = s.run_limit_per_question if kind == "run" else s.submit_limit_per_question
    n = db.scalar(select(func.count(CodeSubmission.id)).where(CodeSubmission.attempt_id == at.id,
                                                              CodeSubmission.question_id == qid, CodeSubmission.kind == kind))
    if n >= limit:
        raise HTTPException(429, f"Limit reached: {limit} {kind}s per question")
    if len(body.source or "") > 64 * 1024:
        raise HTTPException(413, "Source code exceeds 64 KB")
    sub = CodeSubmission(id=uid(), attempt_id=at.id, question_id=qid, kind=kind, language=body.language,
                         source=body.source, custom_input=body.custom_input if kind == "run" else None)
    db.add(sub)
    svc.save_answer(db, at, qid, {"language": body.language, "source": body.source}, False, 0)
    db.commit()
    jobs.enqueue_submission(sub)
    return sub


@router.post("/attempts/{atid}/code/{qid}/run")
def run_code(atid: str, qid: str, body: CodeIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    sub = _code_submit(db, _my_attempt(db, atid, user), qid, body, "run")
    return {"submission_id": sub.id, "status": sub.status}


@router.post("/attempts/{atid}/code/{qid}/submit")
def submit_code(atid: str, qid: str, body: CodeIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    sub = _code_submit(db, _my_attempt(db, atid, user), qid, body, "submit")
    return {"submission_id": sub.id, "status": sub.status}


@router.get("/submissions/{sid}")
def submission(sid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    sub = db.get(CodeSubmission, sid)
    if not sub:
        raise HTTPException(404, "Submission not found")
    at = db.get(Attempt, sub.attempt_id) if sub.attempt_id else None
    is_owner = at and at.candidate_id == user.id
    if not is_owner and not user.has("super_admin", "org_admin", "recruiter", "test_creator", "evaluator"):
        raise HTTPException(404, "Submission not found")
    q = db.get(Question, sub.question_id)
    if not is_owner:
        same_org(user, q.org_id if q else None)  # staff may only read their own organisation's submissions
    res = sub.result or {}
    if is_owner:
        res = public_view(res)
    return {"id": sub.id, "kind": sub.kind, "language": sub.language, "status": sub.status, "score": sub.score,
            "max_score": sub.max_score, "question_marks": q.marks if q else None,
            "created_at": aware(sub.created_at).isoformat(), "result": res}


@router.get("/attempts/{atid}/code/{qid}/history")
def code_history(atid: str, qid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    at = _my_attempt(db, atid, user)
    subs = db.scalars(select(CodeSubmission).where(CodeSubmission.attempt_id == at.id, CodeSubmission.question_id == qid)
                      .order_by(CodeSubmission.created_at.desc())).all()
    return [{"id": s.id, "kind": s.kind, "language": s.language, "status": s.status, "score": s.score,
             "max_score": s.max_score, "created_at": aware(s.created_at).isoformat(),
             "passed": (s.result or {}).get("passed"), "total": (s.result or {}).get("total")} for s in subs]


# ------------------------------------------------------------------ proctoring
def _enforce(db: Session, at: Attempt, out: dict) -> None:
    """Terminate the exam when the proctoring rules say so: tab limit -> submitted; face limit -> submitted + banned."""
    reason = {"force_submit": "violation_limit", "ban": "face_violation"}.get(out.get("action"))
    if reason:
        svc.terminate_attempt(db, at, reason)
        db.commit()
        jobs.finalize_async(at.id, reason)


@router.post("/attempts/{atid}/proctor/events")
def proctor_events(atid: str, body: EventsIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    at = _my_attempt(db, atid, user)
    if at.status != "in_progress":
        return {"action": "none", "risk_level": at.risk_level}
    out = proctoring.ingest_events(db, at, body.events)
    db.commit()
    _enforce(db, at, out)
    return out


@router.post("/attempts/{atid}/proctor/snapshot")
async def proctor_snapshot(atid: str, kind: str = Form("webcam"), faces: Optional[int] = Form(None),
                           image: UploadFile = File(...), user: User = Depends(current_user), db: Session = Depends(get_db)):
    at = _my_attempt(db, atid, user)
    if at.status != "in_progress":
        return {"action": "none"}
    data = await image.read()
    out = proctoring.save_snapshot(db, at, kind, data, faces)
    db.commit()
    _enforce(db, at, out)
    return out


# ------------------------------------------------------------------ submit & result
@router.post("/attempts/{atid}/submit")
def submit(atid: str, body: dict, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    at = _my_attempt(db, atid, user)
    if at.status != "in_progress":
        return {"status": at.status}
    at.feedback = {k: body.get(k) for k in ("rating", "comment") if body.get(k) is not None}
    at.status = "submitted"
    at.submitted_at = now()
    at.submit_reason = "submitted"
    a = db.get(Assignment, at.assignment_id)
    a.status = "test_taken"
    audit(db, user, "attempt_submit", "attempt", at.id, request=request, org_id=db.get(Test, at.test_id).org_id)
    db.commit()
    jobs.finalize_async(at.id, "submitted")
    return {"status": "submitted"}


@router.post("/attempts/{atid}/feedback")
def feedback(atid: str, body: dict, user: User = Depends(current_user), db: Session = Depends(get_db)):
    at = _my_attempt(db, atid, user)
    at.feedback = {"rating": body.get("rating"), "comment": str(body.get("comment", ""))[:2000]}
    db.commit()
    return {"ok": True}


@router.get("/attempts/{atid}/result")
def result(atid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    at = _my_attempt(db, atid, user)
    t = db.get(Test, at.test_id)
    if not t.results_declared_at or at.status != "evaluated" or not (t.settings or {}).get("show_result_to_candidate", True):
        return {"published": False, "status": at.status, "test": t.title,
                "message": "Your answers were submitted. Results will be shared by the organiser."}
    rep = attempt_report(db, at, staff_view=False)
    rep["published"] = True
    return rep
