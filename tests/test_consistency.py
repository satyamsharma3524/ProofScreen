"""
The consistency engine. Deterministic contradiction detection — arithmetic on
two numbers, not a second model opinion.
"""

from __future__ import annotations

import inspect

import pytest

from api.engine import consistency
from api.schemas import ExtractedFact, Severity


def fact(key: str, num: float | None = None, text: str | None = None, unit: str | None = None):
    return ExtractedFact(key=key, value_num=num, value_text=text, unit=unit, quote="q")


def test_consistency_never_imports_the_llm():
    source = inspect.getsource(consistency)
    assert "from api.llm" not in source and "openai" not in source.lower()


# ---------------------------------------------------------------------------
# the stable / variable distinction — the thing the whole engine rests on
# ---------------------------------------------------------------------------


def test_an_improvement_is_not_a_contradiction():
    """CSAT 78 then 92 is the success the candidate is claiming. Flagging it
    would punish every improvement anyone describes."""
    clash = consistency.compare(
        fact("csat_pct", 78), fact("csat_pct", 92), "bpo_operations"
    )
    assert clash is None


def test_aht_moving_is_not_a_contradiction():
    assert consistency.compare(
        fact("aht_seconds", 520), fact("aht_seconds", 430), "bpo_operations"
    ) is None


def test_team_size_changing_is_a_contradiction():
    """A value that should not move, moving. The example from the spec."""
    clash = consistency.compare(
        fact("team_size", 35), fact("team_size", 20), "bpo_operations"
    )
    assert clash is not None
    assert clash.severity is Severity.MINOR
    assert clash.delta_pct == pytest.approx(42.86, abs=0.01)
    assert "should not change" in clash.note


def test_a_large_divergence_is_major():
    clash = consistency.compare(
        fact("team_size", 45), fact("team_size", 20), "bpo_operations"
    )
    assert clash.severity is Severity.MAJOR


def test_human_approximation_is_not_a_contradiction():
    """35 vs 32 is someone rounding, not lying."""
    assert consistency.compare(
        fact("team_size", 35), fact("team_size", 32), "bpo_operations"
    ) is None


def test_severity_is_symmetric_in_argument_order():
    """Which answer came first must not change how bad the contradiction is."""
    a = consistency.compare(fact("team_size", 20), fact("team_size", 45), "bpo_operations")
    b = consistency.compare(fact("team_size", 45), fact("team_size", 20), "bpo_operations")
    assert a.severity is b.severity
    assert a.delta_pct == b.delta_pct


def test_unknown_fact_keys_never_contradict():
    assert consistency.compare(
        fact("made_up", 1), fact("made_up", 100), "bpo_operations"
    ) is None


# ---------------------------------------------------------------------------
# the fact store gate
# ---------------------------------------------------------------------------


def test_only_taxonomy_keys_are_stored():
    """An open key space would let a model invent a key per answer and never
    contradict itself."""
    kept, clashes = consistency.check_new_facts(
        [fact("team_size", 35), fact("vibes", 99), fact("aht_seconds", 400)],
        [],
        response_id="r_1",
        job_family="bpo_operations",
    )
    assert {f.key for f in kept} == {"team_size", "aht_seconds"}
    assert clashes == []


def test_facts_with_no_value_are_dropped():
    kept, _ = consistency.check_new_facts(
        [ExtractedFact(key="team_size", quote="q")], [], response_id="r", job_family="bpo_operations"
    )
    assert kept == []


def test_contradiction_is_raised_against_session_memory():
    kept, clashes = consistency.check_new_facts(
        [fact("team_size", 20)],
        [fact("team_size", 45)],
        response_id="r_9",
        job_family="bpo_operations",
    )
    assert len(clashes) == 1
    assert clashes[0].later_response_id == "r_9"
    assert kept          # the new reading is still stored


# ---------------------------------------------------------------------------
# scoring and the multiplier
# ---------------------------------------------------------------------------


def test_clean_session_scores_100():
    assert consistency.consistency_score([]) == 100
    assert consistency.multiplier(100) == 1.0


def test_penalties_are_published_and_additive():
    minor = consistency.compare(fact("team_size", 35), fact("team_size", 20), "bpo_operations")
    major = consistency.compare(fact("team_size", 45), fact("team_size", 20), "bpo_operations")
    assert consistency.consistency_score([minor]) == 85
    assert consistency.consistency_score([major]) == 60
    assert consistency.consistency_score([minor, major]) == 45


def test_score_is_floored_so_one_slip_cannot_zero_a_candidate():
    major = consistency.compare(fact("team_size", 45), fact("team_size", 20), "bpo_operations")
    assert consistency.consistency_score([major] * 10) == consistency.CONSISTENCY_FLOOR
    assert consistency.multiplier(consistency.CONSISTENCY_FLOOR) == 0.2


def test_summary_reads_like_english():
    major = consistency.compare(fact("team_size", 45), fact("team_size", 20), "bpo_operations")
    assert "1 major" in consistency.summarise([major])
    assert "No contradictions" in consistency.summarise([])
