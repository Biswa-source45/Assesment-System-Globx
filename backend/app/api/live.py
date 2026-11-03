"""Live view and voice, and the optional whole-exam video.

Live: the server only passes the small messages two browsers need to find each other (WebRTC). Camera, screen and voice then travel
between the browsers, not through the server. Recording: the candidate's browser sends its video in 10-second pieces and the server
appends them to a file under user-assets; files older than the exam's retention days are deleted (services/proctoring.purge_recordings)."""
from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import timedelta
from typing import Dict, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.deps import RECRUIT, ROLE_GROUPS, audit, current_user, same_org
from app.core.security import jwt_decode
from app.db import SessionLocal, get_db
from app.models import Attempt, ProctorEvent, Recording, Test, User, aware, now, uid
from app.services.attempts import proctoring_config

router = APIRouter(tags=["live"])


# ------------------------------------------------------------------ live view and voice
class Room:
    """The people connected for one exam. In memory: one server process serves this office (ponytail: several processes would need a shared channel such as Redis)."""

    def __init__(self) -> None:
        self.examiners: Dict[str, WebSocket] = {}
        self.candidates: Dict[str, tuple] = {}  # attempt id -> (socket, name)
        self.talking: Dict[str, tuple] = {}     # attempt id -> (examiner id, user id, started)


ROOMS: Dict[str, Room] = {}
FROM_CANDIDATE = {"offer", "ice"}
FROM_EXAMINER = {"answer", "ice"}


def _identify(token: str, test_id: str) -> Optional[dict]:
    """Who is connecting: an examiner of this exam's organisation, or a candidate taking this exam right now (and only if its live view is on). None = refuse."""
    try:
        claims = jwt_decode(token)
    except ValueError:
        return None
    if claims.get("typ") != "access":
        return None
    with SessionLocal() as db:
        u, t = db.get(User, claims.get("sub")), db.get(Test, test_id)
        if not u or u.status != "active" or not t:
            return None
        who = {"user_id": u.id, "name": u.name or u.email}
        if u.has("super_admin", *ROLE_GROUPS["recruit"]):
            if u.org_id != t.org_id and not u.has("super_admin"):
                return None
            audit(db, u, "live_view_open", "test", t.id)
            db.commit()
            return {**who, "role": "examiner", "id": "e" + uid()[:8]}
        at = db.scalar(select(Attempt).where(Attempt.test_id == t.id, Attempt.candidate_id == u.id, Attempt.status == "in_progress"))
        if at and proctoring_config(t)["live_view"]:
            return {**who, "role": "candidate", "id": at.id}
    return None


def _record(user_id: str, attempt_id: str, etype: str, payload: dict, duration_ms: int = 0) -> None:
    """A talk or a message becomes part of the candidate's timeline and of the audit log."""
    with SessionLocal() as db:
        db.add(ProctorEvent(id=uid(), attempt_id=attempt_id, type=etype, started_at=now(), duration_ms=duration_ms, weight=0, payload=payload))
        audit(db, db.get(User, user_id), etype, "attempt", attempt_id, payload)
        db.commit()


def _log(user_id: str, attempt_id: str, etype: str, payload: dict, duration_ms: int = 0) -> None:
    """Write the log entry in a worker thread without waiting for it: the people on the line must hear about a change first,
    and a connection that is being torn down must not leave the others in the dark."""
    asyncio.get_running_loop().run_in_executor(None, _record, user_id, attempt_id, etype, payload, duration_ms)


async def _send(ws: WebSocket, msg: dict) -> None:
    try:
        await ws.send_json(msg)
    except Exception:  # that browser has gone; its own disconnect cleans up
        pass


async def _end_talk(room: Room, cid: str) -> None:
    holder = room.talking.pop(cid, None)
    if not holder:
        return
    examiner, user_id, since = holder
    if cid in room.candidates:
        await _send(room.candidates[cid][0], {"type": "talk-stop", "from": examiner})
    for ews in room.examiners.values():
        await _send(ews, {"type": "talking", "id": cid, "by": None})
    _log(user_id, cid, "talk_ended", {}, int((now() - since).total_seconds() * 1000))


async def _relay(room: Room, who: dict, ws: WebSocket, msg: object) -> None:
    if not isinstance(msg, dict):
        return
    kind, to = msg.get("type"), str(msg.get("to") or "")
    out = {"type": kind, "from": who["id"], **{k: msg[k] for k in ("sdp", "candidate", "streams") if k in msg}}
    if len(json.dumps(out)) > 40_000:
        return
    if who["role"] == "candidate":
        if kind in FROM_CANDIDATE and to in room.examiners:
            await _send(room.examiners[to], out)
        return
    if to not in room.candidates:
        return
    target = room.candidates[to][0]
    if kind in FROM_EXAMINER:
        await _send(target, out)
    elif kind == "talk-start":
        holder = room.talking.get(to)
        if holder and holder[0] != who["id"]:
            await _send(ws, {"type": "busy", "id": to})  # one line to a candidate at a time
            return
        if not holder:
            room.talking[to] = (who["id"], who["user_id"], now())
            await _send(target, {"type": "talk-start", "from": who["id"]})
            for ews in room.examiners.values():
                await _send(ews, {"type": "talking", "id": to, "by": who["id"]})
            _log(who["user_id"], to, "talk_started", {"by": who["name"]})
    elif kind == "talk-stop" and room.talking.get(to, (None,))[0] == who["id"]:
        await _end_talk(room, to)
    elif kind == "message":
        text = str(msg.get("text") or "").strip()[:500]
        if text:
            await _send(target, {"type": "message", "from": who["id"], "text": text})
            _log(who["user_id"], to, "message_sent", {"by": who["name"], "text": text})


@router.websocket("/live/{test_id}")
async def live(ws: WebSocket, test_id: str, access_token: str = Query("")):
    who = await asyncio.to_thread(_identify, access_token, test_id)
    if not who:
        await ws.close(code=4403)
        return
    await ws.accept()
    room = ROOMS.setdefault(test_id, Room())
    me = who["id"]
    if who["role"] == "examiner":
        room.examiners[me] = ws
        await _send(ws, {"type": "peers", "you": me, "peers": [{"id": c, "name": n} for c, (_, n) in room.candidates.items()],
                         "talking": {c: t[0] for c, t in room.talking.items()}})
        for cws, _ in list(room.candidates.values()):
            await _send(cws, {"type": "examiner", "id": me})  # the candidate's browser then offers its camera and screen
    else:
        room.candidates[me] = (ws, who["name"])
        await _send(ws, {"type": "examiners", "ids": list(room.examiners)})
        for ews in list(room.examiners.values()):
            await _send(ews, {"type": "peer", "id": me, "name": who["name"]})
    try:
        while True:
            try:
                msg = await ws.receive_json()
            except ValueError:
                continue
            await _relay(room, who, ws, msg)
    except WebSocketDisconnect:
        pass
    finally:
        if who["role"] == "candidate":
            room.candidates.pop(me, None)
            await _end_talk(room, me)
            for ews in list(room.examiners.values()):
                await _send(ews, {"type": "peer-left", "id": me})
        else:
            room.examiners.pop(me, None)
            for cid in [c for c, t in room.talking.items() if t[0] == me]:
                await _end_talk(room, cid)
            for cws, _ in list(room.candidates.values()):
                await _send(cws, {"type": "examiner-left", "id": me})
        if not room.examiners and not room.candidates:
            ROOMS.pop(test_id, None)


@router.get("/live/ice")
def ice_servers(user: User = Depends(current_user)):
    try:
        servers = json.loads(get_settings().live_ice_servers)
    except ValueError:
        servers = []
    return {"iceServers": servers if isinstance(servers, list) else []}


# ------------------------------------------------------------------ whole-exam video
PART = re.compile(r"^[a-z0-9]{1,24}$")
MAX_PIECE, MAX_FILE = 8 * 1024 * 1024, 600 * 1024 * 1024


@router.post("/attempts/{atid}/recording/{kind}")
async def upload_piece(atid: str, kind: str, part: str, seq: int, piece: UploadFile = File(...), user: User = Depends(current_user), db: Session = Depends(get_db)):
    """One 10-second piece of this candidate's video. `part` names one run of the recorder (a page reload starts a new part and a new file),
    `seq` numbers its pieces: a piece that was already stored is ignored, a missing one is counted as a gap."""
    at = db.get(Attempt, atid)
    if not at or at.candidate_id != user.id:
        raise HTTPException(404, "Attempt not found")
    if kind not in ("webcam", "screen") or not PART.match(part) or seq < 0:
        raise HTTPException(422, "Bad recording piece")
    cfg = proctoring_config(db.get(Test, at.test_id))
    if cfg["evidence"] != "video" or (kind == "screen" and not cfg["screen_share"]):
        raise HTTPException(403, "This exam does not record that video")
    if at.status != "in_progress" and (not at.submitted_at or now() - aware(at.submitted_at) > timedelta(minutes=2)):
        raise HTTPException(423, "This attempt is finished")  # the last piece may arrive just after the submit
    data = await piece.read(MAX_PIECE + 1)
    if len(data) > MAX_PIECE:
        raise HTTPException(413, "Piece too large")
    rec = db.scalar(select(Recording).where(Recording.attempt_id == atid, Recording.kind == kind, Recording.part == part))
    if not rec:
        rec = Recording(id=uid(), attempt_id=atid, kind=kind, part=part, path=f"recordings/{atid}/{kind}-{part}.webm")
        db.add(rec)
        db.flush()
    if rec.expired:
        raise HTTPException(410, "This video was deleted")
    if seq < rec.pieces:
        return {"ok": True, "duplicate": True}
    if rec.bytes + len(data) > MAX_FILE:
        raise HTTPException(413, "Recording too large")
    path = os.path.join(get_settings().storage_dir, *rec.path.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "ab") as f:
        f.write(data)
    rec.gaps += seq - rec.pieces
    rec.pieces, rec.bytes, rec.last_at = seq + 1, rec.bytes + len(data), now()
    db.commit()
    return {"ok": True, "next": rec.pieces}


@router.get("/attempts/{atid}/recordings")
def list_recordings(atid: str, user: User = Depends(RECRUIT), db: Session = Depends(get_db)):
    at = db.get(Attempt, atid)
    if not at:
        raise HTTPException(404, "Attempt not found")
    t = db.get(Test, at.test_id)
    same_org(user, t.org_id)
    days = proctoring_config(t)["video_retention_days"]
    recs = db.scalars(select(Recording).where(Recording.attempt_id == atid).order_by(Recording.kind, Recording.started_at)).all()
    return {"retention_days": days, "recordings": [
        {"id": r.id, "kind": r.kind, "bytes": r.bytes, "pieces": r.pieces, "gaps": r.gaps, "expired": r.expired,
         "started_at": aware(r.started_at).isoformat(), "deletes_at": aware(r.last_at + timedelta(days=days)).isoformat()} for r in recs]}


@router.get("/recordings/{rid}/file")
def recording_file(rid: str, user: User = Depends(RECRUIT), db: Session = Depends(get_db)):
    r = db.get(Recording, rid)
    if not r:
        raise HTTPException(404, "Not found")
    same_org(user, db.get(Test, db.get(Attempt, r.attempt_id).test_id).org_id)
    root = os.path.realpath(get_settings().storage_dir)
    p = os.path.realpath(os.path.join(root, r.path))
    if r.expired or os.path.commonpath([root, p]) != root or not os.path.exists(p):
        raise HTTPException(404, "This video was deleted or is missing")
    return FileResponse(p, media_type="video/webm")
