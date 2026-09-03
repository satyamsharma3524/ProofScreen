"""
LLM call #1 — resume text -> job family + typed, weighted claims.

Every claim comes out classified against the taxonomy, because the claim TYPE
is what carries the recruiter's importance weight. An unclassified claim cannot
be ranked, so classification is validated in Python and never trusted blindly:
a claim_type the model invents is silently reclassified by keyword.
"""

from __future__ import annotations

import logging
import re

from api.config import settings
from api.llm import complete_json, load_prompt
from api.schemas import ClaimExtraction, ExtractedClaim
from api.taxonomy import (
    GENERAL,
    claim_type_menu,
    classify_claim,
    detect_family,
    families,
    family_label,
    normalise_claim_type,
    resolve_family,
)

log = logging.getLogger("proofscreen.extract")

MAX_RESUME_CHARS = 8000
MIN_CLAIM_SCORE = 2

_STRONG_VERBS = (
    "led", "built", "build", "managed", "manage", "improved", "improve",
    "reduced", "reduce", "increased", "increase", "launched", "launch",
    "migrated", "migrate", "designed", "owned", "scaled", "scale",
    "automated", "automate", "delivered", "deliver", "cut", "grew", "grow",
    "shipped", "rearchitected", "optimised", "optimized", "negotiated",
    "onboarded", "trained", "recovered", "handled", "resolved", "closed",
    "achieved", "exceeded", "processed", "supervised", "coached", "drove",
)

_FLUFF = (
    "team player", "hard working", "hard-working", "passionate", "self-motivated",
    "detail oriented", "detail-oriented", "results-driven", "results driven",
    "excellent communication", "go-getter", "quick learner", "dynamic professional",
    "strong work ethic", "out of the box", "excellent interpersonal",
)

_UNIT = r"(?:%|percent|ms|minutes?|mins?|months?|weeks?|days?|hours?|hrs?|lakh|cr|bn|k|m|x)"
_NUMBER = re.compile(rf"(?<![A-Za-z\d])\d+(?:[.,]\d+)?\s*{_UNIT}?", re.IGNORECASE)
_FROM_TO = re.compile(
    rf"from\s+([\d.,]+\s*{_UNIT}?)\s+to\s+([\d.,]+\s*{_UNIT}?)", re.IGNORECASE
)
_BULLET = re.compile(r"^[\s\-•\*●‣⁃o]+")
_PAREN_YEAR = re.compile(r"\((?:19|20)\d\d")
_DATE_RANGE = re.compile(
    r"\b(?:19|20)\d\d\s*[-–—]\s*(?:present|current|(?:19|20)\d\d)\b", re.IGNORECASE
)


def _metric_of(text: str) -> str | None:
    """Compress the measurable core. A before/after pair beats the first number."""
    pair = _FROM_TO.search(text)
    if pair:
        return f"{pair.group(1).strip()} -> {pair.group(2).strip()}"
    found = [m.group(0).strip() for m in _NUMBER.finditer(text)]
    found = [f for f in found if any(c.isdigit() for c in f)]
    if not found:
        return None
    percents = [f for f in found if "%" in f]
    if len(percents) >= 2:
        return f"{percents[0]} -> {percents[1]}"
    return found[0]


def _score_line(line: str) -> int:
    low = line.lower()
    if any(f in low for f in _FLUFF):
        return -5

    has_verb = any(re.search(rf"\b{v}\b", low) for v in _STRONG_VERBS)

    # "Support Lead, Northwind (2021 - present)" is a heading, always.
    if _PAREN_YEAR.search(line):
        return -1
    if _DATE_RANGE.search(line) and not has_verb:
        return -1
    # "Python, SQL, Tableau, Power BI, machine learning" is a skills list.
    if line.count(",") >= 3 and not has_verb:
        return -1

    score = 0
    if any(c.isdigit() for c in line):
        score += 3
    if "%" in line:
        score += 1
    score += sum(1 for v in _STRONG_VERBS if re.search(rf"\b{v}\b", low))
    return score


def heuristic_claims(
    resume_text: str, job_family: str, limit: int | None = None
) -> list[ExtractedClaim]:
    """No-LLM claim extraction. Deterministic, and good enough to demo on."""
    limit = limit or settings.max_claims
    candidates: list[tuple[int, str]] = []
    for raw in (resume_text or "").split("\n"):
        line = _BULLET.sub("", raw).strip(" .;")
        if not (25 <= len(line) <= 300) or line.endswith(":"):
            continue
        score = _score_line(line)
        if score >= MIN_CLAIM_SCORE:
            candidates.append((score, line))

    candidates.sort(key=lambda pair: (-pair[0], len(pair[1])))

    claims: list[ExtractedClaim] = []
    seen: set[str] = set()
    seen_types: set[str] = set()

    # Two passes: first take the strongest line of each distinct claim type, so
    # a resume with four latency bullets does not produce four latency claims
    # and leave team handling unprobed.
    for require_new_type in (True, False):
        for _, line in candidates:
            if len(claims) >= limit:
                break
            key = line.lower()[:60]
            if key in seen:
                continue
            claim_type = classify_claim(line, job_family)
            if require_new_type and claim_type in seen_types:
                continue
            seen.add(key)
            seen_types.add(claim_type)
            claims.append(
                ExtractedClaim(
                    text=line,
                    claim_type=claim_type,
                    metric=_metric_of(line),
                    verifiable=True,
                )
            )

    if not claims:
        snippet = (resume_text or "").strip().replace("\n", " ")[:200]
        claims = [
            ExtractedClaim(
                text=snippet or "Resume contained no parseable claims",
                claim_type=classify_claim(snippet, job_family),
                metric=None,
                verifiable=bool(snippet),
            )
        ]
    return claims[:limit]


def _family_menu() -> str:
    return "\n".join(f"  {key} — {cfg['label']}" for key, cfg in families().items())


async def extract_claims(
    resume_text: str,
    job_family: str | None = None,
    limit: int | None = None,
) -> tuple[str, list[ExtractedClaim]]:
    """LLM call #1. Returns (job_family, claims), both validated in Python."""
    limit = limit or settings.max_claims
    trimmed = (resume_text or "")[:MAX_RESUME_CHARS]

    # P1-07 — ROUTING PRECEDENCE, decided here and nowhere else:
    #
    #   1. the requisition's job_family, when the caller supplied a real one
    #   2. otherwise deterministic detection from the resume
    #
    # There is no third rung. The model's opinion is logged below, never
    # honoured. A recruiter hiring for a support role gets the support rubric
    # even when the resume reads like sales, because the requisition is a fact
    # about the job and detection is only an inference about the candidate.
    supplied = resolve_family(job_family) if job_family else GENERAL
    routed = supplied if supplied != GENERAL else detect_family(trimmed)

    prompt = load_prompt(
        "extract_claims",
        resume_text=trimmed,
        max_claims=limit,
        family_key=routed,
        family_menu=_family_menu(),
        claim_type_menu=claim_type_menu(routed),
    )

    result = await complete_json(
        prompt,
        ClaimExtraction,
        temperature=settings.llm_temperature_extract,
        fallback=lambda: ClaimExtraction(
            job_family=routed, claims=heuristic_claims(trimmed, routed, limit)
        ),
    )

    # The model still returns a family because the prompt still asks for one —
    # it is a useful disagreement signal and it keeps the response schema
    # stable. It is observed, not obeyed. Routing was already decided above.
    proposed = resolve_family(result.job_family) if result.job_family else routed
    if proposed != routed:
        log.info(
            "extract: model proposed family %s, routing stays %s (source=%s)",
            proposed,
            routed,
            "requisition" if supplied != GENERAL else "detection",
        )
    family = routed

    kept: list[ExtractedClaim] = []
    seen_types: set[str] = set()
    for claim in result.claims:
        text = (claim.text or "").strip()
        if not claim.verifiable or len(text) < 15:
            continue
        claim_type = normalise_claim_type(family, claim.claim_type, text)
        if claim_type in seen_types:
            continue           # one claim per type: breadth beats depth here
        seen_types.add(claim_type)
        kept.append(
            ExtractedClaim(
                text=text,
                claim_type=claim_type,
                metric=claim.metric or _metric_of(text),
                verifiable=True,
            )
        )
        if len(kept) >= limit:
            break

    if not kept:
        log.warning("model returned no usable claims, using heuristic")
        kept = heuristic_claims(trimmed, family, limit)

    log.info(
        "extracted %d claims for %s (%s)",
        len(kept), family_label(family), ", ".join(c.claim_type or "?" for c in kept),
    )
    return family, kept
