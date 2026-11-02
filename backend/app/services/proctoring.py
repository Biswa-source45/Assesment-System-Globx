"""Proctoring ingest, evidence storage and risk scoring (SRS Section 6)."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.domain import risk
from app.models import Attempt, ProctorEvent, ProctorSnapshot, Test, now, uid
from app.services.attempts import proctoring_config

log = logging.getLogger("oap.proctor")
EVENT_TYPES = set(risk.DEFAULT_WEIGHTS) | {"fs_enter", "focus", "resume", "consent", "face_ok"}
FACE_TYPES = {"face_missing", "multi_face"}
_cv = None


def _cv2():
    global _cv
    if _cv is None:
        try:
            import cv2  # optional dependency
            casc = cv2.CascadeClassifier(os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml"))
            _cv = (cv2, casc)
        except Exception:
            _cv = False
    return _cv or None


def face_count(image_bytes: bytes) -> Optional[int]:
    cv = _cv2()
    if not cv:
        return None
    cv2, casc = cv
    try:
        import numpy as np
        img = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_GRAYSCALE)
        if img is None:
            return None
        faces = casc.detectMultiScale(img, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40))
        return int(len(faces))
    except Exception:
        return None


def recompute(db: Session, at: Attempt, test: Optional[Test] = None) -> Dict:
    test = test or db.get(Test, at.test_id)
    cfg = proctoring_config(test)
    evs = db.scalars(select(ProctorEvent).where(ProctorEvent.attempt_id == at.id)).all()
    items = [{"type": e.type, "duration_ms": e.duration_ms} for e in evs if e.type in risk.DEFAULT_WEIGHTS]
    if at.plagiarism_level == "high":
        items.append({"type": "plagiarism_high", "duration_ms": 0})
    r = risk.compute(items, cfg.get("weights") or {})
    at.risk_score, at.risk_level, at.risk_breakdown, at.violations = r["score"], r["level"], r["breakdown"], r["violations"]
    return r


def ingest_events(db: Session, at: Attempt, events: List[Dict]) -> Dict:
    test = db.get(Test, at.test_id)
    cfg = proctoring_config(test)
    weights = {**risk.DEFAULT_WEIGHTS, **(cfg.get("weights") or {})}
    for e in events[:200]:
        t = str(e.get("type", ""))[:32]
        if t not in EVENT_TYPES:
            continue
        d = max(0, min(int(e.get("duration_ms") or 0), 6 * 3600 * 1000))
        try:
            ts = datetime.fromisoformat(str(e.get("started_at")).replace("Z", "+00:00")) if e.get("started_at") else now()
        except ValueError:
            ts = now()
        db.add(ProctorEvent(id=uid(), attempt_id=at.id, type=t, started_at=ts, duration_ms=d,
                            weight=risk.event_weight(t, d, weights) if t in risk.DEFAULT_WEIGHTS else 0,
                            payload={k: v for k, v in (e.get("payload") or {}).items()} if isinstance(e.get("payload"), dict) else {}))
    db.flush()
    r = recompute(db, at, test)
    limit = int(cfg.get("tab_switch_limit") or 0)
    face_limit = int(cfg.get("face_limit") or 0)
    faces = face_incidents(db, at, cfg)
    live = at.status == "in_progress"
    action = "none"
    msg = ""
    if face_limit and faces >= face_limit and live:
        action = "ban"
        msg = f"Your face was not visible {faces} times. Your exam has been terminated."
    elif limit and r["violations"] > limit and cfg.get("limit_action", "submit") == "submit" and live:
        action = "force_submit"
        msg = f"You left the test environment {r['violations']} times (limit {limit}). Your exam has been terminated."
    elif face_limit and any(e.get("type") in FACE_TYPES for e in events):
        action = "warn"
        msg = f"Warning {faces} of {face_limit}: keep exactly one face in the camera view."
    elif limit and r["violations"] and any(e.get("type") in risk.VIOLATION_TYPES for e in events):
        action = "warn"
        msg = f"Warning {r['violations']} of {limit}: leaving fullscreen or switching tabs is recorded."
    return {"risk_score": r["score"], "risk_level": r["level"], "band": r["band"], "violations": r["violations"],
            "limit": limit, "face_incidents": faces, "face_limit": face_limit, "action": action, "message": msg}


def face_incidents(db: Session, at: Attempt, cfg: Dict) -> int:
    """Browser-reported episodes of no face (>= face_min_seconds) or several faces. Server snapshot checks are
    evidence only (payload source=snapshot) and not counted, so one episode is never counted twice."""
    min_ms = int(cfg.get("face_min_seconds") or 0) * 1000
    evs = db.scalars(select(ProctorEvent).where(ProctorEvent.attempt_id == at.id,
                                                ProctorEvent.type.in_(FACE_TYPES))).all()
    return sum(1 for e in evs if (e.payload or {}).get("source") != "snapshot"
               and (e.type == "multi_face" or e.duration_ms >= min_ms))


def save_snapshot(db: Session, at: Attempt, kind: str, data: bytes, client_faces: Optional[int]) -> Dict:
    s = get_settings()
    kind = kind if kind in ("webcam", "screen", "audio") else "webcam"
    ext = {"webcam": "jpg", "screen": "jpg", "audio": "webm"}[kind]
    sid = uid()
    rel = f"proctor/{at.id}/{now().strftime('%Y%m%dT%H%M%S')}_{kind}_{sid[:6]}.{ext}"  # stored relative to the storage folder, so the folder can move
    path = os.path.join(s.storage_dir, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data[: 6 * 1024 * 1024])
    faces = face_count(data) if kind == "webcam" else None
    if faces is None and kind == "webcam":
        faces = client_faces
    flags = []
    events = []
    interval = proctoring_config(db.get(Test, at.test_id)).get("snapshot_seconds", 15)
    if kind == "webcam" and faces is not None:
        if faces == 0:
            flags.append("no_face")
            events.append({"type": "face_missing", "duration_ms": int(interval) * 1000 + 1000, "payload": {"source": "snapshot"}})
        elif faces > 1:
            flags.append("multiple_faces")
            events.append({"type": "multi_face", "duration_ms": 0, "payload": {"source": "snapshot"}})
    db.add(ProctorSnapshot(id=sid, attempt_id=at.id, kind=kind, path=rel, face_count=faces, flags=flags))
    out = ingest_events(db, at, events) if events else {"risk_score": at.risk_score, "risk_level": at.risk_level}
    out.update({"snapshot_id": sid, "faces": faces, "flags": flags})
    return out
