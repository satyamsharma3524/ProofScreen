"""
ARTIFACT 3 — question generation.  LLM call #2.

The POLICY decides which claim and which probe level (engine/orchestrator.py).
The model only chooses the wording. If it is slow, down or off, the
hand-written fallback for that level is used and the candidate notices nothing.

Every fallback is anchored to the claim text, because a candidate reading
"Tell me about a specific time this went wrong" on WhatsApp has no idea which
of their three resume lines "this" refers to.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from string import Template

from api.config import settings
from api.llm import complete_json, load_prompt
from api.schemas import Dimension, GeneratedQuestion, ProbeLevel
from api.taxonomy import claim_type_label, family_label

log = logging.getLogger("proofscreen.question")

_WS = re.compile(r"\s+")


# ---------------------------------------------------------------------------
# the planner -> wording contract for a TRANSFER probe
#
# `select_transfer()` lives in engine/orchestrator.py, beside the rest of the
# policy — Python decides WHAT to ask. Its output type lives HERE, next to the
# wording that consumes it, because orchestrator imports question and never the
# other way round; defining it there would be an import cycle, and defining it
# in schemas.py would touch the frozen file a second time.
#
# Note what the spec does NOT carry: a job family. A transfer question is built
# from the candidate's own words, so the mechanism costs nothing per cohort.
# ---------------------------------------------------------------------------


class TransferOperator(str, Enum):
    """The perturbation applied to the candidate's own reasoning. T2, T4 and T5
    are designed in docs/TRANSFER_DESIGN_AUDIT.md §3 and deliberately not built."""

    T1 = "T1"      # substitute the problem: their method, their OTHER claim
    T3 = "T3"      # invert the outcome: the number moved against them


@dataclass(frozen=True)
class TransferSpec:
    """Every slot is the candidate's own language, lifted from stored signals.

    `basis` is why this operator and target were chosen. It is for the log and
    the dashboard, never for the prompt — the model does not need to know how
    the planner decided.
    """

    operator: TransferOperator
    their_method: str
    other_problem: str = ""
    target_claim_id: str | None = None
    basis: str = ""


# What each probe level is for, injected into the prompt so the model asks at
# the right depth instead of rephrasing the same question five times.
PROBE_BRIEFS: dict[ProbeLevel, str] = {
    ProbeLevel.VALIDATION: (
        "VALIDATION — establish that they actually held this scope. Ask for the "
        "shape of it: how many, how long, who else was involved, what the "
        "numbers were. This is the opening question about this claim."
    ),
    ProbeLevel.OPERATIONAL: (
        "OPERATIONAL — find out how the work ran day to day. Ask for the "
        "mechanics: the steps, the cadence, the systems they worked in, what "
        "they looked at each morning."
    ),
    ProbeLevel.INCIDENT: (
        "INCIDENT — get one specific episode. Ask about a particular time it "
        "went wrong, or the hardest week. Real practitioners produce concrete "
        "detail here; people who did not do the work produce generalities."
    ),
    ProbeLevel.DECISION: (
        "DECISION — find the judgement they exercised. Ask what they decided, "
        "what they considered and rejected, and why they chose as they did."
    ),
    ProbeLevel.OUTCOME: (
        "OUTCOME — close the loop. Ask what happened afterwards, how they knew "
        "it worked, which number moved, and what they would do differently."
    ),
    ProbeLevel.TRANSFER: (
        "TRANSFER — pose a problem the candidate has NOT solved and ask them to "
        "reason about it with the method they already described. A memorised "
        "resume can be recited; it cannot be transferred. This is the one probe "
        "level where a hypothetical is the point.\n"
        "Ask only for the reasoning: where they would start, what they would "
        "look at, what would rule a cause out. Do NOT ask for numbers, tools or "
        "results — this did not happen, so there are none, and asking invites "
        "invention."
    ),
}

# The concrete substitution, appended to the TRANSFER brief once the planner
# has chosen an operator. One template per operator; the only domain content in
# either is the candidate's own words.
TRANSFER_INSTRUCTIONS: dict[TransferOperator, Template] = {
    TransferOperator.T1: Template(
        "Hold their method constant and swap the subject.\n"
        "  Their method: $their_method\n"
        "  What to swap in, taken from another claim on their own resume: "
        "$other_problem\n"
        "Ask how they would approach the second subject using the first "
        "method. Do not tell them how the second one actually turned out — "
        "they claimed it elsewhere, and the point is the reasoning they would "
        "apply, not the result they already reported."
    ),
    TransferOperator.T3: Template(
        "Invert the outcome they reported.\n"
        "  What they did: $their_method\n"
        "Ask them to reason about the same action having moved the number "
        "against them instead of for them: first hypothesis, and what would "
        "rule it out."
    ),
}

FALLBACK_QUESTIONS: dict[ProbeLevel, str] = {
    ProbeLevel.VALIDATION: (
        "Tell me more about this — what exactly was your scope, and what were "
        "the numbers?"
    ),
    ProbeLevel.OPERATIONAL: (
        "How did this work day to day? Walk me through the steps and the "
        "systems you used."
    ),
    ProbeLevel.INCIDENT: (
        "Tell me about one specific time this went wrong. What happened that "
        "week?"
    ),
    ProbeLevel.DECISION: (
        "What did you decide to do about it, and what did you consider but "
        "decide against?"
    ),
    ProbeLevel.OUTCOME: (
        "What happened afterwards? How did you know it worked, and which "
        "number moved?"
    ),
    # Used only when the planner could not build a spec. Still poses a
    # situation the candidate has not described — the inversion needs nothing
    # but the claim it is anchored to.
    ProbeLevel.TRANSFER: (
        "Suppose that had moved the number the wrong way instead. What would "
        "you check first, and what would rule a cause out?"
    ),
}

# The offline transfer question. A template rather than a fixed sentence,
# because the substance has to come from the candidate's own claims — a
# hand-written scenario would be a per-cohort authoring cost, which is the
# failure mode docs/TRANSFER_DESIGN_AUDIT.md §5 exists to prevent.
TRANSFER_FALLBACKS: dict[TransferOperator, Template] = {
    # "taken on", not "solved" or "moved": the slot holds another claim's
    # subject, which may be a metric, a system or a team, and the wording has
    # to fit all three without knowing which it got.
    TransferOperator.T1: Template(
        "Suppose you had taken on $other_problem instead. Using "
        "$their_method, where would you start?"
    ),
    TransferOperator.T3: Template(
        "Suppose $their_method had made things worse instead of better. "
        "What is your first hypothesis, and what would rule it out?"
    ),
}

# When the policy wants a specific dimension covered, nudge the wording.
GAP_HINTS: dict[Dimension, str] = {
    Dimension.SPECIFICITY: (
        "The answers so far have been short on concrete figures. Word the "
        "question so a number, a headcount or a timeframe is the natural answer."
    ),
    Dimension.PROCESS: (
        "The answers so far have not described how the work actually ran. Word "
        "the question so the natural answer is a sequence of steps."
    ),
    Dimension.METRIC_OWNERSHIP: (
        "The candidate has named metrics without defining them. Word the "
        "question so they have to say how the metric was captured or calculated "
        "in their own operation — not as a definition quiz."
    ),
    Dimension.CAUSAL_REASONING: (
        "The answers so far state outcomes without causes. Word the question so "
        "the natural answer connects a cause, an action and a result."
    ),
    Dimension.AUTHENTICITY: (
        "The answers so far have been general. Word the question so only a "
        "specific remembered episode can answer it."
    ),
    Dimension.TOOL_FAMILIARITY: (
        "The candidate has named tools without describing use. Word the question "
        "so they have to say what they actually did inside the system."
    ),
}


def _short(text: str, limit: int = 90) -> str:
    clean = _WS.sub(" ", text or "").strip()
    return clean if len(clean) <= limit else clean[: limit - 3].rstrip() + "..."


def fallback_question(
    probe_level: ProbeLevel,
    claim_text: str | None = None,
    *,
    transfer: TransferSpec | None = None,
) -> GeneratedQuestion:
    if probe_level is ProbeLevel.TRANSFER and transfer is not None:
        base = TRANSFER_FALLBACKS[transfer.operator].substitute(
            their_method=transfer.their_method,
            other_problem=transfer.other_problem,
        )
    else:
        base = FALLBACK_QUESTIONS[probe_level]
    if not claim_text:
        return GeneratedQuestion(question=base, probe_level=probe_level)
    return GeneratedQuestion(
        question=f'On "{_short(claim_text)}" — {base}', probe_level=probe_level
    )


def _brief_for(probe_level: ProbeLevel, transfer: TransferSpec | None) -> str:
    """The probe brief, plus the concrete substitution when there is one.

    The planner has already chosen the operator, the method and the problem.
    All that is left for the model is the wording — so the brief hands it the
    slots filled in and nothing else. `transfer.basis` is deliberately withheld:
    how the planner decided is for the log and the dashboard, and telling the
    model about the selection logic invites it to second-guess the selection.
    """
    brief = PROBE_BRIEFS[probe_level]
    if probe_level is not ProbeLevel.TRANSFER or transfer is None:
        return brief
    instruction = TRANSFER_INSTRUCTIONS[transfer.operator].substitute(
        their_method=transfer.their_method,
        other_problem=transfer.other_problem,
    )
    return f"{brief}\n\n{instruction}"


def _format_prior(prior_qa: list[tuple[str, str]]) -> str:
    if not prior_qa:
        return "(nothing yet — this is the first question of the session)"
    return "\n\n".join(f"Q: {q}\nA: {a[:500]}" for q, a in prior_qa[-5:])


async def generate_question(
    claim_text: str,
    probe_level: ProbeLevel,
    *,
    claim_type: str | None = None,
    claim_metric: str | None = None,
    job_family: str = "general",
    prior_qa: list[tuple[str, str]] | None = None,
    target_dimension: Dimension | None = None,
    transfer: TransferSpec | None = None,
) -> GeneratedQuestion:
    """`transfer` is required for a TRANSFER probe and ignored for every other
    level. It is the planner's choice of what to ask; this function still only
    chooses how to say it. No prompt-file change was needed: the template
    already interpolates `$probe_level_brief`, and its no-hypotheticals rule
    already carves out "UNLESS the probe brief above explicitly asks for one".
    """
    prompt = load_prompt(
        "generate_question",
        claim_text=claim_text,
        claim_type_label=claim_type_label(job_family, claim_type),
        claim_metric=claim_metric or "none stated",
        family_label=family_label(job_family),
        probe_level=probe_level.value,
        probe_level_brief=_brief_for(probe_level, transfer),
        prior_qa=_format_prior(prior_qa or []),
        gap_hint=GAP_HINTS.get(target_dimension, "") if target_dimension else "",
    )

    result = await complete_json(
        prompt,
        GeneratedQuestion,
        temperature=settings.llm_temperature_question,
        fallback=lambda: fallback_question(probe_level, claim_text, transfer=transfer),
        # Wording is non-deterministic on purpose; caching would make every
        # follow-up on a repeated claim identical.
        cache=False,
    )

    text = (result.question or "").strip()
    if len(text) < 12:
        log.warning("model returned an unusable question, using fallback")
        return fallback_question(probe_level, claim_text, transfer=transfer)

    # The policy owns the probe level, not the model. A drifting level would
    # corrupt the dimension-coverage bookkeeping that drives the next question.
    return GeneratedQuestion(question=text, probe_level=probe_level)
