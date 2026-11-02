"""Invites: parse pasted text / CSV / XLSX, create candidate accounts and assignments, send mails."""
from __future__ import annotations

import csv
import io
import re
import secrets
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password, new_password, new_token, sha256
from app.models import Assignment, Test, User, UserRole, aware, now, uid
from app.services.mail import queue_mail

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


def parse_rows(text: Optional[str] = None, filename: str = "", data: Optional[bytes] = None) -> List[Dict]:
    rows: List[List[str]] = []
    if data is not None and filename.lower().endswith((".xlsx", ".xlsm")):
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = wb.active
        for r in ws.iter_rows(values_only=True):
            rows.append([("" if v is None else str(v)).strip() for v in r])
            if len(rows) > 50001:
                break
    else:
        if data is not None:
            text = data.decode("utf-8-sig", errors="replace")
        sample = (text or "")[:2000]
        delim = "\t" if "\t" in sample else ","
        for r in csv.reader(io.StringIO(text or ""), delimiter=delim):
            rows.append([c.strip() for c in r])
            if len(rows) > 20001:
                break
    out: List[Dict] = []
    seen = set()
    for i, r in enumerate(rows):
        if not r or not any(r):
            continue
        if i == 0 and r[0].lower() in ("email", "e-mail", "email address"):
            continue
        email = r[0].lower()
        first = r[1] if len(r) > 1 else ""
        last = r[2] if len(r) > 2 else ""
        phone = r[3] if len(r) > 3 else ""
        tag = r[4] if len(r) > 4 else ""
        status = "valid"
        if not EMAIL.match(email):
            status = "invalid_email"
        elif email in seen:
            status = "duplicate"
        seen.add(email)
        out.append({"row": i + 1, "email": email, "first_name": first, "last_name": last, "phone": phone,
                    "tag": tag, "status": status})
    return out


def invite_link(token: str) -> str:
    return f"{get_settings().public_base_url.rstrip('/')}/#/invite/{token}"


def send_invite_mail(db: Session, a: Assignment, token: Optional[str]) -> None:
    test = db.get(Test, a.test_id)
    u = db.get(User, a.candidate_id)
    if token is None:  # scheduled send: rotate the token so the link is fresh
        token = new_token(32)
        a.token_hash = sha256(token)
    exp = aware(a.expires_at).strftime("%d %b %Y %H:%M UTC") if a.expires_at else "the end of the test window"
    queue_mail(db, u.email, f"Invitation: {test.title}",
               f"Dear {u.name or u.email},\n\nYou are invited to take the assessment '{test.title}' "
               f"({test.duration_min} minutes).\n\nStart here: {invite_link(token)}\n\n"
               f"The link is personal and valid until {exp}. You will sign in with a one-time code sent to this email.\n"
               "Please use a laptop/desktop with Chrome, Edge or Firefox, a webcam and a microphone.\n\nGLOBX Assess",
               "invite", test.org_id)
    a.sent_at = now()


def _free_username(db: Session, org_id: str, name: str) -> str:
    base = re.sub(r"[^a-z0-9]", "", (name.split() or ["cand"])[0].lower())[:12] or "cand"
    while True:
        cand = f"{base}{secrets.randbelow(900) + 100}"
        if not db.scalar(select(User.id).where(User.org_id == org_id, User.username == cand)):
            return cand


def create_participants(db: Session, test: Test, names: List[str]) -> List[Dict]:
    """Exam-specific logins: one new candidate per name with a generated username and password.
    Passwords are returned here once; only the hash is stored."""
    out = []
    for raw in names:
        name = raw.strip()
        if not name:
            continue
        username, password = _free_username(db, test.org_id, name), new_password()
        u = User(id=uid(), org_id=test.org_id, email=f"{username}@exam.local", username=username, name=name,
                 password_hash=hash_password(password))
        u.roles = [UserRole(role="candidate")]
        db.add(u)
        db.flush()
        a = Assignment(id=uid(), test_id=test.id, candidate_id=u.id, token_hash=sha256(new_token(32)),
                       sent_at=now())  # no expiry of its own: the exam window decides when they may start
        db.add(a)
        db.flush()
        out.append({"assignment_id": a.id, "name": name, "username": username, "password": password})
    return out


def create_invites(db: Session, test: Test, rows: List[Dict], expires_at: Optional[datetime],
                   schedule_at: Optional[datetime], extra_time_min: int = 0) -> Dict:
    created, skipped, links = 0, 0, []
    for r in rows:
        if r.get("status", "valid") != "valid":
            skipped += 1
            continue
        email = r["email"].lower()
        u = db.scalar(select(User).where(User.org_id == test.org_id, User.email == email))
        if not u:
            u = User(id=uid(), org_id=test.org_id, email=email,
                     name=" ".join(x for x in (r.get("first_name"), r.get("last_name")) if x).strip(),
                     phone=r.get("phone", ""))
            u.roles = [UserRole(role="candidate")]
            db.add(u)
            db.flush()
        elif not u.has("candidate"):
            u.roles.append(UserRole(role="candidate"))
        a = db.scalar(select(Assignment).where(Assignment.test_id == test.id, Assignment.candidate_id == u.id))
        token = new_token(32)
        if a:
            if a.status not in ("invited", "expired", "cancelled"):
                skipped += 1
                continue
            a.status = "invited"
            a.token_hash = sha256(token)
        else:
            a = Assignment(id=uid(), test_id=test.id, candidate_id=u.id, token_hash=sha256(token))
            db.add(a)
        a.expires_at = expires_at or test.ends_at
        a.extra_time_min = extra_time_min
        a.tag = r.get("tag", "")
        a.scheduled_at = schedule_at
        a.sent_at = None
        if not schedule_at or schedule_at <= now():
            send_invite_mail(db, a, token)
        links.append({"email": email, "link": invite_link(token), "scheduled": bool(schedule_at and schedule_at > now())})
        created += 1
    return {"created": created, "skipped": skipped, "links": links}
