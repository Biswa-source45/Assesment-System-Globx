"""Request dependencies: current user, role checks, audit helper."""
from __future__ import annotations

from typing import Callable, Optional

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.security import jwt_decode
from app.db import get_db
from app.models import AuditLog, User

STAFF = {"super_admin", "org_admin", "recruiter", "test_creator", "evaluator"}


def client_ip(request: Optional[Request]) -> str:
    if request is None:
        return ""
    fwd = request.headers.get("x-forwarded-for")
    return (fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else ""))[:64]


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    auth = request.headers.get("authorization", "")
    token = auth[7:] if auth.lower().startswith("bearer ") else request.query_params.get("access_token", "")
    if not token:
        raise HTTPException(401, "Not authenticated")
    try:
        claims = jwt_decode(token)
    except ValueError as e:
        raise HTTPException(401, str(e))
    if claims.get("typ") != "access":
        raise HTTPException(401, "Wrong token type")
    u = db.get(User, claims.get("sub"))
    if not u or u.status != "active":
        raise HTTPException(401, "Account disabled")
    request.state.user = u
    return u


# Who may do what. The one place to read or change it: every router uses these groups, and /auth/me sends the same answers to the
# browser (`can`), so a screen shows exactly the buttons the server will accept. A Super Admin always passes.
ROLE_GROUPS = {
    "author": ("test_creator", "org_admin"),                          # create and edit exams, questions, departments; publish
    "recruit": ("recruiter", "test_creator", "org_admin"),            # participants and their logins, extend/end/re-open, export
    "view": ("recruiter", "test_creator", "evaluator", "org_admin"),  # see exams, the live monitor, candidates and reports
    "bank": ("test_creator", "evaluator", "org_admin"),               # read questions with their answer keys
    "evaluate": ("evaluator", "org_admin"),                           # mark answers and override AI marks
    "admin": ("org_admin",),                                          # users, audit log, mail outbox
}


def require(*roles: str) -> Callable:
    def dep(user: User = Depends(current_user)) -> User:
        if user.has("super_admin") or user.has(*roles):
            return user
        raise HTTPException(403, "You do not have permission for this action")
    return dep


AUTHOR, RECRUIT, VIEW, BANK, EVAL, ADMIN = (require(*ROLE_GROUPS[g]) for g in ("author", "recruit", "view", "bank", "evaluate", "admin"))
SUPER = require("super_admin")


def permissions(user: User) -> dict:
    return {**{g: user.has("super_admin", *roles) for g, roles in ROLE_GROUPS.items()}, "super": user.has("super_admin")}


def staff(user: User = Depends(current_user)) -> User:
    if not user.has(*STAFF):
        raise HTTPException(403, "Staff only")
    return user


def same_org(user: User, org_id: Optional[str]) -> None:
    if user.has("super_admin"):
        return
    if org_id != user.org_id:
        raise HTTPException(404, "Not found")


def audit(db: Session, user: Optional[User], action: str, entity: str, entity_id: str = "",
          detail: Optional[dict] = None, request: Optional[Request] = None, org_id: Optional[str] = None) -> None:
    db.add(AuditLog(org_id=org_id or (user.org_id if user else None), actor_id=user.id if user else None,
                    actor_email=user.email if user else "", action=action, entity=entity, entity_id=str(entity_id),
                    detail=detail or {}, ip=client_ip(request)))
