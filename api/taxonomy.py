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

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

TAXONOMY_PATH = Path(__file__).resolve().parents[1] / "data" / "claim_taxonomy.json"

GENERAL = "general"


@lru_cache(maxsize=1)
def _raw() -> dict[str, Any]:
    return json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))


def _clean(mapping: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in mapping.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# families
# ---------------------------------------------------------------------------


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


def _hits(text: str, keywords: list[str]) -> int:
    low = (text or "").lower()
    return sum(1 for kw in keywords if kw in low)


def detect_family(text: str) -> str:
    """Best job family for a resume by keyword hit count."""
    scores = {
        key: _hits(text, cfg.get("keywords", []))
        for key, cfg in families().items()
        if key != GENERAL
    }
    best = max(scores, key=lambda k: scores[k]) if scores else GENERAL
    return best if scores.get(best, 0) >= 2 else GENERAL


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
    """Rendered into the claim-extraction prompt so the model picks a real key."""
    return "\n".join(
        f"  {key} — {cfg['label']} (importance {cfg['weight']})"
        for key, cfg in claim_types(family_key).items()
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
