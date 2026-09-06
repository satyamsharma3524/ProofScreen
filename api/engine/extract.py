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

from pydantic import BaseModel, Field

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


# ---------------------------------------------------------------------------
# ROLE CLASSIFICATION (LLM #0) — which profession should this person be
# interviewed as?
#
# THE PROBLEM THIS SOLVES, MEASURED. `match_family()` scores keyword density,
# and a product manager's achievements are written in the vocabulary of sales:
# revenue, pipeline, conversion, GTM, ARR, funnel, B2B. On six real PM resumes
# the keyword router chose `sales` three times and `data_analytics` twice.
#
# The damage is not the label. `extract_claims` builds its prompt with
# `claim_type_menu(routed)`, so a resume routed to `sales` is handed the sales
# claim types and asked to find claims that fit them -- and it obliges, from
# whatever sales job is on the page. Four of those six resumes produced claims
# from a job the candidate left in 2021. The interview then asked about it.
#
# So the family has to be right BEFORE extraction, not corrected after.
# ---------------------------------------------------------------------------

_SECTION_HEAD = re.compile(
    r"^\s*(professional\s+summary|summary|profile|objective|about\s+me|"
    r"career\s+objective|experience\s+summary|core\s+skills|skills|"
    r"key\s+skills|technical\s+skills|technology\s+stack[^:]*|"
    r"areas\s+of\s+expertise)\s*:?\s*$",
    re.IGNORECASE,
)
# A WIDER date pattern than `_DATE_RANGE`, used ONLY here. `_DATE_RANGE` drives
# `_score_line` and therefore `heuristic_claims`, so it is not being touched:
# it requires year-dash-year and misses "Jul 2017 - Aug 2021", where a month
# name sits between the dash and the year. That is the commonest way a resume
# writes a tenure, and it is how job titles are found.
_MONTH_YEAR = re.compile(
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?,?\s*(?:19|20)\d\d\b",
    re.IGNORECASE,
)
HEADER_SLICE_CHARS = 1800
MIN_HEADER_CHARS = 40


def _has_strong_verb(line: str) -> bool:
    low = line.lower()
    return any(re.search(rf"\b{verb}\b", low) for verb in _STRONG_VERBS)


def _is_tenure_line(line: str) -> bool:
    """A dates-and-place line, not an achievement. The distinction is the verb —
    the same one `_score_line` draws to tell a heading from a bullet."""
    if _has_strong_verb(line):
        return False
    return bool(
        _PAREN_YEAR.search(line) or _DATE_RANGE.search(line) or _MONTH_YEAR.search(line)
    )


def header_slice(text: str, max_chars: int = HEADER_SLICE_CHARS) -> str:
    """The top of a resume: headline, title history, summary, skills.

    ACHIEVEMENT BULLETS ARE EXCLUDED, and that is the entire point. They are
    where the revenue-and-pipeline language lives, and that language is what
    routes a product manager to sales. The fix is not to weigh the body more
    cleverly; it is not to send the body.

    Bullets are identified with `_score_line`, which already draws exactly this
    line for `heuristic_claims`: a parenthesised year or a bare date range with
    no verb is a HEADING, a comma-heavy line with no verb is a SKILLS LIST, and
    anything with digits and strong verbs is an achievement. Reused rather than
    re-derived, so the two cannot disagree about what a bullet is.

    Deterministic. No model call.
    """
    lines = [line.strip() for line in (text or "").splitlines()]
    parts: list[str] = []

    # 1. the headline — name, contact, and whatever one-liner sits under it
    head = [line for line in lines[:8] if line][:5]
    if head:
        parts.append("HEADER:\n" + "\n".join(head))

    # 2. title history. A title and its dates are usually two lines ("Product
    #    Lead - Pync" / "Apr 2025 - Present | Bangalore"), so a date line pulls
    #    in the line above it.
    titles: list[str] = []
    seen: set[str] = set()
    for index, line in enumerate(lines):
        if not line or len(line) > 140 or not _is_tenure_line(line):
            continue
        # A title and its dates are usually two lines. Take the nearest
        # non-empty line above, when it reads like a heading rather than a
        # bullet, then the tenure line itself.
        candidates: list[str] = []
        previous = next((l for l in reversed(lines[max(0, index - 2):index]) if l), None)
        if previous and len(previous) <= 140 and not _has_strong_verb(previous):
            candidates.append(previous)
        candidates.append(line)
        for candidate in candidates:
            key = candidate.lower()
            if key in seen:
                continue
            seen.add(key)
            titles.append(candidate)
    if titles:
        parts.append(
            "JOB TITLES (in resume order):\n"
            + "\n".join(f"- {t}" for t in titles[:8])
        )

    # 3. the summary and skills sections, achievement bullets removed
    for index, line in enumerate(lines):
        if not _SECTION_HEAD.match(line):
            continue
        body: list[str] = []
        for following in lines[index + 1: index + 12]:
            if _SECTION_HEAD.match(following):
                break
            if not following:
                if body:
                    break
                continue
            if _score_line(following) > 0:
                continue                      # an achievement bullet
            body.append(following)
            if len(body) >= 6:
                break
        if body:
            parts.append(f"{line.rstrip(':').upper()}:\n" + "\n".join(body))

    return "\n\n".join(parts)[:max_chars]


class RoleClassification(BaseModel):
    """The classifier's reply. LOCAL TO THIS MODULE, deliberately.

    Not in `api/schemas.py`: that file is frozen and is the contract with the
    dashboard, and nothing outside this module reads any of these fields.

    `confidence` and `seniority` are RECORDED AND NEVER BRANCHED ON.
    CLAUDE.md rule 1 forbids parsing a rating or a confidence out of a model
    response and acting on it, and there is no exemption for routing. They are
    logged so a later change can be argued from data instead of from intuition.
    Certainty comes from the precedence order, not from a number the model
    made up about itself.
    """

    family: str | None = None
    confidence: float | None = None
    seniority: str | None = None
    current_title: str | None = None
    reasoning: list[str] = Field(default_factory=list)


async def classify_role(resume_text: str, taxonomy_family: str) -> str:
    """LLM #0. Returns a family key — never a score, never a probability.

    Falls back to `taxonomy_family`, which is what routing did before this
    existed. A model that is down, slow or unparseable therefore costs routing
    ACCURACY and never costs the interview (CLAUDE.md rule 5).
    """
    if not settings.role_classifier:
        return taxonomy_family

    header = header_slice(resume_text)
    if len(header) < MIN_HEADER_CHARS:
        # No headline, no titles, no summary. There is nothing here a recruiter
        # could route on either, and inventing one is worse than the keywords.
        log.info("role classifier: header too thin, keeping taxonomy %s", taxonomy_family)
        return taxonomy_family

    result = await complete_json(
        load_prompt("classify_role", family_menu=_family_menu(), header=header),
        RoleClassification,
        temperature=0.0,
        fallback=lambda: RoleClassification(family=taxonomy_family),
    )

    chosen = resolve_family(result.family) if result.family else taxonomy_family
    log.info(
        "role classifier: %s (title=%r seniority=%s self-reported=%s) vs taxonomy %s%s",
        chosen,
        result.current_title,
        result.seniority,
        result.confidence,
        taxonomy_family,
        "" if chosen == taxonomy_family else "  [OVERRIDE]",
    )
    return chosen


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
    #   2. the role classifier, on the TOP of the resume only        (LLM #0)
    #   3. deterministic keyword detection from the whole resume
    #   4. general
    #
    # Rung 1 is unchanged and still absolute: a recruiter hiring for a support
    # role gets the support rubric even when the resume reads like sales,
    # because the requisition is a fact about the job and everything below it
    # is an inference about the candidate.
    #
    # Rung 2 was added because rung 3 routes on vocabulary, and a product
    # manager's vocabulary is a salesperson's -- see `classify_role` above for
    # the measurement. It is an ORDERED LIST, not a weighted blend: there is no
    # threshold to tune, and no model-reported confidence is read (rule 1).
    # Rung 3 is reached when the classifier is off, has too little to read, or
    # fails -- `complete_json`'s fallback returns the rung-3 answer, so a dead
    # model degrades to exactly the behaviour that shipped before this.
    #
    # The classifier runs BEFORE the prompt below is built, and that ordering
    # is the whole point: `claim_type_menu(routed)` decides which claims the
    # model is allowed to find, so a family corrected after extraction would
    # leave sales claims wearing product labels.
    supplied = resolve_family(job_family) if job_family else GENERAL
    if supplied != GENERAL:
        routed = supplied
    else:
        routed = await classify_role(trimmed, detect_family(trimmed))

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
