"""
ARTIFACT 4a — the signal rubrics.  NO LLM IN THIS FILE.

Turns COUNTS of extracted signals into 0-100 per dimension. This is the file
that makes the whole product defensible: the model reports what it found and
quotes it; these published rubrics decide what it is worth.

Every rubric is the same shape:

    score = 100 * min(1, weighted_signal_count / TARGET)
    then a GATE caps the score when a necessary ingredient is missing

The gates are the interesting part. Without them, a candidate who names four
teams and no numbers would score 80 on Specificity. The gate says: no numbers,
no more than 55 on Specificity, however many names you list.

Targets are deliberately low (2-5 signals). We are not testing eloquence. A
real practitioner answering a direct question about their own work produces
these signals almost involuntarily; someone who did not do the work cannot
produce them at all.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from api.schemas import (
    AnswerSignals,
    Dimension,
    DimensionScore,
    ProbeLevel,
)
from api.engine.question import MOVE_DIMENSIONS
from api.taxonomy import family_vocabulary

# D7 — the published rubrics, versioned.
#
# BUMP THIS WHENEVER A TARGET, A WEIGHT OR A GATE IN THIS FILE MOVES. Those
# three are the entire mapping from counts to a 0-100 dimension score, so a
# change to any of them makes yesterday's evaluation and today's incomparable
# even though every stored signal is identical. A version nobody bumps is worse
# than no version, so the test suite pins the constant against the structure it
# describes: `test_rubric_version_covers_targets_gates_and_weights`.
#
# rub_2 — `score_claim` credits probed dimensions from a move's own
# `MOVE_DIMENSIONS` entry when one is on record, instead of always reading
# `PROBE_LEVEL_DIMENSIONS` off the stored (many-to-one) probe_level. Same
# stored signals, different `probed` flags for any forensic-path claim.
RUBRIC_VERSION = "rub_2"

# ---------------------------------------------------------------------------
# which dimensions each probe level is designed to elicit
#
# Read two ways: the question policy uses it to pick a level that will cover a
# weak dimension, and scoring uses it to know which dimensions were actually
# PROBED (asked about) versus merely absent.
# ---------------------------------------------------------------------------

PROBE_LEVEL_DIMENSIONS: dict[ProbeLevel, tuple[Dimension, ...]] = {
    ProbeLevel.VALIDATION: (Dimension.SPECIFICITY, Dimension.METRIC_OWNERSHIP, Dimension.KNOWLEDGE),
    ProbeLevel.OPERATIONAL: (Dimension.PROCESS, Dimension.TOOL_FAMILIARITY, Dimension.EXECUTION),
    ProbeLevel.INCIDENT: (Dimension.AUTHENTICITY, Dimension.SPECIFICITY, Dimension.PROBLEM_SOLVING),
    ProbeLevel.DECISION: (Dimension.CAUSAL_REASONING, Dimension.PROCESS, Dimension.JUDGMENT),
    ProbeLevel.OUTCOME: (Dimension.METRIC_OWNERSHIP, Dimension.CAUSAL_REASONING, Dimension.OWNERSHIP),
    # Only two, and deliberately. A transfer answer is about something that
    # never happened, so it carries no quantities, no tools they used and no
    # metric to define — asking it to mark SPECIFICITY or TOOL_FAMILIARITY
    # probed would report coverage the answer cannot contain. What it does
    # carry is reasoning and sequence. Nothing is subtracted either: claim
    # scoring runs the rubric over the UNION of a claim's signals, so a
    # transfer answer can only add. See docs/TRANSFER_DESIGN_AUDIT.md §3 — this is
    # the paragraph that exists so nobody later "fixes" the missing numbers.
    ProbeLevel.TRANSFER: (Dimension.CAUSAL_REASONING, Dimension.PROCESS, Dimension.ADAPTABILITY),
}

# Every probe level the policy may select. `ProbeLevel`'s own docstring makes
# this tuple the registry: a level not listed here is declared but unreachable.
PROBE_ORDER: tuple[ProbeLevel, ...] = (
    ProbeLevel.VALIDATION,
    ProbeLevel.OPERATIONAL,
    ProbeLevel.INCIDENT,
    ProbeLevel.DECISION,
    ProbeLevel.OUTCOME,
    ProbeLevel.TRANSFER,
)

# The rungs the policy climbs in order — PROBE_ORDER minus TRANSFER.
#
# TRANSFER is selectable but it is not a rung. It is an exit ramp, offered once
# by `plan_next` to a claim that has stalled, and it must never be reached by
# the ordinary "next unused level" walk: a claim that is still producing
# evidence should be asked about what it did, not about what it did not do.
# Anything meaning "the ladder" reads THIS tuple; only the stall branch names
# TRANSFER. Keeping the two apart is what makes "TRANSFER never opens a claim"
# a property of the code rather than a convention.
LADDER_ORDER: tuple[ProbeLevel, ...] = tuple(
    lv for lv in PROBE_ORDER if lv is not ProbeLevel.TRANSFER
)

# Published targets. Tune these and the whole product's strictness moves.
TARGETS: dict[Dimension, float] = {
    Dimension.SPECIFICITY: 5.0,
    Dimension.PROCESS: 4.0,
    Dimension.METRIC_OWNERSHIP: 2.0,
    Dimension.CAUSAL_REASONING: 2.0,
    Dimension.AUTHENTICITY: 3.0,
    Dimension.TOOL_FAMILIARITY: 2.0,
    # Universal Competence Framework
    Dimension.KNOWLEDGE: 3.0,
    Dimension.EXECUTION: 4.0,
    Dimension.PROBLEM_SOLVING: 3.0,
    Dimension.JUDGMENT: 3.0,
    Dimension.OWNERSHIP: 3.0,
    Dimension.ADAPTABILITY: 2.0,
}

# Score ceiling applied when the dimension's necessary ingredient is absent.
GATES: dict[Dimension, tuple[int, str]] = {
    Dimension.SPECIFICITY: (55, "no quantity given"),
    Dimension.PROCESS: (50, "no process step described"),
    Dimension.METRIC_OWNERSHIP: (45, "metric never defined"),
    Dimension.CAUSAL_REASONING: (50, "no complete cause-action-outcome chain"),
    Dimension.AUTHENTICITY: (40, "no specific incident recalled"),
    Dimension.TOOL_FAMILIARITY: (40, "tool named but usage not described"),
    # Universal Competence Framework
    Dimension.KNOWLEDGE: (45, "no concept explanation or domain reasoning provided"),
    Dimension.EXECUTION: (50, "no process step described"),
    Dimension.PROBLEM_SOLVING: (45, "no incident marker or causal chain provided"),
    Dimension.JUDGMENT: (45, "no decision with stated trade-off/reasoning provided"),
    Dimension.OWNERSHIP: (40, "no explicit boundary or scope declared"),
    Dimension.ADAPTABILITY: (40, "no transfer reasoning provided"),
}

# Partial credit for incomplete signals.
PARTIAL_CAUSAL = 0.4        # a chain missing its outcome
NAMED_ONLY_TOOL = 0.1       # bare tool mention (prevent tool-mention inflation)
NAMED_ONLY_METRIC = 0.4     # metric mentioned, never defined
REFERRING_QUANTITY = 0.3    # a number attached to something ("CSAT was 78")
VOCAB_SIGNAL = 0.25         # one domain vocabulary hit
MAX_VOCAB_CREDIT = 1.5      # domain words alone can never carry PROCESS


def _saturate(weighted: float, target: float) -> int:
    if target <= 0:
        return 0
    return int(round(100 * min(1.0, max(0.0, weighted) / target)))


def _score(
    dimension: Dimension,
    weighted: float,
    raw_count: int,
    basis: str,
    quotes: list[str],
    gate_open: bool,
) -> DimensionScore:
    value = _saturate(weighted, TARGETS[dimension])
    if not gate_open:
        ceiling, reason = GATES[dimension]
        if value > ceiling:
            value = ceiling
        basis = f"{basis} — capped at {ceiling}: {reason}" if basis else reason
    return DimensionScore(
        dimension=dimension,
        score=value,
        signal_count=raw_count,
        basis=basis or "no signals found",
        quotes=[q for q in quotes if q][:4],
        probed=True,
    )


def _plural(n: int, singular: str, plural: str | None = None) -> str:
    return f"{n} {singular if n == 1 else (plural or singular + 's')}"


# ---------------------------------------------------------------------------
# the six rubrics
# ---------------------------------------------------------------------------


def score_specificity(sig: AnswerSignals) -> DimensionScore:
    """Concrete numbers, named things, timeframes."""
    quantities, entities = sig.quantities, sig.entities
    weighted = float(len(quantities)) + float(len(entities))
    basis = ", ".join(
        part for part in (
            _plural(len(quantities), "quantity", "quantities") if quantities else "",
            _plural(len(entities), "named entity", "named entities") if entities else "",
        ) if part
    )
    quotes = [q.quote for q in quantities] + [e.quote for e in entities]
    return _score(
        Dimension.SPECIFICITY, weighted, len(quantities) + len(entities),
        basis, quotes, gate_open=bool(quantities),
    )


def score_process(sig: AnswerSignals, job_family: str = "general") -> DimensionScore:
    """Does the candidate know HOW the work happened, step by step."""
    steps = sig.process_steps
    vocab = family_vocabulary(job_family)
    haystack = " ".join(
        [s.step for s in steps]
        + [s.quote for s in steps]
        + [e.entity for e in sig.entities]
        + [sig.summary]
    ).lower()
    vocab_hits = sum(1 for word in vocab if word and word in haystack)
    vocab_credit = min(MAX_VOCAB_CREDIT, vocab_hits * VOCAB_SIGNAL)

    weighted = float(len(steps)) + vocab_credit
    basis = ", ".join(
        part for part in (
            _plural(len(steps), "process step") if steps else "",
            f"{vocab_hits} domain term{'' if vocab_hits == 1 else 's'}" if vocab_hits else "",
        ) if part
    )
    return _score(
        Dimension.PROCESS, weighted, len(steps), basis,
        [s.quote for s in steps], gate_open=bool(steps),
    )


def score_metric_ownership(sig: AnswerSignals) -> DimensionScore:
    """Can they define the metric they claim, not just repeat its name."""
    defined = [m for m in sig.metric_definitions if m.how_measured]
    named = [m for m in sig.metric_definitions if not m.how_measured]
    referring = [q for q in sig.quantities if q.refers_to]

    weighted = (
        len(defined)
        + len(named) * NAMED_ONLY_METRIC
        + min(1.0, len(referring) * REFERRING_QUANTITY)
    )
    basis = ", ".join(
        part for part in (
            _plural(len(defined), "metric") + " defined" if defined else "",
            f"{len(named)} named only" if named else "",
            _plural(len(referring), "number") + " tied to a metric" if referring else "",
        ) if part
    )
    return _score(
        Dimension.METRIC_OWNERSHIP, weighted, len(sig.metric_definitions),
        basis, [m.quote for m in defined] + [m.quote for m in named],
        gate_open=bool(defined),
    )


def score_causal_reasoning(sig: AnswerSignals) -> DimensionScore:
    """Problem -> action -> result. The dimension fabrication fails hardest on."""
    complete = [c for c in sig.causal_links if c.is_complete]
    partial = [c for c in sig.causal_links if not c.is_complete]

    weighted = len(complete) + len(partial) * PARTIAL_CAUSAL
    basis = ", ".join(
        part for part in (
            _plural(len(complete), "complete causal chain") if complete else "",
            f"{len(partial)} partial" if partial else "",
        ) if part
    )
    return _score(
        Dimension.CAUSAL_REASONING, weighted, len(sig.causal_links), basis,
        [c.quote for c in complete] + [c.quote for c in partial],
        gate_open=bool(complete),
    )


def score_authenticity(sig: AnswerSignals) -> DimensionScore:
    """Real people remember real incidents. This is not a fluency test — a
    two-line answer naming one specific bad week outscores three polished
    paragraphs of generalities, which is the entire point."""
    markers = sig.incident_markers
    return _score(
        Dimension.AUTHENTICITY, float(len(markers)), len(markers),
        _plural(len(markers), "specific incident detail") if markers else "",
        [m.quote for m in markers], gate_open=bool(markers),
    )


def score_tool_familiarity(sig: AnswerSignals) -> DimensionScore:
    """Usage, not certification. Naming a tool is a resume keyword."""
    used = [t for t in sig.tools if t.usage]
    named = [t for t in sig.tools if not t.usage]

    weighted = len(used) + len(named) * NAMED_ONLY_TOOL
    basis = ", ".join(
        part for part in (
            _plural(len(used), "tool") + " with described usage" if used else "",
            f"{len(named)} named only" if named else "",
        ) if part
    )
    return _score(
        Dimension.TOOL_FAMILIARITY, weighted, len(sig.tools), basis,
        [t.quote for t in used] + [t.quote for t in named],
        gate_open=bool(used),
    )


def score_knowledge(sig: AnswerSignals, job_family: str = "general") -> DimensionScore:
    """Domain understanding & explanation of why concepts apply."""
    concepts = sig.concept_explanations
    defined_metrics = [m for m in sig.metric_definitions if m.how_measured]
    weighted = float(len(concepts)) + 0.5 * float(len(defined_metrics))
    basis = ", ".join(
        part for part in (
            _plural(len(concepts), "concept explanation") if concepts else "",
            _plural(len(defined_metrics), "defined metric") if defined_metrics else "",
        ) if part
    )
    quotes = [c.quote for c in concepts] + [m.quote for m in defined_metrics]
    return _score(
        Dimension.KNOWLEDGE, weighted, len(concepts) + len(defined_metrics),
        basis, quotes, gate_open=bool(concepts or defined_metrics),
    )


def score_execution(sig: AnswerSignals, job_family: str = "general") -> DimensionScore:
    """First-person description of mechanics and sequence of work done."""
    steps = sig.process_steps
    used_tools = [t for t in sig.tools if t.usage]
    quantities = sig.quantities
    weighted = float(len(steps)) + 0.5 * float(len(used_tools)) + min(1.0, len(quantities) * 0.3)
    basis = ", ".join(
        part for part in (
            _plural(len(steps), "process step") if steps else "",
            _plural(len(used_tools), "tool used") if used_tools else "",
            _plural(len(quantities), "quantity") if quantities else "",
        ) if part
    )
    quotes = [s.quote for s in steps] + [t.quote for t in used_tools]
    return _score(
        Dimension.EXECUTION, weighted, len(steps), basis,
        quotes, gate_open=bool(steps),
    )


def score_problem_solving(sig: AnswerSignals) -> DimensionScore:
    """Evidence of diagnosing and resolving incidents/exceptions."""
    incidents = sig.incident_markers
    causals = [c for c in sig.causal_links if c.is_complete]
    constraints = sig.constraints
    weighted = float(len(incidents)) + float(len(causals)) + 0.5 * float(len(constraints))
    basis = ", ".join(
        part for part in (
            _plural(len(incidents), "incident marker") if incidents else "",
            _plural(len(causals), "complete causal chain") if causals else "",
            _plural(len(constraints), "constraint") if constraints else "",
        ) if part
    )
    quotes = [i.quote for i in incidents] + [c.quote for c in causals]
    return _score(
        Dimension.PROBLEM_SOLVING, weighted, len(incidents) + len(causals),
        basis, quotes, gate_open=bool(incidents or causals),
    )


def score_judgment(sig: AnswerSignals) -> DimensionScore:
    """Reasoned choices and tradeoffs under constraints."""
    decisions = sig.decisions
    weighted = float(len(decisions))
    basis = _plural(len(decisions), "reasoned decision") if decisions else ""
    quotes = [d.quote for d in decisions]
    return _score(
        Dimension.JUDGMENT, weighted, len(decisions),
        basis, quotes, gate_open=bool(decisions),
    )


def score_ownership(sig: AnswerSignals) -> DimensionScore:
    """Explicit scope boundaries and accountability."""
    boundaries = sig.boundaries
    entities = [e for e in sig.entities if e.kind in ("team", "person", "role")]
    weighted = float(len(boundaries)) + 0.3 * float(len(entities))
    basis = ", ".join(
        part for part in (
            _plural(len(boundaries), "boundary statement") if boundaries else "",
            _plural(len(entities), "role entity", "role entities") if entities else "",
        ) if part
    )
    quotes = [b.quote for b in boundaries] + [e.quote for e in entities]
    return _score(
        Dimension.OWNERSHIP, weighted, len(boundaries),
        basis, quotes, gate_open=bool(boundaries),
    )


def score_adaptability(sig: AnswerSignals) -> DimensionScore:
    """Transferring knowledge and reasoning to new scenarios."""
    causals = [c for c in sig.causal_links if c.is_complete]
    weighted = float(len(causals))
    basis = _plural(len(causals), "transfer causal chain") if causals else ""
    quotes = [c.quote for c in causals]
    return _score(
        Dimension.ADAPTABILITY, weighted, len(causals),
        basis, quotes, gate_open=bool(causals),
    )


# ---------------------------------------------------------------------------
# public entry point
# ---------------------------------------------------------------------------


def score_answer(
    sig: AnswerSignals, job_family: str = "general"
) -> dict[Dimension, DimensionScore]:
    """All dimensions for one answer. Pure function of the signal counts."""
    return {
        Dimension.SPECIFICITY: score_specificity(sig),
        Dimension.PROCESS: score_process(sig, job_family),
        Dimension.METRIC_OWNERSHIP: score_metric_ownership(sig),
        Dimension.CAUSAL_REASONING: score_causal_reasoning(sig),
        Dimension.AUTHENTICITY: score_authenticity(sig),
        Dimension.TOOL_FAMILIARITY: score_tool_familiarity(sig),
        # Universal Competence Framework
        Dimension.KNOWLEDGE: score_knowledge(sig, job_family),
        Dimension.EXECUTION: score_execution(sig, job_family),
        Dimension.PROBLEM_SOLVING: score_problem_solving(sig),
        Dimension.JUDGMENT: score_judgment(sig),
        Dimension.OWNERSHIP: score_ownership(sig),
        Dimension.ADAPTABILITY: score_adaptability(sig),
    }


def total_signals(sig: AnswerSignals) -> int:
    return (
        len(sig.quantities)
        + len(sig.process_steps)
        + len(sig.causal_links)
        + len(sig.tools)
        + len(sig.metric_definitions)
        + len(sig.incident_markers)
        + len(sig.entities)
    )


def dimensions_for_level(level: ProbeLevel) -> tuple[Dimension, ...]:
    return PROBE_LEVEL_DIMENSIONS.get(level, ())


def level_for_dimension(dimension: Dimension) -> ProbeLevel:
    """The earliest probe level designed to elicit this dimension. Lets the
    policy answer "which question would cover the gap I have?".

    Walks the ladder, not PROBE_ORDER: a dimension gap is a reason to ask about
    what the candidate did, never a reason to hand them a hypothetical.
    """
    for level in LADDER_ORDER:
        if dimension in PROBE_LEVEL_DIMENSIONS[level]:
            return level
    return ProbeLevel.VALIDATION

# ---------------------------------------------------------------------------
# accumulating evidence across a claim's answers
#
# Evidence ADDS UP over an interview. A candidate who gives one complete causal
# chain in the DECISION answer and another in the OUTCOME answer has
# demonstrated causal reasoning twice, and the claim score must see both.
#
# So the claim-level score is the rubric run once over the UNION of that
# claim's signals — not the best of the per-answer scores. Per-answer scores
# are still stored, because the dashboard shows what each answer contributed.
# ---------------------------------------------------------------------------

_DEDUPE_WS = __import__("re").compile(r"\s+")


def _key(*parts: object) -> str:
    return _DEDUPE_WS.sub(" ", " ".join(str(p or "") for p in parts)).strip().lower()


def merge_signals(answers: "Sequence[AnswerSignals]") -> AnswerSignals:
    """Union of every signal across a claim's answers, deduplicated.

    Deduplication is on content, not identity: a candidate who repeats "we had
    35 agents" in three answers has said one thing, not three.
    """
    merged = AnswerSignals()
    seen: dict[str, set[str]] = {}

    def add(bucket: str, item: object, key: str) -> None:
        keys = seen.setdefault(bucket, set())
        if key in keys:
            return
        keys.add(key)
        getattr(merged, bucket).append(item)

    for sig in answers:
        for q in sig.quantities:
            add("quantities", q, _key(q.value, q.refers_to))
        for st in sig.process_steps:
            add("process_steps", st, _key(st.step))
        for cl in sig.causal_links:
            add("causal_links", cl, _key(cl.cause, cl.action, cl.outcome))
        for tl in sig.tools:
            add("tools", tl, _key(tl.tool))
        for md in sig.metric_definitions:
            add("metric_definitions", md, _key(md.metric))
        for im in sig.incident_markers:
            add("incident_markers", im, _key(im.detail))
        for en in sig.entities:
            add("entities", en, _key(en.entity))
        for ft in sig.facts:
            add("facts", ft, _key(ft.key, ft.value_num, ft.value_text))

    # A tool or metric described in ANY answer counts as described everywhere.
    # Otherwise a duplicate bare mention could shadow the richer one.
    for bucket, attr in (("tools", "usage"), ("metric_definitions", "how_measured")):
        best: dict[str, object] = {}
        for item in getattr(merged, bucket):
            name = _key(getattr(item, "tool", None) or getattr(item, "metric", None))
            current = best.get(name)
            if current is None or (getattr(item, attr) and not getattr(current, attr)):
                best[name] = item
        setattr(merged, bucket, list(best.values()))

    merged.summary = next((s.summary for s in reversed(answers) if s.summary), "")
    return merged


def score_claim(
    answers: "Sequence[AnswerSignals]",
    levels_used: "Iterable[ProbeLevel]",
    job_family: str = "general",
    moves_used: "Iterable[str | None] | None" = None,
) -> dict[Dimension, DimensionScore]:
    """Claim-level dimension scores: the rubric over the union of all answers.

    `probed` is set from what was actually asked, so a 0 on a dimension nobody
    asked about is visibly different from a 0 the candidate earned.

    `moves_used`, when given, is parallel to `levels_used` -- one entry per
    answer, in the same order, `None` where no move is on record. A move is
    credited from its own `MOVE_DIMENSIONS` entry (comma-split, so a
    re-targeted question credits both moves it actually spent) rather than
    from its stored `probe_level`: `MOVE_PROBE_LEVEL` is a many-to-one
    compatibility label kept for storage and replay, and crediting from it
    would credit a move for whatever an unrelated co-mapped sibling covers
    (COHERENCE and METRIC_DEFINITION both store "OUTCOME", for one). An index
    with no usable move -- `moves_used` omitted, shorter than `levels_used`,
    or `None`/unrecognised at that position -- falls back to
    `PROBE_LEVEL_DIMENSIONS[level]` unchanged, which is what every
    pre-forensic caller (including replay of a pre-forensic evaluation) still
    is.
    """
    if not answers:
        return {
            d: DimensionScore(dimension=d, score=0, basis="not probed", probed=False)
            for d in PROBE_ORDER and TARGETS
        }

    scores = score_answer(merge_signals(answers), job_family)

    levels = list(levels_used)
    moves = list(moves_used) if moves_used is not None else []

    probed: set[Dimension] = set()
    for index, level in enumerate(levels):
        move = moves[index] if index < len(moves) else None
        credited = False
        for token in (move or "").split(","):
            dims = MOVE_DIMENSIONS.get(token.strip())
            if dims:
                probed.update(dims)
                credited = True
        if not credited:
            probed.update(PROBE_LEVEL_DIMENSIONS.get(level, ()))

    for dimension, entry in scores.items():
        entry.probed = dimension in probed or entry.score > 0
        if not entry.probed:
            entry.basis = "not probed"
    return scores
