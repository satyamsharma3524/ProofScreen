"""
LLM call #2 — write the next probe for a claim on a given dimension.

Policy is code (orchestrator.py). Wording is the LLM. If the LLM is slow,
down, or off, the pre-written fallback for that dimension is used and the
candidate never notices.
"""

from __future__ import annotations

import logging
import re

from api.config import settings
from api.llm import complete_json, load_prompt
from api.schemas import Dimension, GeneratedQuestion

log = logging.getLogger("proofscreen.question")

# One hand-written question per dimension. These are the safety net that keeps
# a dead LLM off the projector — and they are genuinely decent questions.
FALLBACK_QUESTIONS: dict[Dimension, str] = {
    Dimension.OWNERSHIP: (
        "Which parts of this did you personally do, and which parts did other "
        "people on the team handle?"
    ),
    Dimension.DEPTH: (
        "What was actually causing the problem, and why did your fix work when "
        "it did?"
    ),
    Dimension.SPECIFICITY: (
        "Can you give me the specifics — the numbers, the tools you used, and "
        "the timeframe?"
    ),
    Dimension.OPERATIONAL: (
        "How did you roll this out, and what broke or needed fixing afterwards?"
    ),
}


_WS = re.compile(r"\s+")


def _claim_hint(claim_text: str, limit: int = 90) -> str:
    short = _WS.sub(" ", claim_text or "").strip()
    return short if len(short) <= limit else short[: limit - 3].rstrip() + "..."


def fallback_question(
    dimension: Dimension, claim_text: str | None = None
) -> GeneratedQuestion:
    """The pre-written probe for a dimension, anchored to its claim.

    The anchor is not decoration. A candidate on WhatsApp seeing "Which parts
    of this did you personally do?" has no idea which resume line "this" is —
    and without it, two claims probed on the same dimension produce two
    byte-identical questions.
    """
    base = FALLBACK_QUESTIONS[dimension]
    if not claim_text:
        return GeneratedQuestion(question=base, intent=dimension)
    return GeneratedQuestion(
        question=f'On "{_claim_hint(claim_text)}" — {base}', intent=dimension
    )


def _format_prior(prior_qa: list[tuple[str, str]]) -> str:
    if not prior_qa:
        return "(nothing yet — this is the first question of the session)"
    return "\n\n".join(
        f"Q: {q}\nA: {a[:600]}" for q, a in prior_qa[-4:]
    )


async def generate_question(
    claim_text: str,
    dimension: Dimension,
    claim_metric: str | None = None,
    prior_qa: list[tuple[str, str]] | None = None,
) -> GeneratedQuestion:
    prompt = load_prompt(
        "generate_question",
        claim_text=claim_text,
        claim_metric=claim_metric or "none stated",
        dimension=dimension.value,
        prior_qa=_format_prior(prior_qa or []),
    )

    result = await complete_json(
        prompt,
        GeneratedQuestion,
        temperature=settings.llm_temperature_question,
        fallback=lambda: fallback_question(dimension, claim_text),
        # question wording is non-deterministic on purpose; caching it would
        # make every follow-up on a repeated claim identical
        cache=False,
    )

    text = result.question.strip()
    if not text or len(text) < 10:
        log.warning("model returned an unusable question, using fallback")
        return fallback_question(dimension, claim_text)

    # The policy decides the dimension, not the model. Never let a drifting
    # `intent` corrupt coverage bookkeeping.
    return GeneratedQuestion(question=text, intent=dimension)
