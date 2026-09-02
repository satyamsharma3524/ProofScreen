"""
Deterministic scoring. NO LLM IN THIS FILE. Pure functions, fully unit-tested.

This is the file you open on stage when a judge asks "isn't the score just the
LLM's opinion?". The answer: verdicts are enums produced by the model, weights
are constants in this file, and the score is arithmetic. Every term in it
points at a verbatim quote from the candidate's own answer.

    claim_confidence  = clamp( SUM over dimensions of weight_d * points_d, 0, 1 )
    competence_score  = mean( claim_confidence for all claims )
    badge             = verified   if competence >= 0.70
                        partial    if competence >= 0.40
                        unverified otherwise
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from typing import Any

from api.schemas import Badge, Dimension, Verdict

# ---------------------------------------------------------------------------
# the constants that make the score defensible
# ---------------------------------------------------------------------------

VERDICT_POINTS: dict[Verdict, float] = {
    Verdict.SUPPORTED: 1.0,
    Verdict.PARTIAL: 0.5,
    Verdict.UNSUPPORTED: 0.0,
    Verdict.CONTRADICTED: -0.5,
}

DIMENSION_WEIGHT: dict[Dimension, float] = {
    Dimension.OWNERSHIP: 0.30,
    Dimension.DEPTH: 0.30,
    Dimension.SPECIFICITY: 0.20,
    Dimension.OPERATIONAL: 0.20,
}

# Deterministic tie-break order, used by the question policy.
DIMENSION_ORDER: tuple[Dimension, ...] = (
    Dimension.OWNERSHIP,
    Dimension.DEPTH,
    Dimension.SPECIFICITY,
    Dimension.OPERATIONAL,
)

BADGE_VERIFIED_AT = 0.70
BADGE_PARTIAL_AT = 0.40

# A claim is "well covered" once it passes this, which is what lets the
# question policy move on to the next claim instead of over-probing one.
WELL_COVERED_AT = 0.70


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


# ---------------------------------------------------------------------------
# node normalisation
#
# Accepts Pydantic EvidenceNode / RawEvidenceNode, ORM Evidence rows, or plain
# dicts. Anything with .dimension and .verdict works, so B's code and A's code
# and seed.py can all call straight into here.
# ---------------------------------------------------------------------------


def _field(node: Any, name: str) -> Any:
    if isinstance(node, dict):
        return node.get(name)
    return getattr(node, name, None)


def _as_pair(node: Any) -> tuple[Dimension, Verdict] | None:
    try:
        return Dimension(_field(node, "dimension")), Verdict(_field(node, "verdict"))
    except (ValueError, TypeError):
        return None


def points_by_dimension(nodes: Iterable[Any]) -> dict[Dimension, float]:
    """Best points achieved per dimension across all nodes.

    Multiple answers can touch the same dimension. We take the BEST verdict
    per dimension rather than the mean: once a candidate has demonstrably
    evidenced ownership, a later vague answer does not un-evidence it. The one
    exception is CONTRADICTED, which is negative and therefore can only ever
    be the best score if nothing else touched that dimension.
    """
    out: dict[Dimension, float] = {}
    for node in nodes:
        pair = _as_pair(node)
        if pair is None:
            continue
        dimension, verdict = pair
        points = VERDICT_POINTS[verdict]
        if dimension not in out or points > out[dimension]:
            out[dimension] = points
    return out


def claim_confidence(nodes: Iterable[Any]) -> float:
    """Weighted sum of per-dimension points, clamped to [0, 1]."""
    points = points_by_dimension(nodes)
    if not points:
        return 0.0
    total = sum(DIMENSION_WEIGHT[d] * p for d, p in points.items())
    return round(clamp(total), 4)


def competence_score(confidences: Sequence[float]) -> float:
    """Mean claim confidence.

    Callers must pass one entry per CLAIM, not per scored claim: an unprobed
    claim contributes 0.0. A candidate does not get a high score by answering
    one question well and ignoring the rest.
    """
    if not confidences:
        return 0.0
    return round(sum(confidences) / len(confidences), 4)


def badge_for(score: float) -> Badge:
    if score >= BADGE_VERIFIED_AT:
        return Badge.verified
    if score >= BADGE_PARTIAL_AT:
        return Badge.partial
    return Badge.unverified


def is_well_covered(nodes: Iterable[Any]) -> bool:
    return claim_confidence(nodes) >= WELL_COVERED_AT


# ---------------------------------------------------------------------------
# coverage — what the adaptive question policy reads
# ---------------------------------------------------------------------------


def coverage(nodes: Iterable[Any]) -> dict[Dimension, float]:
    """Points per dimension, with every dimension present (0.0 if untouched)."""
    scored = points_by_dimension(nodes)
    return {d: scored.get(d, 0.0) for d in DIMENSION_ORDER}


def weakest_dimension(nodes: Iterable[Any]) -> Dimension:
    """The dimension with the least weighted evidence.

    Weighted, so an untouched OWNERSHIP (worth 0.30) is probed before an
    untouched SPECIFICITY (worth 0.20). Ties break in DIMENSION_ORDER, which
    makes the policy fully reproducible — the same session always asks the
    same questions.
    """
    cov = coverage(nodes)
    return min(
        DIMENSION_ORDER,
        key=lambda d: (round(cov[d] * DIMENSION_WEIGHT[d], 6), DIMENSION_ORDER.index(d)),
    )


def weakest_dimension_across(node_groups: Iterable[Iterable[Any]]) -> Dimension:
    """Least-covered dimension across every claim in the session (Q5's policy)."""
    totals = {d: 0.0 for d in DIMENSION_ORDER}
    for group in node_groups:
        cov = coverage(group)
        for d in DIMENSION_ORDER:
            totals[d] += cov[d] * DIMENSION_WEIGHT[d]
    return min(
        DIMENSION_ORDER,
        key=lambda d: (round(totals[d], 6), DIMENSION_ORDER.index(d)),
    )


# ---------------------------------------------------------------------------
# resume_score — the deliberately shallow number
#
# Its only job is to sit next to the competence score on the dashboard and be
# visibly different. It is keyword overlap against the job description, which
# is exactly what a GenAI-optimised resume is built to maximise. That is the
# point: a 0.94 resume_score next to a 0.31 competence_score IS the pitch.
# ---------------------------------------------------------------------------

_STOPWORDS = frozenset(
    """a an and are as at be by for from has have in into is it its of on or that the
    to was were will with you your our their they we able using use used work working
    role responsible including etc across within strong good excellent""".split()
)
_TOKEN = re.compile(r"[a-z][a-z+#.\-]{2,}")


def _terms(text: str) -> set[str]:
    return {t for t in _TOKEN.findall((text or "").lower()) if t not in _STOPWORDS}


def resume_score(resume_text: str, job_description: str) -> float:
    """Fraction of the job description's significant terms present in the resume."""
    jd = _terms(job_description)
    if not jd:
        return 0.0
    hits = len(jd & _terms(resume_text))
    return round(clamp(hits / len(jd)), 4)
