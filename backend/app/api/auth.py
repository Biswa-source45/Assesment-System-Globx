"""Authentication: staff password (+TOTP MFA), candidate email OTP, JWT access + rotating refresh tokens."""
from __future__ import annotations

from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.deps import STAFF, audit, current_user, permissions
from app.core.security import (hash_otp, hash_password, jwt_encode, new_otp, new_token, new_totp_secret,
                               password_policy_error, sha256, totp_uri, totp_verify, verify_password)
from app.db import get_db
from app.models import (Assignment, Organization, OtpCode, RefreshToken, Test, User, aware, now, uid)
from app.services.mail import queue_mail

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    email: str
    password: str
    totp: Optional[str] = None


class OtpRequestIn(BaseModel):
    email: str
    invite_token: Optional[str] = None


class OtpVerifyIn(BaseModel):
    email: str
    otp: str
    invite_token: Optional[str] = None


class RefreshIn(BaseModel):
    refresh_token: str


class PasswordIn(BaseModel):
    current_password: str
    new_password: str


def user_out(u: User, db: Session) -> dict:
    org = db.get(Organization, u.org_id)
    return {"id": u.id, "email": u.email, "name": u.name, "roles": u.role_names, "org_id": u.org_id,
            "org_name": org.name if org else "", "mfa_enabled": u.mfa_enabled,
            "is_staff": bool(set(u.role_names) & STAFF), "can": permissions(u)}


def issue_tokens(db: Session, u: User, single_session: bool = False) -> dict:
    s = get_settings()
    if single_session:
        for rt in db.scalars(select(RefreshToken).where(RefreshToken.user_id == u.id, RefreshToken.revoked.is_(False))).all():
            rt.revoked = True
    raw = new_token(32)
    db.add(RefreshToken(id=uid(), user_id=u.id, token_hash=sha256(raw), expires_at=now() + timedelta(hours=s.refresh_token_hours)))
    access = jwt_encode({"sub": u.id, "typ": "access", "roles": u.role_names, "org": u.org_id}, s.access_token_minutes * 60)
    u.last_login_at = now()
    return {"access_token": access, "refresh_token": raw, "token_type": "bearer",
            "expires_in": s.access_token_minutes * 60, "user": user_out(u, db)}


@router.post("/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    users = db.scalars(select(User).where(or_(func.lower(User.email) == email, func.lower(User.username) == email),
                                           User.password_hash.is_not(None))).all()
    typed = {body.password, body.password.strip()}  # a space pasted along with the password must not cost a login
    for u in users:
        if u.failed_logins >= 10:
            raise HTTPException(423, "Account locked after 10 failed logins. Ask an administrator to unlock it.")
        if any(verify_password(p, u.password_hash) for p in typed):
            if u.status != "active":
                raise HTTPException(403, "Account is disabled")
            if u.mfa_enabled:
                if not body.totp:
                    raise HTTPException(401, detail={"mfa_required": True, "message": "Enter the 6-digit code from your authenticator app"})
                if not totp_verify(u.mfa_secret or "", body.totp):
                    raise HTTPException(401, "Invalid authenticator code")
            u.failed_logins = 0
            out = issue_tokens(db, u, single_session=not u.has(*STAFF))  # candidates: one session at a time
            out["mfa_setup_required"] = bool(get_settings().require_admin_mfa and u.has("super_admin", "org_admin")
                                             and not u.mfa_enabled)
            audit(db, u, "login", "user", u.id, request=request)
            db.commit()
            return out
    for u in users:
        u.failed_logins += 1
    db.commit()
    raise HTTPException(401, "Invalid email or password")


@router.post("/refresh")
def refresh(body: RefreshIn, db: Session = Depends(get_db)):
    rt = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == sha256(body.refresh_token)))
    if not rt or rt.revoked or aware(rt.expires_at) < now():
        raise HTTPException(401, "Session expired, please sign in again")
    rt.revoked = True  # rotation
    u = db.get(User, rt.user_id)
    if not u or u.status != "active":
        raise HTTPException(401, "Account disabled")
    out = issue_tokens(db, u)
    db.commit()
    return out


@router.post("/logout")
def logout(body: RefreshIn, db: Session = Depends(get_db)):
    rt = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == sha256(body.refresh_token)))
    if rt:
        rt.revoked = True
        db.commit()
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return user_out(user, db)


@router.post("/password")
def change_password(body: PasswordIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(400, "Current password is wrong")
    err = password_policy_error(body.new_password)
    if err:
        raise HTTPException(400, err)
    user.password_hash = hash_password(body.new_password)
    audit(db, user, "password_change", "user", user.id, request=request)
    db.commit()
    return {"ok": True}


@router.post("/mfa/setup")
def mfa_setup(user: User = Depends(current_user), db: Session = Depends(get_db)):
    user.mfa_secret = new_totp_secret()
    user.mfa_enabled = False
    db.commit()
    return {"secret": user.mfa_secret, "otpauth_uri": totp_uri(user.mfa_secret, user.email)}


@router.post("/mfa/enable")
def mfa_enable(body: dict, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not user.mfa_secret or not totp_verify(user.mfa_secret, str(body.get("code", ""))):
        raise HTTPException(400, "Code does not match. Check the time on your phone and try again.")
    user.mfa_enabled = True
    audit(db, user, "mfa_enabled", "user", user.id, request=request)
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ candidates
def _assignment_by_token(db: Session, token: str) -> Assignment:
    a = db.scalar(select(Assignment).where(Assignment.token_hash == sha256(token or "")))
    if not a:
        raise HTTPException(404, "This invitation link is invalid or has been replaced by a newer one")
    return a


@router.get("/invite/{token}")
def invite_info(token: str, db: Session = Depends(get_db)):
    a = _assignment_by_token(db, token)
    t = db.get(Test, a.test_id)
    org = db.get(Organization, t.org_id)
    email = a.candidate.email
    masked = email[0] + "***" + email[email.index("@") - 1:] if "@" in email and email.index("@") > 1 else email
    return {"test": {"title": t.title, "duration_min": t.duration_min, "description": t.description,
                     "starts_at": aware(t.starts_at).isoformat() if t.starts_at else None,
                     "ends_at": aware(t.ends_at).isoformat() if t.ends_at else None},
            "organization": org.name if org else "", "email_hint": masked, "status": a.status,
            "expires_at": aware(a.expires_at).isoformat() if a.expires_at else None}


@router.post("/otp/request")
def otp_request(body: OtpRequestIn, db: Session = Depends(get_db)):
    s = get_settings()
    email = body.email.strip().lower()
    if body.invite_token:
        a = _assignment_by_token(db, body.invite_token)
        if a.candidate.email.lower() != email:
            raise HTTPException(400, "Please use the email address this invitation was sent to")
        if a.status in ("expired", "cancelled"):
            raise HTTPException(410, "This invitation has expired")
        org_id = a.candidate.org_id
    else:
        u = db.scalar(select(User).where(func.lower(User.email) == email))
        if not u or not u.has("candidate"):
            return {"sent": True, "message": "If this email has an invitation, a code has been sent."}
        org_id = u.org_id
    hour_ago = now() - timedelta(hours=1)
    recent = db.scalars(select(OtpCode).where(OtpCode.email == email)).all()
    if sum(1 for o in recent if aware(o.created_at) > hour_ago) >= s.otp_max_sends_per_hour:
        raise HTTPException(429, "Too many codes requested. Please wait and try again later.")
    last = max((aware(o.created_at) for o in recent), default=None)
    if last and (now() - last).total_seconds() < 60:
        raise HTTPException(429, f"Please wait {60 - int((now() - last).total_seconds())} s before requesting a new code")
    code = new_otp()
    db.add(OtpCode(id=uid(), email=email, code_hash=hash_otp(email, code), expires_at=now() + timedelta(minutes=s.otp_minutes)))
    queue_mail(db, email, "Your APTIVON sign-in code",
               f"Your one-time sign-in code is {code}. It is valid for {s.otp_minutes} minutes.\n"
               "If you did not request it, ignore this email.", "otp", org_id)
    db.commit()
    out = {"sent": True, "valid_minutes": s.otp_minutes, "resend_after_s": 60}
    if s.demo_mode and not s.smtp_host:
        out["demo_otp"] = code
        out["message"] = "DEMO MODE: email is not configured, so the code is shown here."
    return out


@router.post("/otp/verify")
def otp_verify(body: OtpVerifyIn, request: Request, db: Session = Depends(get_db)):
    s = get_settings()
    email = body.email.strip().lower()
    o = db.scalar(select(OtpCode).where(OtpCode.email == email, OtpCode.used.is_(False)).order_by(OtpCode.created_at.desc()))
    if not o or aware(o.expires_at) < now():
        raise HTTPException(410, "The code has expired. Request a new one.")
    if o.attempts >= s.otp_max_attempts:
        raise HTTPException(429, "Too many wrong codes. Request a new one.")
    o.attempts += 1
    if o.code_hash != hash_otp(email, body.otp.strip()):
        db.commit()
        raise HTTPException(400, f"Wrong code. {s.otp_max_attempts - o.attempts} attempts left.")
    o.used = True
    asg_id = None
    if body.invite_token:
        a = _assignment_by_token(db, body.invite_token)
        u = a.candidate
        asg_id = a.id
    else:
        u = db.scalar(select(User).where(func.lower(User.email) == email))
    if not u or u.status != "active":
        raise HTTPException(403, "Account disabled")
    out = issue_tokens(db, u, single_session=True)
    out["assignment_id"] = asg_id
    audit(db, u, "otp_login", "user", u.id, request=request)
    db.commit()
    return out
