"""
Data model.  Owned by Dev A.  Dev B reads it and never edits it.

The seam is the `responses` table: A fills it, B consumes it. That is the
entire coupling between the two halves of this build.

No Alembic. `Base.metadata.create_all()` runs at startup (see db.py).
Deliberate: migrations are a tax a nine-day build does not need to pay. If a
column changes, drop the volume (`docker compose down -v`) and re-seed.

NOTE — enum columns are stored as plain strings, not native Postgres ENUMs.
Reason: a native enum needs a migration to add a value, and create_all()
cannot do that. The Pydantic layer in schemas.py is what enforces the values.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


_TS = DateTime(timezone=True)


class Candidate(Base):
    __tablename__ = "candidates"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(40), index=True, default=None)
    email: Mapped[str | None] = mapped_column(String(200), default=None)
    # additive vs the spec table list: the dashboard fixture shows a role label
    role: Mapped[str | None] = mapped_column(String(200), default=None)
    created_at: Mapped[datetime] = mapped_column(_TS, default=utcnow)


class Resume(Base):
    __tablename__ = "resumes"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), index=True
    )
    raw_text: Mapped[str] = mapped_column(Text)
    filename: Mapped[str | None] = mapped_column(String(300), default=None)
    # additive: resume_score is keyword overlap and needs something to overlap with
    job_description: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(_TS, default=utcnow)


class ChatSession(Base):
    """`sessions` row. Class is not named Session to avoid colliding with
    sqlalchemy.orm.Session in every file that imports both."""

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), index=True
    )
    channel: Mapped[str] = mapped_column(String(20), default="web")
    state: Mapped[str] = mapped_column(String(20), default="NEW", index=True)
    questions_asked: Mapped[int] = mapped_column(Integer, default=0)
    current_claim_id: Mapped[str | None] = mapped_column(String(32), default=None)
    # additive: how a candidate binds their phone to this session over WhatsApp
    join_code: Mapped[str | None] = mapped_column(String(12), index=True, default=None)
    started_at: Mapped[datetime] = mapped_column(_TS, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(_TS, default=None)


class Claim(Base):
    __tablename__ = "claims"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    resume_id: Mapped[str] = mapped_column(
        ForeignKey("resumes.id", ondelete="CASCADE"), index=True
    )
    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), index=True
    )
    text: Mapped[str] = mapped_column(Text)
    metric: Mapped[str | None] = mapped_column(String(200), default=None)
    category: Mapped[str] = mapped_column(String(60), default="general")
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(_TS, default=utcnow)


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    claim_id: Mapped[str] = mapped_column(
        ForeignKey("claims.id", ondelete="CASCADE"), index=True
    )
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    text: Mapped[str] = mapped_column(Text)
    intent: Mapped[str] = mapped_column(String(20))          # Dimension
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    asked_at: Mapped[datetime] = mapped_column(_TS, default=utcnow)
    answered: Mapped[bool] = mapped_column(default=False)


class Response(Base):
    """──────── THE SEAM ────────  A writes. B reads."""

    __tablename__ = "responses"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    question_id: Mapped[str] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), index=True
    )
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    channel: Mapped[str] = mapped_column(String(20), default="web")
    raw_text: Mapped[str] = mapped_column(Text, default="")
    audio_url: Mapped[str | None] = mapped_column(String(600), default=None)
    transcript: Mapped[str | None] = mapped_column(Text, default=None)
    received_at: Mapped[datetime] = mapped_column(_TS, default=utcnow)

    @property
    def answer_text(self) -> str:
        """Transcript wins when the answer arrived as a voice note."""
        return (self.transcript or self.raw_text or "").strip()


class Evidence(Base):
    """B writes."""

    __tablename__ = "evidence"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    response_id: Mapped[str] = mapped_column(
        ForeignKey("responses.id", ondelete="CASCADE"), index=True
    )
    claim_id: Mapped[str] = mapped_column(
        ForeignKey("claims.id", ondelete="CASCADE"), index=True
    )
    dimension: Mapped[str] = mapped_column(String(20))
    verdict: Mapped[str] = mapped_column(String(20))
    quote: Mapped[str] = mapped_column(String(240), default="")
    created_at: Mapped[datetime] = mapped_column(_TS, default=utcnow)


class ClaimScore(Base):
    """B writes. One row per claim, recomputed on every new answer."""

    __tablename__ = "claim_scores"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    claim_id: Mapped[str] = mapped_column(
        ForeignKey("claims.id", ondelete="CASCADE"), unique=True, index=True
    )
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    rationale: Mapped[str] = mapped_column(String(280), default="")
    computed_at: Mapped[datetime] = mapped_column(_TS, default=utcnow)


class Profile(Base):
    """B writes. One row per candidate — what the dashboard ranks on."""

    __tablename__ = "profiles"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), unique=True, index=True
    )
    competence_score: Mapped[float] = mapped_column(Float, default=0.0)
    resume_score: Mapped[float] = mapped_column(Float, default=0.0)
    badge: Mapped[str] = mapped_column(String(20), default="unverified")
    status: Mapped[str] = mapped_column(String(20), default="NEW")
    computed_at: Mapped[datetime] = mapped_column(_TS, default=utcnow)


Index("ix_questions_session_order", Question.session_id, Question.order_index)
Index("ix_evidence_claim_dimension", Evidence.claim_id, Evidence.dimension)
