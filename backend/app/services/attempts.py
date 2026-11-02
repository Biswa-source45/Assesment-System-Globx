"""Attempt lifecycle: draw questions, candidate payloads, autosave, section timers, submit and grading."""
from __future__ import annotations

import logging
import random
import time
from datetime import timedelta
from typing import Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain import scoring
from app.models import (Answer, Assignment, Attempt, AttemptQuestion, CodeSubmission, Evaluation, Question,
                        QuestionGroup, Section, SectionItem, Test, aware, now, uid)
from app.sandbox.languages import get_language
from app.sandbox.sql import SQL_ENGINES, describe_tables
from app.services import ai

log = logging.getLogger("oap.attempts")
GRACE_S = 5
SUBJECTIVE = ("short", "long")
CODELIKE = ("coding", "sql")


# ------------------------------------------------------------------ drawing
def _pool_questions(db: Session, org_id: str, pool: Dict, rng: random.Random, exclude: set) -> List[Question]:
    flt = pool.get("filter", {}) or {}
    stmt = select(Question).where(Question.org_id == org_id, Question.status == "approved",
                                  Question.group_id.is_(None))
    if flt.get("types"):
        stmt = stmt.where(Question.type.in_(flt["types"]))
    cand = [q for q in db.scalars(stmt).all() if q.id not in exclude]
    skills = set(flt.get("skills") or [])
    if skills:
        cand = [q for q in cand if skills & set(q.skills or [])]
    draw = int(pool.get("draw") or 0)
    mix = pool.get("mix") or {}
    picked: List[Question] = []
    if mix:
        for diff, n in mix.items():
            opts = [q for q in cand if q.difficulty == diff and q not in picked]
            rng.shuffle(opts)
            picked += opts[: int(n)]
    rest = [q for q in cand if q not in picked]
    rng.shuffle(rest)
    picked += rest[: max(0, draw - len(picked))]
    return picked[:draw] if draw else picked


def draw_questions(db: Session, test: Test, attempt: Attempt) -> List[AttemptQuestion]:
    rng = random.Random(attempt.seed)
    rows: List[AttemptQuestion] = []
    used: set = set()
    for sec in test.sections:
        blocks: List[List[tuple]] = []
        for it in sec.items:
            mo, no = it.marks_override, it.negative_override
            if it.kind == "question" and it.question_id:
                q = db.get(Question, it.question_id)
                if q and q.id not in used:
                    blocks.append([(q, mo, no)])
                    used.add(q.id)
            elif it.kind == "group" and it.group_id:
                g = db.get(QuestionGroup, it.group_id)
                qs = [q for q in (g.questions if g else []) if q.status != "archived" and q.id not in used]
                if qs:
                    blocks.append([(q, mo, no) for q in qs])
                    used.update(q.id for q in qs)
            elif it.kind == "pool" and it.pool:
                for q in _pool_questions(db, test.org_id, it.pool, rng, used):
                    blocks.append([(q, mo, no)])
                    used.add(q.id)
        if test.shuffle_questions and sec.shuffle:
            rng.shuffle(blocks)
        order = 0
        for b in blocks:
            for q, mo, no in b:
                opts = [o["id"] for o in (q.config.get("options") or [])]
                if test.shuffle_options and q.type.startswith("mcq"):
                    rng.shuffle(opts)
                rows.append(AttemptQuestion(attempt_id=attempt.id, section_id=sec.id, question_id=q.id, order=order,
                                            option_order=opts, marks=float(mo if mo is not None else q.marks),
                                            negative=float(no if no is not None else q.negative_marks)))
                order += 1
    return rows


def start_attempt(db: Session, asg: Assignment, test: Test, ip: str, ua: str, consent: Dict, check: Dict) -> Attempt:
    t = now()
    dur = timedelta(minutes=test.duration_min + (asg.extra_time_min or 0))
    deadline = t + dur
    if test.ends_at and aware(test.ends_at) < deadline:
        deadline = max(aware(test.ends_at), t + timedelta(minutes=1))
    at = Attempt(id=uid(), assignment_id=asg.id, test_id=test.id, candidate_id=asg.candidate_id, started_at=t,
                 deadline_at=deadline, seed=random.randint(1, 2 ** 31 - 1), ip=ip, user_agent=ua[:300],
                 consent=consent, system_check=check, section_state={})
    db.add(at)
    db.flush()
    rows = draw_questions(db, test, at)
    if not rows:
        raise HTTPException(400, "This test has no questions")
    db.add_all(rows)
    at.max_score = scoring.r2(sum(r.marks for r in rows))
    asg.status = "in_progress"
    return at


# ------------------------------------------------------------------ candidate payloads (no answer keys!)
def candidate_question(aq: AttemptQuestion, db: Session) -> Dict:
    q = aq.question
    c = q.config or {}
    out = {"id": q.id, "type": q.type, "title": q.title, "body": q.body, "difficulty": q.difficulty,
           "skills": q.skills, "marks": aq.marks, "negative": aq.negative, "section_id": aq.section_id,
           "order": aq.order}
    if q.group_id:
        g = db.get(QuestionGroup, q.group_id)
        out["group"] = {"id": g.id, "title": g.title, "stimulus": g.stimulus} if g else None
    if q.type.startswith("mcq"):
        by_id = {o["id"]: o for o in c.get("options", [])}
        out["options"] = [{"id": oid, "text": by_id[oid]["text"]} for oid in aq.option_order if oid in by_id]
        out["multi"] = q.type == "mcq_multi"
        out["partial"] = bool(c.get("partial", True))
    elif q.type in SUBJECTIVE:
        out.update({"min_words": c.get("min_words", 0), "max_words": c.get("max_words", 150 if q.type == "short" else 800),
                    "allow_file": bool(c.get("allow_file", q.type == "long"))})
        if c.get("show_rubric", True) and c.get("rubric"):
            out["rubric"] = [{"name": r.get("name"), "max": r.get("max")} for r in c["rubric"]]
    elif q.type == "coding":
        langs = [k for k in (c.get("languages") or []) if (get_language(k) and get_language(k).available())]
        out.update({"languages": [{"key": k, "name": get_language(k).name} for k in langs],
                    "starter": {k: (c.get("starter") or {}).get(k, "") for k in langs},
                    "time_limit_ms": c.get("time_limit_ms", 2000), "memory_mb": c.get("memory_mb", 256),
                    "open_cases": [{"ordinal": t.ordinal, "input": t.input, "expected": t.expected, "weight": t.weight}
                                   for t in q.cases if t.visibility == "open"],
                    "hidden_weights": [t.weight for t in q.cases if t.visibility == "hidden"]})
    elif q.type == "sql":
        import json
        engines = [e for e in (c.get("engines") or ["sqlite"]) if SQL_ENGINES.get(e) and SQL_ENGINES[e].available()]
        out.update({"schema": c.get("schema", ""), "seed": c.get("seed", ""), "ordered": bool(c.get("ordered")),
                    "engines": [{"key": e, "name": SQL_ENGINES[e].name} for e in engines],
                    "open_cases": [{"ordinal": t.ordinal, "input": t.input,
                                    "expected": json.loads(t.expected or "{}"), "weight": t.weight,
                                    "tables": describe_tables(c.get("schema", ""), c.get("seed", ""), t.input)}
                                   for t in q.cases if t.visibility == "open"],
                    "hidden_weights": [t.weight for t in q.cases if t.visibility == "hidden"]})
    return out


def content_version(db: Session, at: Attempt) -> int:
    """Changes whenever the examiner saves any question of this attempt (every save adds one to the question's version).
    The exam page compares it on each clock check and reloads the questions when it moves."""
    return int(db.scalar(select(func.coalesce(func.sum(Question.version), 0)).join(AttemptQuestion, AttemptQuestion.question_id == Question.id)
                         .where(AttemptQuestion.attempt_id == at.id)) or 0)


def sync_live_attempts(db: Session, q: Question) -> None:
    """The examiner edited a question: candidates taking an exam right now get its current marks and options (the text is read live).
    An exam's own marks override still wins. Attempts that are already finished keep what they were graded with."""
    rows = db.scalars(select(AttemptQuestion).join(Attempt, Attempt.id == AttemptQuestion.attempt_id)
                      .where(AttemptQuestion.question_id == q.id, Attempt.status == "in_progress")).all()
    ids = [o["id"] for o in (q.config or {}).get("options") or []] if q.type.startswith("mcq") else None
    for aq in rows:
        items = db.scalars(select(SectionItem).where(SectionItem.section_id == aq.section_id)).all()
        mine = [i for i in items if i.question_id == q.id or (i.group_id and i.group_id == q.group_id)] or [i for i in items if i.kind == "pool"]
        mo, no = (mine[0].marks_override, mine[0].negative_override) if mine else (None, None)
        aq.marks, aq.negative = float(mo if mo is not None else q.marks), float(no if no is not None else q.negative_marks)
        if ids is not None:  # a new option appears at the end of this candidate's order, a removed one disappears
            aq.option_order = [i for i in aq.option_order if i in ids] + [i for i in ids if i not in aq.option_order]
    db.flush()
    for aid in {aq.attempt_id for aq in rows}:
        db.get(Attempt, aid).max_score = scoring.r2(sum(float(r.marks) for r in db.scalars(select(AttemptQuestion).where(AttemptQuestion.attempt_id == aid))))


def attempt_state(db: Session, at: Attempt, test: Test) -> Dict:
    aqs = db.scalars(select(AttemptQuestion).where(AttemptQuestion.attempt_id == at.id)
                     .order_by(AttemptQuestion.order)).all()
    answers = {a.question_id: a for a in db.scalars(select(Answer).where(Answer.attempt_id == at.id)).all()}
    secs = []
    for s in test.sections:
        qs = [aq for aq in aqs if aq.section_id == s.id]
        if not qs:
            continue
        st = (at.section_state or {}).get(s.id, {})
        secs.append({"id": s.id, "title": s.title, "timer_min": s.timer_min, "lock_nav": s.lock_nav,
                     "marks": scoring.r2(sum(q.marks for q in qs)), "count": len(qs),
                     "deadline": st.get("deadline"), "closed": bool(st.get("closed")),
                     "questions": [candidate_question(aq, db) for aq in qs]})
    return {"attempt": {"id": at.id, "status": at.status, "started_at": aware(at.started_at).isoformat(),
                        "deadline_at": aware(at.deadline_at).isoformat(), "server_time": now().isoformat(),
                        "risk_level": at.risk_level, "violations": at.violations,
                        "max_score": at.max_score, "content_version": content_version(db, at)},
            "test": {"id": test.id, "title": test.title, "instructions": test.instructions,
                     "proctoring": proctoring_config(test)},
            "sections": secs,
            "answers": {qid: {"response": a.response, "flagged": a.flagged, "seq": a.seq,
                              "saved_at": aware(a.saved_at).isoformat()} for qid, a in answers.items()}}


def proctoring_config(test: Test) -> Dict:
    p = dict((test.settings or {}).get("proctoring") or {})
    p.setdefault("enabled", True)
    p.setdefault("webcam", True)
    p.setdefault("snapshot_seconds", 15)
    p.setdefault("fullscreen", True)
    p.setdefault("tab_switch_limit", 3)    # leaves allowed; the next one terminates the exam
    p.setdefault("face_limit", 5)          # face incidents; this one terminates and bans
    p.setdefault("face_min_seconds", 3)    # no/extra face must last this long to count as an incident
    p.setdefault("limit_action", "submit")
    p.setdefault("block_paste", True)
    p.setdefault("screen_capture", False)
    p.setdefault("screenshot_seconds", 60)
    p.setdefault("audio", True)
    p.setdefault("block_multi_display", True)
    p.setdefault("weights", {})
    return p


def terminate_attempt(db: Session, at: Attempt, reason: str) -> None:
    """Stop the exam now because of a violation. Grading follows in the background (jobs.finalize_async).
    reason 'face_violation' bans the login: assignment 'banned' until an admin resets it."""
    at.status, at.submitted_at, at.submit_reason = "auto_submitted", now(), reason
    asg = db.get(Assignment, at.assignment_id)
    if asg:
        asg.status = "banned" if reason == "face_violation" else "test_taken"


# ------------------------------------------------------------------ autosave & timers
def ensure_active(at: Attempt) -> None:
    if at.status != "in_progress":
        raise HTTPException(423, "This attempt is already submitted")
    if now() > aware(at.deadline_at) + timedelta(seconds=GRACE_S):
        raise HTTPException(423, "Time is over")


def enter_section(db: Session, at: Attempt, test: Test, section_id: str) -> Dict:
    ensure_active(at)
    state = dict(at.section_state or {})
    sec = next((s for s in test.sections if s.id == section_id), None)
    if not sec:
        raise HTTPException(404, "Section not found")
    if state.get(section_id, {}).get("closed"):
        raise HTTPException(403, "This section is closed")
    for sid, st in state.items():
        other = next((s for s in test.sections if s.id == sid), None)
        if sid != section_id and other and other.lock_nav and st.get("started_at") and not st.get("closed"):
            st["closed"] = True
    st = state.get(section_id) or {}
    if not st.get("started_at"):
        st["started_at"] = now().isoformat()
        if sec.timer_min:
            dl = min(now() + timedelta(minutes=sec.timer_min), aware(at.deadline_at))
            st["deadline"] = dl.isoformat()
    state[section_id] = st
    at.section_state = state
    return st


def _section_open(at: Attempt, section_id: str) -> bool:
    from datetime import datetime
    st = (at.section_state or {}).get(section_id, {})
    if st.get("closed"):
        return False
    if st.get("deadline"):
        return now() <= datetime.fromisoformat(st["deadline"]) + timedelta(seconds=GRACE_S)
    return True


def save_answer(db: Session, at: Attempt, question_id: str, response: Dict, flagged: bool, seq: int) -> Answer:
    ensure_active(at)
    aq = db.scalar(select(AttemptQuestion).where(AttemptQuestion.attempt_id == at.id,
                                                 AttemptQuestion.question_id == question_id))
    if not aq:
        raise HTTPException(404, "Question is not part of this attempt")
    if not _section_open(at, aq.section_id):
        raise HTTPException(403, "This section is closed")
    a = db.scalar(select(Answer).where(Answer.attempt_id == at.id, Answer.question_id == question_id))
    if a and seq and a.seq and seq < a.seq:
        raise HTTPException(409, "A newer version of this answer is already saved")
    if not a:
        a = Answer(id=uid(), attempt_id=at.id, question_id=question_id)
        db.add(a)
    resp = dict(response or {})
    if aq.question.type in SUBJECTIVE and "html" in resp:
        from app.services.sanitize import sanitize_html
        resp["html"] = sanitize_html(resp.get("html", ""))[:60000]
    if aq.question.type in CODELIKE and a.response:
        # keep server-side best submission pointer
        for k in ("best_submission_id", "best_score"):
            if k in (a.response or {}):
                resp[k] = a.response[k]
    a.response = resp
    a.flagged = bool(flagged)
    if seq:
        a.seq = max(seq, a.seq or 0)
    a.saved_at = now()
    return a


# ------------------------------------------------------------------ grading
def _text_of(resp: Dict) -> str:
    import re
    html = (resp or {}).get("html") or (resp or {}).get("text") or ""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def grade_answer(db: Session, aq: AttemptQuestion, a: Optional[Answer], use_ai: bool = True) -> Answer:
    q = aq.question
    c = q.config or {}
    if a is None:
        a = Answer(id=uid(), attempt_id=aq.attempt_id, question_id=q.id, response={})
        db.add(a)
    if a.id is None:
        a.id = uid()
    resp = a.response or {}
    flags: List[str] = []
    if q.type.startswith("mcq"):
        opts = [o["id"] for o in c.get("options", [])]
        correct = [o["id"] for o in c.get("options", []) if o.get("correct")]
        sc = scoring.score_mcq(resp.get("selected") or [], correct, opts, aq.marks, aq.negative,
                               q.type == "mcq_multi", bool(c.get("partial", True)))
        a.auto_score = a.final_score = sc
        a.status = "final"
        db.add(Evaluation(answer_id=a.id, method="auto", score=sc))
    elif q.type in CODELIKE:
        subs = db.scalars(select(CodeSubmission).where(CodeSubmission.attempt_id == aq.attempt_id,
                                                       CodeSubmission.question_id == q.id,
                                                       CodeSubmission.kind == "submit",
                                                       CodeSubmission.status == "done")).all()
        best = None
        for s in subs:
            scaled = (s.score or 0) / (s.max_score or 1) * aq.marks if s.max_score else 0
            if best is None or scaled > best[0] or (scaled == best[0] and s.created_at > best[1].created_at):
                best = (scaled, s)
        if best:
            sc = scoring.r2(best[0])
            flags = list(best[1].result.get("flags", []))
            resp = {**resp, "best_submission_id": best[1].id, "best_score": sc, "language": best[1].language}
            a.response = resp
        else:
            sc = 0.0
            if (resp.get("source") or "").strip():
                flags.append("not_submitted")
        a.auto_score = a.final_score = sc
        a.status = "final"
        db.add(Evaluation(answer_id=a.id, method="auto", score=sc, rationale=", ".join(flags)))
    elif q.type in SUBJECTIVE:
        text = _text_of(resp)
        has_file = bool(resp.get("files"))
        if not text and not has_file:
            a.auto_score = a.final_score = 0.0
            a.status = "final"
            db.add(Evaluation(answer_id=a.id, method="auto", score=0, rationale="No answer"))
        elif q.type == "short":
            cov = scoring.keyword_coverage(text, c.get("keywords") or [])
            semantic, conf, rationale = None, None, ""
            if use_ai and ai.llm_enabled() and c.get("model_answer"):
                try:
                    r = ai.ai_semantic_similarity(_text_of({"html": q.body}), c["model_answer"], text)
                    semantic, conf, rationale = r["similarity"], r["confidence"], r["rationale"]
                except Exception as e:
                    rationale = f"AI unavailable: {e}"
            sc = scoring.score_short(aq.marks, cov, semantic)
            a.auto_score = scoring.quarter(aq.marks * cov)
            a.ai_score = sc if semantic is not None else None
            a.ai_confidence, a.ai_rationale = conf, rationale
            a.ai_detail = {"keyword_coverage": round(cov, 3), "semantic": semantic}
            if semantic is not None and (conf or 0) >= 0.7:
                a.final_score, a.status = sc, "final"
                db.add(Evaluation(answer_id=a.id, method="ai", score=sc, rationale=rationale))
            else:
                a.final_score, a.status = None, "review"
        else:  # long
            rub = c.get("rubric") or ([{"id": "overall", "name": "Correct and complete compared with the model answer",
                                        "max": aq.marks}] if c.get("model_answer") else [])
            if use_ai and ai.llm_enabled() and rub and text:
                try:
                    r = ai.ai_rubric_score(_text_of({"html": q.body}), c.get("model_answer", ""), rub, text)
                    a.ai_score = min(aq.marks, scoring.score_rubric(rub, r["scores"]))
                    a.ai_confidence, a.ai_rationale = r["confidence"], r["rationale"]
                    a.ai_detail = {"rubric_scores": r["scores"], "provider": r.get("provider")}
                except Exception as e:
                    a.ai_rationale = f"AI unavailable: {e}"
            a.final_score, a.status = None, "review"   # evaluator confirmation is mandatory
    a.flags = flags
    return a


def recompute_totals(db: Session, at: Attempt, test: Optional[Test] = None) -> None:
    test = test or db.get(Test, at.test_id)
    aqs = db.scalars(select(AttemptQuestion).where(AttemptQuestion.attempt_id == at.id)).all()
    answers = {a.question_id: a for a in db.scalars(select(Answer).where(Answer.attempt_id == at.id)).all()}
    per_sec: Dict[str, List[float]] = {}
    pending = False
    for aq in aqs:
        a = answers.get(aq.question_id)
        if a is None:
            v = 0.0
        elif a.status == "final" and a.final_score is not None:
            v = a.final_score
        else:
            pending = True
            v = a.ai_score if a.ai_score is not None else (a.auto_score or 0.0)
        per_sec.setdefault(aq.section_id, []).append(float(v))
    allow = {s.id: s.allow_negative for s in test.sections}
    sec_scores = scoring.aggregate_sections(per_sec, allow)
    at.section_scores = sec_scores
    at.total_score = scoring.r2(sum(sec_scores.values()))
    below = at.total_score < float(test.cutoff or 0)
    for s in test.sections:
        if s.min_score is not None and sec_scores.get(s.id, 0) < float(s.min_score):
            below = True
    at.below_cutoff = below
    if at.status in ("submitted", "auto_submitted", "evaluating", "review_pending", "evaluated"):
        at.status = "review_pending" if pending else "evaluated"
        asg = db.get(Assignment, at.assignment_id)
        if asg and asg.status not in ("shortlisted", "archived", "banned"):
            asg.status = "review_pending" if pending else "evaluated"


def finalize_attempt(db: Session, attempt_id: str, reason: str = "submitted", wait_code_s: int = 120) -> None:
    """Close an attempt and grade it. Safe to call more than once."""
    at = db.get(Attempt, attempt_id)
    if not at or at.status not in ("in_progress", "submitted", "auto_submitted"):
        return
    if at.status == "in_progress":
        at.status = "auto_submitted" if reason != "submitted" else "submitted"
        at.submitted_at = now()
        at.submit_reason = reason
        asg = db.get(Assignment, at.assignment_id)
        if asg:
            asg.status = "test_taken"
        db.commit()
    t_end = time.time() + wait_code_s
    while time.time() < t_end:
        pend = db.scalars(select(CodeSubmission.id).where(CodeSubmission.attempt_id == at.id,
                                                          CodeSubmission.status.in_(["queued", "running"]))).all()
        if not pend:
            break
        time.sleep(0.5)
        db.expire_all()
    at = db.get(Attempt, attempt_id)
    at.status = "evaluating"
    db.commit()
    test = db.get(Test, at.test_id)
    aqs = db.scalars(select(AttemptQuestion).where(AttemptQuestion.attempt_id == at.id)).all()
    answers = {a.question_id: a for a in db.scalars(select(Answer).where(Answer.attempt_id == at.id)).all()}
    for aq in aqs:
        a = answers.get(aq.question_id)
        if a is None:
            a = Answer(id=uid(), attempt_id=at.id, question_id=aq.question_id, response={})
            db.add(a)
            db.flush()
        grade_answer(db, aq, a)
    db.flush()
    at.status = "submitted"
    recompute_totals(db, at, test)
    db.commit()
