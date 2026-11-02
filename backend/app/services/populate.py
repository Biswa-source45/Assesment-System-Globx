"""Auto populate: pick random questions from the bank for an exam section."""
from __future__ import annotations

import random
from typing import Dict, List, Optional, Sequence, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Question, Test

DIFFICULTIES = ("easy", "medium", "hard")


def _publishable(q: Question) -> bool:
    """A coding or SQL question whose solution does not pass cannot go into a published exam, so it is never picked."""
    return not (q.type in ("coding", "sql") and not (q.config or {}).get("validated"))


def pick_questions(db: Session, test: Test, mix: Dict[str, int], department_id: Optional[str] = None,
                   types: Sequence[str] = (), skills: Sequence[str] = (),
                   rng: Optional[random.Random] = None) -> Tuple[List[Question], Dict[str, int]]:
    """Random approved questions that match, `mix` giving how many of each difficulty. Questions already in the exam are
    left out. Returns (picked, shortfall): shortfall says how many of a difficulty the bank could not supply."""
    rng = rng or random.SystemRandom()
    stmt = select(Question).where(Question.org_id == test.org_id, Question.status == "approved", Question.group_id.is_(None))
    if department_id:
        stmt = stmt.where(Question.department_id == department_id)
    if types:
        stmt = stmt.where(Question.type.in_(list(types)))
    used = {it.question_id for s in test.sections for it in s.items if it.question_id}
    wanted = {s.strip().lower() for s in skills if s.strip()}
    pool = [q for q in db.scalars(stmt).all()
            if q.id not in used and _publishable(q) and (not wanted or wanted & {x.lower() for x in q.skills or []})]
    picked: List[Question] = []
    shortfall: Dict[str, int] = {}
    for diff in DIFFICULTIES:
        want = mix.get(diff, 0)
        same = [q for q in pool if q.difficulty == diff]
        picked += rng.sample(same, min(want, len(same)))
        if len(same) < want:
            shortfall[diff] = want - len(same)
    return picked, shortfall
