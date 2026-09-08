"""
Unit tests for final pre-hackathon ProofScreen fixes.
"""

import pytest

from api.engine import question as question_engine
from api.engine import signals as signal_rubrics
from api.engine.orchestrator import ClaimState
from api.models import Claim
from api.schemas import (
    AnswerSignals,
    CausalLink,
    ConceptExplanation,
    ConstraintSignal,
    DecisionSignal,
    Dimension,
    IncidentMarker,
    ProbeLevel,
    ProcessStep,
)


def test_adaptability_pending_prevents_saturation_closure():
    """FIX 1: Saturation (score >= 80) should NOT close a claim if Move.PERTURB is still pending."""
    claim = Claim(id="cl_test1", text="Built latency optimization service", metric="latency")
    state = ClaimState(claim=claim, weight=1.0, score=85)
    
    # Move.PERTURB not in moves_used, and move_available(Move.PERTURB) is True
    assert state.saturated is True
    assert question_engine.Move.PERTURB.value not in state.moves_used
    assert state.forensic_closed is False, "Claim should remain open for Move.PERTURB despite high score"

    # Once PERTURB is used, saturation closes the claim
    state.moves_used.add(question_engine.Move.PERTURB.value)
    assert state.forensic_closed is True, "Claim should close once PERTURB has been used and score >= 80"


def test_authentic_incident_opens_knowledge_and_judgment_gates():
    """FIX 2: Authentic incident markers, causal links, and constraints should open Knowledge and Judgment gates."""
    # Authentic answer containing incident detail, causal link, and constraint (no formal metric definition or decision)
    sig = AnswerSignals(
        incident_markers=[IncidentMarker(detail="DB connection pool exhausted on Tuesday night", quote="DB connection pool exhausted")],
        causal_links=[CausalLink(cause="traffic spiked", action="killed idle queries and bumped max_connections", outcome="recovered DB", quote="traffic spiked so killed idle queries")],
        constraints=[ConstraintSignal(limitation="max 300 DB connections limit", quote="max 300 DB connections limit")],
        process_steps=[ProcessStep(step="killed idle queries", quote="killed idle queries")],
    )

    k_score = signal_rubrics.score_knowledge(sig)
    j_score = signal_rubrics.score_judgment(sig)

    assert k_score.probed is True
    assert k_score.score > 45, f"Knowledge gate should be open and score > 45 for authentic operational answer, got {k_score.score}"
    assert "Capped at 45" not in k_score.basis

    assert j_score.probed is True
    assert j_score.score > 0, f"Judgment gate should be open for authentic operational answer, got {j_score.score}"
    assert "Capped at 45" not in j_score.basis


def test_single_clean_orientation_prefix():
    """FIX 3: Fallback questions and repair questions should not double-prefix when context is already in base."""
    fb = question_engine.fallback_question(
        ProbeLevel.OPERATIONAL,
        claim_text="Implemented Prometheus and Grafana monitoring",
    )
    # Shouldn't start with double "On" or awkward stacked prefixes
    assert not fb.question.startswith('On "On ')
    
    rep = question_engine.repair_question(
        ProbeLevel.OPERATIONAL,
        claim_text="Implemented Prometheus and Grafana monitoring",
        job_family="software_engineering",
    )
    # FAMILY_REPAIR_PROMPTS for software engineering starts with "Walk me through..."
    assert rep.startswith('On "') or rep.startswith("Walk me through")


def test_prospective_transfer_reasoning_scores_adaptability():
    """FIX 4: Prospective causal reasoning (incomplete causal link), concepts, and decisions should score Adaptability."""
    sig = AnswerSignals(
        causal_links=[CausalLink(cause="traffic doubled", action="switch to async queue with read replicas", outcome=None, quote="switch to async queue")],
        concept_explanations=[ConceptExplanation(concept="read replica horizontal scaling", reasoning="offload read load", quote="offload read load")],
        decisions=[DecisionSignal(choice="cache read queries in Redis", reason="prevent connection pool starvation", quote="cache read queries in Redis")],
    )

    a_score = signal_rubrics.score_adaptability(sig)
    assert a_score.probed is True
    assert a_score.score >= 50, f"Adaptability should score > 0 for prospective transfer reasoning, got {a_score.score}"
    assert "Capped at 40" not in a_score.basis


def test_operational_evidence_bonus():
    """Operational evidence bonus applies to claim score when incident markers, complete causal links, or constraints exist."""
    from api.engine import scoring
    from api.schemas import MetricDefinition

    # Textbook answer (Candidate A)
    sig_a = AnswerSignals(
        process_steps=[
            ProcessStep(step="step1", quote="step1"),
            ProcessStep(step="step2", quote="step2"),
            ProcessStep(step="step3", quote="step3"),
        ],
        metric_definitions=[MetricDefinition(metric="SLA", how_measured="99.9%", quote="SLA")],
        decisions=[DecisionSignal(choice="use Grafana", quote="Grafana")],
    )
    dims_a = signal_rubrics.score_answer(sig_a, "general")
    score_a_base = scoring.claim_score(dims_a, "general")
    score_a_with_bonus = scoring.claim_score(dims_a, "general", signals=sig_a)
    assert score_a_base == score_a_with_bonus

    # Operational incident answer (Candidate B)
    sig_b = AnswerSignals(
        incident_markers=[IncidentMarker(detail="Black Friday DB pool crash", quote="Black Friday")],
        causal_links=[CausalLink(cause="exhaustion", action="killed 120 queries", outcome="recovered DB", quote="exhaustion killed queries recovered DB")],
        constraints=[ConstraintSignal(limitation="max_connections pool limit", quote="pool limit")],
        process_steps=[ProcessStep(step="killed queries", quote="killed queries")],
    )
    dims_b = signal_rubrics.score_answer(sig_b, "general")
    score_b_base = scoring.claim_score(dims_b, "general")
    score_b_with_bonus = scoring.claim_score(dims_b, "general", signals=sig_b)
    
    assert score_b_with_bonus > score_b_base
    assert score_b_with_bonus >= score_a_with_bonus
