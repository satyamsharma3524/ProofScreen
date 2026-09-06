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
    claim_types,
    classify_claim,
    classify_claim_debug,
    default_claim_weights,
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

_INVENTORY_EXTRA_VERBS = (
    "integrated", "developed", "implemented", "collaborated", "architected",
    "enabled",
)
"""Recognised only by `_is_claim_line`, not `_score_line`.

`_STRONG_VERBS` also drives `_has_strong_verb` -- `header_slice` and
`_is_tenure_line` use it to tell a heading from a bullet -- so it stays as
measured. These are implementation/integration verbs `_score_line` never
scored (D2, docs/EXTRACTION_ARCHITECTURE_REVIEW.md): a resume line whose only
verb is "integrated" or "developed" scored 0 for its verb and, being
comma-heavy by nature (it lists the systems integrated), was misread as a
skills list and rejected outright -- not deprioritised, dropped as not a
claim at all.
"""

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
_WS_RUN = re.compile(r"\s+")


def _dedupe_key(text: str) -> str:
    """Two renderings of one sentence collapse to one claim.

    Deliberately crude and prefix-based -- the same shape `heuristic_claims`
    already uses for its own `seen` set, so the model path and the fallback
    path agree about what counts as a repeat. This is NOT claim selection: a
    resume that states the same achievement in a summary line and again in a
    bullet has made one claim, and inventory mode still wants it once.
    """
    return _WS_RUN.sub(" ", (text or "").lower()).strip()[:60]


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


def _is_claim_line(line: str) -> bool:
    """Inventory-mode predicate: is this line a distinct verifiable claim at all?

    Unlike `_score_line`, this never ranks and never eliminates on precision --
    there is no `MIN_CLAIM_SCORE` here. Recall-first extraction has nothing to
    rank for; a line either is a claim (something owned, built, integrated,
    delivered, run) or it is a heading, a skills list or fluff. Those three
    rejections are the only ones extraction is allowed to make
    (docs/EXTRACTION_ARCHITECTURE_REVIEW.md §4).

    Uses `_INVENTORY_EXTRA_VERBS` on top of `_STRONG_VERBS` so an
    implementation/integration bullet with no outcome verb and no number --
    "Integrated Twilio's SDK to enable SMS, voice, and WhatsApp
    communications..." -- has a recognised verb and is not misread as a
    comma-heavy skills list (D2). The comma rule also requires the line to
    have no digits, not just no verb -- a metric with no recognised verb
    should still survive as a claim.
    """
    low = line.lower()
    if any(f in low for f in _FLUFF):
        return False
    verbs = _STRONG_VERBS + _INVENTORY_EXTRA_VERBS
    has_verb = any(re.search(rf"\b{v}\b", low) for v in verbs)
    if _PAREN_YEAR.search(line):
        return False
    if _DATE_RANGE.search(line) and not has_verb:
        return False
    has_digit = any(c.isdigit() for c in line)
    if line.count(",") >= 3 and not has_verb and not has_digit:
        return False
    return True


def heuristic_claims(
    resume_text: str, job_family: str, limit: int | None = None
) -> list[ExtractedClaim]:
    """No-LLM claim extraction. Deterministic, and good enough to demo on."""
    limit = limit or (
        settings.max_inventory_claims if settings.claim_inventory
        else settings.max_claims
    )
    lines: list[str] = []
    for raw in (resume_text or "").split("\n"):
        line = _BULLET.sub("", raw).strip(" .;")
        if not (25 <= len(line) <= 300) or line.endswith(":"):
            continue
        lines.append(line)

    claims: list[ExtractedClaim] = []
    if settings.claim_inventory:
        # RECALL-FIRST: every line that survives `_is_claim_line`, in resume
        # order -- no score, no rank, no type spread, no top-N. Selection is a
        # planning decision (`orchestrator.plan_next`), not an extraction one.
        # `limit` is a safety ceiling on a runaway document, not a budget: it
        # only bites far above any real resume, and it logs when it does.
        seen: set[str] = set()
        for line in lines:
            if not _is_claim_line(line):
                continue
            key = _WS_RUN.sub(" ", line.lower()).strip()
            if key in seen:
                continue
            seen.add(key)
            claims.append(
                ExtractedClaim(
                    text=line,
                    claim_type=classify_claim(line, job_family),
                    metric=_metric_of(line),
                    verifiable=True,
                )
            )
        if len(claims) > limit:
            log.warning(
                "heuristic_claims: %d claims exceeds safety ceiling %d, truncating",
                len(claims), limit,
            )
            claims = claims[:limit]
    else:
        # LEGACY, unchanged: score, rank by score, spread across claim types,
        # cap at `limit`. This is the pre-inventory behaviour and it is what
        # runs while CLAIM_INVENTORY=false.
        candidates: list[tuple[int, str]] = []
        for line in lines:
            score = _score_line(line)
            if score >= MIN_CLAIM_SCORE:
                candidates.append((score, line))
        candidates.sort(key=lambda pair: (-pair[0], len(pair[1])))

        seen = set()
        seen_types: set[str] = set()
        # Two passes: first take the strongest line of each distinct claim
        # type, so a resume with four latency bullets does not produce four
        # latency claims and leave team handling unprobed.
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

    # HOW MANY TO ASK FOR. In inventory mode: NONE. No number reaches the
    # model at all -- extraction is a recall step, the number of claims a
    # resume contains is a property of the resume, and a cardinality target in
    # the prompt is an anchor even when phrased as "stop at N only if more
    # exist" (measured, docs/EXTRACTION_ARCHITECTURE_REVIEW.md D1: raising the
    # rendered ceiling from 12 to 40 raised the model's own count from 12 to
    # 17 and 14 on two real resumes -- the lower number was not a true count,
    # it was the model satisficing near what it was told). `ceiling` still
    # exists, but only as a Python-side safety ceiling (`max_inventory_claims`,
    # below) and as the offline heuristic fallback's limit -- it is never
    # rendered into the prompt in this mode.
    #
    # In legacy mode this is unchanged: a small overshoot over `limit`, capped
    # at the family's own type count, still told to the model, so the weight
    # sort below has something to choose among. That is the pre-inventory
    # behaviour and it is what runs while `CLAIM_INVENTORY=false`.
    ceiling = (
        settings.max_inventory_claims if settings.claim_inventory
        else min(limit + 3, len(claim_types(routed)))
    )
    stop_condition = (
        "There is no fixed number to return -- a short resume may hold three "
        "claims, a long one twenty or more. Do not stop early because you "
        "reached a round number; do not hold back a real claim to keep the "
        "count small."
        if settings.claim_inventory
        else f"Stop at {ceiling} only if the resume genuinely contains more than that."
    )

    # DISCOVERY VS TYPING, split at the prompt level. In inventory mode the
    # model is never asked for a claim_type at all -- not even as a soft,
    # non-gating label -- because whether that ask is truly inert is
    # unmeasured (docs/EXTRACTION_ARCHITECTURE_REVIEW.md D5, docs/
    # PARSE_EXTRACT_MERGE_REVIEW.md's "what must be checked before committing
    # to D"). `normalise_claim_type` below already assigns a type from `None`
    # exactly as it does today from an invented key -- this is not a new code
    # path, only a more frequent one. Legacy mode is unchanged: the four
    # `$claim_type_*` / `$share_type_note` placeholders below render byte-for-
    # byte what used to be static text (verified in tests/test_extract.py).
    if settings.claim_inventory:
        share_type_note = ""
        claim_type_section = ""
        claim_type_field = ""
        claims_example_type = ""
    else:
        share_type_note = (
            "\nSEVERAL CLAIMS MAY SHARE A CLAIM TYPE. That is expected and "
            "correct. Never drop\na real claim because you already returned "
            "one of its type, and never stretch a\nclaim onto a type it does "
            "not fit in order to spread the types out.\n"
        )
        claim_type_section = (
            f"\nCLAIM TYPES for the family you picked ({routed}):\n"
            f"{claim_type_menu(routed)}\n\n"
            "The importance number beside each type is for a LATER stage. Use "
            "the list ONLY\nto label a claim you have already decided to "
            "include. It must never decide\nwhether to include one.\n"
        )
        claim_type_field = (
            "  claim_type  - one key from the CLAIM TYPES list above. Nothing else.\n"
        )
        claims_example_type = ', "claim_type": "string"'

    prompt = load_prompt(
        "extract_claims",
        resume_text=trimmed,
        stop_condition=stop_condition,
        share_type_note=share_type_note,
        claim_type_section=claim_type_section,
        claim_type_field=claim_type_field,
        claims_example_type=claims_example_type,
        family_key=routed,
        family_menu=_family_menu(),
    )

    result = await complete_json(
        prompt,
        ClaimExtraction,
        temperature=settings.llm_temperature_extract,
        fallback=lambda: ClaimExtraction(
            job_family=routed, claims=heuristic_claims(trimmed, routed, ceiling)
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

    # WHAT SURVIVES, AND WHY THE TWO MODES DIFFER.
    #
    # Three filters run in BOTH modes, and none of them is a ranking decision:
    #   * `verifiable=false` -- the model says no question could test it
    #   * text shorter than 15 chars -- not a sentence
    #   * duplicate TEXT -- one sentence stated twice is one claim
    #
    # INVENTORY MODE stops there. No claim_type dedup and no top-N, because
    # both are SELECTION, and selection belongs downstream where the interview
    # budget and the role weights live. Resume order is preserved so
    # `Claim.order_index` still means "where this appeared on the page".
    #
    # LEGACY MODE additionally keeps one claim per type and ranks by the
    # family's importance weights. It is the pre-inventory behaviour and it is
    # what runs while `CLAIM_INVENTORY=false`.
    candidates: list[ExtractedClaim] = []
    pool: list[ExtractedClaim] = []
    seen_text: set[str] = set()
    # OBSERVABILITY ONLY: every raw claim the model proposed, tagged with why it
    # did or did not make `candidates`. None of this feeds a decision — it is
    # assembled from the same branches below, purely so a rejected claim is
    # still visible in the log instead of vanishing silently.
    rejected: list[tuple[str, str]] = []
    for claim in result.claims:
        text = (claim.text or "").strip()
        if not claim.verifiable:
            rejected.append((text, "model marked not verifiable"))
            continue
        if len(text) < 15:
            rejected.append((text, "shorter than 15 chars"))
            continue
        key = _dedupe_key(text)
        if key in seen_text:
            rejected.append((text, "duplicate text"))
            continue
        seen_text.add(key)

        model_type = claim.claim_type
        trusted = bool(model_type and model_type in claim_types(family))
        claim_type = normalise_claim_type(family, model_type, text)
        log.info(
            "claim classification: text=%r family=%s model_type=%s trusted=%s "
            "selected=%s scores=%s",
            text[:80], family, model_type, trusted, claim_type,
            {
                k: v[0]
                for k, v in sorted(
                    classify_claim_debug(text, family).items(),
                    key=lambda kv: -kv[1][0],
                )
                if v[0] > 0
            },
        )

        pool.append(
            ExtractedClaim(
                text=text,
                claim_type=claim_type,
                metric=claim.metric or _metric_of(text),
                verifiable=True,
            )
        )

    if settings.claim_inventory:
        candidates = pool
    else:
        # LIVE_INTERVIEW_QUALITY_AUDIT F4/P2 — rank by strength BEFORE the
        # one-per-type cap decides who keeps the slot, not by document
        # position. A resume lists jobs in reverse-chronological order, not in
        # order of evidentiary strength, so the old cap kept whichever claim of
        # a type happened to appear first on the page: the summary's own
        # lead achievement lost its slot to an earlier, weaker line of the same
        # type in both real interviews this session was measured against.
        # Weight, then a metric beating no metric, then document position as
        # the final tiebreak.
        weights = default_claim_weights(family)
        ranked = sorted(
            enumerate(pool),
            key=lambda iv: (-weights.get(iv[1].claim_type, 0.0), not iv[1].metric, iv[0]),
        )
        seen_types: set[str] = set()
        for _, ranked_claim in ranked:
            if ranked_claim.claim_type in seen_types:
                rejected.append((
                    ranked_claim.text,
                    f"one-per-type cap: {ranked_claim.claim_type} already kept",
                ))
                continue       # one claim per type: breadth beats depth here
            seen_types.add(ranked_claim.claim_type)
            candidates.append(ranked_claim)

    if settings.claim_inventory:
        # Not a top-N -- a warning-logged backstop against a pathological
        # reply, the same shape as `heuristic_claims`'s own safety ceiling.
        # `max_inventory_claims` must stay well above any real resume's claim
        # count (measured saturation: 17) or this silently reproduces the
        # exact defect removing the prompt-side number was meant to fix.
        if len(candidates) > ceiling:
            log.warning(
                "extract_claims: model returned %d claims, exceeds safety "
                "ceiling %d, truncating",
                len(candidates), ceiling,
            )
        kept = candidates[:ceiling]
        dropped_by_limit = candidates[ceiling:]
        limit_reason = "max_inventory_claims ceiling"
    else:
        weights = default_claim_weights(family)
        candidates.sort(key=lambda c: -weights.get(c.claim_type, 0.0))
        kept = candidates[:limit]
        dropped_by_limit = candidates[limit:]
        limit_reason = "max_claims limit, ranked by claim_type weight"

    for c in dropped_by_limit:
        rejected.append((c.text, limit_reason))

    if not kept:
        log.warning("model returned no usable claims, using heuristic")
        kept = heuristic_claims(trimmed, family, ceiling)

    if rejected:
        log.info(
            "claim ranking: %d claim(s) not selected: %s",
            len(rejected),
            [{"text": t[:70], "reason": r} for t, r in rejected],
        )

    log.info(
        "extracted %d claims for %s (%s)",
        len(kept), family_label(family), ", ".join(c.claim_type or "?" for c in kept),
    )
    claim_weights_for_log = default_claim_weights(family)
    for i, c in enumerate(kept):
        log.info(
            "claim %d [%s] weight=%s%s: %s",
            i + 1, c.claim_type or "?",
            claim_weights_for_log.get(c.claim_type or "", 0.0),
            f" metric={c.metric}" if c.metric else "",
            c.text,
        )
    return family, kept
