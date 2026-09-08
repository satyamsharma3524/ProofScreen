"""
Unit tests for the 3 recruiter-alignment fixes:
1. Remove unprobed dimension dilution in claim_score.
2. Operational troubleshooting step detection and 1.5x weighting in score_execution.
3. Strong claim prioritization ranking bonus.
"""

from api.engine.scoring import claim_score
from api.engine.signals import (
    _is_troubleshooting_step,
    claim_strength_bonus,
    score_execution,
)
from api.schemas import (
    AnswerSignals,
    Dimension,
    DimensionScore,
    ProcessStep,
)


def test_fix1_recruiter_dimension_coverage_preference():
    """Candidate B demonstrating evidence across 6 dimensions outranks Candidate A with only 2 dimensions."""
    dims_candidate_a = {
        Dimension.EXECUTION: DimensionScore(dimension=Dimension.EXECUTION, score=95, probed=True),
        Dimension.KNOWLEDGE: DimensionScore(dimension=Dimension.KNOWLEDGE, score=85, probed=True),
    }
    dims_candidate_b = {
        Dimension.EXECUTION: DimensionScore(dimension=Dimension.EXECUTION, score=95, probed=True),
        Dimension.KNOWLEDGE: DimensionScore(dimension=Dimension.KNOWLEDGE, score=90, probed=True),
        Dimension.PROBLEM_SOLVING: DimensionScore(dimension=Dimension.PROBLEM_SOLVING, score=85, probed=True),
        Dimension.ADAPTABILITY: DimensionScore(dimension=Dimension.ADAPTABILITY, score=80, probed=True),
        Dimension.OWNERSHIP: DimensionScore(dimension=Dimension.OWNERSHIP, score=40, probed=True),
        Dimension.JUDGMENT: DimensionScore(dimension=Dimension.JUDGMENT, score=35, probed=True),
    }
    score_a = claim_score(dims_candidate_a)
    score_b = claim_score(dims_candidate_b)
    # Recruiters prefer Candidate B who proved evidence across 6 dimensions over Candidate A with only 2
    assert score_b > score_a


def test_fix2_troubleshooting_step_detection():
    """Troubleshooting steps receive 1.5x weight and explicit basis annotation."""
    assert _is_troubleshooting_step("recovered corrupted production database")
    assert _is_troubleshooting_step("isolated memory leak in auth service")
    assert _is_troubleshooting_step("fixed Black Friday outage")
    assert not _is_troubleshooting_step("built docker container")

    sig_routine = AnswerSignals(
        process_steps=[ProcessStep(step="built docker container", quote="built docker container")]
    )
    sig_trouble = AnswerSignals(
        process_steps=[ProcessStep(step="recovered corrupted production database", quote="recovered corrupted production database")]
    )

    res_routine = score_execution(sig_routine)
    res_trouble = score_execution(sig_trouble)

    assert res_trouble.score > res_routine.score
    assert "Operational troubleshooting step" in res_trouble.basis
    assert "Executed step" in res_routine.basis


def test_fix3_strong_claim_prioritization():
    """Claims with incidents, metrics, constraints, or ownership rank higher than generic bullets."""
    claim_generic = "I worked on backend services"
    claim_metric = "I reduced latency by 70%"
    claim_incident = "I fixed a Black Friday outage"
    claim_constraint = "I migrated 50M rows with zero downtime"
    claim_ownership = "I led the payments service redesign"

    bonus_generic = claim_strength_bonus(claim_generic)
    bonus_metric = claim_strength_bonus(claim_metric)
    bonus_incident = claim_strength_bonus(claim_incident)
    bonus_constraint = claim_strength_bonus(claim_constraint)
    bonus_ownership = claim_strength_bonus(claim_ownership)

    assert bonus_metric > bonus_generic
    assert bonus_incident > bonus_generic
    assert bonus_constraint > bonus_generic
    assert bonus_ownership > bonus_generic
