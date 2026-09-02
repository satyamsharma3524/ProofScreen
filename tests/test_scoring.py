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


def test_specificity_gate_caps_name_dropping_without_numbers():
    """Five named things and no number cannot beat the gate."""
    sig = AnswerSignals(
        entities=[NamedEntity(entity=f"thing {i}", quote="q") for i in range(6)]
    )
    result = signals.score_specificity(sig)
    assert result.score <= signals.GATES[Dimension.SPECIFICITY][0]
    assert "no quantity given" in result.basis


def test_specificity_rewards_quantities():
    sig = AnswerSignals(
        quantities=[Quantity(value=f"{i}0%", refers_to="CSAT", quote="q") for i in range(5)]
    )
    assert signals.score_specificity(sig).score == 100


def test_causal_gate_partial_chains_cannot_reach_full_marks():
    partial = AnswerSignals(
        causal_links=[CausalLink(cause="a", action="b", quote="q") for _ in range(5)]
    )
    complete = AnswerSignals(
        causal_links=[
            CausalLink(cause="a", action="b", outcome="c", quote="q") for _ in range(2)
        ]
    )
    assert signals.score_causal_reasoning(partial).score <= 50
    assert signals.score_causal_reasoning(complete).score == 100


def test_metric_ownership_needs_a_definition_not_a_mention():
    named = AnswerSignals(metric_definitions=[MetricDefinition(metric="CSAT", quote="q")])
    defined = AnswerSignals(
        metric_definitions=[
            MetricDefinition(metric="CSAT", how_measured="percent of 4-5 survey ratings", quote="q"),
            MetricDefinition(metric="AHT", how_measured="talk + hold + ACW", quote="q"),
        ]
    )
    assert signals.score_metric_ownership(named).score <= 45
    assert signals.score_metric_ownership(defined).score == 100


def test_tool_familiarity_is_usage_not_name_dropping():
    named = AnswerSignals(tools=[ToolMention(tool=f"tool{i}", quote="q") for i in range(5)])
    used = AnswerSignals(
        tools=[
            ToolMention(tool="Genesys", usage="pulled the AHT report each morning", quote="q"),
            ToolMention(tool="Zendesk", usage="tagged repeat callers", quote="q"),
        ]
    )
    assert signals.score_tool_familiarity(named).score <= 40
    assert signals.score_tool_familiarity(used).score == 100


def test_authenticity_counts_remembered_incidents():
    sig = AnswerSignals(
        incident_markers=[IncidentMarker(detail=f"episode {i}", quote="q") for i in range(3)]
    )
    assert signals.score_authenticity(sig).score == 100
    assert signals.score_authenticity(AnswerSignals()).score == 0


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
    single = signals.score_claim([one], [ProbeLevel.DECISION])
    both = signals.score_claim([one, two], [ProbeLevel.DECISION, ProbeLevel.OUTCOME])
    assert both[Dimension.CAUSAL_REASONING].score > single[Dimension.CAUSAL_REASONING].score


def test_repetition_is_not_evidence():
    """Saying the same thing three times is one signal, not three."""
    same = AnswerSignals(quantities=[Quantity(value="35", refers_to="team size", quote="35 agents")])
    once = signals.score_claim([same], [ProbeLevel.VALIDATION])
    thrice = signals.score_claim([same, same, same], [ProbeLevel.VALIDATION])
    assert once[Dimension.SPECIFICITY].score == thrice[Dimension.SPECIFICITY].score


def test_unprobed_dimensions_are_marked_not_silently_zero():
    """A 0 nobody asked about must be distinguishable from a 0 they earned."""
    scores = signals.score_claim([AnswerSignals()], [ProbeLevel.VALIDATION])
    assert scores[Dimension.SPECIFICITY].probed is True        # VALIDATION targets it
    assert scores[Dimension.AUTHENTICITY].probed is False      # INCIDENT does, and wasn't asked
    assert scores[Dimension.AUTHENTICITY].basis == "not probed"


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
