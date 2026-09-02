"""
ARTIFACT 4c — the scoring engine.  NO LLM IN THIS FILE.

This is the file you open on the projector.

    dimension score   (engine/signals.py — counts -> 0-100, published rubrics)
        |
        v
    claim score       = SUM over 6 dimensions of  dimension_weight x dimension_score
        |
        v
    weighted evidence = SUM over claims of  claim_weight x claim_score
        |                (claim_weight comes from the role, not from us)
        v
    competence score  = weighted evidence  x  consistency multiplier
        |
        v
    badge             verified >= 70,  partial >= 40,  else unverified

Every arrow is arithmetic. Every dimension score points at verbatim quotes
from the candidate's own answers. Nothing in this file calls a model.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence

from api.engine.signals import PROBE_LEVEL_DIMENSIONS
from api.schemas import (
    Badge,
    Dimension,
    DimensionScore,
    ProbeLevel,
)
from api.taxonomy import dimension_weights

BADGE_VERIFIED_AT = 70
BADGE_PARTIAL_AT = 40

# A claim at or above this is "well evidenced" — the question policy stops
# deepening it and spends the remaining budget elsewhere.
SATURATION_AT = 80

# Voice contributes this share of a claim's score, and ONLY for claims the
# candidate answered by voice. Text-only claims are scored on content alone
# (weight renormalised to 1.0) so nobody is penalised for typing.
#
# Kept small on purpose. The voice signal is duration and word count — how
# much they actually said — and nothing else. Accent, fluency, pause pattern
# and "speech confidence" are not measured, because in India they are proxies
# for region and class, not competence.
DEFAULT_VOICE_WEIGHT = 0.10

DIMENSION_ORDER: tuple[Dimension, ...] = (
    Dimension.SPECIFICITY,
    Dimension.PROCESS,
    Dimension.METRIC_OWNERSHIP,
    Dimension.CAUSAL_REASONING,
    Dimension.AUTHENTICITY,
    Dimension.TOOL_FAMILIARITY,
)


def clamp100(value: float) -> int:
    return int(round(max(0.0, min(100.0, value))))


def dimension_weights_for(job_family: str = "general") -> dict[str, float]:
    """Per-family dimension weights, summing to exactly 1.0."""
    return dimension_weights(job_family)


# ---------------------------------------------------------------------------
# merging several answers about one claim
# ---------------------------------------------------------------------------


def merge_dimension_scores(
    per_answer: Sequence[tuple[ProbeLevel, Mapping[Dimension, DimensionScore]]],
) -> dict[Dimension, DimensionScore]:
    """DEPRECATED — kept only so nothing silently breaks.

    Superseded by engine.signals.score_claim(), which runs the rubric over the
    UNION of a claim's signals instead of taking the best per-answer score.
    Taking the best meant two complete causal chains in two different answers
    scored the same as one, which under-credited exactly the candidates the
    protocol is designed to find.
    """
    probed: set[Dimension] = set()
    for level, _ in per_answer:
        probed.update(PROBE_LEVEL_DIMENSIONS.get(level, ()))

    merged: dict[Dimension, DimensionScore] = {}
    for dimension in DIMENSION_ORDER:
        best: DimensionScore | None = None
        for _, scores in per_answer:
            current = scores.get(dimension)
            if current and (best is None or current.score > best.score):
                best = current
        merged[dimension] = best or DimensionScore(
            dimension=dimension, score=0, basis="not probed",
            probed=dimension in probed,
        )
    return merged


# ---------------------------------------------------------------------------
# claim score
# ---------------------------------------------------------------------------


def claim_score(
    dimensions: Mapping[Dimension, DimensionScore] | Mapping[Dimension, int],
    job_family: str = "general",
    weights: Mapping[str, float] | None = None,
    voice_effort: int | None = None,
    voice_weight: float = DEFAULT_VOICE_WEIGHT,
) -> int:
    """Weighted sum over all six dimensions, 0-100.

    An un-probed dimension contributes 0. That is deliberate: this is a
    CONFIDENCE score, and one great answer about one dimension is not
    confidence that the whole claim is real. `probed_dimensions` is reported
    alongside so a low score from thin questioning is visible as such.
    """
    active = dict(weights) if weights else dimension_weights(job_family)
    total_weight = sum(active.get(d.value, 0.0) for d in DIMENSION_ORDER) or 1.0

    content = 0.0
    for dimension in DIMENSION_ORDER:
        entry = dimensions.get(dimension)
        value = entry if isinstance(entry, (int, float)) else (entry.score if entry else 0)
        content += active.get(dimension.value, 0.0) * float(value)
    content = content / total_weight

    if voice_effort is None:
        return clamp100(content)
    blended = content * (1.0 - voice_weight) + float(voice_effort) * voice_weight
    return clamp100(blended)


def probed_count(dimensions: Mapping[Dimension, DimensionScore]) -> int:
    return sum(1 for d in DIMENSION_ORDER if dimensions.get(d) and dimensions[d].probed)


def is_saturated(score: int) -> bool:
    return score >= SATURATION_AT


# ---------------------------------------------------------------------------
# candidate score
# ---------------------------------------------------------------------------


def weighted_evidence_score(
    claims: Sequence[tuple[str, int]],
    claim_weights: Mapping[str, float],
) -> tuple[int, int]:
    """Role-weighted mean of claim scores. Returns (score, role_coverage).

    `claims` is [(claim_type, claim_score)]. Weights come from the ROLE, so the
    same evidence ranks differently for two recruiters — that is Artifact 5.

    Weights are renormalised over the claim types the candidate actually made,
    and `role_coverage` reports how much of the role's weight their resume
    speaks to at all. Keeping those two numbers separate matters: "evidenced it
    badly" and "never claimed it" are different facts, and folding them into
    one score would hide which is which from the recruiter.
    """
    if not claims:
        return 0, 0

    present = 0.0
    accumulated = 0.0
    seen_types: set[str] = set()

    for claim_type, score in claims:
        weight = float(claim_weights.get(claim_type, 0.0))
        if weight <= 0:
            weight = 1.0                        # unknown type still counts a little
        accumulated += weight * float(score)
        present += weight
        seen_types.add(claim_type)

    score = clamp100(accumulated / present) if present else 0

    total_role_weight = sum(
        float(w) for t, w in claim_weights.items() if t in seen_types
    )
    denominator = sum(float(w) for w in claim_weights.values()) or 100.0
    coverage = clamp100(total_role_weight / denominator * 100)
    return score, coverage


def competence_score(weighted_evidence: int, consistency_multiplier: float) -> int:
    """The headline number. One multiplication, and both inputs are shown."""
    return clamp100(float(weighted_evidence) * float(consistency_multiplier))


def badge_for(score: int) -> Badge:
    if score >= BADGE_VERIFIED_AT:
        return Badge.verified
    if score >= BADGE_PARTIAL_AT:
        return Badge.partial
    return Badge.unverified


def candidate_dimension_profile(
    per_claim: Sequence[tuple[float, Mapping[Dimension, DimensionScore]]],
) -> list[DimensionScore]:
    """Candidate-level reading per dimension, weighted by claim importance.

    This is the radar chart on the dashboard: where is this person strong, and
    where did they fold — across every claim at once.
    """
    if not per_claim:
        return [
            DimensionScore(dimension=d, score=0, basis="no claims scored")
            for d in DIMENSION_ORDER
        ]

    out: list[DimensionScore] = []
    for dimension in DIMENSION_ORDER:
        weight_total = 0.0
        accumulated = 0.0
        signal_total = 0
        probed_any = False
        quotes: list[str] = []
        for weight, dimensions in per_claim:
            entry = dimensions.get(dimension)
            if entry is None:
                continue
            w = max(weight, 1.0)
            accumulated += w * entry.score
            weight_total += w
            signal_total += entry.signal_count
            probed_any = probed_any or entry.probed
            quotes.extend(entry.quotes)
        score = clamp100(accumulated / weight_total) if weight_total else 0
        out.append(
            DimensionScore(
                dimension=dimension,
                score=score,
                signal_count=signal_total,
                basis=f"across {len(per_claim)} claim(s)",
                quotes=quotes[:3],
                probed=probed_any,
            )
        )
    return out


# ---------------------------------------------------------------------------
# resume_score — the deliberately shallow contrast metric
#
# Keyword overlap against the job description: exactly what a GenAI-optimised
# resume is built to maximise. Its only job is to sit beside the competence
# score and be visibly, embarrassingly different.
# ---------------------------------------------------------------------------

_STOPWORDS = frozenset(
    """a an and are as at be by for from has have in into is it its of on or that the
    to was were will with you your our their they we able using use used work working
    role responsible including etc across within strong good excellent ability""".split()
)
_TOKEN = re.compile(r"[a-z][a-z+#.\-]{2,}")


def _terms(text: str) -> set[str]:
    return {t for t in _TOKEN.findall((text or "").lower()) if t not in _STOPWORDS}


def resume_score(resume_text: str, job_description: str) -> int:
    """Percentage of the job description's significant terms present in the resume."""
    jd = _terms(job_description)
    if not jd:
        return 0
    return clamp100(len(jd & _terms(resume_text)) / len(jd) * 100)


def normalise_weights(weights: Mapping[str, float], total: float = 100.0) -> dict[str, float]:
    """Rescale a recruiter's weights so they sum to `total`.

    Recruiters type 40/30/20/20. Rather than rejecting that, rescale it — the
    ranking only depends on the ratios, and a rejected form is a recruiter who
    stops using the product.
    """
    values = {k: float(v) for k, v in weights.items() if float(v) > 0}
    current = sum(values.values())
    if not values or current <= 0:
        return {}
    factor = total / current
    keys = list(values)
    out = {k: round(values[k] * factor, 4) for k in keys[:-1]}
    # Last key absorbs the rounding remainder, so the weights sum to exactly
    # `total`. Otherwise a recruiter typing 40/30/20/20 sees 99.9999 in the
    # weight editor and reasonably assumes the product is broken.
    out[keys[-1]] = round(total - sum(out.values()), 4)
    return out


def all_dimensions() -> tuple[Dimension, ...]:
    return DIMENSION_ORDER


def dimension_labels() -> dict[Dimension, str]:
    return {
        Dimension.SPECIFICITY: "Specificity",
        Dimension.PROCESS: "Process understanding",
        Dimension.METRIC_OWNERSHIP: "Metric ownership",
        Dimension.CAUSAL_REASONING: "Causal reasoning",
        Dimension.AUTHENTICITY: "Experience authenticity",
        Dimension.TOOL_FAMILIARITY: "Tool familiarity",
    }
