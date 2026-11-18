"""Results of one exam: calculated automatically after its end time, reviewed by a person, then declared to the candidates."""
from __future__ import annotations

import io
import re
import zipfile
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.tests import _test
from app.core.config import get_settings
from app.core.deps import EVAL, ROLE_GROUPS, VIEW, audit, current_user, same_org
from app.core.paging import limit_q, offset_q, page_rows
from app.db import get_db
from app.models import Answer, Attempt, Evaluation, Test, User, aware, now, uid
from app.services import jobs
from app.services.analytics import attempt_analytics, progress
from app.services.attempts import recompute_totals
from app.services.report_card import card_data, card_pdf, file_name, is_real_email, mail_states, queue_report_cards, visible_to_candidate
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
def results(tid: str, q: Optional[str] = None, limit: Optional[int] = Depends(limit_q), offset: int = Depends(offset_q),
            user: User = Depends(VIEW), db: Session = Depends(get_db)):
    """The summary always covers everyone; `rows` is the whole table, or with ?limit=&offset= (and q to search) one page of it, `total` the rows that match.
    ?limit=0 is the summary alone."""
    t = _test(db, tid, user)
    review = _review_by_attempt(db, t)
    rows = candidates_table(db, t)
    for r in rows:
        r["attention"] = review.get(r["attempt_id"], 0)
    done = [r for r in rows if r["outcome"] not in ("absent", "in_progress")]
    scored = [r for r in done if r["percent"] is not None]
    attention = sum(review.values())
    states, mail_error = mail_states(db, t, [r["attempt_id"] for r in rows if r["attempt_id"]])
    for r in done:
        r["mail"] = "no_email" if not is_real_email(r["email"]) else states.get(r["attempt_id"], "")
    mail = {k: sum(1 for r in done if r.get("mail") == k) for k in ("sent", "queued", "failed", "logged", "no_email")}
    page, total = page_rows(rows, q, limit, offset)
    return {"state": _state(t, attention), "attention": attention, "active": _active(db, t), "title": t.title, "cutoff": t.cutoff, "ends_at": aware(t.ends_at).isoformat() if t.ends_at else None,
            "calculated_at": aware(t.calculated_at).isoformat() if t.calculated_at else None,
            "declared_at": aware(t.results_declared_at).isoformat() if t.results_declared_at else None,
            "summary": {"assigned": len(rows), "appeared": len(done), "absent": sum(1 for r in rows if r["outcome"] == "absent"),
                        "ended_early": sum(1 for r in done if r["outcome"] in ENDED_EARLY),
                        "passed": sum(1 for r in done if r["result"] == "passed"), "failed": sum(1 for r in done if r["result"] == "not_passed"),
                        "not_attempted": sum(1 for r in done if r["result"] == "not_attempted"),
                        "average_percent": round(sum(r["percent"] for r in scored) / len(scored), 1) if scored else 0,
                        "highest": max((r["score"] for r in scored), default=None)},
            "mail": {**mail, "error": mail_error, "smtp": bool(get_settings().smtp_host), "shared": bool((t.settings or {}).get("show_result_to_candidate", True))},
            "rows": page, "total": total}


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
        mails = queue_report_cards(db, t)  # each candidate with a real e-mail address gets the report card as a PDF
    else:
        t.results_declared_at, mails = None, {}
    audit(db, user, "declare_results" if body.declared else "withdraw_results", "test", t.id, mails, request=request)
    db.commit()
    return {"declared": body.declared, "mails": mails}


@router.post("/tests/{tid}/email-report-cards")
def email_report_cards(tid: str, request: Request, user: User = Depends(EVAL), db: Session = Depends(get_db)):
    """After declaring: mail the report card to those who have not got it (and again to those whose mail failed)."""
    t = _test(db, tid, user)
    if not t.results_declared_at:
        raise HTTPException(409, "Declare the results first")
    if not (t.settings or {}).get("show_result_to_candidate", True):
        raise HTTPException(409, "This exam does not share its results with candidates")
    mails = queue_report_cards(db, t)
    audit(db, user, "email_report_cards", "test", t.id, mails, request=request)
    db.commit()
    return mails


# ------------------------------------------------------------------ the report card: for the candidate (once declared) and for staff (any time)
def _card_attempt(db: Session, user: User, atid: str) -> Attempt:
    at = db.get(Attempt, atid)
    if not at:
        raise HTTPException(404, "Report card not found")
    t = db.get(Test, at.test_id)
    if at.candidate_id == user.id:
        if t.status == "archived":
            raise HTTPException(404, "Report card not found")
        if reason := visible_to_candidate(t, at):
            raise HTTPException(409, reason)
    elif user.has("super_admin", *ROLE_GROUPS["view"]):
        same_org(user, t.org_id)
        if at.status not in FINAL:
            raise HTTPException(409, "This candidate has no result yet")
    else:
        raise HTTPException(404, "Report card not found")
    return at


@router.get("/attempts/{atid}/report-card")
def report_card(atid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return card_data(db, _card_attempt(db, user, atid))


@router.get("/attempts/{atid}/report-card.pdf")
def report_card_pdf(atid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    d = card_data(db, _card_attempt(db, user, atid))
    return Response(card_pdf(d), media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{file_name(d)}"'})


@router.get("/attempts/{atid}/analytics")
def attempt_analytics_route(atid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """One candidate against the class: the candidate for their own declared result, staff for any finished attempt. Same gate as the report card."""
    return attempt_analytics(db, _card_attempt(db, user, atid))


@router.get("/me/progress")
def my_progress(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return progress(db, user)


@router.get("/tests/{tid}/report-cards.zip")
def report_cards_zip(tid: str, user: User = Depends(VIEW), db: Session = Depends(get_db)):
    """Every finished candidate's report card in one file (a preview before the results are declared, too)."""
    t = _test(db, tid, user)
    attempts = db.scalars(select(Attempt).where(Attempt.test_id == t.id, Attempt.status.in_(FINAL)).order_by(Attempt.started_at)).all()
    if not attempts:
        raise HTTPException(409, "No candidate has a result yet")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for i, at in enumerate(attempts, 1):
            d = card_data(db, at)
            z.writestr(f"{i:03d}-{file_name(d)}", card_pdf(d))
    name = re.sub(r"[^A-Za-z0-9]+", "-", t.title).strip("-")[:50] or "exam"
    return Response(buf.getvalue(), media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="report-cards-{name}.zip"'})
