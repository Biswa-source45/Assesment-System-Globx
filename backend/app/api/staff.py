"""Staff endpoints: evaluation queue, candidate reports, evidence files, dashboard, and system administration."""
from __future__ import annotations

import os
from datetime import timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.deps import ADMIN, EVAL, SUPER, VIEW, audit, same_org, staff
from app.core.security import hash_password, password_policy_error
from app.db import get_db
from app.domain import scoring
from app.models import (ROLES, Answer, Assignment, Attempt, AttemptQuestion, AuditLog, CodeSubmission, Evaluation,
                        MailOutbox, Organization, ProctorSnapshot, Question, RefreshToken, Test, User, UserRole, aware, now, uid)
from app.sandbox import remote
from app.services import ai
from app.services.departments import create_defaults
from app.services.attempts import _text_of, grade_answer, recompute_totals
from app.services.reports import attempt_report, results_of

router = APIRouter(tags=["staff"])


class EvalIn(BaseModel):
    rubric_scores: List[Dict[str, Any]] = []
    final_score: Optional[float] = None
    override_reason: str = ""
    feedback: str = ""


class UserIn(BaseModel):
    email: str = ""
    name: str = ""
    roles: List[str] = []
    password: Optional[str] = None
    org_id: Optional[str] = None
    status: Optional[str] = None  # left out on an edit: unchanged
    unlock: bool = False


class OrgIn(BaseModel):
    name: str
    slug: str
    plan: str = "enterprise"
    credits: int = 0
    data_region: str = "IN"
    status: str = "active"


def _attempt(db: Session, atid: str, user: User) -> Attempt:
    at = db.get(Attempt, atid)
    if not at:
        raise HTTPException(404, "Attempt not found")
    same_org(user, db.get(Test, at.test_id).org_id)
    return at


# ------------------------------------------------------------------ evaluation
@router.get("/evaluations/queue")
def queue(test_id: Optional[str] = None, user: User = Depends(EVAL), db: Session = Depends(get_db)):
    stmt = (select(Answer, Attempt, Test).join(Attempt, Answer.attempt_id == Attempt.id).join(Test, Attempt.test_id == Test.id)
            .where(Answer.status == "review", Test.org_id == user.org_id))
    if test_id:
        stmt = stmt.where(Test.id == test_id)
    out = []
    for a, at, t in db.execute(stmt.order_by(Answer.saved_at)).all():
        q = db.get(Question, a.question_id)
        reason = "Long answer - evaluator confirmation" if q.type == "long" else (
            "Low AI confidence" if a.ai_confidence is not None else "AI unavailable - keyword score only")
        if (a.response or {}).get("files"):
            reason += " + file"
        out.append({"answer_id": a.id, "attempt_id": at.id, "candidate_ref": "C-" + at.id[:6].upper(), "test": t.title,
                    "question": q.title, "type": q.type, "ai_score": a.ai_score, "auto_score": a.auto_score,
                    "marks": db.scalar(select(AttemptQuestion.marks).where(AttemptQuestion.attempt_id == at.id,
                                                                            AttemptQuestion.question_id == q.id)),
                    "reason": reason})
    return out


@router.get("/answers/{aid}")
def answer_detail(aid: str, blind: bool = True, user: User = Depends(VIEW), db: Session = Depends(get_db)):
    a = db.get(Answer, aid)
    if not a:
        raise HTTPException(404, "Answer not found")
    at = _attempt(db, a.attempt_id, user)
    q = db.get(Question, a.question_id)
    aq = db.scalar(select(AttemptQuestion).where(AttemptQuestion.attempt_id == at.id, AttemptQuestion.question_id == q.id))
    u = db.get(User, at.candidate_id)
    evs = db.scalars(select(Evaluation).where(Evaluation.answer_id == a.id).order_by(Evaluation.created_at)).all()
    c = q.config or {}
    return {"answer": {"id": a.id, "response": a.response, "status": a.status, "auto_score": a.auto_score,
                       "ai_score": a.ai_score, "ai_confidence": a.ai_confidence, "ai_rationale": a.ai_rationale,
                       "ai_detail": a.ai_detail, "final_score": a.final_score, "feedback": a.feedback, "flags": a.flags,
                       "words": len(_text_of(a.response).split())},
            "question": {"id": q.id, "title": q.title, "type": q.type, "body": q.body, "marks": aq.marks if aq else q.marks,
                         "model_answer": c.get("model_answer", ""), "keywords": c.get("keywords", []),
                         "rubric": c.get("rubric", [])},
            "candidate": ({"ref": "C-" + at.id[:6].upper()} if blind else {"ref": "C-" + at.id[:6].upper(), "name": u.name, "email": u.email}),
            "attempt_id": at.id,
            "history": [{"method": e.method, "score": e.score, "by": e.evaluator_id, "reason": e.override_reason,
                         "at": aware(e.created_at).isoformat()} for e in evs]}


@router.post("/answers/{aid}/evaluate")
def evaluate(aid: str, body: EvalIn, request: Request, user: User = Depends(EVAL), db: Session = Depends(get_db)):
    a = db.get(Answer, aid)
    if not a:
        raise HTTPException(404, "Answer not found")
    at = _attempt(db, a.attempt_id, user)
    q = db.get(Question, a.question_id)
    aq = db.scalar(select(AttemptQuestion).where(AttemptQuestion.attempt_id == at.id, AttemptQuestion.question_id == q.id))
    marks = aq.marks if aq else q.marks
    rub = (q.config or {}).get("rubric") or []
    for s in body.rubric_scores:
        cr = next((r for r in rub if str(r["id"]) == str(s.get("id"))), None)
        if cr is None:
            raise HTTPException(422, f"Unknown rubric criterion {s.get('id')}")
        v = float(s.get("score", 0))
        if v < 0 or v > float(cr.get("max", 1)) or abs(v * 4 - round(v * 4)) > 1e-9:
            raise HTTPException(422, f"'{cr.get('name')}' must be between 0 and {cr.get('max')} in steps of 0.25")
    final = body.final_score
    if final is None:
        final = scoring.score_rubric(rub, body.rubric_scores) if body.rubric_scores else None
    if final is None:
        raise HTTPException(422, "Enter a final score")
    lo = -float(aq.negative if aq else 0)
    if final < lo or final > marks:
        raise HTTPException(422, f"Final score must be between {lo} and {marks}")
    suggested = a.ai_score if a.ai_score is not None else a.auto_score
    if suggested is not None and abs(final - suggested) > 1e-9 and not body.override_reason.strip():
        raise HTTPException(422, "An override reason is required when the final score differs from the suggested score")
    a.final_score, a.status, a.feedback = scoring.r2(final), "final", body.feedback
    db.add(Evaluation(id=uid(), answer_id=a.id, evaluator_id=user.id, method="manual", score=a.final_score,
                      rubric_scores=body.rubric_scores, override_reason=body.override_reason))
    recompute_totals(db, at)
    audit(db, user, "evaluate", "answer", a.id, {"score": a.final_score, "suggested": suggested,
                                                 "reason": body.override_reason}, request)
    db.commit()
    return {"ok": True, "attempt_status": at.status, "total_score": at.total_score}


@router.post("/answers/{aid}/ai")
def rerun_ai(aid: str, user: User = Depends(EVAL), db: Session = Depends(get_db)):
    if not ai.llm_enabled():
        raise HTTPException(400, "No AI provider is configured (LLM_PROVIDER=none)")
    a = db.get(Answer, aid)
    if not a:
        raise HTTPException(404, "Answer not found")
    at = _attempt(db, a.attempt_id, user)
    aq = db.scalar(select(AttemptQuestion).where(AttemptQuestion.attempt_id == at.id, AttemptQuestion.question_id == a.question_id))
    grade_answer(db, aq, a, use_ai=True)
    recompute_totals(db, at)
    db.commit()
    return {"ai_score": a.ai_score, "ai_rationale": a.ai_rationale, "status": a.status}


# ------------------------------------------------------------------ reports & evidence
@router.get("/reports/attempts/{atid}")
def report(atid: str, user: User = Depends(VIEW), db: Session = Depends(get_db)):
    return attempt_report(db, _attempt(db, atid, user), staff_view=True)


@router.get("/snapshots/{sid}")
def snapshot_file(sid: str, user: User = Depends(VIEW), db: Session = Depends(get_db)):
    s = db.get(ProctorSnapshot, sid)
    if not s:
        raise HTTPException(404, "Not found")
    _attempt(db, s.attempt_id, user)
    root = os.path.realpath(get_settings().storage_dir)
    p = os.path.realpath(os.path.join(root, s.path))  # a relative path; an absolute one (older rows) is used as it is
    if os.path.commonpath([root, p]) != root or not os.path.exists(p):
        raise HTTPException(404, "File missing")
    return FileResponse(p)


@router.get("/files/{atid}/{fid}")
def answer_file(atid: str, fid: str, user: User = Depends(VIEW), db: Session = Depends(get_db)):
    _attempt(db, atid, user)
    if "/" in fid or "\\" in fid or ".." in fid:
        raise HTTPException(400, "Bad file id")
    p = os.path.join(get_settings().storage_dir, "uploads", atid, fid)
    if not os.path.exists(p):
        raise HTTPException(404, "File missing")
    return FileResponse(p, filename=fid)


@router.get("/dashboard")
def dashboard(user: User = Depends(staff), db: Session = Depends(get_db)):
    org = user.org_id
    tests = db.scalars(select(Test).where(Test.org_id == org, Test.status != "archived")).all()
    tids = [t.id for t in tests]
    asgs = db.scalars(select(Assignment).where(Assignment.test_id.in_(tids))).all() if tids else []
    atts = db.scalars(select(Attempt).where(Attempt.test_id.in_(tids))).all() if tids else []
    review = db.scalar(select(func.count(Answer.id)).join(Attempt, Answer.attempt_id == Attempt.id)
                       .where(Attempt.test_id.in_(tids), Answer.status == "review")) if tids else 0
    return {"tests": len(tests), "live": sum(1 for t in tests if t.status == "published"),
            "invited": len(asgs), "attempted": len(atts),
            "in_progress": sum(1 for a in atts if a.status == "in_progress"),
            "evaluated": sum(1 for a in atts if a.status == "evaluated"),
            "cleared": sum(1 for t in tests for r in results_of(db, t, [a for a in atts if a.test_id == t.id and a.status in ("evaluated", "review_pending")]).values() if r == "passed"),
            "review_pending": review, "critical": sum(1 for a in atts if a.risk_level == "critical"),
            "ai_provider": get_settings().llm_provider, "demo_mode": get_settings().demo_mode}


# ------------------------------------------------------------------ administration
STAFF_ROLES = [r for r in ROLES if r != "candidate"]


def _user_out(u: User, exams: Optional[List[str]] = None) -> dict:
    out = {"id": u.id, "email": u.email, "username": u.username, "name": u.name, "roles": u.role_names, "org_id": u.org_id, "status": u.status,
           "mfa_enabled": u.mfa_enabled, "locked": u.failed_logins >= 10,
           "created_at": aware(u.created_at).isoformat() if u.created_at else None,
           "last_login_at": aware(u.last_login_at).isoformat() if u.last_login_at else None}
    if exams is not None:
        out["exams"] = exams
    return out


@router.get("/users")
def list_users(role: Optional[str] = None, org_id: Optional[str] = None, user: User = Depends(ADMIN), db: Session = Depends(get_db)):
    """Staff by default; role=candidate lists the people who sit exams, with the exams they were given."""
    oid = org_id if (org_id and user.has("super_admin")) else user.org_id
    us = db.scalars(select(User).where(User.org_id == oid).order_by(User.created_at.desc())).all()
    if role:
        us = [u for u in us if role in u.role_names]
    else:
        us = [u for u in us if set(u.role_names) - {"candidate"}]
    if role != "candidate":
        return [_user_out(u) for u in us]
    taken: Dict[str, List[str]] = {}
    for cid, title in db.execute(select(Assignment.candidate_id, Test.title).join(Test, Test.id == Assignment.test_id).order_by(Test.created_at)).all():
        taken.setdefault(cid, []).append(title)
    return [_user_out(u, taken.get(u.id, [])) for u in us]


def _staff_roles(user: User, wanted: List[str]) -> List[str]:
    roles = [r for r in STAFF_ROLES if r in wanted]
    if "super_admin" in roles and not user.has("super_admin"):
        raise HTTPException(403, "Only a Super Admin can grant Super Admin")
    return roles


def _check_password(pw: str) -> None:
    err = password_policy_error(pw)
    if err:
        raise HTTPException(422, err)


def _sign_out_everywhere(db: Session, u: User) -> None:
    """A new password, or a disabled account, must also end the sessions that are already open."""
    db.execute(update(RefreshToken).where(RefreshToken.user_id == u.id).values(revoked=True))


@router.post("/users")
def create_user(body: UserIn, request: Request, user: User = Depends(ADMIN), db: Session = Depends(get_db)):
    oid = body.org_id if (body.org_id and user.has("super_admin")) else user.org_id
    roles = _staff_roles(user, body.roles)
    if not roles:
        raise HTTPException(422, "Choose at least one role")
    email = body.email.strip().lower()
    if "@" not in email or " " in email:
        raise HTTPException(422, "Enter a valid email address")
    if not body.name.strip():
        raise HTTPException(422, "Enter the person's name")
    if db.scalar(select(User).where(User.org_id == oid, User.email == email)):
        raise HTTPException(409, "A user with this email already exists in the organisation")
    if not body.password:
        raise HTTPException(422, "Set an initial password")
    _check_password(body.password)
    u = User(id=uid(), org_id=oid, email=email, name=body.name.strip(), password_hash=hash_password(body.password))
    u.roles = [UserRole(role=r) for r in roles]
    db.add(u)
    audit(db, user, "create", "user", u.id, {"roles": roles}, request)
    db.commit()
    return _user_out(u)


@router.put("/users/{uid_}")
def update_user(uid_: str, body: UserIn, request: Request, user: User = Depends(ADMIN), db: Session = Depends(get_db)):
    """Name, email, roles, status, a new password, unlock. Candidates keep their candidate role; only name, status and password change."""
    u = db.get(User, uid_)
    if not u:
        raise HTTPException(404, "User not found")
    same_org(user, u.org_id)
    is_super, candidate = user.has("super_admin"), u.has("candidate")
    if u.has("super_admin") and not is_super:
        raise HTTPException(403, "Only a Super Admin can change a Super Admin")
    roles = [] if candidate else _staff_roles(user, body.roles)
    status = body.status if body.status in ("active", "disabled") else u.status
    if u.id == user.id and (status != "active" or (roles and not set(roles) & {"org_admin", "super_admin"})):
        raise HTTPException(409, "You cannot disable yourself or remove your own admin access. Ask another administrator.")
    if body.password:
        _check_password(body.password)
    email = body.email.strip().lower()
    if email and not candidate and email != u.email:
        if "@" not in email or " " in email:
            raise HTTPException(422, "Enter a valid email address")
        if db.scalar(select(User.id).where(User.org_id == u.org_id, User.email == email, User.id != u.id)):
            raise HTTPException(409, "A user with this email already exists in the organisation")
        u.email = email
    if roles:
        u.roles = [UserRole(role=r) for r in roles]
    u.name = body.name.strip() or u.name
    if status != u.status or body.password:
        _sign_out_everywhere(db, u)
    u.status = status
    if body.password:
        u.password_hash = hash_password(body.password)
    if body.unlock or body.password:
        u.failed_logins = 0
    audit(db, user, "update", "user", u.id, {"roles": roles, "status": u.status, "password_reset": bool(body.password), "unlock": body.unlock}, request)
    db.commit()
    return _user_out(u)


@router.get("/orgs")
def list_orgs(user: User = Depends(SUPER), db: Session = Depends(get_db)):
    out = []
    for o in db.scalars(select(Organization).order_by(Organization.created_at)).all():
        out.append({"id": o.id, "name": o.name, "slug": o.slug, "plan": o.plan, "credits": o.credits,
                    "data_region": o.data_region, "status": o.status,
                    "users": db.scalar(select(func.count(User.id)).where(User.org_id == o.id)),
                    "tests": db.scalar(select(func.count(Test.id)).where(Test.org_id == o.id))})
    return out


@router.post("/orgs")
def create_org(body: OrgIn, request: Request, user: User = Depends(SUPER), db: Session = Depends(get_db)):
    if db.scalar(select(Organization).where(Organization.slug == body.slug)):
        raise HTTPException(409, "Slug already used")
    o = Organization(id=uid(), name=body.name, slug=body.slug, plan=body.plan, credits=body.credits,
                     data_region=body.data_region, status=body.status)
    db.add(o)
    db.flush()
    create_defaults(db, o.id)  # every organisation starts with the standard departments
    audit(db, user, "create", "organization", o.id, request=request)
    db.commit()
    return {"id": o.id}


@router.put("/orgs/{oid}")
def update_org(oid: str, body: OrgIn, request: Request, user: User = Depends(SUPER), db: Session = Depends(get_db)):
    o = db.get(Organization, oid)
    if not o:
        raise HTTPException(404, "Organisation not found")
    o.name, o.plan, o.credits, o.data_region, o.status = body.name, body.plan, body.credits, body.data_region, body.status
    audit(db, user, "update", "organization", o.id, request=request)
    db.commit()
    return {"ok": True}


@router.get("/system/sandboxes")
def sandboxes(refresh: bool = False, user: User = Depends(staff)):
    from app.sandbox.process import network_isolation_prefix
    cat = remote.catalog(refresh)
    env = get_settings().environment.lower()
    return {"languages": cat["languages"], "sql": cat["sql"], "isolated": cat["isolated"], "reachable": cat["reachable"], "environment": env,
            "unsafe_in_production": env == "production" and not cat["isolated"],  # the admin screen shows a red warning
            "network_isolation": bool(network_isolation_prefix()), "os": os.name}


@router.post("/system/sandboxes/selftest")
def selftest(user: User = Depends(staff)):
    try:
        return remote.selftest()
    except remote.Unavailable as e:
        raise HTTPException(503, str(e))


@router.get("/system/audit")
def audit_logs(limit: int = 200, user: User = Depends(ADMIN), db: Session = Depends(get_db)):
    stmt = select(AuditLog).order_by(AuditLog.at.desc()).limit(min(limit, 1000))
    if not user.has("super_admin"):
        stmt = stmt.where(AuditLog.org_id == user.org_id)
    return [{"at": aware(a.at).isoformat(), "actor": a.actor_email, "action": a.action, "entity": a.entity,
             "entity_id": a.entity_id, "detail": a.detail, "ip": a.ip} for a in db.scalars(stmt).all()]


@router.get("/system/outbox")
def outbox(limit: int = 100, user: User = Depends(ADMIN), db: Session = Depends(get_db)):
    stmt = select(MailOutbox).order_by(MailOutbox.created_at.desc()).limit(min(limit, 500))
    if not user.has("super_admin"):
        stmt = stmt.where(MailOutbox.org_id == user.org_id)
    return [{"id": m.id, "to": m.to, "subject": m.subject, "body": m.body, "kind": m.kind, "status": m.status,
             "error": m.error, "created_at": aware(m.created_at).isoformat()} for m in db.scalars(stmt).all()]


@router.get("/system/info")
def info(user: User = Depends(staff)):
    s = get_settings()
    return {"app": s.app_name, "environment": s.environment, "database": "sqlite" if s.is_sqlite else "postgresql",
            "demo_mode": s.demo_mode, "smtp": bool(s.smtp_host), "llm_provider": s.llm_provider,
            "judge_workers": s.judge_workers, "public_base_url": s.public_base_url}
