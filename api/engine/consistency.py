"""
ARTIFACT 4b — the consistency engine.  NO LLM IN THIS FILE.

"This is NOT LLM magic. Create memory. Store facts."

The model extracts facts onto a controlled vocabulary of keys (see
data/claim_taxonomy.json). This module keeps them and compares them. A
contradiction is arithmetic on two numbers, not a second model opinion — which
is what makes it survivable under a judge asking "how do you know it's a lie?"

THE ONE DISTINCTION THAT MAKES THIS WORK
----------------------------------------
Fact keys are `stable` or `variable`.

    stable    team_size, direct_reports, tenure_months, ...
              The value should not move between answers. A divergence is a
              contradiction.

    variable  csat_pct, aht_seconds, frt_minutes, ...
              The value moves over time BY DESIGN. "CSAT was 78, then 92" is
              the improvement the candidate is claiming, not a lie.

Without this distinction the engine would flag every success story a candidate
tells as an inconsistency, which is the opposite of the product.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

from api.schemas import Contradiction, ExtractedFact, Severity
from api.taxonomy import fact_is_stable, fact_label, is_known_fact_key

# Divergence thresholds on stable numeric facts.
MINOR_DELTA_PCT = 10.0     # below this, human approximation — not a contradiction
MAJOR_DELTA_PCT = 50.0     # at or above this, the two answers cannot both be true

# Consistency penalties, applied to a score that starts at 100.
PENALTY = {Severity.MINOR: 15, Severity.MAJOR: 40}

# Floor, so one contradiction cannot zero a candidate outright. Mirrors the
# "20 = major mismatch" end of the intended scale.
CONSISTENCY_FLOOR = 20

_WS = re.compile(r"\s+")


def _canon(text: str | None) -> str:
    return _WS.sub(" ", (text or "").strip().lower())


def delta_pct(earlier: float, later: float) -> float:
    """Percentage divergence, relative to the larger magnitude.

    Relative to the LARGER value on purpose: 20 vs 35 is a 43% divergence
    either way round, so the severity of a contradiction does not depend on
    which answer the candidate happened to give first.
    """
    scale = max(abs(earlier), abs(later), 1.0)
    return round(abs(earlier - later) / scale * 100, 2)


def severity_for(delta: float) -> Severity | None:
    if delta >= MAJOR_DELTA_PCT:
        return Severity.MAJOR
    if delta >= MINOR_DELTA_PCT:
        return Severity.MINOR
    return None


# ---------------------------------------------------------------------------
# comparison
# ---------------------------------------------------------------------------


def compare(
    earlier: ExtractedFact,
    later: ExtractedFact,
    job_family: str = "general",
) -> Contradiction | None:
    """Two readings of the same fact key. Returns a Contradiction or None."""
    if earlier.key != later.key:
        return None
    if not fact_is_stable(job_family, later.key):
        return None                       # variable by design — an improvement

    label = fact_label(job_family, later.key)

    if earlier.value_num is not None and later.value_num is not None:
        delta = delta_pct(earlier.value_num, later.value_num)
        level = severity_for(delta)
        if level is None:
            return None
        return Contradiction(
            fact_key=later.key,
            fact_label=label,
            earlier_value=earlier.display,
            later_value=later.display,
            earlier_response_id=None,   # the caller fills this from the fact store
            later_response_id="",         # filled in by the caller
            severity=level,
            delta_pct=delta,
            note=(
                f"{label} was given as {earlier.display} earlier and "
                f"{later.display} later — a {delta:g}% divergence on a value "
                f"that should not change."
            ),
        )

    early_text, late_text = _canon(earlier.value_text), _canon(later.value_text)
    if early_text and late_text and early_text != late_text:
        return Contradiction(
            fact_key=later.key,
            fact_label=label,
            earlier_value=earlier.value_text or "—",
            later_value=later.value_text or "—",
            later_response_id="",
            severity=Severity.MINOR,
            note=f"{label} was described as '{earlier.value_text}' earlier and "
                 f"'{later.value_text}' later.",
        )

    return None


def check_new_facts(
    new_facts: Sequence[ExtractedFact],
    known_facts: Sequence[ExtractedFact],
    *,
    response_id: str,
    job_family: str = "general",
) -> tuple[list[ExtractedFact], list[Contradiction]]:
    """Validate and store-check one answer's facts against session memory.

    Returns (facts worth storing, contradictions raised). Facts on keys outside
    the family's vocabulary are discarded — an open key space would let the
    model invent a key per answer and never contradict itself.
    """
    kept: list[ExtractedFact] = []
    found: list[Contradiction] = []

    by_key: dict[str, ExtractedFact] = {}
    for fact in known_facts:
        by_key.setdefault(fact.key, fact)

    for fact in new_facts:
        if not is_known_fact_key(job_family, fact.key):
            continue
        if fact.value_num is None and not fact.value_text:
            continue

        earlier = by_key.get(fact.key)
        if earlier is not None:
            clash = compare(earlier, fact, job_family)
            if clash is not None:
                clash.later_response_id = response_id
                found.append(clash)

        kept.append(fact)
        by_key.setdefault(fact.key, fact)

    return kept, found


# ---------------------------------------------------------------------------
# session-level score
# ---------------------------------------------------------------------------


def consistency_score(contradictions: Iterable[Contradiction]) -> int:
    """100 minus published penalties, floored. Deterministic and additive."""
    total = 100
    for clash in contradictions:
        total -= PENALTY.get(clash.severity, 0)
    return max(CONSISTENCY_FLOOR, min(100, total))


def multiplier(score: int) -> float:
    """The score is a percentage; the multiplier is that percentage.

    Applied ONCE to the weighted evidence score rather than inside any claim,
    because consistency is a property of the whole session. One fabricated area
    lowering trust globally is the intended behaviour of a trust product.
    """
    return round(max(0.0, min(100, score)) / 100.0, 4)


def summarise(contradictions: Sequence[Contradiction]) -> str:
    if not contradictions:
        return "No contradictions detected across the session."
    major = sum(1 for c in contradictions if c.severity is Severity.MAJOR)
    minor = len(contradictions) - major
    parts = []
    if major:
        parts.append(f"{major} major")
    if minor:
        parts.append(f"{minor} minor")
    return (
        f"{' and '.join(parts)} contradiction(s) on facts that should not change "
        f"between answers."
    )
