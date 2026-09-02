"""
THE CONTRACT.  v2.  Frozen once committed.

What changed from v1 and why it matters for the pitch:

v1 asked the model for an enum verdict per dimension. Defensible, but a judge
can still say "the model chose SUPPORTED, so the model chose the score."

v2 never asks the model for a judgement of any kind. The model returns
COUNTABLE SIGNALS extracted verbatim from the answer — how many quantities,
how many process steps, how many complete cause→action→outcome chains, which
tools with described usage, which specific incidents. Python turns counts into
0-100 per dimension via the published rubrics in engine/signals.py.

So the answer to "isn't the score just the LLM's opinion?" becomes:
"The model found three quantities, two process steps and one complete causal
chain, and quoted each one. The score is arithmetic over those counts."

The model does exactly five jobs (and no others):
  1. claim extraction          -> ClaimExtraction
  2. question generation       -> GeneratedQuestion
  3. signal extraction         -> AnswerSignals
  4. fact extraction           -> ExtractedFact (inside AnswerSignals)
  5. one-line evidence summary -> AnswerSignals.summary

Contradiction detection, every dimension score, every weight and every final
number are computed in Python.

Scale: everything recruiter-facing is 0-100 integers. Weights are floats.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# enums
# ---------------------------------------------------------------------------


class Dimension(str, Enum):
    """ARTIFACT 2 — the six evidence dimensions.

    Deliberately absent: English fluency, accent, grammar, speaking confidence,
    personality. Those are the bias vectors this product exists to avoid, and a
    Team Lead from Jaipur must not score below one from Bangalore for speaking
    less polished English.
    """

    SPECIFICITY = "SPECIFICITY"                # concrete numbers, names, timeframes
    PROCESS = "PROCESS"                        # how the work actually happened
    METRIC_OWNERSHIP = "METRIC_OWNERSHIP"      # can they define what they claim
    CAUSAL_REASONING = "CAUSAL_REASONING"      # cause -> action -> outcome
    AUTHENTICITY = "AUTHENTICITY"              # real people remember real incidents
    TOOL_FAMILIARITY = "TOOL_FAMILIARITY"      # usage, not certification


class ProbeLevel(str, Enum):
    """ARTIFACT 3 — the question generation protocol, in order."""

    VALIDATION = "VALIDATION"      # you mentioned X, tell me more
    OPERATIONAL = "OPERATIONAL"    # how did the work run day to day
    INCIDENT = "INCIDENT"          # describe a specific time it went wrong
    DECISION = "DECISION"          # what did you decide, and what did you reject
    OUTCOME = "OUTCOME"            # what happened after, and how did you know


class Severity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"


class SessionState(str, Enum):
    NEW = "NEW"
    CLAIMS_READY = "CLAIMS_READY"
    AWAITING_OPT_IN = "AWAITING_OPT_IN"   # WhatsApp: candidate must message first
    ASKING = "ASKING"
    SCORING = "SCORING"
    COMPLETE = "COMPLETE"
    ABANDONED = "ABANDONED"


class Badge(str, Enum):
    verified = "verified"
    partial = "partial"
    unverified = "unverified"


class Channel(str, Enum):
    whatsapp = "whatsapp"
    simulated = "simulated"        # /api/dev/* only — never a real candidate


class AnswerMode(str, Enum):
    text = "text"
    voice = "voice"


# ---------------------------------------------------------------------------
# claims
# ---------------------------------------------------------------------------


class ExtractedClaim(BaseModel):
    """LLM call #1 output element. `claim_type` is validated against the
    taxonomy in Python — a made-up key is reclassified, never trusted."""

    text: str
    claim_type: str | None = None
    metric: str | None = None
    verifiable: bool = True


class ClaimExtraction(BaseModel):
    job_family: str | None = None
    claims: list[ExtractedClaim] = Field(default_factory=list)


class ClaimOut(BaseModel):
    id: str
    text: str
    claim_type: str
    claim_type_label: str
    metric: str | None = None
    weight: float = 0.0            # importance within the role, 0-100


# ---------------------------------------------------------------------------
# questions
# ---------------------------------------------------------------------------


class GeneratedQuestion(BaseModel):
    """LLM call #2 output. The policy picks claim + level; the model only words
    it. `probe_level` is overwritten by the policy on the way out."""

    question: str
    probe_level: ProbeLevel | None = None


# ---------------------------------------------------------------------------
# signals — everything the model is allowed to return about an answer
#
# Every item carries a `quote` that MUST appear verbatim in the answer. Items
# whose quote cannot be found are dropped before scoring, in Python.
# ---------------------------------------------------------------------------


class Quantity(BaseModel):
    value: str = Field(max_length=60)          # as said: "78%", "9 hours", "35"
    refers_to: str = Field(default="", max_length=80)
    quote: str = Field(default="", max_length=240)


class ProcessStep(BaseModel):
    step: str = Field(max_length=160)
    quote: str = Field(default="", max_length=240)


class CausalLink(BaseModel):
    """A chain is COMPLETE only when cause, action and outcome are all present.
    Partial chains score half — see engine/signals.py."""

    cause: str | None = Field(default=None, max_length=160)
    action: str | None = Field(default=None, max_length=160)
    outcome: str | None = Field(default=None, max_length=160)
    quote: str = Field(default="", max_length=240)

    @property
    def is_complete(self) -> bool:
        return bool(self.cause and self.action and self.outcome)


class ToolMention(BaseModel):
    """`usage` present = they described using it. Absent = they only named it,
    which is a resume keyword, not evidence."""

    tool: str = Field(max_length=80)
    usage: str | None = Field(default=None, max_length=160)
    quote: str = Field(default="", max_length=240)


class MetricDefinition(BaseModel):
    """`how_measured` present = they can define the metric they claim."""

    metric: str = Field(max_length=80)
    how_measured: str | None = Field(default=None, max_length=200)
    quote: str = Field(default="", max_length=240)


class IncidentMarker(BaseModel):
    """A detail only someone who was there would produce: a named week, a
    specific escalation, a person's role, a one-off event."""

    detail: str = Field(max_length=200)
    quote: str = Field(default="", max_length=240)


class NamedEntity(BaseModel):
    entity: str = Field(max_length=100)
    kind: str = Field(default="other", max_length=40)   # system|team|process|place
    quote: str = Field(default="", max_length=240)


class ExtractedFact(BaseModel):
    """A durable numeric or short textual fact on a taxonomy fact key. This is
    the memory the consistency engine compares across answers."""

    key: str = Field(max_length=60)
    value_num: float | None = None
    value_text: str | None = Field(default=None, max_length=120)
    unit: str | None = Field(default=None, max_length=24)
    quote: str = Field(default="", max_length=240)

    @property
    def display(self) -> str:
        if self.value_num is not None:
            shown = (
                f"{self.value_num:g}" if self.value_num % 1 else f"{int(self.value_num)}"
            )
            return f"{shown}{(' ' + self.unit) if self.unit else ''}"
        return self.value_text or "—"


class AnswerSignals(BaseModel):
    """LLM call #3 output. Counts in, no scores out."""

    quantities: list[Quantity] = Field(default_factory=list)
    process_steps: list[ProcessStep] = Field(default_factory=list)
    causal_links: list[CausalLink] = Field(default_factory=list)
    tools: list[ToolMention] = Field(default_factory=list)
    metric_definitions: list[MetricDefinition] = Field(default_factory=list)
    incident_markers: list[IncidentMarker] = Field(default_factory=list)
    entities: list[NamedEntity] = Field(default_factory=list)
    facts: list[ExtractedFact] = Field(default_factory=list)
    summary: str = Field(default="", max_length=280)


# ---------------------------------------------------------------------------
# scores — all computed in Python
# ---------------------------------------------------------------------------


class DimensionScore(BaseModel):
    """`basis` is the sentence the dashboard shows under the bar: the exact
    counts the number came from. `quotes` is what those counts point at."""

    dimension: Dimension
    score: int = Field(ge=0, le=100)
    signal_count: int = 0
    basis: str = ""
    quotes: list[str] = Field(default_factory=list)
    probed: bool = False


class EvidenceNode(BaseModel):
    """One dimension's reading from one answer — a row in the `evidence` table."""

    dimension: Dimension
    score: int = Field(ge=0, le=100)
    basis: str = ""
    quotes: list[str] = Field(default_factory=list)
    source_response_id: str
    probe_level: ProbeLevel


class Contradiction(BaseModel):
    fact_key: str
    fact_label: str = ""
    earlier_value: str
    later_value: str
    earlier_response_id: str | None = None
    later_response_id: str
    severity: Severity
    delta_pct: float | None = None
    note: str = Field(default="", max_length=280)


class VoiceSignals(BaseModel):
    """Measured from the audio only: how long they spoke and how much they
    said. Accent, fluency, pause pattern and 'speech confidence' are NOT
    measured and never will be — they are proxies for region and class."""

    duration_seconds: float = 0.0
    word_count: int = 0
    words_per_minute: float | None = None
    effort_score: int = Field(default=0, ge=0, le=100)


class ScoreRequest(BaseModel):
    """A -> B. The seam, unchanged in spirit: A supplies an answer, B returns
    evidence. `known_facts` is what makes contradiction detection possible."""

    claim: ClaimOut
    question_text: str
    probe_level: ProbeLevel
    answer_text: str
    response_id: str
    job_family: str = "general"
    known_facts: list[ExtractedFact] = Field(default_factory=list)
    voice: VoiceSignals | None = None


class ScoreResult(BaseModel):
    """B -> A."""

    # The verbatim-validated signals for this answer. Persisted verbatim so a
    # claim — or a whole candidate under a different role's weights — can be
    # rescored from stored evidence without paying for the model again. This is
    # what makes live re-ranking possible.
    signals: AnswerSignals = Field(default_factory=AnswerSignals)
    nodes: list[EvidenceNode] = Field(default_factory=list)
    facts: list[ExtractedFact] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    answer_score: int = Field(default=0, ge=0, le=100)
    summary: str = Field(default="", max_length=280)
    signals_found: int = 0
    quotes_dropped: int = 0


# ---------------------------------------------------------------------------
# the evidence graph
# ---------------------------------------------------------------------------


class QATurn(BaseModel):
    question: str
    probe_level: ProbeLevel
    answer: str
    answered_by: AnswerMode = AnswerMode.text
    voice: VoiceSignals | None = None
    question_id: str | None = None
    response_id: str | None = None
    answer_score: int | None = None


class ClaimGraph(BaseModel):
    id: str
    text: str
    claim_type: str
    claim_type_label: str
    metric: str | None = None
    weight: float = 0.0                    # role importance, 0-100
    claim_score: int | None = None         # weighted over the six dimensions
    dimensions: list[DimensionScore] = Field(default_factory=list)
    probed_dimensions: int = 0
    qa: list[QATurn] = Field(default_factory=list)
    summary: str | None = None
    facts: list[ExtractedFact] = Field(default_factory=list)


class ConsistencyReport(BaseModel):
    """Session-level, not per-claim: consistency only exists BETWEEN answers.

    The multiplier is applied once to the weighted evidence score, which is how
    one fabricated area lowers trust globally — the behaviour we want from a
    trust product.
    """

    score: int = Field(default=100, ge=0, le=100)
    multiplier: float = 1.0
    facts_tracked: int = 0
    contradictions: list[Contradiction] = Field(default_factory=list)
    note: str = ""


class CandidateRef(BaseModel):
    id: str
    name: str
    role: str | None = None
    phone: str | None = None


class RoleRef(BaseModel):
    id: str
    title: str
    job_family: str


class CandidateGraph(BaseModel):
    """GET /api/recruiter/candidates/{id} — what the dashboard renders.

    `weighted_evidence_score` before consistency, `competence_score` after.
    Showing both is the point: the recruiter sees exactly what the consistency
    multiplier cost this candidate.
    """

    candidate: CandidateRef
    job_family: str
    job_family_label: str
    scored_for: RoleRef | None = None          # which weight profile produced this
    state: SessionState = SessionState.NEW
    questions_asked: int = 0
    resume_score: int = Field(default=0, ge=0, le=100)
    weighted_evidence_score: int = Field(default=0, ge=0, le=100)
    competence_score: int = Field(default=0, ge=0, le=100)
    badge: Badge = Badge.unverified
    # How much of what this ROLE weights the candidate's resume even speaks to.
    # Kept separate from the score on purpose: "evidenced badly" and "never
    # claimed it" are different facts and a recruiter needs both.
    role_coverage: int = Field(default=0, ge=0, le=100)
    consistency: ConsistencyReport = Field(default_factory=ConsistencyReport)
    dimension_profile: list[DimensionScore] = Field(default_factory=list)
    claims: list[ClaimGraph] = Field(default_factory=list)
    computed_at: datetime | None = None


class CandidateSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    role: str | None = None
    job_family: str = "general"
    job_family_label: str = ""
    resume_score: int = 0
    weighted_evidence_score: int = 0
    competence_score: int = 0
    badge: Badge = Badge.unverified
    role_coverage: int = 0
    consistency_score: int = 100
    contradiction_count: int = 0
    state: SessionState | None = None
    claims_count: int = 0
    questions_asked: int = 0
    computed_at: datetime | None = None


# ---------------------------------------------------------------------------
# role weight profiles — ARTIFACT 5, the recruiter ranking layer
# ---------------------------------------------------------------------------


class RoleWeightsIn(BaseModel):
    title: str
    job_family: str = "general"
    claim_weights: dict[str, float] = Field(default_factory=dict)
    dimension_weights: dict[str, float] = Field(default_factory=dict)


class RoleOut(BaseModel):
    id: str
    title: str
    job_family: str
    job_family_label: str = ""
    claim_weights: dict[str, float] = Field(default_factory=dict)
    dimension_weights: dict[str, float] = Field(default_factory=dict)
    is_default: bool = False


class RankedCandidates(BaseModel):
    """Same evidence, different ranking. Two calls with two role_ids returning
    two different orders is the strongest 20 seconds of the demo."""

    scored_for: RoleRef | None = None
    candidates: list[CandidateSummary] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# channel normalisation
# ---------------------------------------------------------------------------


class InboundMessage(BaseModel):
    """What every channel adapter normalises an inbound message down to.

    Cloud API specifics that shape this: a voice note arrives as a media ID
    (not a URL), the sender is a bare wa_id, and the provider message id is
    needed to send a read receipt back.
    """

    channel: Channel
    text: str | None = None
    media_id: str | None = None
    external_id: str | None = None            # wa_id, e.g. "919812345678"
    profile_name: str | None = None           # WhatsApp display name
    provider_message_id: str | None = None    # wamid..., for read receipts


# ---------------------------------------------------------------------------
# candidate intake
# ---------------------------------------------------------------------------


class CandidateTextIn(BaseModel):
    resume_text: str
    name: str
    phone: str
    email: str | None = None
    role: str | None = None
    job_family: str | None = None      # None => detected from the resume
    role_id: str | None = None
    job_description: str | None = None


class CandidateCreateOut(BaseModel):
    candidate_id: str
    session_id: str
    job_family: str
    job_family_label: str
    claims: list[ClaimOut] = Field(default_factory=list)
    state: SessionState
    opt_in_code: str
    whatsapp_instructions: str
    outreach_sent: bool = False
    outreach_note: str | None = None


class SessionOut(BaseModel):
    session_id: str
    candidate_id: str
    state: SessionState
    channel: Channel
    job_family: str
    questions_asked: int
    max_questions: int
    current_claim_id: str | None = None
    current_probe_level: ProbeLevel | None = None
    next_question: str | None = None
    opt_in_code: str | None = None


# ---------------------------------------------------------------------------
# dev endpoints
# ---------------------------------------------------------------------------


class SimulateIn(BaseModel):
    resume_text: str
    answers: list[str] = Field(default_factory=list)
    name: str = "Simulated Candidate"
    role: str | None = None
    phone: str | None = None
    job_family: str | None = None
    job_description: str | None = None


class SimulateOut(BaseModel):
    candidate_id: str
    session_id: str
    questions_asked: int
    graph: CandidateGraph


class DevAnswerIn(BaseModel):
    """Step one answer into a session without WhatsApp. Dev tool, not a channel."""

    text: str
    audio_seconds: float | None = None      # fake a voice note's duration


class DevAnswerOut(BaseModel):
    session_id: str
    state: SessionState
    questions_asked: int
    accepted_text: str
    answer_score: int
    next_question: str | None = None
    next_probe_level: ProbeLevel | None = None
    contradictions: list[Contradiction] = Field(default_factory=list)
    done: bool = False


class HealthOut(BaseModel):
    status: str
    database: str
    llm_mode: str
    model: str | None = None
    whatsapp: str
    max_questions: int
    job_families: int
