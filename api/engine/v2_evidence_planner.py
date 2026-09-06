"""
v2 — Evidence Planner (prototype, parallel to the existing forensic planner).

Not wired to anything. This is the "what should we ask about next" layer from
the resume -> investigation redesign: given what has been established about
one claim so far, decide which evidence category to go after next. No LLM
call, no wording, no orchestrator wiring — plan_next() returns a target
category and a reason, the same shape the existing planner already returns a
QuestionBrief. Turning a target into words is a different file's job.

Pure functions throughout: nothing here calls a model, nothing here is
random, and EvidenceState is never mutated in place. update_coverage() and
plan_next() both take a state and return a new one (or, for plan_next, a
target) — the same interview always produces the same plan.
"""

from __future__ import annotations

from enum import Enum
from typing import NamedTuple


class EvidenceCategory(str, Enum):
    OWNERSHIP = "ownership"
    PROCESS = "process"
    METRIC_DEFINITION = "metric_definition"
    DECISION = "decision"
    DEPENDENCY = "dependency"
    INCIDENT = "incident"
    CONSTRAINT = "constraint"
    CAUSAL_CHAIN = "causal_chain"
    ARTIFACT = "artifact"
    CROSS_CLAIM_LINK = "cross_claim_link"


class CoverageState(str, Enum):
    MISSING = "missing"
    PARTIAL = "partial"
    ESTABLISHED = "established"


# Rule 4 — acquisition priority, highest invention-cost first. Fixed order,
# not configurable per claim: cost is a property of the CATEGORY, not of
# whatever archetype the claim happens to be.
PRIORITY_ORDER: tuple[EvidenceCategory, ...] = (
    EvidenceCategory.INCIDENT,
    EvidenceCategory.CROSS_CLAIM_LINK,
    EvidenceCategory.DECISION,
    EvidenceCategory.CAUSAL_CHAIN,
    EvidenceCategory.METRIC_DEFINITION,
    EvidenceCategory.CONSTRAINT,
    EvidenceCategory.DEPENDENCY,
    EvidenceCategory.PROCESS,
    EvidenceCategory.ARTIFACT,
    EvidenceCategory.OWNERSHIP,
)

# Rule 8 — escalation level. CROSS_CLAIM_LINK sits alone at the top: it is the
# only category that requires a SECOND claim to already carry evidence, so it
# cannot be reached before the ordinary levels below it exist for that other
# claim.
ESCALATION_LEVEL: dict[EvidenceCategory, int] = {
    EvidenceCategory.OWNERSHIP: 1,
    EvidenceCategory.PROCESS: 1,
    EvidenceCategory.ARTIFACT: 1,
    EvidenceCategory.METRIC_DEFINITION: 2,
    EvidenceCategory.DEPENDENCY: 2,
    EvidenceCategory.DECISION: 2,
    EvidenceCategory.CAUSAL_CHAIN: 2,
    EvidenceCategory.INCIDENT: 3,
    EvidenceCategory.CONSTRAINT: 3,
    EvidenceCategory.CROSS_CLAIM_LINK: 4,
}

# Rule 9 — a claim stops being probed once ownership and process are both
# established AND at least one genuinely high-cost (escalation level 3+)
# category is too. DECISION is deliberately EXCLUDED even though the original
# rule named it: DECISION sits at escalation level 2, reached almost
# immediately after ownership/process clear, so including it here let a claim
# stop right after its 4th answer, every time, before the escalation ladder
# ever reached INCIDENT or CROSS_CLAIM_LINK -- the two categories level 3/4
# exist specifically to be the HARD, late things an interview reaches. A stop
# condition satisfied by an easy category defeats the escalation design.
_STOP_REQUIRED: tuple[EvidenceCategory, ...] = (
    EvidenceCategory.OWNERSHIP,
    EvidenceCategory.PROCESS,
)
_STOP_ONE_OF: tuple[EvidenceCategory, ...] = (
    EvidenceCategory.INCIDENT,
    EvidenceCategory.CROSS_CLAIM_LINK,
)


class GraphEdge(NamedTuple):
    """One edge out of claim_graph.txt's output.

    `frm` because `from` is a reserved word — matches the prompt's own
    from/type/to field names otherwise.
    """

    frm: str
    type: str  # "DEPENDS_ON" | "PRODUCED" | "EXTENDS" | "ENABLED"
    to: str


class EvidenceState(NamedTuple):
    """Coverage for one claim, as of one point in the interview.

    Treat as immutable: update_coverage() always returns a new EvidenceState
    rather than mutating this one's dicts in place.
    """

    claim_id: str
    coverage: dict[EvidenceCategory, CoverageState]
    last_touched: dict[EvidenceCategory, int]  # turn index each category last advanced
    turn: int  # how many answers have been scored against this claim so far
    attempts: dict[EvidenceCategory, int]  # times targeted without reaching ESTABLISHED


class PlannerTarget(NamedTuple):
    """plan_next()'s output. No question, no wording — an investigation
    strategy for the question generator to render."""

    claim_id: str
    target_evidence: EvidenceCategory
    reason: str
    escalation_level: int
    linked_claim_id: str | None = None  # set only when target_evidence is CROSS_CLAIM_LINK


def new_state(claim_id: str) -> EvidenceState:
    return EvidenceState(
        claim_id=claim_id,
        coverage={category: CoverageState.MISSING for category in EvidenceCategory},
        last_touched={},
        turn=0,
        attempts={},
    )


# A category asked about this many times without ever reaching ESTABLISHED is
# given up on. Without this, a category with no real signal source at all
# (see coverage_from_signals()'s known gaps) is offered forever: nothing ever
# marks it "touched" via last_touched (Rule 7 only fires when a count > 0
# arrives), so the SAME category, and often the literal same question, would
# repeat every remaining turn. Caught live: a fresh claim asked about
# ARTIFACT six turns in a row with an identical question each time, because
# ARTIFACT had no signal mapping at all. 2 is deliberately small — this is a
# give-up threshold, not a retry budget.
EXHAUST_AFTER = 2


def update_coverage(
    state: EvidenceState,
    observed: dict[EvidenceCategory, int],
    *,
    targeted: EvidenceCategory | None = None,
) -> EvidenceState:
    """Advance one claim's coverage by one answer's worth of signal counts.

    `observed` is per-category evidence units found in the answer just
    scored — see coverage_from_signals() for how those counts are derived
    from extract_signals.txt's existing output. A category with zero counts
    this turn keeps its prior state and its prior last_touched. A category
    with at least one count moves MISSING -> PARTIAL -> ESTABLISHED, never
    backwards. This is a UNION over the whole interview, on purpose — an
    answer to one question can carry incidental evidence for a category
    nobody asked about yet, and that evidence should still count.

    `targeted` — the category plan_next() actually asked about this turn.
    last_touched is stamped ONLY for this category, not for every category
    that happened to gain a count this turn — Rule 7 exists to stop the SAME
    question being asked twice in a row, not to penalise a category for the
    coincidence of being advanced by someone else's answer. Caught live: a
    single rich DECISION answer also advanced CAUSAL_CHAIN and CONSTRAINT
    incidentally; stamping last_touched for all three meant CAUSAL_CHAIN
    looked "just asked about" on the very next turn even though it had never
    been targeted, blocking it, and with escalation keeping CONSTRAINT and
    CROSS_CLAIM_LINK locked, plan_next had nothing left to offer and returned
    None — a false "interview complete" after a single good answer.
    Tracked independently of `observed` for EXHAUST_AFTER too: a category can
    be targeted and yield nothing (no matching signal came back at all), and
    that has to be visible even when `observed` never mentions the category.
    """
    turn = state.turn + 1
    coverage = dict(state.coverage)
    last_touched = dict(state.last_touched)
    attempts = dict(state.attempts)
    for category, count in observed.items():
        if count <= 0:
            continue
        current = coverage.get(category, CoverageState.MISSING)
        if current is CoverageState.MISSING:
            coverage[category] = CoverageState.PARTIAL
        elif current is CoverageState.PARTIAL:
            coverage[category] = CoverageState.ESTABLISHED
    if targeted is not None:
        last_touched[targeted] = turn
        if coverage.get(targeted) is not CoverageState.ESTABLISHED:
            attempts[targeted] = attempts.get(targeted, 0) + 1
    return EvidenceState(
        claim_id=state.claim_id,
        coverage=coverage,
        last_touched=last_touched,
        turn=turn,
        attempts=attempts,
    )


def sufficiently_covered(state: EvidenceState) -> bool:
    """Rule 9 — stop asking about this claim."""
    if any(
        state.coverage.get(category) is not CoverageState.ESTABLISHED
        for category in _STOP_REQUIRED
    ):
        return False
    return any(
        state.coverage.get(category) is CoverageState.ESTABLISHED for category in _STOP_ONE_OF
    )


def _exhausted(state: EvidenceState, category: EvidenceCategory) -> bool:
    """Given up on: targeted EXHAUST_AFTER times and still not ESTABLISHED."""
    return (
        state.coverage.get(category) is not CoverageState.ESTABLISHED
        and state.attempts.get(category, 0) >= EXHAUST_AFTER
    )


def _unlocked_level(state: EvidenceState, applicable: frozenset[EvidenceCategory]) -> int:
    """Rule 8 — the lowest escalation level that still has an unresolved
    category. plan_next() will not offer anything above this level: an
    interview should not be handed INCIDENT (level 3) while OWNERSHIP or
    PROCESS (level 1) is still MISSING, just because INCIDENT sits first in
    PRIORITY_ORDER. Once every applicable category is ESTABLISHED or
    exhausted there is nothing left to unlock; return the highest applicable
    level so nothing is filtered by mistake (plan_next will have already
    returned None via sufficiently_covered).

    `applicable` excludes categories that do not apply to this claim at all
    (METRIC_DEFINITION on a claim with no metric) — an inapplicable category
    must never count as "still MISSING", or a metric-less claim would stay
    capped at escalation level 2 forever, since METRIC_DEFINITION would never
    become ESTABLISHED and would keep dragging the unlocked level down.

    An EXHAUSTED category (see EXHAUST_AFTER) is excluded the same way and
    for the same reason: a category with no real signal source can never
    become ESTABLISHED, so treating it as "still unresolved" here would cap
    the unlocked level forever, exactly like the metric-less case above.
    """
    unresolved = [
        ESCALATION_LEVEL[category]
        for category in applicable
        if state.coverage.get(category) is not CoverageState.ESTABLISHED
        and not _exhausted(state, category)
    ]
    return min(unresolved) if unresolved else max(ESCALATION_LEVEL[c] for c in applicable)


def _linked_claim(claim_id: str, graph_edges: tuple[GraphEdge, ...]) -> str | None:
    """Rule 6 — the claim graph makes CROSS_CLAIM_LINK a real target instead
    of an arbitrary one. Prefers an edge where THIS claim is the dependent
    side (`frm`): the RCA/dataset example probes the thing this claim
    NEEDED, not the thing that needed this claim. Falls back to the reverse
    direction so a claim on either side of an edge can still be linked.
    """
    for edge in graph_edges:
        if edge.frm == claim_id:
            return edge.to
    for edge in graph_edges:
        if edge.to == claim_id:
            return edge.frm
    return None


def plan_next(
    state: EvidenceState,
    *,
    graph_edges: tuple[GraphEdge, ...] = (),
    has_metric: bool = True,
) -> PlannerTarget | None:
    """Rule 3 — pick the highest-priority category that is not yet ESTABLISHED.

    Rule 5 — an ESTABLISHED category is never re-targeted through this path;
    a SEAM coherence-check or a TRANSFER re-visit is a different, explicit
    call this function does not make on its own.

    Rule 7 — a category touched on the immediately preceding turn is skipped,
    so two consecutive answers never chase the same thing.

    `has_metric` — planner eligibility, not a prompt problem: pass
    `anatomy.has_metric` for this claim. When False, METRIC_DEFINITION is
    never offered — asking "how was the metric measured" on a claim with no
    named metric produces a nonsense question no matter how the wording
    prompt is written, because there is nothing to define.

    A category targeted EXHAUST_AFTER times with no signal ever coming back
    (see update_coverage(..., targeted=...)) is skipped from here on — a
    category with no real signal source in the extractor (see
    coverage_from_signals()'s known gaps) would otherwise be offered forever,
    since nothing ever advances it out of MISSING.

    Returns None once sufficiently_covered() — the claim is done — or once
    every remaining applicable category is ESTABLISHED, exhausted, or was
    just touched.
    """
    if sufficiently_covered(state):
        return None

    applicable = frozenset(
        category
        for category in EvidenceCategory
        if has_metric or category is not EvidenceCategory.METRIC_DEFINITION
    )

    unlocked = _unlocked_level(state, applicable)
    for category in PRIORITY_ORDER:
        if category not in applicable:
            continue
        current = state.coverage.get(category, CoverageState.MISSING)
        if current is CoverageState.ESTABLISHED:
            continue
        if _exhausted(state, category):
            continue
        if state.last_touched.get(category) == state.turn:
            continue
        if ESCALATION_LEVEL[category] > unlocked:
            continue

        if category is EvidenceCategory.CROSS_CLAIM_LINK:
            linked = _linked_claim(state.claim_id, graph_edges)
            if linked is None:
                continue  # no edge to hang a cross-claim question on — try the next category
            return PlannerTarget(
                claim_id=state.claim_id,
                target_evidence=category,
                reason=f"connects to {linked} via the claim graph",
                escalation_level=ESCALATION_LEVEL[category],
                linked_claim_id=linked,
            )

        return PlannerTarget(
            claim_id=state.claim_id,
            target_evidence=category,
            reason=(
                "highest-priority missing evidence"
                if current is CoverageState.MISSING
                else "highest-priority partially-covered evidence"
            ),
            escalation_level=ESCALATION_LEVEL[category],
        )

    return None


def coverage_from_signals(raw: dict) -> dict[EvidenceCategory, int]:
    """Map a signal extractor's output onto evidence categories.

    Works against `v2_extract_signals.txt`'s schema, which is the existing
    `extract_signals.txt` plus `decisions` and `constraints` — both raw
    signal lists, not judgments; the extractor still only reports what is
    present in one answer, never whether a category has become
    "established" overall. That aggregation is this function plus
    update_coverage(), not the prompt.

    ARTIFACT reads off `entities` tagged `kind: "product"` — the schema
    already distinguishes a concrete produced thing from a system/team/place,
    so this costs no new extraction field, only a filter here. Product-kind
    entities are excluded from DEPENDENCY's count so nothing is credited to
    both categories from the same mention.

    OWNERSHIP still has no corresponding field in either extractor's schema —
    it reads MISSING forever, and EXHAUST_AFTER (plan_next) is what stops
    that from looping the interview, not a real signal. That is not a bug in
    this file; it is the one category genuinely unmapped, narrowed down from
    four originally.
    """
    entities = raw.get("entities") or ()
    product_entities = [e for e in entities if isinstance(e, dict) and e.get("kind") == "product"]
    other_entities = [e for e in entities if not (isinstance(e, dict) and e.get("kind") == "product")]
    return {
        EvidenceCategory.PROCESS: len(raw.get("process_steps") or ()),
        EvidenceCategory.CAUSAL_CHAIN: len(raw.get("causal_links") or ()),
        EvidenceCategory.METRIC_DEFINITION: len(raw.get("metric_definitions") or ()),
        EvidenceCategory.INCIDENT: len(raw.get("incident_markers") or ()),
        EvidenceCategory.DEPENDENCY: len(raw.get("tools") or ()) + len(other_entities),
        EvidenceCategory.DECISION: len(raw.get("decisions") or ()),
        EvidenceCategory.CONSTRAINT: len(raw.get("constraints") or ()),
        EvidenceCategory.ARTIFACT: len(product_entities),
    }
