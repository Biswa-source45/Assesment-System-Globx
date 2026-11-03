"""Candidate report, test analytics and exports (SRS FR-REP)."""
from __future__ import annotations

import csv
import io
from collections import Counter
from typing import Dict, List

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.risk import BAND
from app.domain.scoring import rank_key
from app.models import (Answer, Assignment, Attempt, AttemptQuestion, CodeSubmission, ProctorEvent, ProctorSnapshot,
                        Question, Test, User, aware, now)
from app.services.attempts import _text_of, proctoring_config
from app.services.plagiarism import candidate_summary

FINAL = ("review_pending", "evaluated")
OUTCOME_LABEL = {"submitted": "Submitted", "time_over": "Time over", "violation_limit": "Ended: left the window too often",
                 "face_violation": "Ended: face rule, login locked", "admin_ended": "Ended by admin", "absent": "Did not attend"}
ENDED_EARLY = ("violation_limit", "face_violation", "admin_ended")


def ranked_attempts(db: Session, test_id: str) -> List[Attempt]:
    atts = db.scalars(select(Attempt).where(Attempt.test_id == test_id, Attempt.status.in_(FINAL))).all()

    def key(a):
        took = ((aware(a.submitted_at) - aware(a.started_at)).total_seconds() if a.submitted_at else 1e9)
        return rank_key(a.total_score or 0, a.risk_score or 0, took, aware(a.submitted_at).timestamp() if a.submitted_at else 0)
    return sorted(atts, key=key)


def attempt_report(db: Session, at: Attempt, staff_view: bool = True) -> Dict:
    test = db.get(Test, at.test_id)
    u = db.get(User, at.candidate_id)
    asg = db.get(Assignment, at.assignment_id)
    ranked = ranked_attempts(db, test.id)
    rank = next((i + 1 for i, a in enumerate(ranked) if a.id == at.id), None)
    aqs = db.scalars(select(AttemptQuestion).where(AttemptQuestion.attempt_id == at.id).order_by(AttemptQuestion.order)).all()
    answers = {a.question_id: a for a in db.scalars(select(Answer).where(Answer.attempt_id == at.id)).all()}
    # section averages across all finished attempts
    avg: Dict[str, float] = {}
    for s in test.sections:
        vals = [float((a.section_scores or {}).get(s.id, 0)) for a in ranked]
        avg[s.id] = round(sum(vals) / len(vals), 2) if vals else 0
    sections = []
    for s in test.sections:
        qs = [aq for aq in aqs if aq.section_id == s.id]
        if not qs:
            continue
        sections.append({"id": s.id, "title": s.title, "score": (at.section_scores or {}).get(s.id, 0),
                         "max": round(sum(q.marks for q in qs), 2), "average": avg.get(s.id, 0)})
    questions = []
    attempted = 0
    for aq in aqs:
        q: Question = aq.question
        a = answers.get(aq.question_id)
        resp = (a.response if a else {}) or {}
        has = bool(resp.get("selected") or _text_of(resp) or resp.get("source") or resp.get("best_submission_id"))
        attempted += 1 if has else 0
        item = {"question_id": q.id, "answer_id": a.id if a else None, "title": q.title, "type": q.type,
                "section_id": aq.section_id, "marks": aq.marks, "negative": aq.negative,
                "score": (a.final_score if a and a.final_score is not None else (a.ai_score if a and a.ai_score is not None else (a.auto_score if a else 0))),
                "status": a.status if a else "unanswered", "flags": a.flags if a else [],
                "feedback": a.feedback if a else ""}
        if staff_view:
            c = q.config or {}
            if q.type.startswith("mcq"):  # every option in the order this candidate saw them: what is right, what they ticked
                by_id = {o["id"]: o for o in c.get("options", [])}
                chosen = set(resp.get("selected", []))
                order = [i for i in aq.option_order if i in by_id] + [i for i in by_id if i not in aq.option_order]
                item["options"] = [{"text": by_id[i]["text"], "correct": bool(by_id[i].get("correct")), "chosen": i in chosen} for i in order]
            elif q.type in ("short", "long"):
                item["model_answer"], item["keywords"] = c.get("model_answer", ""), c.get("keywords", [])
                item["answer_html"] = resp.get("html", "")
                item["files"] = resp.get("files", [])
                item["ai_score"] = a.ai_score if a else None
                item["ai_rationale"] = a.ai_rationale if a else ""
            else:
                sub = db.get(CodeSubmission, resp.get("best_submission_id")) if resp.get("best_submission_id") else None
                n_sub = len(db.scalars(select(CodeSubmission.id).where(CodeSubmission.attempt_id == at.id,
                                                                       CodeSubmission.question_id == q.id,
                                                                       CodeSubmission.kind == "submit")).all())
                item["submission"] = ({"id": sub.id, "language": sub.language, "source": sub.source,
                                       "score": sub.score, "max": sub.max_score, "submissions": n_sub,
                                       "cases": [{k: c2.get(k) for k in ("ordinal", "visibility", "verdict", "time_ms", "memory_kb", "weight")}
                                                 for c2 in sub.result.get("cases", [])],
                                       "flags": sub.result.get("flags", [])} if sub else {"submissions": n_sub})
        questions.append(item)
    evs = db.scalars(select(ProctorEvent).where(ProctorEvent.attempt_id == at.id).order_by(ProctorEvent.started_at)).all()
    counts = Counter(e.type for e in evs)
    snaps = db.scalars(select(ProctorSnapshot).where(ProctorSnapshot.attempt_id == at.id).order_by(ProctorSnapshot.captured_at)).all()
    took = int((aware(at.submitted_at) - aware(at.started_at)).total_seconds()) if at.submitted_at else None
    rep = {"attempt": {"id": at.id, "status": at.status, "started_at": aware(at.started_at).isoformat(),
                       "submitted_at": aware(at.submitted_at).isoformat() if at.submitted_at else None,
                       "submit_reason": at.submit_reason, "seconds_taken": took,
                       "total_score": at.total_score, "max_score": at.max_score,
                       "percent": round(100 * (at.total_score or 0) / at.max_score, 1) if at.max_score else 0,
                       "below_cutoff": at.below_cutoff, "rank": rank, "of": len(ranked),
                       "attempted": attempted, "questions": len(aqs)},
           "candidate": {"id": u.id, "name": u.name, "email": u.email if staff_view else None, "phone": u.phone if staff_view else None},
           "assignment": {"id": asg.id, "status": asg.status, "invited_at": aware(asg.invited_at).isoformat()},
           "test": {"id": test.id, "title": test.title, "cutoff": test.cutoff},
           "sections": sections, "questions": questions}
    if staff_view:
        rep["proctoring"] = {"risk_score": at.risk_score, "risk_level": at.risk_level, "band": BAND.get(at.risk_level, ""),
                             "violations": at.violations, "breakdown": at.risk_breakdown, "counts": dict(counts),
                             "consent": at.consent, "system_check": at.system_check,
                             "events": [{"type": e.type, "at": aware(e.started_at).isoformat(), "duration_ms": e.duration_ms,
                                         "weight": e.weight} for e in evs[-300:]],
                             "snapshots": [{"id": s.id, "kind": s.kind, "at": aware(s.captured_at).isoformat(),
                                            "faces": s.face_count, "flags": s.flags} for s in snaps]}
        rep["plagiarism"] = {"level": at.plagiarism_level, "max": at.plagiarism_max, "matches": candidate_summary(db, at)}
    return rep


def test_analytics(db: Session, test: Test) -> Dict:
    asgs = db.scalars(select(Assignment).where(Assignment.test_id == test.id)).all()
    atts = db.scalars(select(Attempt).where(Attempt.test_id == test.id)).all()
    done = [a for a in atts if a.status in FINAL]
    pct = [100 * (a.total_score or 0) / a.max_score for a in done if a.max_score]
    dist = [0] * 10
    for p in pct:
        dist[min(9, int(p // 10))] += 1
    times = [int((aware(a.submitted_at) - aware(a.started_at)).total_seconds() // 60) for a in done if a.submitted_at]
    langs = Counter()
    for a in done:
        for s in db.scalars(select(CodeSubmission).where(CodeSubmission.attempt_id == a.id, CodeSubmission.kind == "submit")).all():
            langs[s.language] += 1
    qstats = []
    qids = {aq.question_id for a in done for aq in db.scalars(select(AttemptQuestion).where(AttemptQuestion.attempt_id == a.id)).all()}
    for qid in qids:
        q = db.get(Question, qid)
        ans = db.scalars(select(Answer).where(Answer.question_id == qid, Answer.attempt_id.in_([a.id for a in done]))).all()
        aqm = {aq.attempt_id: aq.marks for aq in db.scalars(select(AttemptQuestion).where(AttemptQuestion.question_id == qid)).all()}
        scored = [(x.final_score or 0, aqm.get(x.attempt_id, q.marks)) for x in ans]
        full = sum(1 for s, m in scored if m and s >= m - 1e-9)
        qstats.append({"question_id": qid, "title": q.title, "type": q.type, "attempts": len(ans),
                       "full_marks_pct": round(100 * full / len(ans), 1) if ans else 0,
                       "avg_score": round(sum(s for s, _ in scored) / len(scored), 2) if scored else 0,
                       "health": ("too easy" if ans and full / len(ans) > 0.9 else "too hard" if ans and full / len(ans) < 0.1 else "good")})
    status = Counter(a.status for a in asgs)
    return {"funnel": {"invited": len(asgs), "started": len(atts), "completed": len(done),
                       "cleared_cutoff": sum(1 for a in done if not a.below_cutoff),
                       "shortlisted": status.get("shortlisted", 0)},
            "status_counts": dict(status), "score_distribution": dist,
            "average_percent": round(sum(pct) / len(pct), 1) if pct else 0,
            "time_minutes": {"min": min(times) if times else 0, "max": max(times) if times else 0,
                             "avg": round(sum(times) / len(times), 1) if times else 0},
            "integrity": dict(Counter(a.risk_level for a in done)),
            "plagiarism": dict(Counter(a.plagiarism_level for a in done)),
            "languages": dict(langs), "questions": sorted(qstats, key=lambda x: x["title"])}


def candidates_table(db: Session, test: Test, status: str = "") -> List[Dict]:
    asgs = db.scalars(select(Assignment).where(Assignment.test_id == test.id)).all()
    ranked = ranked_attempts(db, test.id)
    rank = {a.id: i + 1 for i, a in enumerate(ranked)}
    rows = []
    for g in asgs:
        at = db.scalar(select(Attempt).where(Attempt.assignment_id == g.id, Attempt.status != "reset").order_by(Attempt.started_at.desc()))
        st = g.status
        outcome = (at.submit_reason or "submitted") if at and at.status != "in_progress" else ("in_progress" if at else "absent")
        if at and at.status == "in_progress":
            st = "in_progress"
        if status and st != status:
            continue
        rows.append({"assignment_id": g.id, "attempt_id": at.id if at else None, "name": g.candidate.name,
                     "username": g.candidate.username or "", "email": g.candidate.email, "status": st, "tag": g.tag,
                     "invited_at": aware(g.invited_at).isoformat(), "sent": bool(g.sent_at),
                     "expires_at": aware(g.expires_at).isoformat() if g.expires_at else None,
                     "rank": rank.get(at.id) if at else None, "outcome": outcome, "outcome_label": OUTCOME_LABEL.get(outcome, outcome),
                     "score": at.total_score if at else None, "max": at.max_score if at else None,
                     "percent": round(100 * (at.total_score or 0) / at.max_score, 1) if at and at.max_score and at.total_score is not None else None,
                     "section_scores": at.section_scores if at else {},
                     "minutes": int((aware(at.submitted_at) - aware(at.started_at)).total_seconds() // 60) if at and at.submitted_at else None,
                     "risk_level": at.risk_level if at else None, "risk_score": at.risk_score if at else None,
                     "plagiarism": at.plagiarism_level if at else None, "below_cutoff": at.below_cutoff if at else None})
    rows.sort(key=lambda r: (r["rank"] is None, r["rank"] or 0, r["email"]))
    return rows


def export_rows(db: Session, test: Test) -> List[List]:
    secs = test.sections
    header = ["Rank", "Name", "Email", "Status", "Outcome", "Score", "Max", "Percent", "Below cut-off", "Minutes",
              "Risk level", "Risk score", "Plagiarism"] + [s.title for s in secs]
    out = [header]
    for r in candidates_table(db, test):
        pct = round(100 * (r["score"] or 0) / r["max"], 1) if r["max"] else ""
        out.append([r["rank"] or "", r["name"], r["email"], r["status"], r["outcome_label"], r["score"] if r["score"] is not None else "",
                    r["max"] or "", pct, "yes" if r["below_cutoff"] else ("no" if r["below_cutoff"] is False else ""),
                    r["minutes"] or "", r["risk_level"] or "", r["risk_score"] if r["risk_score"] is not None else "",
                    r["plagiarism"] or ""] + [(r["section_scores"] or {}).get(s.id, "") for s in secs])
    return out


def to_csv(rows: List[List]) -> str:
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue()


def to_xlsx(rows: List[List], title: str = "Results") -> bytes:
    import openpyxl
    from openpyxl.styles import Font, PatternFill
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = title[:30]
    for r in rows:
        ws.append(r)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="0B1F44")
    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = min(40, max(10, max(len(str(c.value or "")) for c in col) + 2))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _has_answer(resp: Dict) -> bool:
    """Same rule as the exam palette: a choice, some text, or a submitted program."""
    r = resp or {}
    return bool(r.get("selected") or (r.get("text") or "").strip() or r.get("submitted") or r.get("best_submission_id"))


def _age_s(moment, at) -> int | None:
    return max(0, int((at - aware(moment)).total_seconds())) if moment else None


def monitor_rows(db: Session, test: Test) -> Dict:
    """One row per participant for the live monitor: where they are, how long is left, what the proctoring has seen,
    and when we last heard from their browser. Small exams only: a few queries per participant."""
    from app.services.proctoring import face_incidents  # proctoring imports attempts; keep the import out of module load
    cfg = proctoring_config(test)
    t = now()
    rows = []
    for g in db.scalars(select(Assignment).where(Assignment.test_id == test.id)).all():
        at = db.scalar(select(Attempt).where(Attempt.assignment_id == g.id, Attempt.status != "reset")
                       .order_by(Attempt.started_at.desc()))
        row = {"assignment_id": g.id, "name": g.candidate.name, "username": g.candidate.username or g.candidate.email,
               "status": at.status if at else g.status, "assignment_status": g.status, "attempt": None}
        if at:
            answers = db.scalars(select(Answer).where(Answer.attempt_id == at.id)).all()
            heard = [m for m in (
                db.scalar(select(func.max(ProctorEvent.started_at)).where(ProctorEvent.attempt_id == at.id)),
                db.scalar(select(func.max(ProctorSnapshot.captured_at)).where(ProctorSnapshot.attempt_id == at.id)),
                db.scalar(select(func.max(Answer.saved_at)).where(Answer.attempt_id == at.id))) if m]
            snap = db.scalar(select(ProctorSnapshot).where(ProctorSnapshot.attempt_id == at.id, ProctorSnapshot.kind == "webcam")
                             .order_by(ProctorSnapshot.captured_at.desc()))
            row["attempt"] = {
                "id": at.id, "started_at": aware(at.started_at).isoformat(), "deadline_at": aware(at.deadline_at).isoformat(),
                "submit_reason": at.submit_reason, "violations": at.violations, "face_incidents": face_incidents(db, at, cfg),
                "risk_level": at.risk_level, "risk_score": at.risk_score,
                "answered": sum(1 for a in answers if _has_answer(a.response)),
                "total": db.scalar(select(func.count(AttemptQuestion.id)).where(AttemptQuestion.attempt_id == at.id)),
                "last_seen_s": _age_s(max(heard) if heard else None, t),
                "snapshot_id": snap.id if snap else None, "snapshot_age_s": _age_s(snap.captured_at if snap else None, t),
            }
        rows.append(row)
    live_first = {"in_progress": 0}
    rows.sort(key=lambda r: (live_first.get(r["status"], 1), r["name"].lower()))
    return {"server_time": t.isoformat(), "limits": {"tab": cfg["tab_switch_limit"], "face": cfg["face_limit"], "snapshot_s": cfg["snapshot_seconds"],
                                                      "webcam": bool(cfg["enabled"] and cfg["webcam"]), "live": bool(cfg["enabled"] and cfg["live_view"])},
            "rows": rows}
