"""Pure scoring rules (SRS Section 4). No I/O - fully unit tested."""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Sequence


def r2(x: float) -> float:
    return round(float(x) + 0.0, 2)


def quarter(x: float) -> float:
    """Round to the nearest 0.25."""
    return round(round(float(x) * 4) / 4, 2)


# ---------------------------------------------------------------- MCQ / Linked MCQ
def score_mcq(selected: Iterable[str], correct: Sequence[str], all_options: Sequence[str],
              marks: float, negative: float, multi: bool, partial: bool = True) -> float:
    """SRS 4.1 - single / multiple correct with HackerEarth-style partial scoring.

    * blank -> 0
    * single: correct -> marks, wrong -> -negative
    * multi + over-selection (more options than correct answers) -> -negative
    * multi + partial: each correct option +marks/k, each wrong option -negative/m
    * multi without partial: exact set -> marks else -negative
    """
    sel = {s for s in (selected or []) if s in set(all_options)}
    cor = set(correct or [])
    if not sel:
        return 0.0
    if not multi:
        return r2(marks) if sel == cor else r2(-negative)
    if len(sel) > len(cor):
        return r2(-negative)
    if not partial:
        return r2(marks) if sel == cor else r2(-negative)
    k = max(1, len(cor))
    m = max(1, len(set(all_options) - cor))
    hits = len(sel & cor)
    wrong = len(sel - cor)
    return r2(hits * marks / k - wrong * negative / m)


# ---------------------------------------------------------------- Short answer keywords
def keyword_coverage(answer_text: str, keywords: Sequence[str]) -> float:
    """keywords: ["idempotency key|idempotent key", "retry"] - '|' separates synonyms.
    Case-insensitive whole-phrase match. Returns 0..1."""
    if not keywords:
        return 0.0
    text = " " + re.sub(r"\s+", " ", (answer_text or "").lower()) + " "
    hit = 0
    for kw in keywords:
        alts = [a.strip().lower() for a in str(kw).split("|") if a.strip()]
        if any(re.search(r"(?<![a-z0-9])" + re.escape(a) + r"(?![a-z0-9])", text) for a in alts):
            hit += 1
    return hit / len(keywords)


def score_short(marks: float, coverage: float, semantic: Optional[float]) -> float:
    """2 x (0.4 x keyword coverage + 0.6 x semantic) rounded to 0.25; keyword-only if semantic is None."""
    if semantic is None:
        return quarter(marks * coverage)
    return quarter(marks * (0.4 * coverage + 0.6 * max(0.0, min(1.0, semantic))))


def score_rubric(rubric: List[Dict], scores: List[Dict]) -> float:
    """rubric: [{id,name,max}], scores: [{id, score}] - each clipped to [0, max]."""
    mx = {str(c["id"]): float(c.get("max", 1)) for c in rubric or []}
    total = 0.0
    for s in scores or []:
        cid = str(s.get("id"))
        if cid in mx:
            total += max(0.0, min(float(s.get("score", 0) or 0), mx[cid]))
    return quarter(total)


# ---------------------------------------------------------------- Programming / SQL
def score_cases(results: List[Dict]) -> float:
    """results: [{weight, passed}] - score = sum of weights of passed cases."""
    return r2(sum(float(c.get("weight", 0)) for c in results if c.get("passed")))


def cross_verification_flags(results: List[Dict]) -> List[str]:
    opn = [c for c in results if c.get("visibility") == "open"]
    hid = [c for c in results if c.get("visibility") == "hidden"]
    flags = []
    if opn and hid and all(c.get("passed") for c in opn) and not any(c.get("passed") for c in hid):
        flags.append("possible_hard_coding")
    if opn and hid and any(c.get("passed") for c in hid) and not any(c.get("passed") for c in opn):
        flags.append("anomaly_hidden_pass_open_fail")
    return flags


# ---------------------------------------------------------------- Output comparators
def compare_output(actual: str, expected: str, mode: str = "trim") -> bool:
    a = (actual or "").replace("\r\n", "\n")
    e = (expected or "").replace("\r\n", "\n")
    if mode == "exact":
        return a == e
    if mode == "token":
        return a.split() == e.split()
    if mode == "float":
        at, et = a.split(), e.split()
        if len(at) != len(et):
            return False
        for x, y in zip(at, et):
            if x == y:
                continue
            try:
                if abs(float(x) - float(y)) > 1e-6 * max(1.0, abs(float(y))):
                    return False
            except ValueError:
                return False
        return True
    # trim: ignore trailing spaces on each line and trailing blank lines
    norm = lambda s: "\n".join(line.rstrip() for line in s.strip("\n").split("\n")).strip()
    return norm(a) == norm(e)


# ---------------------------------------------------------------- Aggregation
def aggregate_sections(question_scores: Dict[str, List[float]], allow_negative: Dict[str, bool]) -> Dict[str, float]:
    out = {}
    for sid, scores in question_scores.items():
        tot = sum(scores)
        out[sid] = r2(tot if allow_negative.get(sid) else max(0.0, tot))
    return out


def rank_key(total: float, risk: float, seconds_taken: float, submitted_ts: float):
    """Sort ascending -> higher total first, then lower risk, shorter time, earlier submit."""
    return (-total, risk, seconds_taken, submitted_ts)
