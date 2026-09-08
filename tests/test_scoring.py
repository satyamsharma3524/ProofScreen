"""
ARTIFACT 4 — the maths. If a judge asks "isn't the score just the LLM's
opinion?", this file is the answer. Nothing here touches a model, a network or
a database.
"""

from __future__ import annotations

import inspect

import pytest

from api.engine import scoring, signals
from api.schemas import (
    AnswerSignals,
    Badge,
    CausalLink,
    Dimension,
    DimensionScore,
    IncidentMarker,
    MetricDefinition,
    NamedEntity,
    ProbeLevel,
    ProcessStep,
    Quantity,
    ToolMention,
)


# ---------------------------------------------------------------------------
# the structural claim: no model anywhere near a score
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("module", [scoring, signals])
def test_scoring_modules_never_import_the_llm(module):
    """The central architectural claim, asserted rather than promised."""
    source = inspect.getsource(module)
    assert "from api.llm" not in source
    assert "import llm" not in source
    assert "openai" not in source.lower()


def test_answer_signals_carries_no_score_field():
    """The model's output schema has nowhere to put a grade even if it tried."""
    forbidden = {"score", "rating", "confidence", "grade", "quality", "points"}
    assert not (set(AnswerSignals.model_fields) & forbidden)


# ---------------------------------------------------------------------------
# the rubrics
# ---------------------------------------------------------------------------


def test_empty_answer_scores_zero_on_every_dimension():
    scores = signals.score_answer(AnswerSignals())
    assert all(s.score == 0 for s in scores.values())


def test_execution_rewards_quantities():
    sig = AnswerSignals(
        process_steps=[ProcessStep(step=f"step {i}", quote="q") for i in range(3)],
        quantities=[Quantity(value=f"{i}0%", refers_to="CSAT", quote="q") for i in range(5)]
    )
    assert signals.score_execution(sig).score > 50


def test_problem_solving_ignores_partial_chains():
    partial = AnswerSignals(
        causal_links=[CausalLink(cause="a", action="b", quote="q") for _ in range(5)]
    )
    complete = AnswerSignals(
        causal_links=[
            CausalLink(cause="a", action="b", outcome="c", quote="q") for _ in range(2)
        ]
    )
    assert signals.score_problem_solving(partial).score <= 45
    assert signals.score_problem_solving(complete).score > 45


def test_knowledge_needs_a_definition_not_a_mention():
    named = AnswerSignals(metric_definitions=[MetricDefinition(metric="CSAT", quote="q")])
    defined = AnswerSignals(
        metric_definitions=[
            MetricDefinition(metric="CSAT", how_measured="percent of 4-5 survey ratings", quote="q"),
            MetricDefinition(metric="AHT", how_measured="talk + hold + ACW", quote="q"),
        ]
    )
    assert signals.score_knowledge(named).score == 0
    assert signals.score_knowledge(defined).score > 0


def test_execution_tool_familiarity_is_usage_not_name_dropping():
    named = AnswerSignals(
        process_steps=[ProcessStep(step=f"step {i}", quote="q") for i in range(3)],
        tools=[ToolMention(tool=f"tool{i}", quote="q") for i in range(5)]
    )
    used = AnswerSignals(
        process_steps=[ProcessStep(step=f"step {i}", quote="q") for i in range(3)],
        tools=[
            ToolMention(tool="Genesys", usage="pulled the AHT report each morning", quote="q"),
            ToolMention(tool="Zendesk", usage="tagged repeat callers", quote="q"),
        ]
    )
    assert signals.score_execution(named).score <= 75
    assert signals.score_execution(used).score > 75


def test_problem_solving_counts_remembered_incidents():
    sig = AnswerSignals(
        incident_markers=[IncidentMarker(detail=f"episode {i}", quote="q") for i in range(3)]
    )
    assert signals.score_problem_solving(sig).score > 45
    assert signals.score_problem_solving(AnswerSignals()).score <= 45


def test_a_blunt_specific_answer_beats_a_polished_vague_one():
    """The anti-bias property, as a test. Fluency is not scored; evidence is."""
    blunt = AnswerSignals(
        quantities=[Quantity(value="35", refers_to="team", quote="q"),
                    Quantity(value="9 hours", refers_to="queue", quote="q")],
        incident_markers=[IncidentMarker(detail="three resigned before month-end", quote="q")],
        process_steps=[ProcessStep(step="moved email agents to voice", quote="q")],
    )
    polished = AnswerSignals(
        entities=[NamedEntity(entity="stakeholder alignment", quote="q"),
                  NamedEntity(entity="operational excellence", quote="q")],
        summary="A thoughtful and articulate reflection on leadership philosophy.",
    )
    assert scoring.claim_score(signals.score_answer(blunt)) > scoring.claim_score(
        signals.score_answer(polished)
    )


# ---------------------------------------------------------------------------
# accumulation across a claim's answers
# ---------------------------------------------------------------------------


def test_evidence_accumulates_across_answers():
    """Two complete causal chains in two different answers must beat one."""
    one = AnswerSignals(causal_links=[CausalLink(cause="a", action="b", outcome="c", quote="q1")])
    two = AnswerSignals(causal_links=[CausalLink(cause="d", action="e", outcome="f", quote="q2")])
    single = signals.score_claim([one], [ProbeLevel.INCIDENT])
    both = signals.score_claim([one, two], [ProbeLevel.INCIDENT, ProbeLevel.DECISION])
    assert both[Dimension.PROBLEM_SOLVING].score > single[Dimension.PROBLEM_SOLVING].score


def test_repetition_is_not_evidence():
    """Saying the same thing three times is one signal, not three."""
    same = AnswerSignals(quantities=[Quantity(value="35", refers_to="team size", quote="35 agents")])
    once = signals.score_claim([same], [ProbeLevel.OPERATIONAL])
    thrice = signals.score_claim([same, same, same], [ProbeLevel.OPERATIONAL])
    assert once[Dimension.EXECUTION].score == thrice[Dimension.EXECUTION].score


def test_unprobed_dimensions_are_marked_not_silently_zero():
    """A 0 nobody asked about must be distinguishable from a 0 they earned."""
    scores = signals.score_claim([AnswerSignals()], [ProbeLevel.OPERATIONAL])
    assert scores[Dimension.EXECUTION].probed is True        # OPERATIONAL targets it
    assert scores[Dimension.ADAPTABILITY].probed is False    # TRANSFER does, and wasn't asked
    assert scores[Dimension.ADAPTABILITY].basis == "not probed"


# ---------------------------------------------------------------------------
# claim, candidate and badge maths
# ---------------------------------------------------------------------------


def _perfect() -> dict[Dimension, DimensionScore]:
    return {d: DimensionScore(dimension=d, score=100, probed=True) for d in scoring.DIMENSION_ORDER}


def test_all_dimensions_perfect_is_100():
    assert scoring.claim_score(_perfect(), "bpo_operations") == 100


def test_claim_score_is_weighted_not_averaged():
    """A perfect score on the heaviest dimension beats one on the lightest."""
    weights = scoring.dimension_weights_for("general")
    heavy = max(weights, key=lambda k: weights[k])
    light = min(weights, key=lambda k: weights[k])
    only_heavy = {Dimension(heavy): DimensionScore(dimension=Dimension(heavy), score=100, probed=True)}
    only_light = {Dimension(light): DimensionScore(dimension=Dimension(light), score=100, probed=True)}
    assert scoring.claim_score(only_heavy, "general") > scoring.claim_score(only_light, "general")


def test_voice_contributes_only_its_configured_share():
    content = _perfect()
    text_only = scoring.claim_score(content, "general")
    with_bad_voice = scoring.claim_score(content, "general", voice_effort=0, voice_weight=0.10)
    assert text_only == 100
    assert with_bad_voice == pytest.approx(90, abs=1)


def test_voice_weight_zero_removes_the_text_voice_asymmetry():
    content = _perfect()
    assert scoring.claim_score(content, "general", voice_effort=0, voice_weight=0.0) == 100


def test_role_weights_change_the_weighted_score():
    """Artifact 5, at the arithmetic level."""
    claims = [("team_handling", 90), ("aht_control", 20)]
    people = {"team_handling": 80, "aht_control": 20}
    ops = {"team_handling": 20, "aht_control": 80}
    people_score, _ = scoring.weighted_evidence_score(claims, people)
    ops_score, _ = scoring.weighted_evidence_score(claims, ops)
    assert people_score > ops_score


def test_role_coverage_reports_what_the_resume_never_claimed():
    """'Evidenced badly' and 'never claimed' must stay separate facts."""
    weights = {"a": 50, "b": 30, "c": 20}
    _, coverage = scoring.weighted_evidence_score([("a", 80)], weights)
    assert coverage == 50


def test_consistency_multiplier_applies_once_globally():
    assert scoring.competence_score(85, 0.6) == 51
    assert scoring.competence_score(85, 1.0) == 85


@pytest.mark.parametrize(
    "score,expected",
    [(100, Badge.verified), (70, Badge.verified), (69, Badge.partial),
     (40, Badge.partial), (39, Badge.unverified), (0, Badge.unverified)],
)
def test_badge_thresholds_are_exact(score, expected):
    assert scoring.badge_for(score) is expected


def test_recruiter_weights_are_rescaled_not_rejected():
    """A recruiter typing 40/30/20/20 gets what they meant."""
    out = scoring.normalise_weights({"a": 40, "b": 30, "c": 20, "d": 20})
    assert sum(out.values()) == pytest.approx(100.0)
    assert out["a"] > out["b"] > out["c"]


# ---------------------------------------------------------------------------
# resume_score — the deliberately shallow contrast metric
# ---------------------------------------------------------------------------

JD = "Team lead responsible for CSAT improvement, AHT reduction, escalation handling and SLA attainment"


def test_resume_score_is_bounded():
    assert scoring.resume_score(JD, JD) == 100
    assert 0 <= scoring.resume_score("nothing relevant", JD) <= 100
    assert scoring.resume_score("anything", "") == 0


def test_keyword_stuffing_beats_substance():
    """The whole reason resume_score exists — and the pitch's money slide."""
    stuffed = ("CSAT improvement AHT reduction escalation handling SLA attainment team "
               "lead responsible csat aht sla escalation")
    honest = "I ran a support team for four years and customers were happier by the end."
    assert scoring.resume_score(stuffed, JD) > scoring.resume_score(honest, JD)
