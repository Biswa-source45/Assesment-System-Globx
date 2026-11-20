"""Invites: parse pasted text / CSV / XLSX, create candidate accounts and assignments, send mails."""
from __future__ import annotations

import csv
import io
import re
import secrets
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password, new_token, sha256
from app.models import Assignment, Attempt, Test, User, UserRole, aware, now, uid
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
               "Please use a laptop/desktop with Chrome, Edge or Firefox, a webcam and a microphone.\n\nKAUTILYA by GLOBX",
               "invite", test.org_id)
    a.sent_at = now()


def _first_word(name: str) -> str:
    """The first word of a name in lower case, letters and digits only ('Asha Rao' -> 'asha')."""
    return re.sub(r"[^a-z0-9]", "", (name.split() or ["cand"])[0].lower())[:20] or "cand"


def _free_username(db: Session, org_id: str, name: str) -> str:
    """The first word of the name; a number is added only when somebody already has it (asha, asha2, asha3...)."""
    base = _first_word(name)
    cand, n = base, 1
    while db.scalar(select(User.id).where(User.org_id == org_id, User.username == cand)):
        n += 1
        cand = f"{base}{n}"
    return cand


def login_password(name: str) -> str:
    """Readable and easy to type from a sheet: 3 letters of the first name, @globx, 3 random digits ('Asha Rao' -> 'ash@globx472')."""
    return f"{_first_word(name)[:3]}@globx{secrets.randbelow(900) + 100}"


def _login_account(db: Session, org_id: str, email: str) -> Optional[User]:
    return db.scalar(select(User).where(User.org_id == org_id, func.lower(User.email) == email))


def _is_exam_login(u: User) -> bool:
    """A participant's own login (a candidate-only account with a username), as opposed to staff or a person who signs in by e-mail."""
    return bool(u.username) and u.role_names == ["candidate"]


def parse_participants(db: Session, org_id: str, lines: List[str], email_required: bool = False, test: Optional[Test] = None) -> List[Tuple[str, Optional[str]]]:
    """Each line is 'Name' or 'Name, email' (a comma, semicolon or tab); with `email_required` the email must be there. The whole list is checked first,
    so a bad line creates nobody. An email that already belongs to somebody's exam login is allowed (that person is added to this exam too) unless they
    are in this exam already or taking another exam right now."""
    people, seen, problems = [], set(), []
    for i, raw in enumerate(lines, 1):
        name, *rest = re.split(r"\s*[,;\t]\s*", raw.strip(), maxsplit=1)
        if not name:
            continue
        email = rest[0].lower() if rest and rest[0] else None
        if not email and email_required:
            problems.append(f"Line {i}: add the email after the name, like  {name}, name@example.com")
        elif email and not EMAIL.match(email):
            problems.append(f"Line {i}: '{email}' is not a valid email. Type one person per line (press Enter between names); only an email goes after a comma")
        elif email and email in seen:
            problems.append(f"Line {i}: {email} is on the list twice")
        elif email and (u := _login_account(db, org_id, email)):
            if not _is_exam_login(u):
                problems.append(f"Line {i}: {email} belongs to a staff or e-mail login. Use a different email")
            elif test and db.scalar(select(Assignment.id).where(Assignment.test_id == test.id, Assignment.candidate_id == u.id)):
                problems.append(f"Line {i}: {email} is already in this exam")
            elif db.scalar(select(Attempt.id).where(Attempt.candidate_id == u.id, Attempt.status == "in_progress")):
                problems.append(f"Line {i}: {email} is taking another exam right now. Add them after it ends")
        seen.add(email)
        people.append((name, email))
    if problems:
        raise HTTPException(422, "; ".join(problems))
    return people


def create_participants(db: Session, test: Test, people: List[Tuple[str, Optional[str]]]) -> List[Dict]:
    """Exam-specific logins: one new candidate per person with a username and a password made from the name; a person whose email already has an
    exam login keeps that login (same username, a new password) and gets a new place in this exam.
    Passwords are returned here once; only the hash is stored."""
    out = []
    for name, email in people:
        password = login_password(name)
        u = _login_account(db, test.org_id, email) if email else None
        reused = u is not None
        if reused:  # checked by parse_participants: an exam login that is free to be added
            u.password_hash, u.failed_logins = hash_password(password), 0
            username, name = u.username, u.name or name
        else:
            username = _free_username(db, test.org_id, name)
            u = User(id=uid(), org_id=test.org_id, email=email or f"{username}@exam.local", username=username, name=name,
                     password_hash=hash_password(password))
            u.roles = [UserRole(role="candidate")]
            db.add(u)
        db.flush()
        a = Assignment(id=uid(), test_id=test.id, candidate_id=u.id, token_hash=sha256(new_token(32)),
                       sent_at=now())  # no expiry of its own: the exam window decides when they may start
        db.add(a)
        db.flush()
        out.append({"assignment_id": a.id, "name": name, "username": username, "password": password, "existing": reused})
    return out


def edit_participant(db: Session, a: Assignment, name: str, email: str) -> None:
    """Correct a participant's name and email. The username and the password stay; nothing is mailed."""
    u = a.candidate
    if not _is_exam_login(u):
        raise HTTPException(422, "Only a participant's own exam login can be edited here")
    name = " ".join((name or "").split())
    email = (email or "").strip().lower()
    if not name or len(name) > 120:
        raise HTTPException(422, "Type the full name (up to 120 letters)")
    if not EMAIL.match(email):
        raise HTTPException(422, f"'{email}' is not a valid email address")
    if email != (u.email or "").lower():
        if db.scalar(select(User.id).where(User.org_id == u.org_id, func.lower(User.email) == email, User.id != u.id)):
            raise HTTPException(422, f"{email} is already used by another login")
        u.email = email
    u.name = name


# ---------------------------------------------------------------- the student sheet (CSV or Excel): Full name, Email
_HEAD_NAME = {"full name", "fullname", "name", "student name", "candidate name", "participant name", "student", "candidate"}
_HEAD_EMAIL = {"email", "e-mail", "email address", "e-mail address", "email id", "mail id", "mail"}
SHEET_LIMIT = 200


def _sheet_rows(data: bytes, filename: str) -> List[List[str]]:
    name = (filename or "").lower()
    rows: List[List[str]] = []
    if name.endswith((".xlsx", ".xlsm")):
        import openpyxl
        try:
            ws = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True).active
            for r in ws.iter_rows(values_only=True):
                rows.append([("" if v is None else str(v)).strip() for v in r])
                if len(rows) > 5000:
                    break
        except Exception:
            raise HTTPException(422, "This Excel file could not be read. Open it in Excel and save it again as .xlsx or CSV")
    elif name.endswith((".csv", ".tsv", ".txt")):
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("cp1252", errors="replace")  # a sheet saved by older Excel
        first = text.split("\n", 1)[0]
        delim = max(",;\t", key=first.count) if any(d in first for d in ",;\t") else ","
        for r in csv.reader(io.StringIO(text), delimiter=delim):
            rows.append([c.strip() for c in r])
            if len(rows) > 5000:
                break
    else:
        raise HTTPException(422, "This file type is not supported. Save the sheet as CSV or Excel (.xlsx) and upload that")
    return rows


def parse_sheet(data: bytes, filename: str) -> Dict:
    """The people in a sheet as "Full name, email" lines for the participants box, plus a problem for every row that cannot be used. Nothing is created.
    The columns are found by their headings (Full name, Email); with no headings the first column is the name and the second the email."""
    rows = [(i + 1, r) for i, r in enumerate(_sheet_rows(data, filename)) if any(c for c in r)]  # (the sheet's own row number, its cells)
    if not rows:
        raise HTTPException(422, "The sheet is empty")
    head = [c.strip().lower() for c in rows[0][1]]
    has_head = any(c in _HEAD_NAME or c in _HEAD_EMAIL for c in head)
    ncol = max(len(r) for _, r in rows)
    if has_head:
        e_col = next((i for i, c in enumerate(head) if c in _HEAD_EMAIL), None)
        n_col = next((i for i, c in enumerate(head) if c in _HEAD_NAME), None)
        if n_col is None:
            n_col = next((i for i in range(ncol) if i != e_col), 0)
        if e_col is None:
            e_col = next((i for i in range(ncol) if i != n_col), 1)
        body = rows[1:]
    else:
        n_col, e_col = 0, 1
        if len(rows[0][1]) > 1 and "@" in rows[0][1][0] and "@" not in rows[0][1][1]:
            n_col, e_col = 1, 0  # the columns are the other way round
        body = rows
    lines, problems, seen, samples = [], [], set(), 0
    for no, r in body:
        cell = lambda i: r[i].strip() if i < len(r) else ""  # noqa: E731
        name, email = " ".join(re.sub(r"[,;\t]", " ", cell(n_col)).split()), cell(e_col).lower()
        if not name and not email:
            continue
        if email.endswith("@example.com"):  # the sample rows of the downloadable sheet
            samples += 1
            continue
        if not name:
            problems.append(f"Row {no}: the full name is missing")
        elif not email:
            problems.append(f"Row {no}: the email of {name} is missing")
        elif not EMAIL.match(email):
            problems.append(f"Row {no}: '{email}' is not a valid email")
        elif email in seen:
            problems.append(f"Row {no}: {email} is in the sheet twice")
        else:
            seen.add(email)
            lines.append(f"{name}, {email}")
    if len(lines) + len(problems) > SHEET_LIMIT:
        raise HTTPException(422, f"The sheet has {len(lines) + len(problems)} people. Add up to {SHEET_LIMIT} at a time: split the sheet")
    return {"lines": lines, "problems": problems, "samples": samples}


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
