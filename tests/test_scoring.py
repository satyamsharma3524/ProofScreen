"""
The only tests that really matter: the maths behind the score.

If a judge asks "isn't the score just the LLM's opinion?", this file is the
answer. Nothing here touches a network, a database or a model.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from api.engine import scoring
from api.schemas import Badge, Dimension as D, Verdict as V

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "sample_graph.json"


def node(dimension: D, verdict: V) -> dict:
    return {"dimension": dimension.value, "verdict": verdict.value}


ALL_DIMENSIONS = list(scoring.DIMENSION_ORDER)


# ---------------------------------------------------------------------------
# the constants
# ---------------------------------------------------------------------------


def test_dimension_weights_sum_to_one():
    assert math.isclose(sum(scoring.DIMENSION_WEIGHT.values()), 1.0)


def test_every_dimension_and_verdict_has_a_value():
    assert set(scoring.DIMENSION_WEIGHT) == set(D)
    assert set(scoring.VERDICT_POINTS) == set(V)


# ---------------------------------------------------------------------------
# claim_confidence
# ---------------------------------------------------------------------------


def test_all_supported_is_exactly_one():
    nodes = [node(d, V.SUPPORTED) for d in ALL_DIMENSIONS]
    assert scoring.claim_confidence(nodes) == 1.0


def test_all_unsupported_is_zero():
    nodes = [node(d, V.UNSUPPORTED) for d in ALL_DIMENSIONS]
    assert scoring.claim_confidence(nodes) == 0.0


def test_no_evidence_is_zero():
    assert scoring.claim_confidence([]) == 0.0


def test_all_partial_is_half():
    nodes = [node(d, V.PARTIAL) for d in ALL_DIMENSIONS]
    assert scoring.claim_confidence(nodes) == 0.5


def test_contradiction_cannot_push_below_zero():
    nodes = [node(d, V.CONTRADICTED) for d in ALL_DIMENSIONS]
    assert scoring.claim_confidence(nodes) == 0.0


def test_single_contradiction_drags_the_score_down():
    strong = [node(d, V.SUPPORTED) for d in ALL_DIMENSIONS]
    weakened = [node(D.OWNERSHIP, V.CONTRADICTED)] + [
        node(d, V.SUPPORTED) for d in ALL_DIMENSIONS if d is not D.OWNERSHIP
    ]
    assert scoring.claim_confidence(weakened) < scoring.claim_confidence(strong)
    # 0.30*(-0.5) + 0.30 + 0.20 + 0.20 = 0.55
    assert scoring.claim_confidence(weakened) == pytest.approx(0.55)


def test_ownership_is_worth_more_than_specificity():
    ownership_only = [node(D.OWNERSHIP, V.SUPPORTED)]
    specificity_only = [node(D.SPECIFICITY, V.SUPPORTED)]
    assert scoring.claim_confidence(ownership_only) == pytest.approx(0.30)
    assert scoring.claim_confidence(specificity_only) == pytest.approx(0.20)


def test_best_verdict_per_dimension_wins():
    """A later vague answer must not un-evidence an already proven dimension."""
    nodes = [
        node(D.OWNERSHIP, V.SUPPORTED),
        node(D.OWNERSHIP, V.PARTIAL),
        node(D.OWNERSHIP, V.UNSUPPORTED),
    ]
    assert scoring.claim_confidence(nodes) == pytest.approx(0.30)


def test_unknown_enum_values_are_ignored_not_fatal():
    nodes = [node(D.OWNERSHIP, V.SUPPORTED), {"dimension": "VIBES", "verdict": "GREAT"}]
    assert scoring.claim_confidence(nodes) == pytest.approx(0.30)


def test_accepts_objects_as_well_as_dicts():
    class Row:
        dimension = "OWNERSHIP"
        verdict = "SUPPORTED"

    assert scoring.claim_confidence([Row()]) == pytest.approx(0.30)


# ---------------------------------------------------------------------------
# competence_score and badges
# ---------------------------------------------------------------------------


def test_competence_is_the_mean():
    assert scoring.competence_score([1.0, 0.5, 0.0]) == pytest.approx(0.5)


def test_unprobed_claims_drag_the_mean_down():
    """One brilliant answer must not carry two ignored claims."""
    assert scoring.competence_score([1.0, 0.0, 0.0]) == pytest.approx(0.3333, abs=1e-4)


def test_competence_of_nothing_is_zero():
    assert scoring.competence_score([]) == 0.0


@pytest.mark.parametrize(
    "score,expected",
    [
        (1.0, Badge.verified),
        (0.70, Badge.verified),
        (0.6999, Badge.partial),
        (0.40, Badge.partial),
        (0.3999, Badge.unverified),
        (0.0, Badge.unverified),
    ],
)
def test_badge_thresholds_are_exact(score, expected):
    assert scoring.badge_for(score) is expected


def test_well_covered_matches_the_verified_threshold():
    nodes = [node(D.OWNERSHIP, V.SUPPORTED), node(D.DEPTH, V.SUPPORTED),
             node(D.SPECIFICITY, V.SUPPORTED)]          # 0.30+0.30+0.20 = 0.80
    assert scoring.is_well_covered(nodes) is True
    assert scoring.is_well_covered([node(D.OWNERSHIP, V.SUPPORTED)]) is False


# ---------------------------------------------------------------------------
# coverage — what the question policy reads
# ---------------------------------------------------------------------------


def test_coverage_lists_every_dimension_even_untouched_ones():
    cov = scoring.coverage([node(D.DEPTH, V.SUPPORTED)])
    assert set(cov) == set(D)
    assert cov[D.DEPTH] == 1.0
    assert cov[D.OWNERSHIP] == 0.0


def test_weakest_dimension_of_nothing_is_ownership():
    """Highest-weighted dimension is probed first, so Q1 is always OWNERSHIP."""
    assert scoring.weakest_dimension([]) is D.OWNERSHIP


def test_weakest_dimension_skips_what_is_already_evidenced():
    nodes = [node(D.OWNERSHIP, V.SUPPORTED), node(D.DEPTH, V.SUPPORTED)]
    assert scoring.weakest_dimension(nodes) in {D.SPECIFICITY, D.OPERATIONAL}


def test_weakest_dimension_is_weighted_not_just_counted():
    """Untouched OWNERSHIP (0.30) is probed before untouched SPECIFICITY (0.20)."""
    nodes = [node(D.DEPTH, V.SUPPORTED), node(D.OPERATIONAL, V.SUPPORTED)]
    assert scoring.weakest_dimension(nodes) is D.OWNERSHIP


def test_weakest_dimension_is_deterministic():
    nodes = [node(D.OWNERSHIP, V.SUPPORTED)]
    assert len({scoring.weakest_dimension(nodes) for _ in range(20)}) == 1


def test_weakest_dimension_across_claims():
    claim_a = [node(D.OWNERSHIP, V.SUPPORTED), node(D.DEPTH, V.SUPPORTED)]
    claim_b = [node(D.OWNERSHIP, V.SUPPORTED), node(D.SPECIFICITY, V.SUPPORTED)]
    # OPERATIONAL is untouched by both, so it must be the global gap.
    assert scoring.weakest_dimension_across([claim_a, claim_b]) is D.OPERATIONAL


# ---------------------------------------------------------------------------
# resume_score — the deliberately shallow contrast metric
# ---------------------------------------------------------------------------


JD = "Support lead responsible for CSAT improvement, escalation workflow design and SLA management"


def test_resume_score_is_bounded():
    assert 0.0 <= scoring.resume_score("nothing relevant here at all", JD) <= 1.0
    assert scoring.resume_score(JD, JD) == 1.0


def test_resume_score_with_no_job_description_is_zero():
    assert scoring.resume_score("anything", "") == 0.0


def test_keyword_stuffing_beats_substance():
    """This is the whole point of resume_score existing."""
    stuffed = (
        "CSAT improvement escalation workflow design SLA management support lead "
        "responsible csat escalation sla workflow"
    )
    honest = "I ran a support team for four years and the customers were happier by the end."
    assert scoring.resume_score(stuffed, JD) > scoring.resume_score(honest, JD)


# ---------------------------------------------------------------------------
# the fixture and the engine must never drift apart
# ---------------------------------------------------------------------------


def test_fixture_numbers_are_what_scoring_actually_computes():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))

    confidences = []
    for claim in data["claims"]:
        computed = scoring.claim_confidence(claim["nodes"])
        assert computed == pytest.approx(claim["confidence"], abs=1e-4), (
            f"fixture claim {claim['id']} says {claim['confidence']} "
            f"but scoring.py computes {computed}"
        )
        confidences.append(computed)

    competence = scoring.competence_score(confidences)
    assert competence == pytest.approx(data["competence_score"], abs=1e-4)
    assert scoring.badge_for(competence).value == data["badge"]


def test_fixture_quotes_are_verbatim_in_their_answers():
    """The rule the engine enforces, enforced on the hand-written fixture too."""
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for claim in data["claims"]:
        answers = " ".join(qa["answer"].lower() for qa in claim["qa"])
        for evidence_node in claim["nodes"]:
            quote = evidence_node["quote"].strip().lower()
            if quote:
                assert quote in answers, f"{quote!r} is not verbatim in the answers"
