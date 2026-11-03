"""Results of one exam: calculated automatically after its end time, reviewed by a person, then declared to the candidates."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.tests import _test
from app.core.deps import EVAL, VIEW, audit
from app.db import get_db
from app.models import Answer, Attempt, Evaluation, Test, User, aware, now, uid
from app.services import jobs
from app.services.attempts import recompute_totals
from app.services.reports import ENDED_EARLY, FINAL, candidates_table

router = APIRouter(tags=["results"])


def _active(db: Session, t: Test) -> int:
    return db.scalar(select(func.count(Attempt.id)).where(Attempt.test_id == t.id, Attempt.status.in_(jobs.ACTIVE))) or 0


def _review_by_attempt(db: Session, t: Test) -> dict:
    """Answers waiting for a person (AI unsure, AI failed, no AI, a file instead of text), per attempt."""
    q = (select(Answer.attempt_id, func.count(Answer.id)).join(Attempt, Answer.attempt_id == Attempt.id)
         .where(Attempt.test_id == t.id, Attempt.status.in_(FINAL), Answer.status == "review").group_by(Answer.attempt_id))
    return dict(db.execute(q).all())


def _state(t: Test, attention: int) -> str:
    if t.results_declared_at:
        return "declared"
    if t.calculated_at:
        return "needs_attention" if attention else "ready"
    return "calculating" if t.ends_at and aware(t.ends_at) < now() else "open"


@router.get("/tests/{tid}/results")
def results(tid: str, user: User = Depends(VIEW), db: Session = Depends(get_db)):
    t = _test(db, tid, user)
    review = _review_by_attempt(db, t)
    rows = candidates_table(db, t)
    for r in rows:
        r["attention"] = review.get(r["attempt_id"], 0)
    done = [r for r in rows if r["outcome"] not in ("absent", "in_progress")]
    scored = [r for r in done if r["percent"] is not None]
    attention = sum(review.values())
    return {"state": _state(t, attention), "attention": attention, "active": _active(db, t), "title": t.title, "cutoff": t.cutoff, "ends_at": aware(t.ends_at).isoformat() if t.ends_at else None,
            "calculated_at": aware(t.calculated_at).isoformat() if t.calculated_at else None,
            "declared_at": aware(t.results_declared_at).isoformat() if t.results_declared_at else None,
            "summary": {"assigned": len(rows), "appeared": len(done), "absent": sum(1 for r in rows if r["outcome"] == "absent"),
                        "ended_early": sum(1 for r in done if r["outcome"] in ENDED_EARLY),
                        "passed": sum(1 for r in done if r["below_cutoff"] is False), "failed": sum(1 for r in done if r["below_cutoff"]),
                        "average_percent": round(sum(r["percent"] for r in scored) / len(scored), 1) if scored else 0,
                        "highest": max((r["score"] for r in scored), default=None)},
            "rows": rows}


@router.post("/tests/{tid}/calculate")
def calculate(tid: str, request: Request, user: User = Depends(EVAL), db: Session = Depends(get_db)):
    """For an exam without an end time, or to run the calculation again (a corrected answer key, a retry after the AI was down)."""
    t = _test(db, tid, user)
    if t.status != "published":
        raise HTTPException(409, "Only a published exam has results")
    if n := _active(db, t):
        raise HTTPException(409, f"{n} candidate(s) are still taking the exam or being marked. Wait, or end their exams first.")
    audit(db, user, "calculate_results", "test", t.id, request=request)
    db.commit()
    jobs.calculate_async(t.id)
    return {"started": True}


@router.post("/tests/{tid}/accept-ai")
def accept_ai(tid: str, request: Request, user: User = Depends(EVAL), db: Session = Depends(get_db)):
    """Every answer still waiting for a person that has a suggested mark takes that mark. Answers with no suggestion stay for hand marking."""
    t = _test(db, tid, user)
    if not t.calculated_at:  # before the calculation the suggestion is only the keyword score, without the AI
        raise HTTPException(409, "The results are not calculated yet")
    rows = db.execute(select(Answer, Attempt).join(Attempt, Answer.attempt_id == Attempt.id)
                      .where(Attempt.test_id == t.id, Attempt.status.in_(FINAL), Answer.status == "review")).all()
    touched, accepted = {}, 0
    for a, at in rows:
        suggested = a.ai_score if a.ai_score is not None else a.auto_score
        if suggested is None:
            continue
        a.final_score, a.status = suggested, "final"
        db.add(Evaluation(id=uid(), answer_id=a.id, evaluator_id=user.id, method="manual", score=suggested, override_reason="accepted the suggested mark"))
        touched[at.id] = at
        accepted += 1
    db.flush()
    for at in touched.values():
        recompute_totals(db, at, t)
    audit(db, user, "accept_ai_marks", "test", t.id, {"answers": accepted}, request)
    db.commit()
    return {"accepted": accepted}


class DeclareIn(BaseModel):
    declared: bool = True


@router.post("/tests/{tid}/declare")
def declare(tid: str, body: DeclareIn, request: Request, user: User = Depends(EVAL), db: Session = Depends(get_db)):
    t = _test(db, tid, user)
    if body.declared:
        attention = sum(_review_by_attempt(db, t).values())
        if not t.calculated_at:
            raise HTTPException(409, "The results are not calculated yet")
        if _active(db, t):
            raise HTTPException(409, "Some candidates are still taking the exam or being marked")
        if attention:
            raise HTTPException(409, f"{attention} answer(s) still need your attention. Accept or mark them first.")
        t.results_declared_at = now()
    else:
        t.results_declared_at = None
    audit(db, user, "declare_results" if body.declared else "withdraw_results", "test", t.id, request=request)
    db.commit()
    return {"declared": body.declared}
