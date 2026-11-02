"""Departments: which team an exam is for, and which question types its authors can use there."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import audit, require
from app.db import get_db
from app.models import QTYPES, Department, Question, Test, User

router = APIRouter(tags=["departments"])
AUTHOR = require("test_creator", "org_admin")
VIEW = require("recruiter", "org_admin", "test_creator", "evaluator")


class DepartmentIn(BaseModel):
    name: str
    question_types: List[str]


def _out(db: Session, d: Department) -> dict:
    return {"id": d.id, "name": d.name, "question_types": d.question_types,
            "questions": db.scalar(select(func.count(Question.id)).where(Question.department_id == d.id, Question.status != "archived")),
            "exams": db.scalar(select(func.count(Test.id)).where(Test.department_id == d.id, Test.status != "archived"))}


def _mine(db: Session, did: str, user: User) -> Department:
    d = db.get(Department, did)
    if not d or d.org_id != user.org_id:
        raise HTTPException(404, "Department not found")
    return d


def _clean(db: Session, body: DepartmentIn, user: User, own_id: str = "") -> tuple:
    name = body.name.strip()
    if not name or len(name) > 80:
        raise HTTPException(422, "Give the department a name of up to 80 characters")
    types = [t for t in QTYPES if t in body.question_types]  # canonical order; unknown types are dropped
    if not types:
        raise HTTPException(422, "Choose at least one question type")
    clash = db.scalar(select(Department).where(Department.org_id == user.org_id, func.lower(Department.name) == name.lower()))
    if clash and clash.id != own_id:
        raise HTTPException(409, f"There is already a department called {clash.name}")
    return name, types


@router.get("/departments")
def list_departments(user: User = Depends(VIEW), db: Session = Depends(get_db)):
    return [_out(db, d) for d in db.scalars(select(Department).where(Department.org_id == user.org_id).order_by(Department.created_at, Department.name)).all()]


@router.post("/departments")
def create_department(body: DepartmentIn, request: Request, user: User = Depends(AUTHOR), db: Session = Depends(get_db)):
    name, types = _clean(db, body, user)
    d = Department(org_id=user.org_id, name=name, question_types=types)
    db.add(d)
    db.flush()
    audit(db, user, "create", "department", d.id, {"name": name}, request)
    db.commit()
    return _out(db, d)


@router.put("/departments/{did}")
def update_department(did: str, body: DepartmentIn, request: Request, user: User = Depends(AUTHOR), db: Session = Depends(get_db)):
    d = _mine(db, did, user)
    d.name, d.question_types = _clean(db, body, user, own_id=d.id)
    audit(db, user, "update", "department", d.id, {"name": d.name}, request)
    db.commit()
    return _out(db, d)


@router.delete("/departments/{did}")
def delete_department(did: str, request: Request, user: User = Depends(AUTHOR), db: Session = Depends(get_db)):
    d = _mine(db, did, user)
    questions = db.scalar(select(func.count(Question.id)).where(Question.department_id == d.id))
    exams = db.scalar(select(func.count(Test.id)).where(Test.department_id == d.id))
    if questions or exams:
        raise HTTPException(409, f"{d.name} is used by {questions} questions and {exams} exams. Move or remove them first.")
    db.delete(d)
    audit(db, user, "delete", "department", did, {"name": d.name}, request)
    db.commit()
    return {"ok": True}
