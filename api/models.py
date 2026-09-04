"""
Data model v2.  Owned by Dev A.  Dev B reads it and never edits it.

The seam is still the `responses` table: A fills it, B consumes it. What
changed is what B writes back — per-dimension 0-100 readings plus the raw
extracted signals, so a claim can be rescored from scratch at any time without
re-calling the model.

Three new tables carry the parts of the architecture that make it defensible:

  session_facts   the memory that makes consistency deterministic
  contradictions  what that memory caught, with severity and arithmetic
  job_roles       recruiter weight profiles — same evidence, different ranking

No Alembic, by design. `Base.metadata.create_all()` at startup; a schema change
means `docker compose down -v` and re-seed.

Enum columns are plain String, not native Postgres ENUMs: adding an enum value
would need a migration, and create_all() cannot do that. Pydantic enforces the
values on the way in and out.
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


class JobRole(Base):
    """ARTIFACT 5 — a recruiter's weight profile.

    `claim_weights_json` is {claim_type: weight}. Two roles over the same
    candidate pool produce two different rankings from identical evidence,
    which is the point.
    """

    __tablename__ = "job_roles"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    job_family: Mapped[str] = mapped_column(String(60), index=True)
    claim_weights_json: Mapped[str] = mapped_column(Text, default="{}")
    dimension_weights_json: Mapped[str] = mapped_column(Text, default="{}")
    is_default: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(_TS, default=utcnow)


class Candidate(Base):
    __tablename__ = "candidates"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(40), index=True, default=None)
    email: Mapped[str | None] = mapped_column(String(200), default=None)
    role: Mapped[str | None] = mapped_column(String(200), default=None)
    job_family: Mapped[str] = mapped_column(String(60), default="general", index=True)
    role_id: Mapped[str | None] = mapped_column(
        ForeignKey("job_roles.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(_TS, default=utcnow)


class Resume(Base):
    __tablename__ = "resumes"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), index=True
    )
    raw_text: Mapped[str] = mapped_column(Text)
    filename: Mapped[str | None] = mapped_column(String(300), default=None)
    job_description: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(_TS, default=utcnow)


class ChatSession(Base):
    """`sessions` row. Not named Session, to avoid colliding with
    sqlalchemy.orm.Session in every file that imports both."""

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), index=True
    )
    channel: Mapped[str] = mapped_column(String(20), default="whatsapp")
    state: Mapped[str] = mapped_column(String(24), default="NEW", index=True)
    job_family: Mapped[str] = mapped_column(String(60), default="general")
    questions_asked: Mapped[int] = mapped_column(Integer, default=0)
    current_claim_id: Mapped[str | None] = mapped_column(String(32), default=None)
    current_probe_level: Mapped[str | None] = mapped_column(String(20), default=None)
    # A candidate types this to bind their WhatsApp number to this session.
    opt_in_code: Mapped[str | None] = mapped_column(String(12), index=True, default=None)
    # Meta only allows free-form messages within 24h of the candidate's last
    # message. Tracked so the orchestrator knows when a template is required.
    last_inbound_at: Mapped[datetime | None] = mapped_column(_TS, default=None)
    last_outbound_at: Mapped[datetime | None] = mapped_column(_TS, default=None)
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
    claim_type: Mapped[str] = mapped_column(String(60), index=True)
    metric: Mapped[str | None] = mapped_column(String(200), default=None)
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
    probe_level: Mapped[str] = mapped_column(String(20))
    target_dimension: Mapped[str | None] = mapped_column(String(24), default=None)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    asked_at: Mapped[datetime] = mapped_column(_TS, default=utcnow)
    answered: Mapped[bool] = mapped_column(default=False)


class Response(Base):
    """──────── THE SEAM ────────  A writes raw_text. B writes signals_json."""

    __tablename__ = "responses"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    question_id: Mapped[str] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), index=True
    )
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    channel: Mapped[str] = mapped_column(String(20), default="whatsapp")
    raw_text: Mapped[str] = mapped_column(Text, default="")
    answered_by: Mapped[str] = mapped_column(String(10), default="text")
    media_id: Mapped[str | None] = mapped_column(String(200), default=None)
    # Meta retries a webhook it believes failed. Without this, one retry
    # becomes two answers to the same question and the interview desyncs.
    provider_message_id: Mapped[str | None] = mapped_column(
        String(200), unique=True, index=True, default=None
    )
    transcript: Mapped[str | None] = mapped_column(Text, default=None)
    voice_duration_seconds: Mapped[float | None] = mapped_column(Float, default=None)
    voice_word_count: Mapped[int | None] = mapped_column(Integer, default=None)
    voice_effort: Mapped[int | None] = mapped_column(Integer, default=None)
    # The validated, verbatim-checked AnswerSignals for this answer. Keeping it
    # means a claim can be rescored from stored evidence without paying for the
    # model again — which is what makes live re-ranking by role possible.
    signals_json: Mapped[str | None] = mapped_column(Text, default=None)
    answer_score: Mapped[int | None] = mapped_column(Integer, default=None)
    signals_found: Mapped[int] = mapped_column(Integer, default=0)
    received_at: Mapped[datetime] = mapped_column(_TS, default=utcnow)

    @property
    def answer_text(self) -> str:
        """Transcript wins when the answer arrived as a voice note."""
        return (self.transcript or self.raw_text or "").strip()


class Evidence(Base):
    """B writes. One row per (answer, dimension) — the provenance trail."""

    __tablename__ = "evidence"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    response_id: Mapped[str] = mapped_column(
        ForeignKey("responses.id", ondelete="CASCADE"), index=True
    )
    claim_id: Mapped[str] = mapped_column(
        ForeignKey("claims.id", ondelete="CASCADE"), index=True
    )
    dimension: Mapped[str] = mapped_column(String(24))
    score: Mapped[int] = mapped_column(Integer, default=0)
    basis: Mapped[str] = mapped_column(String(400), default="")
    quotes_json: Mapped[str] = mapped_column(Text, default="[]")
    probe_level: Mapped[str] = mapped_column(String(20), default="VALIDATION")
    created_at: Mapped[datetime] = mapped_column(_TS, default=utcnow)


class ClaimScore(Base):
    """B writes. One row per claim, recomputed over the UNION of its answers."""

    __tablename__ = "claim_scores"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    claim_id: Mapped[str] = mapped_column(
        ForeignKey("claims.id", ondelete="CASCADE"), unique=True, index=True
    )
    score: Mapped[int] = mapped_column(Integer, default=0)
    dimensions_json: Mapped[str] = mapped_column(Text, default="{}")
    probed_dimensions: Mapped[int] = mapped_column(Integer, default=0)
    answers_count: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[str] = mapped_column(String(400), default="")
    computed_at: Mapped[datetime] = mapped_column(_TS, default=utcnow)


class SessionFact(Base):
    """The memory that makes contradiction detection deterministic.

    One row per (session, fact key, reading). Keys come from the taxonomy's
    controlled vocabulary — an open key space would let the model invent a
    fresh key per answer and never contradict itself.
    """

    __tablename__ = "session_facts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    claim_id: Mapped[str | None] = mapped_column(String(32), default=None)
    source_response_id: Mapped[str | None] = mapped_column(String(32), default=None)
    key: Mapped[str] = mapped_column(String(60), index=True)
    value_num: Mapped[float | None] = mapped_column(Float, default=None)
    value_text: Mapped[str | None] = mapped_column(String(160), default=None)
    unit: Mapped[str | None] = mapped_column(String(24), default=None)
    quote: Mapped[str] = mapped_column(String(240), default="")
    created_at: Mapped[datetime] = mapped_column(_TS, default=utcnow)


class ContradictionRow(Base):
    __tablename__ = "contradictions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    fact_key: Mapped[str] = mapped_column(String(60))
    fact_label: Mapped[str] = mapped_column(String(120), default="")
    earlier_value: Mapped[str] = mapped_column(String(120), default="")
    later_value: Mapped[str] = mapped_column(String(120), default="")
    earlier_response_id: Mapped[str | None] = mapped_column(String(32), default=None)
    later_response_id: Mapped[str] = mapped_column(String(32), default="")
    severity: Mapped[str] = mapped_column(String(10), default="MINOR")
    delta_pct: Mapped[float | None] = mapped_column(Float, default=None)
    note: Mapped[str] = mapped_column(String(400), default="")
    created_at: Mapped[datetime] = mapped_column(_TS, default=utcnow)


class Profile(Base):
    """B writes. One row per candidate — what the dashboard ranks on by default.

    Stored against the candidate's DEFAULT role weights. A request for a
    different role recomputes from claim_scores on the fly; nothing here is
    load-bearing for re-ranking.
    """

    __tablename__ = "profiles"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), unique=True, index=True
    )
    resume_score: Mapped[int] = mapped_column(Integer, default=0)
    weighted_evidence_score: Mapped[int] = mapped_column(Integer, default=0)
    competence_score: Mapped[int] = mapped_column(Integer, default=0)
    consistency_score: Mapped[int] = mapped_column(Integer, default=100)
    contradiction_count: Mapped[int] = mapped_column(Integer, default=0)
    role_coverage: Mapped[int] = mapped_column(Integer, default=0)
    badge: Mapped[str] = mapped_column(String(20), default="unverified")
    status: Mapped[str] = mapped_column(String(24), default="NEW")
    scored_role_id: Mapped[str | None] = mapped_column(String(32), default=None)
    dimension_profile_json: Mapped[str] = mapped_column(Text, default="[]")
    computed_at: Mapped[datetime] = mapped_column(_TS, default=utcnow)


class CandidateOutcome(Base):
    """What a human actually decided. Append-only. B writes.

    THE ROW THAT MAKES THE PRODUCT FALSIFIABLE. Every other number in this
    schema is ProofScreen measuring itself: `resume_score` diverging from
    `competence_score` is a demo, not evidence that the second one is right.
    This is the only table holding a real hiring decision, so it is the second
    column M4a rank-correlates against.

    APPEND-ONLY BY SHAPE, NOT BY COMMENT. There is deliberately no unique
    constraint on `candidate_id`: a candidate moves shortlisted -> interviewed
    -> offered, and each step is a new row. Overwriting would destroy the
    history the correlation is computed over. `create_all()` cannot express a
    trigger, so the guarantee is structural and pinned by
    `test_outcome_rows_are_append_only`.
    """

    __tablename__ = "candidate_outcomes"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), index=True
    )
    # SET NULL, never CASCADE. Deleting a scoring lens must not delete the
    # record that a person was rejected -- the decision happened; the lens it
    # was viewed through is only context. CASCADE here would quietly destroy
    # exactly the rows the validation report is computed over.
    #
    # NOTE, measured: SQLite runs with PRAGMA foreign_keys=0, so this clause
    # (and the other 16 in this file) is inert under the test suite and is
    # enforced only on Postgres. `test_role_id_is_declared_set_null` therefore
    # asserts the DECLARATION through SQLAlchemy metadata rather than trusting
    # the runtime it happens to be tested on.
    role_id: Mapped[str | None] = mapped_column(
        ForeignKey("job_roles.id", ondelete="SET NULL"), default=None
    )
    # Ordinal: rejected < shortlisted < interviewed < offered < hired.
    # Validated by schemas.OutcomeDecision at the API boundary; stored as a
    # string like every other enum column here, so a new value needs no
    # migration.
    decision: Mapped[str] = mapped_column(String(20), index=True)
    # The recruiter's own pipeline naming ("phone screen", "panel 2"). Free
    # text, never read by scoring -- it must not become a second, contradictory
    # status alongside `decision`.
    stage: Mapped[str | None] = mapped_column(String(60), default=None)
    decided_by: Mapped[str | None] = mapped_column(String(120), default=None)
    note: Mapped[str | None] = mapped_column(String(500), default=None)
    decided_at: Mapped[datetime] = mapped_column(_TS, default=utcnow)


Index("ix_questions_session_order", Question.session_id, Question.order_index)
Index("ix_evidence_claim_dimension", Evidence.claim_id, Evidence.dimension)
Index("ix_session_facts_session_key", SessionFact.session_id, SessionFact.key)
# The query the validation report runs per candidate: their decision
# history, in order.
Index(
    "ix_candidate_outcomes_candidate_decided",
    CandidateOutcome.candidate_id,
    CandidateOutcome.decided_at,
)
