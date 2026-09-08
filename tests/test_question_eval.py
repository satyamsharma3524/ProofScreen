"""
Unit tests for Question Quality Evaluation System (api/engine/question_eval.py).

Tests:
1. Five evaluation dimensions: Framing Diversity, Claim Echo Score, Concrete Anchor Score,
   Conversationality Score, Answerability Score.
2. Output schema validation & final weighted score calculation.
3. Penalty logic for repetitive openings, claim restatement, audit jargon, multi-part questions.
4. Reward logic for natural recruiter phrasing, specific anchors, clear asks.
5. Deterministic pure Python evaluator and LLM wrapper fallback mode.
"""

import asyncio

from api.engine.question_eval import (
    QuestionQualityEvaluation,
    evaluate_question_quality,
    evaluate_question_quality_deterministic,
)


def test_question_eval_schema_structure():
    """Verify output schema structure and fields match specification."""
    eval_result = evaluate_question_quality_deterministic(
        question="What was the first thing you monitored once the Prometheus dashboard was live?",
        claim_text="Implemented monitoring dashboards using Prometheus and Grafana.",
    )

    assert isinstance(eval_result, QuestionQualityEvaluation)
    assert 0 <= eval_result.question_quality_score <= 100
    assert 0 <= eval_result.claim_echo_score <= 100
    assert 0 <= eval_result.anchor_score <= 100
    assert 0 <= eval_result.conversationality_score <= 100
    assert 0 <= eval_result.answerability_score <= 100
    assert 0 <= eval_result.evidence_yield_score <= 100
    assert 0 <= eval_result.dimension_alignment_score <= 100


def test_claim_echo_score_penalty():
    """High claim restatement ('On the work where you used Prometheus and Grafana...') should produce high echo score and penalize quality."""
    claim = "Implemented monitoring dashboards using Prometheus and Grafana."
    bad_question = "On the work where you used Prometheus and Grafana, what anomaly required immediate attention?"
    good_question = "Which alert ended up being most useful once the dashboard went live?"

    bad_eval = evaluate_question_quality_deterministic(bad_question, claim)
    good_eval = evaluate_question_quality_deterministic(good_question, claim)

    assert bad_eval.claim_echo_score > good_eval.claim_echo_score
    assert bad_eval.question_quality_score < good_eval.question_quality_score


def test_audit_jargon_conversationality_penalty():
    """Audit/bureaucratic phrasing ('what anomaly required immediate attention') should be penalized in conversationality."""
    claim = "Set up Kubernetes cluster and monitoring."
    audit_question = "What decisions could you make independently and what required approval during execution?"
    natural_question = "Which parts of the Kubernetes setup were yours and where did you need help from the team?"

    audit_eval = evaluate_question_quality_deterministic(audit_question, claim)
    natural_eval = evaluate_question_quality_deterministic(natural_question, claim)

    assert audit_eval.conversationality_score < natural_eval.conversationality_score
    assert natural_eval.question_quality_score >= 80


def test_concrete_anchor_score():
    """Questions with specific tools/artifacts ('Prometheus', 'dashboard') should score high on concrete anchor."""
    claim = "Maintained microservices on AWS."
    unanchored_question = "What issues did you face?"
    anchored_question = "What issue did you face while configuring Prometheus scraping?"

    unanchored_eval = evaluate_question_quality_deterministic(unanchored_question, claim)
    anchored_eval = evaluate_question_quality_deterministic(anchored_question, claim)

    assert unanchored_eval.anchor_score < anchored_eval.anchor_score


def test_answerability_multi_part_and_length_penalty():
    """Overly long or multi-part questions should receive answerability penalties."""
    claim = "Optimized API latency."
    multi_part = "What was the initial latency and how did you measure it and also what tools did you use to track it?"
    concise = "What was the first problem you noticed when search latency spiked?"

    multi_eval = evaluate_question_quality_deterministic(multi_part, claim)
    concise_eval = evaluate_question_quality_deterministic(concise, claim)

    assert multi_eval.answerability_score < concise_eval.answerability_score


def test_framing_diversity_repetition_penalty():
    """Prior questions using the same repetitive framing pattern ('On the work where...') should incur framing penalties."""
    claim = "Built CI/CD pipeline in Jenkins."
    prior = [
        "On the work where you used Docker...",
        "On the work where you built microservices...",
    ]
    repeated_frame_q = "On the work where you set up Jenkins, what broke first?"
    natural_frame_q = "What was the trickiest part of configuring the Jenkins build step?"

    repeated_eval = evaluate_question_quality_deterministic(repeated_frame_q, claim, prior_questions=prior)
    natural_eval = evaluate_question_quality_deterministic(natural_frame_q, claim, prior_questions=prior)

    assert repeated_eval.question_quality_score < natural_eval.question_quality_score


def test_async_evaluate_question_quality_fallback():
    """Verify async evaluate_question_quality API returns structured evaluation in fixture/fallback mode."""
    claim = "Reduced database query time by 40%."
    question = "What query optimization had the biggest impact on performance?"

    result = asyncio.run(evaluate_question_quality(question, claim))

    assert isinstance(result, QuestionQualityEvaluation)
    assert result.question_quality_score > 0
    assert result.evidence_yield_score > 0
    assert result.dimension_alignment_score > 0
