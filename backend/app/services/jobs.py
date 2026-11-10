"""In-process background work (replaces Redis/Celery for the no-Docker MVP).

* JUDGE pool  - code / SQL submissions (Run > Submit priority via separate pools)
* BG pool     - grading, plagiarism, mail
* sweeper     - every 10 s: auto-submit expired attempts, deliver mail, scheduled invites, reminders, expiries
"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Optional

from sqlalchemy import func, select

from app.core.config import get_settings
from app.db import SessionLocal
from app.models import (Answer, Assignment, Attempt, CodeSubmission, Question, Test, aware, now)

log = logging.getLogger("oap.jobs")
_s = get_settings()
RUN_POOL = ThreadPoolExecutor(max_workers=max(1, _s.judge_workers), thread_name_prefix="judge-run")
SUBMIT_POOL = ThreadPoolExecutor(max_workers=max(1, _s.judge_workers), thread_name_prefix="judge-submit")
BG = ThreadPoolExecutor(max_workers=2, thread_name_prefix="bg")
_stop = threading.Event()
_sweeper: Optional[threading.Thread] = None
_plag_pending: set = set()
_plag_lock = threading.Lock()
_last_purge = 0.0  # recorded video is checked for deletion about once an hour
_calc_running: set = set()  # exams being calculated right now, so the sweeper does not start a second run
ACTIVE = ("in_progress", "submitted", "auto_submitted", "evaluating")  # an attempt in any of these is not finished yet


def _cases_of(q: Question):
    return [{"id": c.id, "ordinal": c.ordinal, "visibility": c.visibility, "input": c.input or "",
             "expected": c.expected or "", "weight": float(c.weight)} for c in q.cases]


def run_code_submission(sub_id: str) -> None:
    from app.sandbox.judge import judge_code, judge_sql
    db = SessionLocal()
    try:
        sub = db.get(CodeSubmission, sub_id)
        if not sub or sub.status not in ("queued", "running"):
            return
        sub.status = "running"
        db.commit()
        q = db.get(Question, sub.question_id)
        cfg = q.config or {}
        try:
            if q.type == "sql":
                res = judge_sql(cfg, _cases_of(q), sub.language, sub.source, sub.kind)
            else:
                res = judge_code(cfg, _cases_of(q), sub.language, sub.source, sub.kind, sub.custom_input)
        except Exception as e:  # internal error -> visible, retriable
            log.exception("judge failed")
            res = {"status": "error", "error": f"Internal judge error: {e}"}
        sub.result = res
        sub.status = "done" if res.get("status") == "done" else "error"
        sub.score = res.get("score")
        sub.max_score = res.get("max_score")
        sub.finished_at = now()
        if sub.kind == "submit" and sub.attempt_id and sub.status == "done":
            a = db.scalar(select(Answer).where(Answer.attempt_id == sub.attempt_id, Answer.question_id == q.id))
            if a:
                r = dict(a.response or {})
                scaled = (sub.score or 0) / (sub.max_score or 1)
                if r.get("best_ratio") is None or scaled >= r.get("best_ratio", 0):
                    r.update({"best_submission_id": sub.id, "best_ratio": scaled})
                a.response = r
        db.commit()
    finally:
        db.close()


def enqueue_submission(sub: CodeSubmission) -> None:
    (RUN_POOL if sub.kind == "run" else SUBMIT_POOL).submit(run_code_submission, sub.id)


def finalize_async(attempt_id: str, reason: str = "submitted") -> None:
    BG.submit(_finalize_job, attempt_id, reason)


def _finalize_job(attempt_id: str, reason: str) -> None:
    from app.services.attempts import finalize_attempt
    from app.services.mail import queue_mail
    db = SessionLocal()
    try:
        finalize_attempt(db, attempt_id, reason)
        at = db.get(Attempt, attempt_id)
        if at:
            test = db.get(Test, at.test_id)
            from app.models import User
            u = db.get(User, at.candidate_id)
            if u and test:
                queue_mail(db, u.email, f"Submission received - {test.title}",
                           f"Dear {u.name or u.email},\n\nYour answers for '{test.title}' were received at "
                           f"{aware(at.submitted_at).strftime('%d %b %Y %H:%M UTC') if at.submitted_at else ''}.\n\n"
                           "Thank you.\nAPTIVON by GLOBX", "receipt", test.org_id)
                db.commit()
            schedule_plagiarism(at.test_id)
    except Exception:
        log.exception("finalize failed for %s", attempt_id)
    finally:
        db.close()


def calculate_async(test_id: str) -> None:
    with _plag_lock:
        if test_id in _calc_running:
            return
        _calc_running.add(test_id)
    BG.submit(_calculate_job, test_id)


def _calculate_job(test_id: str) -> None:
    from app.services.attempts import calculate_exam
    db = SessionLocal()
    try:
        calculate_exam(db, db.get(Test, test_id))
    except Exception:
        log.exception("calculation failed for %s", test_id)  # calculated_at stays empty: the sweeper tries again
    finally:
        db.close()
        with _plag_lock:
            _calc_running.discard(test_id)


def schedule_plagiarism(test_id: str, delay: float = 3.0) -> None:
    with _plag_lock:
        if test_id in _plag_pending:
            return
        _plag_pending.add(test_id)

    def job():
        time.sleep(delay)
        with _plag_lock:
            _plag_pending.discard(test_id)
        from app.services.plagiarism import run_for_test
        db = SessionLocal()
        try:
            run_for_test(db, test_id)
        except Exception:
            log.exception("plagiarism failed for %s", test_id)
        finally:
            db.close()
    BG.submit(job)


def sweep_once() -> None:
    from app.services.mail import deliver_pending, queue_mail
    db = SessionLocal()
    try:
        t = now()
        # 1. auto-submit attempts whose time is over
        for at in db.scalars(select(Attempt).where(Attempt.status == "in_progress")).all():
            if aware(at.deadline_at) + timedelta(seconds=20) < t:
                finalize_async(at.id, "time_over")
        # 1b. an exam whose end time has passed and in which nobody is still working or being marked: calculate it
        for test in db.scalars(select(Test).where(Test.status == "published", Test.ends_at.is_not(None), Test.ends_at < t, Test.calculated_at.is_(None))).all():
            if not db.scalar(select(func.count(Attempt.id)).where(Attempt.test_id == test.id, Attempt.status.in_(ACTIVE))):
                calculate_async(test.id)
        # 1c. video older than its exam's retention days is deleted
        global _last_purge
        if time.time() - _last_purge > 3600:
            _last_purge = time.time()
            from app.services.proctoring import purge_recordings
            purge_recordings(db)
        # 2. scheduled invites
        for a in db.scalars(select(Assignment).where(Assignment.sent_at.is_(None),
                                                     Assignment.scheduled_at.is_not(None))).all():
            if aware(a.scheduled_at) <= t:
                from app.services.invites import send_invite_mail
                send_invite_mail(db, a, token=None)
        # 3. expiries and reminders
        for a in db.scalars(select(Assignment).where(Assignment.status == "invited",
                                                     Assignment.expires_at.is_not(None))).all():
            exp = aware(a.expires_at)
            if exp < t:
                a.status = "expired"
                continue
            left = (exp - t).total_seconds()
            if a.sent_at and ((a.reminders_sent == 0 and left < 24 * 3600) or (a.reminders_sent == 1 and left < 2 * 3600)):
                test = db.get(Test, a.test_id)
                queue_mail(db, a.candidate.email, f"Reminder: {test.title} closes soon",
                           f"Dear {a.candidate.name or a.candidate.email},\n\nYour assessment '{test.title}' expires on "
                           f"{exp.strftime('%d %b %Y %H:%M UTC')}. Please use the link in your invitation email.\n\n"
                           "APTIVON by GLOBX", "reminder", test.org_id)
                a.reminders_sent += 1
        db.commit()
        deliver_pending(db)
    except Exception:
        log.exception("sweeper iteration failed")
    finally:
        db.close()


def _sweeper_loop() -> None:
    while not _stop.wait(10):
        sweep_once()


def start_background() -> None:
    global _sweeper
    # resume submissions interrupted by a restart
    db = SessionLocal()
    try:
        for sub in db.scalars(select(CodeSubmission).where(CodeSubmission.status.in_(["queued", "running"]))).all():
            sub.status = "queued"
            db.commit()
            enqueue_submission(sub)
        for at in db.scalars(select(Attempt).where(Attempt.status.in_(["submitted", "auto_submitted", "evaluating"]))).all():
            if at.status == "evaluating":
                at.status = "submitted"
                db.commit()
            finalize_async(at.id, at.submit_reason or "submitted")
    finally:
        db.close()
    if _sweeper is None or not _sweeper.is_alive():
        _stop.clear()
        _sweeper = threading.Thread(target=_sweeper_loop, name="sweeper", daemon=True)
        _sweeper.start()


def stop_background() -> None:
    _stop.set()
