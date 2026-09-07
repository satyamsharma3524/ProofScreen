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

Phase 4 adds three tables and one column to almost every other one:

  tenants         the ownership boundary — see api/tenancy.py
  api_keys        a hashed shared key per tenant; the raw key is never stored
  evaluations     one finalized assessment, immutable, with its provenance

No Alembic, by design. `Base.metadata.create_all()` at startup; a schema change
means `docker compose down -v` and re-seed. `create_all()` cannot ADD a column
to a table that already exists, which is why `db.verify_schema()` fails loudly
at startup on a database from before Phase 4 instead of at the first query.

Enum columns are plain String, not native Postgres ENUMs: adding an enum value
would need a migration, and create_all() cannot do that. Pydantic enforces the
values on the way in and out.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy import event, inspect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


_TS = DateTime(timezone=True)

# ---------------------------------------------------------------------------
# D9 — the tenant column
#
# Declared here rather than in api/tenancy.py because it is a fact about the
# SCHEMA, and tenancy.py imports these models. One direction, no cycle.
#
# THE DEFAULT IS DELIBERATE AND MEASURED. A non-null column with no default
# would break `scripts/interview_study.py`, which constructs Candidate and
# Resume directly and belongs to Phase 3 — under independent review, and not
# editable. So an unspecified tenant lands in the EXPLICIT development tenant
# rather than becoming global or null. Nothing in `api/` relies on it:
# `test_a_tenant_scoped_pipeline_writes_no_development_tenant_rows` drives a
# whole interview under a second tenant and asserts no row fell back here.
#
# No `ondelete`. Deleting a tenant that still holds candidates must FAIL, not
# cascade a customer's entire evidence corpus away on one stray DELETE.
DEVELOPMENT_TENANT_ID = "t_dev"
DEVELOPMENT_TENANT_SLUG = "dev"
DEVELOPMENT_TENANT_NAME = "Development"


def tenant_column() -> Mapped[str]:
    """The owning tenant. One per tenant-owned table, indexed, never null."""
    return mapped_column(
        String(32),
        ForeignKey("tenants.id"),
        index=True,
        nullable=False,
        default=DEVELOPMENT_TENANT_ID,
    )


class Tenant(Base):
    """ARTIFACT 6 — the ownership boundary.

    A tenant is a customer: one company's recruiters, candidates, roles,
    evidence and evaluations. `Candidate` is NOT global — the same human
    applying to two customers is two candidate rows, because their evidence
    belongs to whoever gathered it. The Person/Candidacy split that would make
    identity global is deferred (see PHASE_2_EXECUTION_PLAN.md §Deferred).
    """

    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    # Human-typeable, unique. `dev` is the development tenant every legacy
    # write and every un-keyed request lands in.
    slug: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(_TS, default=utcnow)


class ApiKey(Base):
    """A shared API key per tenant. THE RAW KEY IS NEVER STORED.

    `key_hash` is sha256 hex of the key, so a database dump discloses no
    credential. The key itself is returned exactly once, at creation, and
    cannot be recovered afterwards.

    This is not an authentication system. There are no users, no roles, no
    rotation and no expiry — it is the minimum credential needed to decide
    WHICH TENANT a request belongs to, which is what D9 is actually about.
    """

    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120), default="")
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(_TS, default=utcnow)


class JobRole(Base):
    """ARTIFACT 5 — a recruiter's weight profile.

    `claim_weights_json` is {claim_type: weight}. Two roles over the same
    candidate pool produce two different rankings from identical evidence,
    which is the point.
    """

    __tablename__ = "job_roles"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    tenant_id: Mapped[str] = tenant_column()
    title: Mapped[str] = mapped_column(String(200))
    job_family: Mapped[str] = mapped_column(String(60), index=True)
    claim_weights_json: Mapped[str] = mapped_column(Text, default="{}")
    dimension_weights_json: Mapped[str] = mapped_column(Text, default="{}")
    is_default: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(_TS, default=utcnow)


class Candidate(Base):
    __tablename__ = "candidates"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    tenant_id: Mapped[str] = tenant_column()
    name: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(40), index=True, default=None)
    email: Mapped[str | None] = mapped_column(String(200), default=None)
    role: Mapped[str | None] = mapped_column(String(200), default=None)
    job_family: Mapped[str] = mapped_column(String(60), default="general", index=True)
    # junior/mid/senior/None -- read once from LLM #0 (classify_role) at
    # extraction time, never re-derived. Internal-only: not in api/schemas.py,
    # nothing in any request/response contract exposes it. The planner's
    # level gate (question.level_appropriate) is the only reader.
    seniority: Mapped[str | None] = mapped_column(String(20), default=None)
    role_id: Mapped[str | None] = mapped_column(
        ForeignKey("job_roles.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(_TS, default=utcnow)


class Resume(Base):
    __tablename__ = "resumes"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    tenant_id: Mapped[str] = tenant_column()
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
    tenant_id: Mapped[str] = tenant_column()
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
    tenant_id: Mapped[str] = tenant_column()
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
    tenant_id: Mapped[str] = tenant_column()
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

    # --- P2-03: how this question came to be asked --------------------------
    #
    # Without these, "how often does the system generate bad questions?" is not
    # answerable from stored rows at all, and EXECUTION_STANDARD.md 5 requires
    # every metric to be. M6d-M6g are computed from exactly these four columns.
    #
    # All defaulted and nullable, so `create_all()` is enough and there is no
    # backfill — the schema change is still a `docker compose down -v`.
    #
    # `String` rather than a native enum, per the convention: create_all()
    # cannot add a value to a Postgres enum, and a new question source should
    # not need a migration.
    source: Mapped[str] = mapped_column(String(16), default="model")

    # The forensic move this question was generated from ("FAILURE",
    # "METRIC_DEFINITION", ...). Nullable and defaulted, so `create_all()` is
    # enough and pre-forensic rows stay readable as NULL.
    #
    # It is here rather than derived from `probe_level` because the mapping is
    # many-to-one: FAILURE and PEOPLE both record INCIDENT, EXCLUSION and
    # AUTHORITY both record DECISION. Without the column the planner cannot tell
    # which moves a claim has already spent, and would re-ask one.
    move: Mapped[str | None] = mapped_column(String(40), default=None)
    # 1 or 2. Never higher — the cap is structural in `generate_question()`.
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    # Rules that tripped on ATTEMPT ONE, JSON list. Attempt one is what M6d is
    # about: how often the model produces a bad question. If attempt two also
    # failed, `source` reads "fallback" and that is the second fact worth
    # keeping.
    violations_json: Mapped[str | None] = mapped_column(Text, default=None)
    # Landed here, unused until P2-04, so the phase needs ONE schema reset
    # rather than two. Two resets in one phase is an avoidable demo-day hazard.
    is_repair: Mapped[bool] = mapped_column(default=False)


class Response(Base):
    """──────── THE SEAM ────────  A writes raw_text. B writes signals_json."""

    __tablename__ = "responses"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    tenant_id: Mapped[str] = tenant_column()
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
    tenant_id: Mapped[str] = tenant_column()
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
    tenant_id: Mapped[str] = tenant_column()
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
    tenant_id: Mapped[str] = tenant_column()
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
    tenant_id: Mapped[str] = tenant_column()
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
    tenant_id: Mapped[str] = tenant_column()
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
    # D6 — the pointer. This row stays a MUTABLE CACHE for the fast list view;
    # the immutable record is `evaluations`. The plan's "Profile becomes a pure
    # pointer" is deliberately NOT done here: `rank_candidates` reads these
    # cached scores, and rewriting that is a scoring rewrite. Recorded as
    # deferred in docs/PHASE_4_TASKS.md 7.
    latest_evaluation_id: Mapped[str | None] = mapped_column(String(32), default=None)


class Evaluation(Base):
    """D6 — ONE COMPLETED ASSESSMENT. Immutable once finalized.

    Until Phase 4 an evaluation was implicit: `build_candidate_graph()`
    computed it on demand and threw it away, with `profiles` caching one
    variant and overwriting it in place. "Why did this candidate score 82 in
    March and 71 today?" had no answer, because March was never written down.

    WHAT IS IN HERE AND WHAT IS NOT

    In: the RESULT (the aggregate numbers), the CONFIGURATION it was produced
    under (weights, versions, flags), and POINTERS to the evidence.

    Not in: the evidence. There is no signals blob, no copied quotes and no
    `evidence_nodes` table. `session_id` and `candidate_id` address the graph
    that already exists, and the drill-down endpoint is unchanged. Copying
    evidence in would create a second source of truth for the one thing this
    product cannot afford to have two answers about.

    The weights ARE copied, and that is not a contradiction: `role_id` is
    SET NULL on delete (correctly — deleting a lens must not delete the
    record), so without the snapshot a deleted role would make a finalized
    evaluation unexplainable.

    LIFECYCLE: draft -> finalized. Two states, both observed.

      draft      the interview is in flight. The live detail is
                 `sessions.state`; duplicating it here would recreate exactly
                 the `profiles.status` / `sessions.state` confusion D6 exists
                 to resolve.
      finalized  the record. Nothing about it changes again.

    There is no `abandoned` and no `failed`. `SessionState.ABANDONED` is
    declared in schemas.py and assigned NOWHERE in this codebase — three
    reads, zero writes — so an abandoned evaluation would be an unreachable
    state with an untestable transition. Add it the day something abandons a
    session, and not before.

    ONE EVALUATION PER SESSION, enforced by the unique constraint below. A
    re-interview is a new session and therefore a distinct `ev_` id, which is
    what makes "creating another assessment for the same candidate produces a
    distinct evaluation" true by construction rather than by convention.

    IMMUTABILITY is enforced twice: `evaluation.finalize_evaluation()` refuses
    a second finalization, and the `before_update` listener at the bottom of
    this file raises on ANY update to an already-finalized row. The listener is
    the one that matters — it catches a future callsite that never heard of the
    service function.
    """

    __tablename__ = "evaluations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    tenant_id: Mapped[str] = tenant_column()
    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), index=True
    )
    # UNIQUE: one assessment per interview. See the class docstring.
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), unique=True, index=True
    )
    # SET NULL for the same reason as CandidateOutcome.role_id: the assessment
    # happened; the lens it was viewed through is only context. `role_title`
    # and `claim_weights_json` survive the deletion so the row stays readable.
    role_id: Mapped[str | None] = mapped_column(
        ForeignKey("job_roles.id", ondelete="SET NULL"), default=None
    )
    role_title: Mapped[str | None] = mapped_column(String(200), default=None)
    job_family: Mapped[str] = mapped_column(String(60), default="general", index=True)
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    created_at: Mapped[datetime] = mapped_column(_TS, default=utcnow)
    finalized_at: Mapped[datetime | None] = mapped_column(_TS, default=None)

    # --- the result, as it stood at finalization ---------------------------
    resume_score: Mapped[int] = mapped_column(Integer, default=0)
    weighted_evidence_score: Mapped[int] = mapped_column(Integer, default=0)
    competence_score: Mapped[int] = mapped_column(Integer, default=0)
    badge: Mapped[str] = mapped_column(String(20), default="unverified")
    consistency_score: Mapped[int] = mapped_column(Integer, default=100)
    contradiction_count: Mapped[int] = mapped_column(Integer, default=0)
    role_coverage: Mapped[int] = mapped_column(Integer, default=0)
    claims_scored: Mapped[int] = mapped_column(Integer, default=0)
    questions_asked: Mapped[int] = mapped_column(Integer, default=0)
    dimension_profile_json: Mapped[str] = mapped_column(Text, default="[]")

    # --- the configuration it was produced under ---------------------------
    claim_weights_json: Mapped[str] = mapped_column(Text, default="{}")
    dimension_weights_json: Mapped[str] = mapped_column(Text, default="{}")

    # --- D7 provenance. Typed fields; two dicts with genuinely varying keys.
    taxonomy_version: Mapped[str] = mapped_column(String(40), default="")
    taxonomy_hash: Mapped[str] = mapped_column(String(40), default="")
    rubric_version: Mapped[str] = mapped_column(String(40), default="")
    scoring_version: Mapped[str] = mapped_column(String(40), default="")
    question_policy_version: Mapped[str] = mapped_column(String(40), default="")
    prompt_versions_json: Mapped[str] = mapped_column(Text, default="{}")
    code_version: Mapped[str] = mapped_column(String(64), default="unknown")
    app_version: Mapped[str] = mapped_column(String(40), default="")
    llm_mode: Mapped[str] = mapped_column(String(16), default="fixture")
    model_requested: Mapped[str | None] = mapped_column(String(80), default=None)
    model_returned: Mapped[str | None] = mapped_column(String(80), default=None)
    feature_flags_json: Mapped[str] = mapped_column(Text, default="{}")
    evaluation_version: Mapped[str] = mapped_column(String(40), default="", index=True)


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
    tenant_id: Mapped[str] = tenant_column()
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
    # --- D10 ---------------------------------------------------------------
    #
    # WHICH ASSESSMENT THIS DECISION WAS MADE AGAINST. Nullable, and both
    # reasons matter: rows written before Phase 4 have no evaluation, and a
    # decision can legitimately be recorded for a candidate who never finished
    # an interview. SET NULL rather than CASCADE, for the third time in this
    # file and the same reason each time — the decision happened; deleting its
    # context must not delete the record of it.
    evaluation_id: Mapped[str | None] = mapped_column(
        ForeignKey("evaluations.id", ondelete="SET NULL"), index=True, default=None
    )
    # What this decision REPLACED, denormalised at write time. The previous row
    # is right there in the table, so this is redundant by one join — and it is
    # kept anyway, because "was the decision later changed, and from what?" is
    # the audit question, and answering it should not depend on the reader
    # reconstructing an ordering correctly. Null on the first decision.
    previous_decision: Mapped[str | None] = mapped_column(String(20), default=None)
    # The recruiter's own pipeline naming ("phone screen", "panel 2"). Free
    # text, never read by scoring -- it must not become a second, contradictory
    # status alongside `decision`.
    stage: Mapped[str | None] = mapped_column(String(60), default=None)
    decided_by: Mapped[str | None] = mapped_column(String(120), default=None)
    note: Mapped[str | None] = mapped_column(String(500), default=None)
    decided_at: Mapped[datetime] = mapped_column(_TS, default=utcnow)


class EvaluationFinalized(RuntimeError):
    """An attempt to change an evaluation after it was finalized."""


@event.listens_for(Evaluation, "before_update", propagate=True)
def _finalized_evaluations_are_immutable(mapper, connection, target) -> None:
    """D6 — immutability at the ORM layer, not only in the service function.

    A service-level guard protects the one path that goes through it. This
    protects every path: a future endpoint, a script, a migration helper, a
    well-meaning `row.badge = ...` in a debugging session. SQLAlchemy only
    emits an UPDATE when something actually changed, so this never fires on a
    no-op flush.

    The test is the OLD value of `finalized_at`, not the current one — the
    flush that performs the finalization is itself an update, and reading the
    new value would make finalization impossible.

    `create_all()` cannot express a trigger, so this is where the guarantee
    lives, and `test_a_finalized_evaluation_cannot_be_mutated_by_any_path`
    is what stops it from becoming a comment.
    """
    history = inspect(target).attrs.finalized_at.history
    previously = tuple(history.unchanged or ()) + tuple(history.deleted or ())
    if any(value is not None for value in previously):
        raise EvaluationFinalized(
            f"evaluation {target.id} was finalized at "
            f"{next(v for v in previously if v is not None)} and cannot be changed. "
            f"A new assessment is a new interview and a new evaluation row."
        )


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
# The two queries D6 adds: a candidate's evaluation history, newest first, and
# every evaluation a tenant owns.
Index(
    "ix_evaluations_candidate_created",
    Evaluation.candidate_id,
    Evaluation.created_at,
)
Index("ix_evaluations_tenant_status", Evaluation.tenant_id, Evaluation.status)
