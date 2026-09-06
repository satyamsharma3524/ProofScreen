"""
ARTIFACT 1 — Claim Taxonomy loader.

Reads data/claim_taxonomy.json and answers four questions the rest of the
engine asks constantly:

  * which job family is this resume?
  * which claim type is this claim, and what is it worth in this family?
  * which dimensions matter most for this family?
  * which facts should the consistency engine track for this family?

Weights live in data, not code, so the PM can retune "team handling is worth
25 for a BPO Team Lead" without a deploy or a code review.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, NamedTuple

TAXONOMY_PATH = Path(__file__).resolve().parents[1] / "data" / "claim_taxonomy.json"

GENERAL = "general"


@lru_cache(maxsize=1)
def _load() -> tuple[dict[str, Any], str]:
    """The taxonomy and the hash OF THE BYTES THAT PRODUCED IT.

    One read, both values. Hashing the file separately would let the two
    disagree: `_raw()` caches at first use, and a `taxonomy_hash()` that read
    the file again later could describe content this process never parsed —
    which is the one thing a provenance record must never do. Found in the
    Phase 4 integration review.
    """
    raw = TAXONOMY_PATH.read_bytes()
    return json.loads(raw.decode("utf-8")), hashlib.sha256(raw).hexdigest()[:12]


def _raw() -> dict[str, Any]:
    return _load()[0]


def _clean(mapping: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in mapping.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# families
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# D7 — the taxonomy as a VERSIONED ARTIFACT
#
# Two numbers, and they answer different questions.
#
#   taxonomy_version   what the file SAYS it is. Hand-maintained, and the place
#                      to express intent: bump the minor part for an additive
#                      change (a new fact key, a new claim type — history stays
#                      valid), the major part for a weight or claim-type change
#                      (scores are not comparable across it).
#   taxonomy_hash      what the file ACTUALLY is. Content, not intent. It moves
#                      whether or not anybody remembered to bump the version,
#                      which is the whole point of having both.
#
# `PM tunes a weight without a deploy` is the documented reason this lives in
# data rather than code. It is also exactly the change most likely to move a
# score with nothing in the git history to show for it — so provenance records
# both, and the fingerprint hashes both.
# ---------------------------------------------------------------------------


def taxonomy_version() -> str:
    """The DECLARED version. `tax_0` if the file predates the field."""
    return str(_raw().get("version") or "tax_0")


def taxonomy_hash() -> str:
    """sha256 of the file's bytes, first 12 hex. The MEASURED version.

    Read from the same single load as the taxonomy itself — see `_load()`.
    """
    return _load()[1]


def families() -> dict[str, dict[str, Any]]:
    return _raw()["families"]


def family_keys() -> list[str]:
    return list(families().keys())


def family(key: str | None) -> dict[str, Any]:
    return families().get(key or GENERAL) or families()[GENERAL]


def family_label(key: str | None) -> str:
    return family(key)["label"]


def resolve_family(key: str | None) -> str:
    return key if key in families() else GENERAL


# ---------------------------------------------------------------------------
# dimension weights
# ---------------------------------------------------------------------------


@lru_cache(maxsize=32)
def dimension_weights(family_key: str | None = None) -> dict[str, float]:
    """Global defaults, overlaid with the family's overrides, renormalised to 1.0.

    Renormalisation matters: a family that raises PROCESS to 0.25 without
    lowering anything else would otherwise push the total past 1.0 and inflate
    every claim score in that family.
    """
    base = dict(_clean(_raw()["dimension_weights"]))
    base.update(_clean(family(family_key).get("dimension_weights", {})))
    total = sum(base.values()) or 1.0
    keys = list(base)
    out = {k: round(base[k] / total, 6) for k in keys[:-1]}
    # Last key absorbs the rounding remainder so the weights sum to exactly 1.0.
    out[keys[-1]] = round(1.0 - sum(out.values()), 6)
    return out


# ---------------------------------------------------------------------------
# claim types
# ---------------------------------------------------------------------------


def claim_types(family_key: str | None = None) -> dict[str, dict[str, Any]]:
    return family(family_key)["claim_types"]


def claim_type(family_key: str | None, type_key: str | None) -> dict[str, Any] | None:
    return claim_types(family_key).get(type_key or "")


def claim_type_label(family_key: str | None, type_key: str | None) -> str:
    spec = claim_type(family_key, type_key)
    if spec:
        return spec["label"]
    return (type_key or "Unclassified").replace("_", " ").title()


def default_claim_weights(family_key: str | None = None) -> dict[str, float]:
    """claim_type -> importance, summing to 100 for the family."""
    return {k: float(v["weight"]) for k, v in claim_types(family_key).items()}


def probe_focus(family_key: str | None, type_key: str | None) -> list[str]:
    """Dimensions this claim type is most worth probing. Steers the question
    policy so a coaching claim gets an AUTHENTICITY probe before a TOOL one."""
    spec = claim_type(family_key, type_key)
    return list(spec.get("probe_focus", [])) if spec else []


def fallback_claim_type(family_key: str | None = None) -> str:
    """Heaviest claim type in the family — used when classification fails."""
    weights = default_claim_weights(family_key)
    return max(weights, key=lambda k: weights[k]) if weights else "delivery"


# ---------------------------------------------------------------------------
# fact keys — the controlled vocabulary the consistency engine tracks
# ---------------------------------------------------------------------------


@lru_cache(maxsize=32)
def fact_keys(family_key: str | None = None) -> dict[str, dict[str, Any]]:
    keys = dict(_clean(_raw()["global_fact_keys"]))
    keys.update(_clean(family(family_key).get("fact_keys", {})))
    return keys


def fact_label(family_key: str | None, key: str) -> str:
    spec = fact_keys(family_key).get(key)
    return spec["label"] if spec else key.replace("_", " ").title()


def fact_kind(family_key: str | None, key: str) -> str:
    spec = fact_keys(family_key).get(key)
    return spec["kind"] if spec else "unknown"


def is_known_fact_key(family_key: str | None, key: str) -> bool:
    return key in fact_keys(family_key)


def fact_is_stable(family_key: str | None, key: str) -> bool:
    """True when a divergence between answers is a contradiction rather than a
    before/after. "CSAT went 78 -> 92" is an improvement; "team of 35" then
    "20 reported to me" is not."""
    spec = fact_keys(family_key).get(key)
    return bool(spec) and spec.get("stability") == "stable"


# ---------------------------------------------------------------------------
# classification (deterministic keyword scoring, no LLM)
#
# The LLM is asked for a claim_type and a family, but it can return junk or
# nothing. These functions are both the fallback and the validator.
# ---------------------------------------------------------------------------


# A keyword matches at a word boundary, optionally carrying one ordinary
# inflection. Naked substring matching -- what this replaced -- fired on
# ordinary English: "hr" inside *through* gave every resume an HR point, and
# inside *shrinkage* made BPO's own keyword donate one; "api" inside *rapid*
# and *capital*, "arr" inside *arranged*, "deal" inside *dealt*.
#
# The suffix group is why this is a prefix match and not `\b...\b`: the
# taxonomy stores stems, and "recruit" has to keep matching recruiter,
# recruiting and recruitment. It is deliberately inflections only -- no
# stemmer, because a stemmer is a dependency and a source of surprises, and
# this list is auditable by the PM who edits the taxonomy.
_INFLECTION = r"(?:s|es|ed|ing|er|ers|or|ors|ion|ions|ment|ments)?"


@lru_cache(maxsize=512)
def _term_pattern(term: str) -> re.Pattern[str]:
    """Word-boundary match on a taxonomy term, tolerating one inflection.

    `y -> ies` is handled in the STEM rather than the suffix group, because it
    replaces the y instead of following it: "user story" has to reach "user
    stories", and `story` + `ies` is not a word. 20 taxonomy terms end in -y
    across seven families -- query/queries, policy/policies,
    discovery/discoveries -- and without this each one silently scores nothing
    for its own plural.
    """
    parts = [re.escape(part) for part in term.split()]
    if parts[-1].endswith("y"):
        parts[-1] = parts[-1][:-1] + "(?:y|ies)"
    body = r"\s+".join(parts)
    return re.compile(rf"(?<!\w){body}{_INFLECTION}(?!\w)")


def _matched(text: str, keywords: list[str]) -> tuple[str, ...]:
    """Which keywords appear, each counted once however often it occurs.

    Once, not per occurrence: a resume that says SQL eleven times is not eleven
    times more a data resume, and rewarding repetition would make the router
    trivially gameable by the same keyword stuffing this product exists to see
    through.
    """
    low = (text or "").lower()
    return tuple(kw for kw in keywords if _term_pattern(kw).search(low))


def _hits(text: str, keywords: list[str]) -> int:
    return len(_matched(text, keywords))


# ---------------------------------------------------------------------------
# family routing
# ---------------------------------------------------------------------------

# A family needs at least this many distinct keywords before it beats GENERAL.
# One term is a coincidence; "npa" alone does not make a resume a banking
# resume. Carried over unchanged from the hit-count router it replaced.
MIN_TERMS = 2

# Above this margin a recruiter is entitled to read the routing as settled;
# below it, the call was close and the API says so.
#
# WHY 0.35, AND WHY IT DOES NOT DEMOTE. Measured over the 64-entry golden set:
# every one of the 49 resumes that routes to a real family does so at a margin
# of >= 0.397, and all four deliberately ambiguous entries land between 0.014
# and 0.321. So the floor separates them with zero misclassification -- and it
# is the value `test_taxonomy.py` had already been asserting locally since
# P1-06, promoted here so the API, the tests and the validation report cannot
# hold three different numbers.
#
# D2 specified "below margin threshold => general, flagged in the graph
# response". The flag ships; the DEMOTION does not, and the reason is a
# measurement rather than caution. The confident band bottoms out at 0.397 and
# the ambiguous band tops out at 0.321 -- a 0.076-wide gap, on four ambiguous
# entries. Rohit's seeded BPO resume sits at exactly 0.397, the floor of the
# confident band. Demoting on a threshold that close to a genuine resume trades
# a visible close call for a silent under-route to `general`, which strips every
# claim type and weight the family carries -- the failure mode CLAUDE.md already
# records as collapsing weight assertions across the suite. An under-route is
# not the safe direction; it is the same error with no margin to show for it.
#
# So routing is unchanged by this constant. It classifies, and nothing else.
MARGIN_FLOOR = 0.35


class FamilyMatch(NamedTuple):
    """Why a resume routed where it did.

    THE CROSS-STREAM CONTRACT (P1-06). `graph.py` reads `confidence` for
    `CandidateGraph.routing_confidence` and `/api/dev/detect` renders all four
    fields. Nothing else crosses between the two work streams, so changing this
    shape is a conversation, not a solo edit.

    `confidence` is a MARGIN, not a probability: how far the winner is clear of
    the runner-up, 0.0 when nothing matched and 1.0 when only one family scored
    at all. It answers "was this close?", which is the question a recruiter
    looking at a mis-routed candidate actually has. It is not a claim about
    being right.
    """

    family: str
    confidence: float
    matched_terms: tuple[str, ...]
    per_family_scores: dict[str, float]


@lru_cache(maxsize=1)
def _idf() -> dict[str, float]:
    """Inverse document frequency over the family vocabularies, at load time.

    A term shared by several families discriminates less; one held by a single
    family discriminates most. `pipeline` (sales and data_analytics) is worth
    less than `kubernetes`.

    MEASURED CAVEAT, worth knowing before trusting this: on the taxonomy as it
    stands 105 of 106 terms belong to exactly one family, so IDF is very nearly
    a constant and moves almost nothing today. It earns its place as families
    grow and start to overlap -- and it is honest about what it cannot see. IDF
    measures ambiguity WITHIN the taxonomy, so it scores `data`, `support`,
    `model` and `engagement` as maximally distinctive when their real problem is
    ambiguity against ordinary English. That needs a stop list built from a
    background corpus; it is not this function's job and it is not in Phase 1.
    """
    real = {k: v.get("keywords", []) for k, v in families().items() if k != GENERAL}
    n = len(real) or 1
    df: dict[str, int] = {}
    for keywords in real.values():
        for term in set(keywords):
            df[term] = df.get(term, 0) + 1
    return {term: math.log(n / count) for term, count in df.items()}


@lru_cache(maxsize=1)
def _family_norms() -> dict[str, float]:
    """L2 norm of each family's IDF vector -- the cosine denominator.

    Without it a family wins by owning a longer keyword list: software
    engineering has 19 terms and customer support 11, and raw sums would tilt
    every close call the same way. Square root rather than a plain sum on
    purpose: dividing by the total would let a three-term family reach a third
    of its ceiling on one lucky match.
    """
    idf = _idf()
    norms = {}
    for key, cfg in families().items():
        if key == GENERAL:
            continue
        total = sum(idf.get(term, 0.0) ** 2 for term in set(cfg.get("keywords", [])))
        norms[key] = math.sqrt(total) or 1.0
    return norms


def match_family(text: str) -> FamilyMatch:
    """Route a resume to a job family, deterministically and with no model call.

    Pure function of `text` and the taxonomy file. Same input, same output,
    forever -- which is what makes routing replayable and what lets
    `/api/dev/detect` explain a decision without spending a token.
    """
    idf, norms = _idf(), _family_norms()
    matches = {
        key: _matched(text, cfg.get("keywords", []))
        for key, cfg in families().items()
        if key != GENERAL
    }
    scores = {
        key: round(sum(idf.get(t, 0.0) for t in terms) / norms[key], 6)
        for key, terms in matches.items()
    }
    if not scores:
        return FamilyMatch(GENERAL, 0.0, (), {})

    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    best, top = ranked[0]
    runner_up = ranked[1][1] if len(ranked) > 1 else 0.0

    if len(matches[best]) < MIN_TERMS or top <= 0.0:
        # Too thin to call. Report the terms anyway -- "we saw npa and nothing
        # else" is a more useful thing to show a recruiter than silence.
        return FamilyMatch(GENERAL, 0.0, matches[best], scores)

    confidence = round((top - runner_up) / top, 6)
    return FamilyMatch(best, confidence, matches[best], scores)


def detect_family(text: str) -> str:
    """Best job family for a resume. Signature preserved for existing callers;
    anything needing the reasoning calls `match_family()`."""
    return match_family(text).family


def family_margin(match: FamilyMatch, family_key: str | None) -> float:
    """How clearly the resume belongs to `family_key` — not to the winner.

    WHY THIS EXISTS. `FamilyMatch.confidence` is the margin for the family the
    DETECTOR chose. Since P1-07 the detector is only consulted when the
    requisition supplied nothing, so a candidate can be scored as
    `bpo_operations` while `confidence` describes how clearly the resume read as
    `customer_support`. `CandidateGraph.routing_confidence` documents itself as
    "a low value means the resume did not clearly belong to THIS cohort", and
    only this function answers that question.

    Measured on the seeded personas: Priya and Arjun are both scored as
    `bpo_operations` while the detector prefers `customer_support` (by 0.719 and
    0.171). Reporting those two numbers against a BPO record says the BPO
    routing was confident, which is the opposite of true.

    Signed margins are clamped at 0.0. A resume that points AWAY from its
    assigned cohort and one that sits exactly on the fence both mean the same
    thing to the person reading it -- do not trust this cohort assignment -- and
    the frozen field documents itself as 0.0-1.0. `GET /api/dev/detect` carries
    the unclamped detail for whoever is actually investigating.
    """
    if not family_key or family_key == GENERAL:
        return 0.0
    mine = match.per_family_scores.get(family_key, 0.0)
    if mine <= 0.0:
        return 0.0
    best_other = max(
        (v for k, v in match.per_family_scores.items() if k != family_key),
        default=0.0,
    )
    return round(max(0.0, (mine - best_other) / mine), 6)


def is_low_confidence(match: FamilyMatch) -> bool:
    """Was this routing call too close to present as settled?

    A predicate over an existing `FamilyMatch`, not a fifth field on it:
    `FamilyMatch` is the cross-stream contract Developer B reads in `graph.py`,
    and a derived boolean is not worth changing that shape for. Anyone with the
    match can compute this, and everyone who does gets the same answer.

    A GENERAL route is low confidence by construction -- it carries 0.0 -- which
    is the correct reading: nothing reached the term floor, so there is nothing
    to be confident about.
    """
    return match.confidence < MARGIN_FLOOR


def classify_claim(text: str, family_key: str | None = None) -> str:
    """Best claim type for one claim line, by keyword hit count."""
    types = claim_types(family_key)
    scores = {key: _hits(text, cfg.get("keywords", [])) for key, cfg in types.items()}
    best = max(scores, key=lambda k: scores[k]) if scores else None
    if best and scores[best] > 0:
        return best
    return fallback_claim_type(family_key)


def normalise_claim_type(
    family_key: str | None, type_key: str | None, text: str = ""
) -> str:
    """Trust the model's claim_type only if it exists in this family."""
    if type_key and type_key in claim_types(family_key):
        return type_key
    return classify_claim(text, family_key)


# ---------------------------------------------------------------------------
# prompt helpers
# ---------------------------------------------------------------------------


def claim_type_menu(family_key: str | None = None) -> str:
    """Rendered into the claim-extraction prompt so the model picks a real key.

    Sorted highest-importance first, purely so the model reads the family's
    own priority order top to bottom instead of having to compare numbers
    scattered through the list. The importance values are unchanged and still
    live in data, not here.
    """
    ordered = sorted(
        claim_types(family_key).items(), key=lambda kv: -kv[1]["weight"]
    )
    return "\n".join(
        f"  {key} — {cfg['label']} (importance {cfg['weight']})"
        for key, cfg in ordered
    )


def fact_key_menu(family_key: str | None = None) -> str:
    """Rendered into the evidence prompt so facts come back on known keys."""
    return "\n".join(
        f"  {key} — {spec['label']} ({spec['kind']})"
        for key, spec in fact_keys(family_key).items()
    )


_WORD = re.compile(r"[a-z][a-z+#.\-]{2,}")


def family_vocabulary(family_key: str | None = None) -> set[str]:
    """Every keyword in the family — used by the PROCESS dimension rubric to
    recognise domain vocabulary in an answer."""
    cfg = family(family_key)
    words: set[str] = set(cfg.get("keywords", []))
    for spec in cfg["claim_types"].values():
        words.update(spec.get("keywords", []))
    return words
