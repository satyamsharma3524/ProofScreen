"""
ProofScreen Question Quality Evaluation Engine.

Evaluates generated interview questions across 5 dimensions:
1. Framing Diversity (framing_type, framing_quality)
2. Claim Echo Score (lexical/phrase repetition from claim)
3. Concrete Anchor Score (tool, artifact, process, decision, incident)
4. Conversationality Score (natural recruiter phrasing vs audit jargon)
5. Answerability Score (clarity, cognitive load, single ask)

Calculates an overall question_quality_score (0-100).
Evaluates ONLY the generated question itself (not candidate answers or competence).
"""

from __future__ import annotations

import re
from typing import Sequence
from pydantic import BaseModel, Field

from api.llm import complete_json, load_prompt

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

FRAMING_TYPES = (
    "claim_reference",
    "direct_experience",
    "operational_recall",
    "artifact_anchor",
    "decision_anchor",
    "problem_anchor",
    "scenario_anchor",
    "ownership_anchor",
    "knowledge_anchor",
)

ANCHOR_TYPES = (
    "tool",
    "artifact",
    "process",
    "decision",
    "incident",
    "none",
)


class QuestionQualityEvaluation(BaseModel):
    question_quality_score: int = Field(
        ..., ge=0, le=100, description="Overall weighted question quality score (0-100)"
    )
    framing_type: str = Field(
        ..., description="Classified framing type of the question"
    )
    framing_quality: int = Field(
        ..., ge=0, le=100, description="Framing diversity score (0-100)"
    )
    claim_echo_score: int = Field(
        ..., ge=0, le=100, description="Claim verbatim repetition score (0-100, lower is better)"
    )
    anchor_type: str = Field(
        ..., description="Concrete anchor category present in question"
    )
    anchor_score: int = Field(
        ..., ge=0, le=100, description="Concrete anchor specificity score (0-100)"
    )
    conversationality_score: int = Field(
        ..., ge=0, le=100, description="Recruiter conversational naturalness score (0-100)"
    )
    answerability_score: int = Field(
        ..., ge=0, le=100, description="Clarity and candidate cognitive load score (0-100)"
    )
    strengths: list[str] = Field(
        default_factory=list, description="Key strengths of the question wording"
    )
    weaknesses: list[str] = Field(
        default_factory=list, description="Key weaknesses or friction points"
    )
    suggested_rewrite: str = Field(
        "", description="Suggested rewrite for higher quality and conversationality"
    )


# ---------------------------------------------------------------------------
# Pure Python Deterministic Evaluator (Fallback & Standalone)
# ---------------------------------------------------------------------------

_STOPWORDS = {
    "a", "an", "the", "on", "in", "at", "to", "for", "with", "from", "by", "of",
    "and", "or", "you", "your", "were", "was", "how", "what", "where", "which",
    "why", "when", "did", "does", "do", "using", "used", "work", "project", "claim",
}

_AUDIT_JARGON_RE = re.compile(
    r"\b(anomaly|unilaterally|jurisdiction|material to|delineate|parameters|"
    r"compliance|audit|bureaucracy|independently and what required approval|"
    r"sub-optimal|operationalized|materialized)\b",
    re.IGNORECASE,
)

_TOOLS = {
    "prometheus", "grafana", "jenkins", "kubernetes", "k8s", "docker", "react", "python",
    "kafka", "redis", "postgres", "postgresql", "aws", "gcp", "azure", "fastapi",
    "next.js", "nextjs", "node", "nodejs", "git", "github", "jira", "terraform",
    "ansible", "elasticsearch", "mongodb", "sql", "linux", "datadog",
}

_ARTIFACTS = {
    "dashboard", "pipeline", "cluster", "database", "api", "queue", "config",
    "configuration", "log", "logs", "script", "module", "repo", "repository",
    "schema", "table", "endpoint", "microservice",
}

_INCIDENTS = {
    "outage", "failure", "bug", "alert", "bottleneck", "latency", "crash",
    "down", "error", "spike", "drop", "breakdown", "incident", "issue",
}

_PROCESSES = {
    "deployment", "setup", "migration", "build", "monitoring", "scaling",
    "rollout", "refactoring", "optimization", "integration",
}

_DECISIONS = {
    "tradeoff", "choice", "architecture", "approach", "design", "alternative",
}


def evaluate_question_quality_deterministic(
    question: str,
    claim_text: str,
    prior_questions: Sequence[str] = (),
) -> QuestionQualityEvaluation:
    """Pure, deterministic evaluation of question quality.

    No LLM call. Used directly or as the fallback for complete_json().
    """
    text = (question or "").strip()
    claim = (claim_text or "").strip()
    lower_text = text.lower()
    lower_claim = claim.lower()

    # 1. Framing Type & Quality
    framing_type = "direct_experience"
    if re.search(r"^\s*on the (work|project|claim|role) where", lower_text):
        framing_type = "claim_reference"
    elif re.search(r"tell me about the first time|when did you first|in your experience", lower_text):
        framing_type = "direct_experience"
    elif re.search(r"walk me through|what happened during|how did you (execute|run|deploy)", lower_text):
        framing_type = "operational_recall"
    elif re.search(r"how was .* (configured|setup|built)|what was the configuration", lower_text):
        framing_type = "artifact_anchor"
    elif re.search(r"why did you (choose|select|pick)|what made you opt|why that", lower_text):
        framing_type = "decision_anchor"
    elif re.search(r"what was the (hardest|trickiest|first)|what issue|what problem|where did .* break|what obstacle", lower_text):
        framing_type = "problem_anchor"
    elif re.search(r"if .* failed|where would you start|what would happen if", lower_text):
        framing_type = "scenario_anchor"
    elif re.search(r"which parts were|what did you own|where did your role|how much of", lower_text):
        framing_type = "ownership_anchor"
    elif re.search(r"why does .* work|how does that architecture|what is the underlying", lower_text):
        framing_type = "knowledge_anchor"

    base_framing_quality = 50 if framing_type == "claim_reference" else 85
    # Penalize if prior questions also used claim_reference or exact same framing
    repeat_penalty = 0
    if prior_questions:
        prior_refs = sum(1 for q in prior_questions if re.search(r"^\s*on the (work|project|claim|role) where", q.lower()))
        if framing_type == "claim_reference" and prior_refs > 0:
            repeat_penalty = min(30, prior_refs * 15)

    framing_quality = max(20, min(100, base_framing_quality - repeat_penalty))

    # 2. Claim Echo Score
    claim_words = [w for w in re.findall(r"\w+", lower_claim) if w not in _STOPWORDS]
    question_words = [w for w in re.findall(r"\w+", lower_text) if w not in _STOPWORDS]

    if claim_words and question_words:
        shared = set(claim_words) & set(question_words)
        overlap_ratio = len(shared) / max(1, len(set(claim_words)))
        claim_echo_score = int(round(overlap_ratio * 100))
    else:
        claim_echo_score = 10

    # Boost echo score if phrase restatement detected ("On the work where you used X")
    if "on the work where you" in lower_text or "on the project where you" in lower_text:
        claim_echo_score = max(claim_echo_score, 65)

    claim_echo_score = max(0, min(100, claim_echo_score))

    # 3. Concrete Anchor Score
    tokens = set(re.findall(r"\w+", lower_text))
    anchor_type = "none"
    anchor_score = 25

    if tokens & _TOOLS:
        anchor_type = "tool"
        anchor_score = 100
    elif tokens & _ARTIFACTS:
        anchor_type = "artifact"
        anchor_score = 95
    elif tokens & _INCIDENTS:
        anchor_type = "incident"
        anchor_score = 95
    elif tokens & _PROCESSES:
        anchor_type = "process"
        anchor_score = 80
    elif tokens & _DECISIONS:
        anchor_type = "decision"
        anchor_score = 80

    # 4. Conversationality Score
    conv_score = 85
    if _AUDIT_JARGON_RE.search(lower_text):
        conv_score -= 35
    if framing_type == "claim_reference":
        conv_score -= 15
    if re.search(r"^(what|how|why|which|when|tell me|walk me)\b", lower_text):
        conv_score += 10

    conversationality_score = max(0, min(100, conv_score))

    # 5. Answerability Score (Clarity & Cognitive Load)
    words = lower_text.split()
    word_count = len(words)
    ans_score = 90

    if word_count > 40:
        ans_score -= 25
    elif word_count > 30:
        ans_score -= 10

    # Multi-part question penalty
    if lower_text.count("?") > 1 or re.search(r"\band what\b|\band also\b|\bas well as\b", lower_text):
        ans_score -= 25

    if _AUDIT_JARGON_RE.search(lower_text):
        ans_score -= 15

    answerability_score = max(0, min(100, ans_score))

    # Overall Question Quality Score Weighting
    # answerability 30%, conversationality 25%, concrete_anchor 20%, claim_echo_quality 15%, framing 10%
    echo_quality = max(0, 100 - claim_echo_score)
    raw_score = (
        0.30 * answerability_score
        + 0.25 * conversationality_score
        + 0.20 * anchor_score
        + 0.15 * echo_quality
        + 0.10 * framing_quality
    )
    final_quality_score = int(round(max(0.0, min(100.0, raw_score))))

    # Strengths & Weaknesses
    strengths: list[str] = []
    weaknesses: list[str] = []

    if answerability_score >= 80:
        strengths.append("Clear single ask with low cognitive load")
    else:
        weaknesses.append("High cognitive load or complex multi-part phrasing")

    if conversationality_score >= 80:
        strengths.append("Natural recruiter conversational phrasing")
    else:
        weaknesses.append("Formal, audit-like or bureaucratic phrasing")

    if anchor_score >= 80:
        strengths.append(f"Anchored specifically to a concrete {anchor_type}")
    else:
        weaknesses.append("Lacks a specific concrete anchor")

    if claim_echo_score <= 30:
        strengths.append("Explores work without restating the resume claim text")
    elif claim_echo_score >= 60:
        weaknesses.append("Restates too much of the resume claim text verbatim")

    # Suggested rewrite
    suggested_rewrite = question
    if final_quality_score < 85:
        if anchor_type == "tool":
            suggested_rewrite = f"What was the first problem you noticed when setting up {next(iter(tokens & _TOOLS)).title()}?"
        elif framing_type == "claim_reference":
            # Remove "On the work where you used X"
            clean_q = re.sub(r"^\s*on the (work|project|claim|role) where you used [^,]+,?\s*", "", text, flags=re.I)
            if clean_q:
                suggested_rewrite = clean_q[0].upper() + clean_q[1:]

    return QuestionQualityEvaluation(
        question_quality_score=final_quality_score,
        framing_type=framing_type,
        framing_quality=framing_quality,
        claim_echo_score=claim_echo_score,
        anchor_type=anchor_type,
        anchor_score=anchor_score,
        conversationality_score=conversationality_score,
        answerability_score=answerability_score,
        strengths=strengths,
        weaknesses=weaknesses,
        suggested_rewrite=suggested_rewrite,
    )


# ---------------------------------------------------------------------------
# Public Async Evaluation Entrypoint
# ---------------------------------------------------------------------------

async def evaluate_question_quality(
    question: str,
    claim_text: str,
    prior_questions: Sequence[str] = (),
) -> QuestionQualityEvaluation:
    """Evaluate question quality across 5 dimensions using LLM with deterministic fallback."""

    def fallback() -> QuestionQualityEvaluation:
        return evaluate_question_quality_deterministic(
            question, claim_text, prior_questions=prior_questions
        )

    formatted_priors = (
        "\n".join(f"- {q}" for q in prior_questions)
        if prior_questions
        else "None"
    )

    prompt = load_prompt(
        "evaluate_question",
        question=question,
        claim_text=claim_text,
        prior_questions=formatted_priors,
    )

    return await complete_json(
        prompt,
        QuestionQualityEvaluation,
        fallback=fallback,
    )
