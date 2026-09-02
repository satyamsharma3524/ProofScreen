"""
LLM call #1 — resume text -> the 3 most verifiable claims.

Rejects unverifiable fluff. Falls back to a deterministic heuristic when the
model is unavailable, so the product demos with no API key at all.
"""

from __future__ import annotations

import logging
import re

from api.config import settings
from api.llm import complete_json, load_prompt
from api.schemas import ClaimExtraction, ExtractedClaim

log = logging.getLogger("proofscreen.extract")

MAX_RESUME_CHARS = 8000

# NOTE: bare "lead" and "design" are deliberately absent — on a resume they are
# nouns at least as often as verbs ("Support Lead", "process design"), and every
# job-title heading would score as a claim.
_STRONG_VERBS = (
    "led", "built", "build", "managed", "manage", "improved", "improve",
    "reduced", "reduce", "increased", "increase", "launched", "launch",
    "migrated", "migrate", "designed", "owned", "scaled",
    "scale", "automated", "automate", "delivered", "deliver", "cut", "grew",
    "grow", "shipped", "rearchitected", "optimised", "optimized",
    "negotiated", "onboarded", "trained", "recovered", "handled",
)

_FLUFF = (
    "team player", "hard working", "hard-working", "passionate", "self-motivated",
    "detail oriented", "detail-oriented", "results-driven", "results driven",
    "excellent communication", "go-getter", "quick learner", "dynamic professional",
    "strong work ethic", "out of the box",
)

_CATEGORY_HINTS = {
    "engineering": ("api", "latency", "deploy", "kubernetes", "python", "java",
                    "service", "backend", "frontend", "database", "microservice",
                    "aws", "docker", "code", "release", "bug"),
    "data": ("model", "pipeline", "etl", "ml", "machine learning", "dashboard",
             "analytics", "sql", "forecast", "accuracy"),
    "support": ("csat", "ticket", "escalation", "sla", "helpdesk", "queue",
                "resolution", "customer support"),
    "sales": ("revenue", "quota", "pipeline", "deal", "arr", "closed", "client",
              "account"),
    "marketing": ("campaign", "cac", "seo", "funnel", "impressions", "leads",
                  "brand", "ctr"),
    "operations": ("process", "cost", "vendor", "throughput", "logistics",
                   "headcount", "efficiency", "turnaround"),
    "product": ("roadmap", "feature", "adoption", "retention", "nps", "launch",
                "user research"),
    "hr": ("hiring", "attrition", "onboarding", "recruit", "payroll",
           "engagement survey"),
    "finance": ("budget", "margin", "audit", "reconciliation", "forecast",
                "invoice"),
}

# Longest alternative first: "ms" must beat "m", "minutes" must beat "mins".
_UNIT = r"(?:%|percent|ms|minutes?|mins?|months?|weeks?|days?|hours?|hrs?|lakh|bn|cr|k|m|x)"
_NUMBER = re.compile(rf"(?<![A-Za-z\d])\d+(?:[.,]\d+)?\s*{_UNIT}?", re.IGNORECASE)
_BULLET = re.compile(r"^[\s\-•\*●‣⁃o]+")

# "Support Lead, Northwind Services (2021 - present)" is employment history,
# not a claim. A date range with no verb in it is a heading.
_PAREN_YEAR = re.compile(r"\((?:19|20)\d\d")
_DATE_RANGE = re.compile(
    r"\b(?:19|20)\d\d\s*[-–—]\s*(?:present|current|(?:19|20)\d\d)\b", re.IGNORECASE
)

# Minimum signal for a line to count as a verifiable claim. A bare year (3
# points from the digit rule) is not enough on its own.
MIN_CLAIM_SCORE = 2


def _categorise(text: str) -> str:
    low = text.lower()
    best, best_hits = "general", 0
    for category, hints in _CATEGORY_HINTS.items():
        hits = sum(1 for h in hints if h in low)
        if hits > best_hits:
            best, best_hits = category, hits
    return best


_FROM_TO = re.compile(
    rf"from\s+([\d.,]+\s*{_UNIT}?)\s+to\s+([\d.,]+\s*{_UNIT}?)", re.IGNORECASE
)


def _metric_of(text: str) -> str | None:
    """Compress the measurable core of a claim.

    "improved CSAT from 78% to 92%" must become "78% -> 92%", not "50 -> 78%"
    — a before/after pair is the metric, and the first two numbers in the
    sentence usually are not that pair.
    """
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

    # "Support Lead, Northwind Services (2021 - present)" is a heading, always.
    if _PAREN_YEAR.search(line):
        return -1

    # A bare date range with nothing the candidate actually did.
    if _DATE_RANGE.search(line) and not has_verb:
        return -1

    # "Python, SQL, Tableau, Power BI, machine learning" — a skills list.
    if line.count(",") >= 3 and not has_verb:
        return -1

    score = 0
    if any(c.isdigit() for c in line):
        score += 3
    if "%" in line:
        score += 1
    score += sum(1 for v in _STRONG_VERBS if re.search(rf"\b{v}\b", low))
    return score


def heuristic_claims(resume_text: str, limit: int | None = None) -> list[ExtractedClaim]:
    """No-LLM claim extraction. Deterministic, and good enough to demo on."""
    limit = limit or settings.max_claims
    candidates: list[tuple[int, str]] = []
    for raw in (resume_text or "").split("\n"):
        line = _BULLET.sub("", raw).strip(" .;")
        if not (25 <= len(line) <= 300):
            continue
        if line.endswith(":"):
            continue
        score = _score_line(line)
        if score >= MIN_CLAIM_SCORE:
            candidates.append((score, line))

    candidates.sort(key=lambda pair: (-pair[0], len(pair[1])))
    seen: set[str] = set()
    claims: list[ExtractedClaim] = []
    for _, line in candidates:
        key = line.lower()[:60]
        if key in seen:
            continue
        seen.add(key)
        claims.append(
            ExtractedClaim(
                text=line,
                metric=_metric_of(line),
                category=_categorise(line),
                verifiable=True,
            )
        )
        if len(claims) >= limit:
            break

    if not claims:
        # Absolute floor: never return zero claims, the session cannot start.
        snippet = (resume_text or "").strip().replace("\n", " ")[:200]
        claims = [
            ExtractedClaim(
                text=snippet or "Candidate submitted a resume with no parseable claims",
                metric=None,
                category="general",
                verifiable=bool(snippet),
            )
        ]
    return claims


async def extract_claims(
    resume_text: str, limit: int | None = None
) -> list[ExtractedClaim]:
    """LLM call #1, with the heuristic as the fallback on any failure."""
    limit = limit or settings.max_claims
    trimmed = (resume_text or "")[:MAX_RESUME_CHARS]

    prompt = load_prompt("extract_claims", resume_text=trimmed, max_claims=limit)
    result = await complete_json(
        prompt,
        ClaimExtraction,
        temperature=settings.llm_temperature_extract,
        fallback=lambda: ClaimExtraction(claims=heuristic_claims(trimmed, limit)),
    )

    kept = [c for c in result.claims if c.verifiable and c.text.strip()]
    if not kept:
        log.warning("model returned no verifiable claims, using heuristic")
        kept = heuristic_claims(trimmed, limit)

    log.info("extracted %d claims", len(kept[:limit]))
    return kept[:limit]
