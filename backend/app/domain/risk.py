"""Proctoring risk engine (SRS Section 6). Pure functions."""
from __future__ import annotations

from typing import Dict, Iterable, List, Tuple

DEFAULT_WEIGHTS: Dict[str, float] = {
    "tab_blur": 8,          # per event; < 1 s ignored, > 30 s counts double
    "fs_exit": 6,           # per event
    "face_missing": 1,      # per 10 s of absence (after first 10 s)
    "multi_face": 15,       # per episode
    "face_mismatch": 25,    # per episode
    "voice": 5,             # per event
    "multi_voice": 10,      # per event
    "paste": 4,             # per blocked paste attempt
    "copy": 2,
    "devtools": 6,
    "multi_display": 20,    # once
    "vm_detected": 20,      # once
    "rdp_detected": 20,     # once
    "plagiarism_high": 20,  # once
    "webcam_denied": 20,    # once
    "network_drop": 0,
}
ONCE = {"multi_display", "vm_detected", "rdp_detected", "plagiarism_high", "webcam_denied"}
VIOLATION_TYPES = {"tab_blur", "fs_exit"}  # count towards the "leave test environment" limit
LEVELS: List[Tuple[float, str]] = [(70, "critical"), (45, "high"), (20, "medium"), (0, "low")]
BAND = {"low": "Acceptable", "medium": "Marginally acceptable", "high": "Marginally acceptable - review",
        "critical": "Unacceptable"}


def event_weight(etype: str, duration_ms: int, weights: Dict[str, float]) -> float:
    w = float(weights.get(etype, DEFAULT_WEIGHTS.get(etype, 0)))
    if etype == "tab_blur":
        if duration_ms and duration_ms < 1000:
            return 0.0
        return w * 2 if duration_ms > 30000 else w
    if etype == "face_missing":
        secs = max(0, duration_ms // 1000 - 10)
        return w * (secs // 10 + (1 if secs % 10 else 0)) if duration_ms > 10000 else 0.0
    return w


def compute(events: Iterable[Dict], weights: Dict[str, float] | None = None) -> Dict:
    """events: [{type, duration_ms}] -> {score, level, band, breakdown, violations}"""
    weights = {**DEFAULT_WEIGHTS, **(weights or {})}
    seen_once = set()
    breakdown: Dict[str, Dict[str, float]] = {}
    total = 0.0
    violations = 0
    for e in events:
        t = e.get("type", "")
        d = int(e.get("duration_ms") or 0)
        if t in ONCE:
            if t in seen_once:
                continue
            seen_once.add(t)
        w = event_weight(t, d, weights)
        if t in VIOLATION_TYPES and (t != "tab_blur" or d == 0 or d >= 1000):
            violations += 1
        b = breakdown.setdefault(t, {"count": 0, "points": 0.0})
        b["count"] += 1
        b["points"] += w
        total += w
    score = min(100.0, round(total, 1))
    lvl = level_for(score)
    return {"score": score, "level": lvl, "band": BAND[lvl], "breakdown": breakdown, "violations": violations}


def level_for(score: float) -> str:
    for th, name in LEVELS:
        if score >= th:
            return name
    return "low"
