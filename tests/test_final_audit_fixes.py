"""
Unit tests for the 6 final pre-hackathon audit fixes.

Tests:
1. Ownership false negative reduction (first-person operational actions open Ownership gate and score).
2. Decision quality improvement (strong tradeoff decisions score full weight vs weak choices at half weight).
3. Better quantity extraction (spelled-out numbers, relative/multiplicative quantities).
4. Multi-sentence causal chain extraction recall.
5. Textbook answer theoretical-only detection basis annotation.
6. Descriptive recruiter basis explanations for all dimensions.
"""

from api.engine.evidence import heuristic_signals
from api.engine.signals import (
    _is_strong_decision,
    _is_theoretical_only,
    score_answer,
    score_execution,
    score_judgment,
    score_knowledge,
    score_ownership,
)
from api.schemas import (
    AnswerSignals,
    ConceptExplanation,
    DecisionSignal,
    Dimension,
    MetricDefinition,
    OwnershipBoundary,
    ProcessStep,
    Quantity,
)


def test_fix1_ownership_false_negative_reduction():
    """First-person operational statements ('I isolated', 'I handled') contribute to Ownership."""
    # Answer without formal explicit boundary but with first-person operational actions
    sig = AnswerSignals(
        process_steps=[
            ProcessStep(step="I isolated the leaking endpoint", quote="I isolated the leaking endpoint"),
            ProcessStep(step="I handled the database migration", quote="I handled the database migration"),
        ],
        decisions=[
            DecisionSignal(choice="I decided to kill idle queries", reason="prevent exhaustion", quote="I decided to kill idle queries"),
        ],
    )
    score_result = score_ownership(sig)
    # Ownership gate should be open and score should be > 0
    assert score_result.score > 0
    assert "Owned operational action: I isolated the leaking endpoint" in score_result.basis
    assert "Owned decision: I decided to kill idle queries" in score_result.basis


def test_fix2_decision_quality_improvement():
    """Strong decisions with trade-offs receive higher weight than simple generic choices."""
    weak_d = DecisionSignal(choice="We chose Redis", reason="it was fast", quote="We chose Redis because it was fast")
    strong_d = DecisionSignal(
        choice="Selected Redis over Memcached",
        reason="evaluated Memcached and Redis, selected Redis because persistence was required and operational overhead was lower",
        quote="We evaluated Memcached and Redis, but selected Redis because persistence was required",
    )

    assert not _is_strong_decision(weak_d)
    assert _is_strong_decision(strong_d)

    sig_weak = AnswerSignals(decisions=[weak_d])
    sig_strong = AnswerSignals(decisions=[strong_d])

    res_weak = score_judgment(sig_weak)
    res_strong = score_judgment(sig_strong)

    assert res_strong.score > res_weak.score
    assert "Evaluated decision tradeoff" in res_strong.basis
    assert "Simple choice" in res_weak.basis


def test_fix3_quantity_extraction():
    """Spelled-out numbers and relative/multiplicative quantities are extracted."""
    answer = "We had three engineers working for two quarters on a dozen endpoints. We cut latency in half and doubled throughput."
    sig = heuristic_signals(answer)
    values = [q.value.lower() for q in sig.quantities]

    assert any("three engineers" in v for v in values)
    assert any("two quarters" in v for v in values)
    assert any("dozen endpoints" in v for v in values)
    assert any("cut latency in half" in v or "half" in v for v in values)
    assert any("doubled throughput" in v or "doubled" in v for v in values)


def test_fix4_multi_sentence_causal_chain():
    """Cause -> Action -> Outcome across multiple sentences is captured as a complete causal chain."""
    answer = (
        "The queue started backing up. "
        "We found a consumer lag issue. "
        "We increased partition count. "
        "Latency returned to normal."
    )
    sig = heuristic_signals(answer)
    assert len(sig.causal_links) > 0
    complete = [c for c in sig.causal_links if c.is_complete]
    assert len(complete) > 0
    assert "backing up" in complete[0].cause or "lag" in complete[0].cause
    assert "increased" in complete[0].action
    assert "returned to normal" in complete[0].outcome or "normal" in complete[0].outcome


def test_fix5_textbook_theoretical_only_signal():
    """Theoretical answers without operational evidence are flagged in basis explanations."""
    theory_sig = AnswerSignals(
        concept_explanations=[
            ConceptExplanation(concept="p95 latency", reasoning="95th percentile of response time", quote="p95 latency is the 95th percentile")
        ],
        metric_definitions=[
            MetricDefinition(metric="CSAT", how_measured="customer satisfaction survey", quote="CSAT measured via survey")
        ],
    )
    assert _is_theoretical_only(theory_sig)

    res_k = score_knowledge(theory_sig)
    assert "Primarily theoretical" in res_k.basis

    op_sig = AnswerSignals(
        concept_explanations=[
            ConceptExplanation(concept="p95 latency", reasoning="95th percentile", quote="p95 latency")
        ],
        process_steps=[
            ProcessStep(step="We checked Prometheus metrics", quote="We checked Prometheus metrics")
        ],
    )
    assert not _is_theoretical_only(op_sig)


def test_fix6_recruiter_explanation_improvement():
    """Basis strings surface descriptive human-readable descriptions instead of raw counts."""
    sig = AnswerSignals(
        process_steps=[
            ProcessStep(step="Configured connection pool", quote="Configured connection pool")
        ],
        decisions=[
            DecisionSignal(
                choice="Selected Postgres over MySQL",
                reason="compared features and required JSONB support",
                quote="Selected Postgres over MySQL because we required JSONB support",
            )
        ],
    )
    scores = score_answer(sig)
    exec_basis = scores[Dimension.EXECUTION].basis
    j_basis = scores[Dimension.JUDGMENT].basis

    assert "Executed step: Configured connection pool" in exec_basis
    assert "Evaluated decision tradeoff: Selected Postgres over MySQL" in j_basis
