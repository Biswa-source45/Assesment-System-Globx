"""Default departments for a new organisation, and the question types each one offers."""
from __future__ import annotations

from datetime import timedelta
from typing import Dict

from sqlalchemy.orm import Session

from app.models import Department, now, uid

PEOPLE = ["mcq_single", "mcq_multi", "short", "long"]
DEFAULTS = [("Technical", PEOPLE + ["coding", "sql"]), ("HR", PEOPLE), ("Finance", PEOPLE), ("Operations", PEOPLE), ("General", PEOPLE)]


def create_defaults(db: Session, org_id: str) -> Dict[str, Department]:
    out = {}
    for i, (name, types) in enumerate(DEFAULTS):  # staggered, so the list keeps this order (it is sorted by creation time)
        out[name] = Department(id=uid(), org_id=org_id, name=name, question_types=list(types), created_at=now() + timedelta(milliseconds=i))
        db.add(out[name])
    db.flush()
    return out
