"""
ARTIFACT 3 — the question policy. Pure function of the session's evidence, so
it is testable without a database or a model.
"""

from __future__ import annotations

from dataclasses import dataclass

from api.config import settings
from api.engine import scoring, signals
from api.engine.orchestrator import ClaimState, plan_next
from api.schemas import Dimension, DimensionScore, ProbeLevel


@dataclass
class FakeClaim:
    id: str
    claim_type: str
    text: str = "a claim"
    metric: str | None = None
    order_index: int = 0


def state(
    claim_id: str,
    claim_type: str,
    weight: float,
    *,
    levels: set[ProbeLevel] | None = None,
    scores: dict[Dimension, int] | None = None,
    claim_score: int = 0,
    answers: int = 0,
    last_signals: int = 5,
    order: int = 0,
) -> ClaimState:
    dimensions = {
        d: DimensionScore(
            dimension=d,
            score=(scores or {}).get(d, 0),
            probed=d in (scores or {}),
        )
        for d in scoring.DIMENSION_ORDER
    }
    return ClaimState(
        claim=FakeClaim(claim_id, claim_type, order_index=order),
        weight=weight,
        claim_family="bpo_operations",
        levels_used=set(levels or set()),
        dimensions=dimensions,
        score=claim_score,
        answers=answers,
        last_answer_signals=last_signals,
    )


# ---------------------------------------------------------------------------
# phase 1 — breadth before depth
# ---------------------------------------------------------------------------


def test_first_question_is_validation_on_the_heaviest_claim():
    states = [
        state("c1", "team_handling", 25.0),
        state("c2", "aht_control", 15.0, order=1),
    ]
    plan = plan_next(states, 0)
    assert plan.claim.id == "c1"
    assert plan.probe_level is ProbeLevel.VALIDATION


def test_every_claim_is_touched_before_any_is_deepened():
    """An unprobed claim scores zero and would silently sink the candidate, so
    breadth comes first regardless of how weak the heavy claim looks."""
    states = [
        state("c1", "team_handling", 25.0, levels={ProbeLevel.VALIDATION}, answers=1, claim_score=20),
        state("c2", "aht_control", 15.0, order=1),
    ]
    plan = plan_next(states, 1)
    assert plan.claim.id == "c2"
    assert plan.probe_level is ProbeLevel.VALIDATION


# ---------------------------------------------------------------------------
# phase 2 — gap-driven depth
# ---------------------------------------------------------------------------


def test_depth_targets_the_heaviest_unprobed_dimension():
    """Gaps are chased in weight order, not enum order: an unprobed PROCESS
    (0.238 in BPO) is worth more than an unprobed AUTHENTICITY (0.19), so it
    goes first. Weighting the tie-break is what stops the policy spending a
    question on the 0.05-weighted dimension while a heavy one sits at zero."""
    states = [
        state(
            "c1", "team_handling", 25.0,
            levels={ProbeLevel.VALIDATION},
            scores={Dimension.SPECIFICITY: 90, Dimension.METRIC_OWNERSHIP: 80},
            answers=1, claim_score=40,
        )
    ]
    plan = plan_next(states, 1)
    weights = scoring.dimension_weights_for("bpo_operations")
    assert plan.target_dimension is Dimension.PROCESS
    assert weights["PROCESS"] >= weights["AUTHENTICITY"]
    # and the level chosen is one that can actually elicit that dimension
    assert plan.target_dimension in signals.dimensions_for_level(plan.probe_level)


def test_authenticity_gap_selects_an_incident_probe():
    """Once the heavier gaps are covered, AUTHENTICITY is only reachable by an
    INCIDENT probe — the level whose whole job is 'tell me about one time'."""
    states = [
        state(
            "c1", "team_handling", 25.0,
            levels={ProbeLevel.VALIDATION},
            scores={
                Dimension.SPECIFICITY: 90,
                Dimension.METRIC_OWNERSHIP: 80,
                Dimension.PROCESS: 90,
                Dimension.CAUSAL_REASONING: 85,
                Dimension.TOOL_FAMILIARITY: 80,
            },
            answers=1, claim_score=60,
        )
    ]
    plan = plan_next(states, 1)
    assert plan.target_dimension is Dimension.AUTHENTICITY
    assert plan.probe_level is ProbeLevel.INCIDENT


def test_the_gap_hint_always_matches_the_question_asked():
    """When the ideal level is spent, the hint must be re-pointed at what the
    chosen level can actually elicit — a mismatched hint produces a confused,
    hybrid question."""
    states = [
        state(
            "c1", "team_handling", 25.0,
            levels={ProbeLevel.VALIDATION, ProbeLevel.INCIDENT},
            scores={Dimension.SPECIFICITY: 90, Dimension.AUTHENTICITY: 0},
            answers=2, claim_score=40,
        )
    ]
    plan = plan_next(states, 2)
    covered = signals.dimensions_for_level(plan.probe_level)
    assert plan.target_dimension is None or plan.target_dimension in covered


def test_heavier_claims_are_deepened_first():
    states = [
        state("c1", "team_handling", 25.0, levels={ProbeLevel.VALIDATION}, answers=1, claim_score=30),
        state("c2", "aht_control", 15.0, levels={ProbeLevel.VALIDATION}, answers=1, claim_score=30, order=1),
    ]
    assert plan_next(states, 2).claim.id == "c1"


# ---------------------------------------------------------------------------
# the adaptive stop
# ---------------------------------------------------------------------------


def test_saturated_claims_are_left_alone():
    states = [
        state("c1", "team_handling", 25.0, levels={ProbeLevel.VALIDATION},
              answers=1, claim_score=scoring.SATURATION_AT),
        state("c2", "aht_control", 15.0, levels={ProbeLevel.VALIDATION},
              answers=1, claim_score=20, order=1),
    ]
    assert plan_next(states, 2).claim.id == "c2"


def test_a_claim_that_stops_producing_signals_is_abandoned():
    """Asking a fifth question of someone who has said nothing for two answers
    wastes the budget and the candidate's patience."""
    states = [
        state("c1", "team_handling", 25.0, levels={ProbeLevel.VALIDATION},
              answers=2, last_signals=0, claim_score=10),
        state("c2", "aht_control", 15.0, levels={ProbeLevel.VALIDATION},
              answers=1, last_signals=6, claim_score=30, order=1),
    ]
    assert plan_next(states, 2).claim.id == "c2"


def test_interview_ends_when_every_claim_is_done():
    all_levels = set(signals.PROBE_ORDER)
    states = [state("c1", "team_handling", 25.0, levels=all_levels, answers=5, claim_score=90)]
    assert plan_next(states, 5) is None


def test_budget_is_respected():
    states = [state("c1", "team_handling", 25.0)]
    assert plan_next(states, settings.max_questions) is None


def test_policy_is_deterministic():
    """The same session must always ask the same questions in the same order,
    or 'explainable' is a marketing word."""
    def fresh():
        return [
            state("c1", "team_handling", 25.0, levels={ProbeLevel.VALIDATION},
                  scores={Dimension.SPECIFICITY: 50}, answers=1, claim_score=30),
            state("c2", "aht_control", 15.0, levels={ProbeLevel.VALIDATION},
                  answers=1, claim_score=30, order=1),
        ]
    results = {
        (plan_next(fresh(), 2).claim.id, plan_next(fresh(), 2).probe_level)
        for _ in range(25)
    }
    assert len(results) == 1


def test_no_claim_and_level_pair_is_ever_asked_twice():
    states = [state("c1", "team_handling", 25.0, levels={ProbeLevel.VALIDATION}, answers=1)]
    for _ in range(4):
        plan = plan_next(states, 1)
        assert plan is not None
        assert plan.probe_level not in states[0].levels_used
        states[0].levels_used.add(plan.probe_level)
    assert plan_next(states, 5) is None
