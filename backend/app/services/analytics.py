"""Analytics: the exam as a whole (for staff) and one candidate against the class (candidate-safe: percentages and counts, never an answer key).

Only finished attempts count (review_pending and evaluated). A question's score is final, else AI, else automatic mark, the same rule the report uses."""
from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from typing import Any, Callable, Dict, List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (Answer, Assignment, Attempt, AttemptQuestion, CodeSubmission, Evaluation, ProctorEvent, Question, Test, User,
                        aware)
from app.services.report_card import KIND, question_status, visible_to_candidate
from app.services.reports import FINAL, RESULT_LABEL, has_answer, ranked_attempts, result_of, results_of

EPS = 1e-9
FEW = 5            # fewer answers than this say nothing about a question
DISC_MIN = 6       # discrimination needs enough candidates for an upper and a lower group
KINDS, LEVELS = ["Choice", "Written", "Coding", "SQL"], ["easy", "medium", "hard"]
GROUPS: Dict[str, Callable[[Dict], List[str]]] = {"kinds": lambda r: [r["kind"]], "difficulty": lambda r: [r["difficulty"]], "skills": lambda r: r["skills"]}


# ---------------------------------------------------------------- small pure helpers (unit tested)
def pct(score, top) -> float:
    return round(100 * (score or 0) / top, 1) if top else 0.0


def histogram(values, bins: int = 10) -> List[int]:
    """Counts per 10-percent bin; 100% (or more) is in the last bin, a negative score in the first."""
    out = [0] * bins
    for v in values:
        out[min(bins - 1, max(0, int(v // (100 / bins))))] += 1
    return out


def beat_percent(values, mine) -> Optional[int]:
    """Of the OTHER candidates, the share this score is strictly higher than. None when nobody else finished."""
    others = len(values) - 1
    return round(100 * sum(1 for v in values if v < mine) / others) if others >= 1 else None


def discrimination(rows: List[Tuple[float, float]]) -> Optional[float]:
    """rows = (candidate's total percent, share of this question's marks they got). Upper 27% minus lower 27%: near +1 the question separates strong
    from weak; around 0 it does not; clearly negative means the strong did worse than the weak (often a wrong key). None when there are too few
    candidates or everyone has the same total."""
    if len(rows) < DISC_MIN:
        return None
    rows = sorted(rows, key=lambda r: -r[0])
    if rows[0][0] == rows[-1][0]:
        return None
    k = max(1, round(0.27 * len(rows)))
    return round(statistics.fmean(r[1] for r in rows[:k]) - statistics.fmean(r[1] for r in rows[-k:]), 2)


def _health(n: int, avg_percent: float, skipped_pct: float, disc: Optional[float]) -> str:
    if n < FEW:
        return "few answers"
    if disc is not None and disc <= -0.2:
        return "check the key"
    if avg_percent > 90:
        return "too easy"
    if avg_percent < 10:
        return "too hard"
    return "often skipped" if skipped_pct >= 30 else "good"


# ---------------------------------------------------------------- one pass over the finished attempts
def _score(a: Optional[Answer]) -> float:
    for v in ((a.final_score, a.ai_score, a.auto_score) if a else ()):
        if v is not None:
            return float(v)
    return 0.0


def _load(db: Session, attempts: List[Attempt]) -> Tuple[List[Dict], Dict[str, Question]]:
    """One record per (attempt, question) the candidate was given, including the ones never answered. Two batched reads, not one per row."""
    ids = [a.id for a in attempts]
    if not ids:
        return [], {}
    aqs = db.scalars(select(AttemptQuestion).where(AttemptQuestion.attempt_id.in_(ids))).all()
    qs = {q.id: q for q in db.scalars(select(Question).where(Question.id.in_({aq.question_id for aq in aqs})))}
    ans = {(a.attempt_id, a.question_id): a for a in db.scalars(select(Answer).where(Answer.attempt_id.in_(ids)))}
    recs = []
    for aq in aqs:
        q, a = qs[aq.question_id], ans.get((aq.attempt_id, aq.question_id))
        resp = (a.response if a else None) or {}
        recs.append({"at": aq.attempt_id, "q": q.id, "sec": aq.section_id, "order": aq.order, "marks": float(aq.marks or 0), "score": _score(a),
                     "answered": has_answer(resp), "status": a.status if a else "unanswered", "resp": resp, "type": q.type, "title": q.title,
                     "kind": KIND.get(q.type, "Other"), "difficulty": q.difficulty or "medium",
                     "skills": sorted({str(s).strip()[:40] for s in (q.skills or []) if str(s).strip()})})
    return recs, qs


def _full(r: Dict) -> bool:
    return r["marks"] > 0 and r["score"] >= r["marks"] - EPS


def _by(recs: List[Dict], group: str) -> Dict[str, List[Any]]:
    """name -> [marks earned, marks available, set of question ids] for kinds, difficulty or skills (negative scores count as 0)."""
    g: Dict[str, List[Any]] = defaultdict(lambda: [0.0, 0.0, set()])
    for r in recs:
        if r["marks"] <= 0:
            continue
        for name in GROUPS[group](r):
            e = g[name]
            e[0] += max(0.0, r["score"])
            e[1] += r["marks"]
            e[2].add(r["q"])
    return g


def _ordered(names, order: Optional[List[str]]) -> List[str]:
    return [n for n in (order or []) if n in names] + sorted(n for n in names if n not in (order or []))


def _sections(test: Test, done: List[Attempt], recs: List[Dict]) -> List[Dict]:
    """Per section: marks available and score of every attempt that was given it, as {attempt id: (score, max)}."""
    out = []
    for s in test.sections:
        mx: Dict[str, float] = defaultdict(float)
        for r in recs:
            if r["sec"] == s.id:
                mx[r["at"]] += r["marks"]
        if mx:
            out.append({"id": s.id, "title": s.title, "min_score": s.min_score or 0,
                        "by": {a.id: (float((a.section_scores or {}).get(s.id, 0)), mx[a.id]) for a in done if a.id in mx}})
    return out


def _position(test: Test) -> Callable[[Dict], Tuple[int, float]]:
    """Sort key for the records of one candidate: a question's order restarts in every section, so the section comes first."""
    where = {s.id: i for i, s in enumerate(test.sections)}
    return lambda r: (where.get(r["sec"], 0), r["order"])


def _minutes(a: Attempt) -> Optional[float]:
    return (aware(a.submitted_at) - aware(a.started_at)).total_seconds() / 60 if a.submitted_at else None


# ---------------------------------------------------------------- the exam as a whole (staff)
def exam_analytics(db: Session, test: Test) -> Dict[str, Any]:
    asgs = db.scalars(select(Assignment).where(Assignment.test_id == test.id)).all()
    atts = db.scalars(select(Attempt).where(Attempt.test_id == test.id, Attempt.status != "reset")).all()
    done = [a for a in atts if a.status in FINAL]
    ids = [a.id for a in done]
    recs, qs = _load(db, done)
    percent = {a.id: pct(a.total_score, a.max_score) for a in done}
    vals = [percent[a.id] for a in done if a.max_score]
    results = results_of(db, test, done)

    scores: Dict[str, Any] = {"n": len(vals), "mean": None, "median": None, "std": None, "min": None, "max": None, "q1": None, "q3": None}
    if vals:
        q = statistics.quantiles(vals, n=4, method="inclusive") if len(vals) > 1 else [vals[0]] * 3
        scores.update(mean=round(statistics.fmean(vals), 1), median=round(statistics.median(vals), 1), std=round(statistics.pstdev(vals), 1),
                      min=min(vals), max=max(vals), q1=round(q[0], 1), q3=round(q[2], 1))
    verdicts = Counter(results.values())
    judged = len(done) - verdicts.get("no_pass_mark", 0)
    maxes = [a.max_score for a in done if a.max_score]
    scores["pass_rate"] = round(100 * verdicts.get("passed", 0) / judged) if judged else None
    scores["pass_mark_percent"] = round(100 * test.cutoff / statistics.fmean(maxes), 1) if (test.cutoff or 0) > 0 and maxes else None

    mins = [m for m in (_minutes(a) for a in done) if m is not None]
    limit = test.duration_min or 0  # ponytail: extra time given to one person is ignored here, such a candidate may show above 100%
    names = {i: n for i, n in db.execute(select(User.id, User.name).where(User.id.in_({a.candidate_id for a in done})))} if done else {}
    points = [{"name": names.get(a.candidate_id) or "Candidate", "percent": percent[a.id], "minutes": round(_minutes(a), 1), "risk": a.risk_level}
              for a in done if a.max_score and a.submitted_at]

    sections = []
    for s in _sections(test, done, recs):
        p = [pct(sc, mx) for sc, mx in s["by"].values()]
        sections.append({"id": s["id"], "title": s["title"], "max": round(statistics.fmean(mx for _, mx in s["by"].values()), 2), "mean": round(statistics.fmean(p), 1),
                         "best": max(p), "worst": min(p), "min_score": s["min_score"], "below_min": sum(1 for sc, _ in s["by"].values() if s["min_score"] > 0 and sc < s["min_score"])})

    groups = {}
    for name, order in (("kinds", KINDS), ("difficulty", LEVELS), ("skills", None)):
        g = _by(recs, name)
        rows = [{"name": n, "percent": pct(g[n][0], g[n][1]), "n": len(g[n][2])} for n in _ordered(g, order)]
        groups[name] = sorted(rows, key=lambda r: -r["n"])[:8] if name == "skills" else rows

    by_q: Dict[str, List[Dict]] = defaultdict(list)
    for r in recs:
        by_q[r["q"]].append(r)
    questions = []
    for qid, rs in by_q.items():
        q, n = qs[qid], len(rs)
        ratios = [min(1.0, max(0.0, r["score"] / r["marks"])) for r in rs if r["marks"] > 0]
        avg = round(100 * statistics.fmean(ratios), 1) if ratios else 0.0
        skipped = sum(1 for r in rs if not r["answered"])
        disc = discrimination([(percent[r["at"]], min(1.0, max(0.0, r["score"] / r["marks"]))) for r in rs if r["marks"] > 0])
        item = {"question_id": qid, "title": q.title, "type": q.type, "kind": rs[0]["kind"], "difficulty": rs[0]["difficulty"], "attempts": n,
                "marks": round(statistics.fmean(r["marks"] for r in rs), 2), "full_marks_pct": round(100 * sum(1 for r in rs if _full(r)) / n, 1),
                "avg_score": round(statistics.fmean(r["score"] for r in rs), 2), "avg_percent": avg, "skipped": skipped,
                "skipped_pct": round(100 * skipped / n, 1), "discrimination": disc, "health": _health(n, avg, 100 * skipped / n, disc),
                "_order": (_position(test)(rs[0])[0], statistics.fmean(r["order"] for r in rs))}
        if q.type.startswith("mcq"):
            chosen = Counter(i for r in rs for i in (r["resp"].get("selected") or []))
            item["options"] = [{"label": chr(65 + i), "text": str(o.get("text", ""))[:80], "correct": bool(o.get("correct")), "chosen": chosen.get(o.get("id"), 0)}
                               for i, o in enumerate((q.config or {}).get("options", []))]
        questions.append(item)
    questions.sort(key=lambda x: (x["_order"], x["title"]))
    for x in questions:
        del x["_order"]

    def count(*where) -> int:
        return db.scalar(select(func.count()).select_from(Answer).where(Answer.attempt_id.in_(ids), *where)) or 0 if ids else 0

    marking = {"machine": sum(1 for r in recs if r["type"] not in ("short", "long")), "ai": count(Answer.ai_score.is_not(None)),
               "ai_changed": count(Answer.ai_score.is_not(None), Answer.final_score.is_not(None), Answer.final_score != Answer.ai_score),
               "person": (db.scalar(select(func.count(func.distinct(Evaluation.answer_id))).join(Answer, Answer.id == Evaluation.answer_id)
                                    .where(Answer.attempt_id.in_(ids), Evaluation.method == "manual")) or 0) if ids else 0}
    events = db.execute(select(ProctorEvent.type, func.count()).where(ProctorEvent.attempt_id.in_(ids)).group_by(ProctorEvent.type)
                        .order_by(func.count().desc()).limit(8)).all() if ids else []
    langs = db.execute(select(CodeSubmission.language, func.count()).where(CodeSubmission.attempt_id.in_(ids), CodeSubmission.kind == "submit")
                       .group_by(CodeSubmission.language)).all() if ids else []
    status = Counter(g.status for g in asgs)
    return {"funnel": {"invited": len(asgs), "started": len(atts), "completed": len(done), "cleared_cutoff": verdicts.get("passed", 0),
                       "shortlisted": status.get("shortlisted", 0)},
            "status_counts": dict(status), "calculated": bool(test.calculated_at), "declared": bool(test.results_declared_at),
            "pending_review": sum(1 for a in done if a.status == "review_pending"), "duration_min": limit,
            "scores": scores, "score_distribution": histogram(vals), "average_percent": scores["mean"] or 0, "results": dict(verdicts),
            "time_minutes": {"min": int(min(mins)) if mins else 0, "max": int(max(mins)) if mins else 0, "avg": round(statistics.fmean(mins), 1) if mins else 0},
            "time_distribution": histogram([100 * m / limit for m in mins]) if limit else [0] * 10, "points": points,
            "sections": sections, **groups, "questions": questions, "marking": marking,
            "integrity": dict(Counter(a.risk_level for a in done)), "events": [{"type": t, "count": n} for t, n in events],
            "plagiarism": dict(Counter(a.plagiarism_level for a in done)), "languages": {l: n for l, n in langs}}


# ---------------------------------------------------------------- one candidate against the class (candidate-safe)
def attempt_analytics(db: Session, at: Attempt) -> Dict[str, Any]:
    t = db.get(Test, at.test_id)
    ranked = ranked_attempts(db, t.id)
    recs, _ = _load(db, ranked)
    percent = {a.id: pct(a.total_score, a.max_score) for a in ranked}
    vals = [percent[a.id] for a in ranked if a.max_score]
    me = percent.get(at.id, pct(at.total_score, at.max_score))
    mine = sorted((r for r in recs if r["at"] == at.id), key=_position(t))

    sections = []
    for s in _sections(t, ranked, recs):
        if at.id not in s["by"]:
            continue
        p = [pct(sc, mx) for sc, mx in s["by"].values()]
        sc, mx = s["by"][at.id]
        sections.append({"title": s["title"], "score": round(sc, 2), "max": round(mx, 2), "you": pct(sc, mx), "class": round(statistics.fmean(p), 1), "best": max(p)})
    groups = {}
    for name, order in (("kinds", KINDS), ("difficulty", LEVELS), ("skills", None)):
        me_g, all_g = _by(mine, name), _by(recs, name)
        rows = [{"name": n, "you": pct(me_g[n][0], me_g[n][1]), "class": pct(all_g[n][0], all_g[n][1]), "n": len(me_g[n][2])} for n in _ordered(me_g, order)]
        groups[name] = sorted(rows, key=lambda r: -r["n"])[:8] if name == "skills" else rows

    by_q: Dict[str, List[Dict]] = defaultdict(list)
    for r in recs:
        by_q[r["q"]].append(r)
    questions = []
    for i, r in enumerate(mine, 1):
        everyone = by_q[r["q"]]
        questions.append({"n": i, "title": r["title"], "kind": r["kind"], "marks": r["marks"], "score": round(r["score"], 2), "status": question_status(r),
                          "class_correct": round(100 * sum(1 for x in everyone if _full(x)) / len(everyone)) if len(everyone) >= 2 else None})

    asg = db.get(Assignment, at.assignment_id)
    mins = [m for m in (_minutes(a) for a in ranked) if m is not None]
    mine_min = _minutes(at)
    verdict = result_of(t, at.below_cutoff, any(r["answered"] for r in mine))
    diffs = [(s["you"] - s["class"], s) for s in sections if s["max"]]
    highlights = []
    if len(diffs) >= 2:
        (hi, best), (lo, worst) = max(diffs, key=lambda d: d[0]), min(diffs, key=lambda d: d[0])
        if hi > 0:
            highlights.append(f"Best against the class: {best['title']} ({best['you']:g}% against a class average of {best['class']:g}%).")
        if lo < 0:
            highlights.append(f"Most to improve: {worst['title']} ({worst['you']:g}% against a class average of {worst['class']:g}%).")
    u = db.get(User, at.candidate_id)
    return {"candidate": {"name": u.name or u.username or "Candidate"}, "exam": {"title": t.title, "declared": bool(t.results_declared_at)},
            "score": {"score": round(at.total_score or 0, 2), "max": at.max_score or 0, "percent": me, "result": verdict, "result_label": RESULT_LABEL.get(verdict, "")},
            "rank": next((i + 1 for i, a in enumerate(ranked) if a.id == at.id), None), "of": len(ranked), "beat_percent": beat_percent(vals, me),
            "class": {"n": len(vals), "mean": round(statistics.fmean(vals), 1) if vals else 0, "median": round(statistics.median(vals), 1) if vals else 0, "highest": max(vals, default=0)},
            "histogram": histogram(vals), "you_bin": min(9, max(0, int(me // 10))), "sections": sections, **groups,
            "time": {"taken": round(mine_min, 1) if mine_min is not None else None, "allowed": t.duration_min + (asg.extra_time_min if asg else 0),
                     "class_average": round(statistics.fmean(mins), 1) if mins else None},
            "questions": questions, "highlights": highlights}


# ---------------------------------------------------------------- a candidate's results over all their exams
def progress(db: Session, user: User) -> List[Dict[str, Any]]:
    out = []
    for at in db.scalars(select(Attempt).where(Attempt.candidate_id == user.id, Attempt.status == "evaluated").order_by(Attempt.submitted_at.desc()).limit(40)):
        t = db.get(Test, at.test_id)
        if t.status == "archived" or visible_to_candidate(t, at):
            continue
        ranked = ranked_attempts(db, t.id)
        vals = [pct(a.total_score, a.max_score) for a in ranked if a.max_score]
        out.append({"attempt_id": at.id, "title": t.title, "date": aware(at.submitted_at or at.started_at).isoformat(), "percent": pct(at.total_score, at.max_score),
                    "class_average": round(statistics.fmean(vals), 1) if vals else 0, "rank": next((i + 1 for i, a in enumerate(ranked) if a.id == at.id), None),
                    "of": len(ranked), "result": results_of(db, t, [at])[at.id]})
        if len(out) == 20:
            break
    return sorted(out, key=lambda r: r["date"])
