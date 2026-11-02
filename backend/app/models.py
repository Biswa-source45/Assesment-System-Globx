"""ORM models. Type-specific question attributes live in Question.config (JSON) for the MVP.

Marks are stored as Numeric(8,2) (returned as float) so that -0.5 and 0.25 steps are exact enough.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (JSON, Boolean, DateTime, Float, ForeignKey, Integer, Numeric, String, Text,
                        UniqueConstraint, Index)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def uid() -> str:
    return uuid.uuid4().hex


def now() -> datetime:
    return datetime.now(timezone.utc)


def aware(dt: Optional[datetime]) -> Optional[datetime]:
    """SQLite returns naive datetimes - treat them as UTC."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


Money = Numeric(8, 2, asdecimal=False)
TS = DateTime(timezone=True)

ROLES = ["super_admin", "org_admin", "recruiter", "test_creator", "evaluator", "candidate"]
QTYPES = ["mcq_single", "mcq_multi", "short", "long", "coding", "sql"]


# ------------------------------------------------------------------ tenancy & users
class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    plan: Mapped[str] = mapped_column(String(32), default="enterprise")
    credits: Mapped[int] = mapped_column(Integer, default=0)
    data_region: Mapped[str] = mapped_column(String(32), default="IN")
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = mapped_column(TS, default=now)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("org_id", "email", name="uq_user_org_email"),
                      UniqueConstraint("org_id", "username", name="uq_user_org_username"))
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    email: Mapped[str] = mapped_column(String(255), index=True)
    username: Mapped[Optional[str]] = mapped_column(String(64), index=True, nullable=True)  # candidate login id
    name: Mapped[str] = mapped_column(String(200), default="")
    phone: Mapped[str] = mapped_column(String(32), default="")
    password_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    mfa_secret: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="active")
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(TS, default=now)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(TS, nullable=True)
    roles: Mapped[list["UserRole"]] = relationship(cascade="all, delete-orphan", lazy="selectin")

    @property
    def role_names(self) -> list[str]:
        return sorted({r.role for r in self.roles})

    def has(self, *roles: str) -> bool:
        return bool(set(roles) & set(self.role_names))


class UserRole(Base):
    __tablename__ = "user_roles"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[str] = mapped_column(String(32), primary_key=True)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(TS)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(TS, default=now)


class OtpCode(Base):
    __tablename__ = "otp_codes"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    email: Mapped[str] = mapped_column(String(255), index=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(TS)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    used: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(TS, default=now)


# ------------------------------------------------------------------ question library
class QuestionGroup(Base):
    """Stimulus shared by Linked MCQs (passage / case study / table / code)."""
    __tablename__ = "question_groups"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    stimulus: Mapped[str] = mapped_column(Text, default="")
    skills: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(TS, default=now)
    questions: Mapped[list["Question"]] = relationship(back_populates="group", order_by="Question.created_at")


class Question(Base):
    __tablename__ = "questions"
    __table_args__ = (Index("ix_q_org_type_status", "org_id", "type", "status"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    type: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text, default="")
    difficulty: Mapped[str] = mapped_column(String(8), default="medium")
    skills: Mapped[list] = mapped_column(JSON, default=list)
    marks: Mapped[float] = mapped_column(Money, default=1)
    negative_marks: Mapped[float] = mapped_column(Money, default=0)
    group_id: Mapped[Optional[str]] = mapped_column(ForeignKey("question_groups.id"), nullable=True, index=True)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="approved")  # draft|approved|archived
    created_by: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TS, default=now)
    updated_at: Mapped[datetime] = mapped_column(TS, default=now, onupdate=now)
    group: Mapped[Optional[QuestionGroup]] = relationship(back_populates="questions")
    cases: Mapped[list["TestCase"]] = relationship(cascade="all, delete-orphan", order_by="TestCase.ordinal",
                                                   lazy="selectin")


class TestCase(Base):
    """Programming input/expected pair, or SQL dataset (input = INSERT script, expected = JSON rows)."""
    __tablename__ = "test_cases"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    question_id: Mapped[str] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    visibility: Mapped[str] = mapped_column(String(8), default="open")  # open|hidden
    input: Mapped[str] = mapped_column(Text, default="")
    expected: Mapped[str] = mapped_column(Text, default="")
    weight: Mapped[float] = mapped_column(Money, default=1)
    purpose: Mapped[str] = mapped_column(String(120), default="")


# ------------------------------------------------------------------ tests
class Test(Base):
    __tablename__ = "tests"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    instructions: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft|published|closed|archived
    duration_min: Mapped[int] = mapped_column(Integer, default=60)
    starts_at: Mapped[Optional[datetime]] = mapped_column(TS, nullable=True)
    ends_at: Mapped[Optional[datetime]] = mapped_column(TS, nullable=True)
    access_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    cutoff: Mapped[float] = mapped_column(Money, default=0)
    shuffle_questions: Mapped[bool] = mapped_column(Boolean, default=True)
    shuffle_options: Mapped[bool] = mapped_column(Boolean, default=True)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TS, default=now)
    updated_at: Mapped[datetime] = mapped_column(TS, default=now, onupdate=now)
    sections: Mapped[list["Section"]] = relationship(cascade="all, delete-orphan", order_by="Section.order",
                                                     lazy="selectin")


class Section(Base):
    __tablename__ = "sections"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    test_id: Mapped[str] = mapped_column(ForeignKey("tests.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    order: Mapped[int] = mapped_column(Integer, default=0)
    timer_min: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    shuffle: Mapped[bool] = mapped_column(Boolean, default=True)
    lock_nav: Mapped[bool] = mapped_column(Boolean, default=False)
    min_score: Mapped[Optional[float]] = mapped_column(Money, nullable=True)
    allow_negative: Mapped[bool] = mapped_column(Boolean, default=False)
    items: Mapped[list["SectionItem"]] = relationship(cascade="all, delete-orphan", order_by="SectionItem.order",
                                                      lazy="selectin")


class SectionItem(Base):
    """kind = question | group (whole Linked MCQ set) | pool (draw N by filter)."""
    __tablename__ = "section_items"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    section_id: Mapped[str] = mapped_column(ForeignKey("sections.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16), default="question")
    question_id: Mapped[Optional[str]] = mapped_column(ForeignKey("questions.id"), nullable=True)
    group_id: Mapped[Optional[str]] = mapped_column(ForeignKey("question_groups.id"), nullable=True)
    pool: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    marks_override: Mapped[Optional[float]] = mapped_column(Money, nullable=True)
    negative_override: Mapped[Optional[float]] = mapped_column(Money, nullable=True)
    order: Mapped[int] = mapped_column(Integer, default=0)


# ------------------------------------------------------------------ assignments & attempts
class Assignment(Base):
    __tablename__ = "assignments"
    __table_args__ = (UniqueConstraint("test_id", "candidate_id", name="uq_assign_test_cand"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    test_id: Mapped[str] = mapped_column(ForeignKey("tests.id", ondelete="CASCADE"), index=True)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    # invited|in_progress|test_taken|review_pending|evaluated|shortlisted|archived|expired|cancelled
    status: Mapped[str] = mapped_column(String(20), default="invited", index=True)
    invited_at: Mapped[datetime] = mapped_column(TS, default=now)
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(TS, nullable=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(TS, nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(TS, nullable=True)
    extra_time_min: Mapped[int] = mapped_column(Integer, default=0)
    reminders_sent: Mapped[int] = mapped_column(Integer, default=0)
    tag: Mapped[str] = mapped_column(String(64), default="")
    candidate: Mapped[User] = relationship(lazy="joined")


class Attempt(Base):
    __tablename__ = "attempts"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    assignment_id: Mapped[str] = mapped_column(ForeignKey("assignments.id", ondelete="CASCADE"), index=True)
    test_id: Mapped[str] = mapped_column(ForeignKey("tests.id"), index=True)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    # in_progress|submitted|auto_submitted|evaluating|review_pending|evaluated|reset
    status: Mapped[str] = mapped_column(String(20), default="in_progress", index=True)
    started_at: Mapped[datetime] = mapped_column(TS, default=now)
    deadline_at: Mapped[datetime] = mapped_column(TS)
    submitted_at: Mapped[Optional[datetime]] = mapped_column(TS, nullable=True)
    submit_reason: Mapped[str] = mapped_column(String(40), default="")
    seed: Mapped[int] = mapped_column(Integer, default=0)
    ip: Mapped[str] = mapped_column(String(64), default="")
    user_agent: Mapped[str] = mapped_column(String(300), default="")
    consent: Mapped[dict] = mapped_column(JSON, default=dict)
    system_check: Mapped[dict] = mapped_column(JSON, default=dict)
    section_state: Mapped[dict] = mapped_column(JSON, default=dict)
    total_score: Mapped[Optional[float]] = mapped_column(Money, nullable=True)
    max_score: Mapped[Optional[float]] = mapped_column(Money, nullable=True)
    section_scores: Mapped[dict] = mapped_column(JSON, default=dict)
    below_cutoff: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    risk_score: Mapped[float] = mapped_column(Float, default=0)
    risk_level: Mapped[str] = mapped_column(String(10), default="low")
    risk_breakdown: Mapped[dict] = mapped_column(JSON, default=dict)
    violations: Mapped[int] = mapped_column(Integer, default=0)
    plagiarism_level: Mapped[str] = mapped_column(String(10), default="clear")
    plagiarism_max: Mapped[float] = mapped_column(Float, default=0)
    feedback: Mapped[dict] = mapped_column(JSON, default=dict)


class AttemptQuestion(Base):
    """Frozen per-candidate draw: order, option order and effective marks."""
    __tablename__ = "attempt_questions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    attempt_id: Mapped[str] = mapped_column(ForeignKey("attempts.id", ondelete="CASCADE"), index=True)
    section_id: Mapped[str] = mapped_column(String(32))
    question_id: Mapped[str] = mapped_column(ForeignKey("questions.id"))
    order: Mapped[int] = mapped_column(Integer)
    option_order: Mapped[list] = mapped_column(JSON, default=list)
    marks: Mapped[float] = mapped_column(Money)
    negative: Mapped[float] = mapped_column(Money, default=0)
    question: Mapped[Question] = relationship(lazy="joined")


class Answer(Base):
    __tablename__ = "answers"
    __table_args__ = (UniqueConstraint("attempt_id", "question_id", name="uq_answer_attempt_q"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    attempt_id: Mapped[str] = mapped_column(ForeignKey("attempts.id", ondelete="CASCADE"), index=True)
    question_id: Mapped[str] = mapped_column(ForeignKey("questions.id"), index=True)
    response: Mapped[dict] = mapped_column(JSON, default=dict)
    flagged: Mapped[bool] = mapped_column(Boolean, default=False)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    saved_at: Mapped[datetime] = mapped_column(TS, default=now)
    auto_score: Mapped[Optional[float]] = mapped_column(Money, nullable=True)
    ai_score: Mapped[Optional[float]] = mapped_column(Money, nullable=True)
    ai_rationale: Mapped[str] = mapped_column(Text, default="")
    ai_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ai_detail: Mapped[dict] = mapped_column(JSON, default=dict)
    final_score: Mapped[Optional[float]] = mapped_column(Money, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="saved")  # saved|review|final
    flags: Mapped[list] = mapped_column(JSON, default=list)
    feedback: Mapped[str] = mapped_column(Text, default="")


class CodeSubmission(Base):
    __tablename__ = "code_submissions"
    __table_args__ = (Index("ix_codesub_attempt_q", "attempt_id", "question_id"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    attempt_id: Mapped[Optional[str]] = mapped_column(ForeignKey("attempts.id", ondelete="CASCADE"), nullable=True)
    question_id: Mapped[str] = mapped_column(ForeignKey("questions.id"))
    kind: Mapped[str] = mapped_column(String(10), default="run")  # run|submit|validate
    language: Mapped[str] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(Text)
    custom_input: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(12), default="queued")  # queued|running|done|error
    score: Mapped[Optional[float]] = mapped_column(Money, nullable=True)
    max_score: Mapped[Optional[float]] = mapped_column(Money, nullable=True)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(TS, default=now)
    finished_at: Mapped[Optional[datetime]] = mapped_column(TS, nullable=True)


class Evaluation(Base):
    __tablename__ = "evaluations"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    answer_id: Mapped[str] = mapped_column(ForeignKey("answers.id", ondelete="CASCADE"), index=True)
    evaluator_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    method: Mapped[str] = mapped_column(String(10))  # auto|ai|manual
    score: Mapped[float] = mapped_column(Money)
    rubric_scores: Mapped[list] = mapped_column(JSON, default=list)
    rationale: Mapped[str] = mapped_column(Text, default="")
    override_reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(TS, default=now)


# ------------------------------------------------------------------ proctoring / plagiarism / audit / mail
class ProctorEvent(Base):
    __tablename__ = "proctor_events"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    attempt_id: Mapped[str] = mapped_column(ForeignKey("attempts.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(32))
    started_at: Mapped[datetime] = mapped_column(TS, default=now)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    weight: Mapped[float] = mapped_column(Float, default=0)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)


class ProctorSnapshot(Base):
    __tablename__ = "proctor_snapshots"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    attempt_id: Mapped[str] = mapped_column(ForeignKey("attempts.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(12))  # webcam|screen|audio
    path: Mapped[str] = mapped_column(String(400))
    captured_at: Mapped[datetime] = mapped_column(TS, default=now)
    face_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    flags: Mapped[list] = mapped_column(JSON, default=list)


class PlagiarismMatch(Base):
    __tablename__ = "plagiarism_matches"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    test_id: Mapped[str] = mapped_column(ForeignKey("tests.id", ondelete="CASCADE"), index=True)
    question_id: Mapped[str] = mapped_column(String(32))
    attempt_a: Mapped[str] = mapped_column(String(32))
    attempt_b: Mapped[str] = mapped_column(String(32))
    similarity: Mapped[float] = mapped_column(Float)
    longest_run: Mapped[int] = mapped_column(Integer, default=0)
    level: Mapped[str] = mapped_column(String(10))
    decision: Mapped[str] = mapped_column(String(20), default="")
    created_at: Mapped[datetime] = mapped_column(TS, default=now)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    org_id: Mapped[Optional[str]] = mapped_column(String(32), index=True, nullable=True)
    actor_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    actor_email: Mapped[str] = mapped_column(String(255), default="")
    action: Mapped[str] = mapped_column(String(64))
    entity: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str] = mapped_column(String(64), default="")
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    ip: Mapped[str] = mapped_column(String(64), default="")
    at: Mapped[datetime] = mapped_column(TS, default=now, index=True)


class MailOutbox(Base):
    __tablename__ = "mail_outbox"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    org_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    to: Mapped[str] = mapped_column(String(255))
    subject: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(20), default="general")
    status: Mapped[str] = mapped_column(String(12), default="queued")  # queued|sent|logged|failed
    error: Mapped[str] = mapped_column(Text, default="")
    send_after: Mapped[Optional[datetime]] = mapped_column(TS, nullable=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(TS, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TS, default=now)
