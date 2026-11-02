"""Plagiarism job: compares every pair of final answers per question inside a test (SRS Section 8)."""
from __future__ import annotations

import logging
import re
from itertools import combinations
from typing import Dict, List

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.domain import plagiarism as P
from app.models import (Answer, Attempt, AttemptQuestion, CodeSubmission, PlagiarismMatch, Question, uid)

log = logging.getLogger("oap.plagiarism")


def _final_texts(db: Session, test_id: str) -> Dict[str, Dict[str, Dict]]:
    """question_id -> attempt_id -> {kind, lang, text}"""
    atts = db.scalars(select(Attempt).where(Attempt.test_id == test_id,
                                            Attempt.status.in_(["review_pending", "evaluated", "submitted"]))).all()
    out: Dict[str, Dict[str, Dict]] = {}
    for at in atts:
        for a in db.scalars(select(Answer).where(Answer.attempt_id == at.id)).all():
            q = db.get(Question, a.question_id)
            if not q or q.type.startswith("mcq"):
                continue
            r = a.response or {}
            if q.type in ("coding", "sql"):
                sub = db.get(CodeSubmission, r.get("best_submission_id")) if r.get("best_submission_id") else None
                src = sub.source if sub else (r.get("source") or "")
                lang = "sql" if q.type == "sql" else (sub.language if sub else r.get("language", "python"))
                if src.strip():
                    out.setdefault(q.id, {})[at.id] = {"kind": "code", "lang": lang, "text": src}
            else:
                txt = re.sub(r"<[^>]+>", " ", r.get("html") or r.get("text") or "")
                if txt.strip():
                    out.setdefault(q.id, {})[at.id] = {"kind": "text", "text": txt}
    return out


def run_for_test(db: Session, test_id: str) -> Dict:
    data = _final_texts(db, test_id)
    db.execute(delete(PlagiarismMatch).where(PlagiarismMatch.test_id == test_id, PlagiarismMatch.decision == ""))
    decided = {(m.question_id, m.attempt_a, m.attempt_b) for m in
               db.scalars(select(PlagiarismMatch).where(PlagiarismMatch.test_id == test_id)).all()}
    best: Dict[str, float] = {}
    n = 0
    for qid, per in data.items():
        q = db.get(Question, qid)
        starters = (q.config or {}).get("starter") or {}
        excl_by_lang = {lang: P.fingerprints(P.tokens(src, lang)) for lang, src in starters.items() if src}
        for (a1, x), (a2, y) in combinations(sorted(per.items()), 2):
            if x["kind"] == "code":
                if x["lang"] != y["lang"]:
                    continue
                sim, run, _ = P.code_similarity(x["text"], y["text"], x["lang"], excl_by_lang.get(x["lang"], set()))
            else:
                sim, run = P.text_similarity(x["text"], y["text"]), 0
            lvl = P.level(sim)
            best[a1] = max(best.get(a1, 0), sim)
            best[a2] = max(best.get(a2, 0), sim)
            if lvl != "clear" and (qid, a1, a2) not in decided:
                db.add(PlagiarismMatch(id=uid(), test_id=test_id, question_id=qid, attempt_a=a1, attempt_b=a2,
                                       similarity=sim, longest_run=run, level=lvl))
                n += 1
    from app.services.proctoring import recompute
    for at in db.scalars(select(Attempt).where(Attempt.test_id == test_id)).all():
        m = best.get(at.id, 0.0)
        confirmed_fp = db.scalars(select(PlagiarismMatch).where(
            PlagiarismMatch.test_id == test_id, PlagiarismMatch.decision == "false_positive",
            (PlagiarismMatch.attempt_a == at.id) | (PlagiarismMatch.attempt_b == at.id))).all()
        lvl = P.level(m)
        if lvl != "clear" and confirmed_fp and all(fp.similarity >= m for fp in confirmed_fp):
            lvl = "clear"
        at.plagiarism_max, at.plagiarism_level = m, lvl
        recompute(db, at)
    db.commit()
    return {"pairs_flagged": n, "questions": len(data)}


def candidate_summary(db: Session, attempt: Attempt) -> List[Dict]:
    rows = db.scalars(select(PlagiarismMatch).where(
        PlagiarismMatch.test_id == attempt.test_id,
        (PlagiarismMatch.attempt_a == attempt.id) | (PlagiarismMatch.attempt_b == attempt.id))).all()
    return [{"id": m.id, "question_id": m.question_id, "peer_attempt": m.attempt_b if m.attempt_a == attempt.id else m.attempt_a,
             "similarity": m.similarity, "level": m.level, "decision": m.decision} for m in rows]
