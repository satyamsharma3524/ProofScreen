"""
THE CONTRACT.  Frozen.

Everything else in this repo is downstream of this file. Per the build spec,
this is the only file with two owners, and it does not change after Day 0.
If you think you need to change it, that is a 2-minute conversation with the
other dev, not a commit.

Rule that matters for the pitch: the LLM produces evidence nodes with ENUM
verdicts. It never produces a number. Every float in this file is computed in
Python from those verdicts (see engine/scoring.py).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# enums  (mirrored as plain strings in models.py columns)
# ---------------------------------------------------------------------------


class Dimension(str, Enum):
    OWNERSHIP = "OWNERSHIP"
    DEPTH = "DEPTH"
    SPECIFICITY = "SPECIFICITY"
    OPERATIONAL = "OPERATIONAL"


class Verdict(str, Enum):
    SUPPORTED = "SUPPORTED"
    PARTIAL = "PARTIAL"
    UNSUPPORTED = "UNSUPPORTED"
    CONTRADICTED = "CONTRADICTED"


class SessionState(str, Enum):
    NEW = "NEW"
    CLAIMS_READY = "CLAIMS_READY"
    ASKING = "ASKING"
    SCORING = "SCORING"
    COMPLETE = "COMPLETE"


class Badge(str, Enum):
    verified = "verified"
    partial = "partial"
    unverified = "unverified"


class Channel(str, Enum):
    web = "web"
    whatsapp = "whatsapp"


# ---------------------------------------------------------------------------
# the seam:  A -> B  and  B -> A
# ---------------------------------------------------------------------------


class ClaimOut(BaseModel):
    id: str
    text: str                       # "Improved CSAT from 78% to 92%"
    metric: str | None = None       # "CSAT 78->92"
    category: str                   # "operations" | "engineering" | ...


class EvidenceNode(BaseModel):
    dimension: Dimension
    verdict: Verdict
    quote: str = Field(max_length=240)   # verbatim from the candidate's answer
    source_response_id: str


class ScoreRequest(BaseModel):           # A -> B
    claim: ClaimOut
    question_text: str
    answer_text: str
    response_id: str


class ScoreResult(BaseModel):            # B -> A
    nodes: list[EvidenceNode]
    claim_confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(default="", max_length=280)


# ---------------------------------------------------------------------------
# LLM output contracts
#
# These are what complete_json() validates against. Note that the model is
# never asked for source_response_id (Python attaches it) and never asked for
# a score of any kind.
# ---------------------------------------------------------------------------


class ExtractedClaim(BaseModel):
    text: str
    metric: str | None = None
    category: str = "general"
    verifiable: bool = True


class ClaimExtraction(BaseModel):
    """LLM call #1 output."""
    claims: list[ExtractedClaim] = Field(default_factory=list)


class GeneratedQuestion(BaseModel):
    """LLM call #2 output."""
    question: str
    intent: Dimension


class RawEvidenceNode(BaseModel):
    """An evidence node as the model returns it — no id, no number."""
    dimension: Dimension
    verdict: Verdict
    quote: str = Field(default="", max_length=240)


class EvidenceExtraction(BaseModel):
    """LLM call #3 output."""
    nodes: list[RawEvidenceNode] = Field(default_factory=list)
    rationale: str = Field(default="", max_length=280)


# ---------------------------------------------------------------------------
# channel normalisation
# ---------------------------------------------------------------------------


class InboundMessage(BaseModel):
    """What every channel adapter normalises an inbound message down to."""
    channel: Channel
    text: str | None = None
    media_url: str | None = None
    external_id: str | None = None   # e.g. "whatsapp:+919812345678"
    session_id: str | None = None    # web channel knows it directly


# ---------------------------------------------------------------------------
# HTTP: candidate side
# ---------------------------------------------------------------------------


class CandidateTextIn(BaseModel):
    """Additive convenience endpoint — paste resume text instead of a file."""
    resume_text: str
    name: str
    phone: str | None = None
    email: str | None = None
    role: str | None = None
    job_description: str | None = None
    channel: Channel = Channel.web


class CandidateCreateOut(BaseModel):
    candidate_id: str
    session_id: str
    claims: list[ClaimOut]
    # additive, but this is what makes the WhatsApp demo actually work:
    join_code: str
    first_question: str | None = None
    whatsapp_instructions: str | None = None


class SessionOut(BaseModel):
    session_id: str
    candidate_id: str
    state: SessionState
    channel: Channel
    questions_asked: int
    max_questions: int
    current_claim_id: str | None = None
    next_question: str | None = None
    join_code: str | None = None


class WebMessageIn(BaseModel):
    session_id: str
    text: str | None = None
    audio_url: str | None = None


class WebMessageOut(BaseModel):
    session_id: str
    state: SessionState
    accepted_text: str
    questions_asked: int
    next_question: str | None = None
    done: bool = False


# ---------------------------------------------------------------------------
# HTTP: recruiter side  (the evidence graph the dashboard renders)
# ---------------------------------------------------------------------------


class QAPair(BaseModel):
    question: str
    answer: str
    question_id: str | None = None
    response_id: str | None = None


class ClaimGraph(BaseModel):
    id: str
    text: str
    metric: str | None = None
    confidence: float | None = None
    rationale: str | None = None
    qa: list[QAPair] = Field(default_factory=list)
    nodes: list[EvidenceNode] = Field(default_factory=list)


class CandidateRef(BaseModel):
    id: str
    name: str
    role: str | None = None


class CandidateGraph(BaseModel):
    """GET /api/recruiter/candidates/{id} — matches fixtures/sample_graph.json."""
    candidate: CandidateRef
    resume_score: float | None = None
    competence_score: float | None = None
    badge: Badge | None = None
    claims: list[ClaimGraph] = Field(default_factory=list)


class CandidateSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    role: str | None = None
    resume_score: float | None = None
    competence_score: float | None = None
    badge: Badge | None = None
    state: SessionState | None = None
    claims_count: int = 0
    questions_asked: int = 0
    computed_at: datetime | None = None


# ---------------------------------------------------------------------------
# HTTP: /api/dev/simulate  — the most valuable endpoint in the repo
# ---------------------------------------------------------------------------


class SimulateIn(BaseModel):
    resume_text: str
    answers: list[str] = Field(default_factory=list)
    name: str = "Simulated Candidate"
    role: str | None = None
    job_description: str | None = None
    persist: bool = True     # true => shows up on the recruiter dashboard


class SimulateOut(BaseModel):
    candidate_id: str
    session_id: str
    questions_asked: int
    transcript: list[QAPair]
    graph: CandidateGraph


class HealthOut(BaseModel):
    status: str
    database: str
    llm_mode: str            # "live" | "fixture"
    model: str | None = None
    adaptive_followups: bool
    max_questions: int
