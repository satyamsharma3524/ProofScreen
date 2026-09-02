"""ARTIFACT 1 — the taxonomy has to hold its own invariants or every weight
downstream is wrong."""

from __future__ import annotations

import pytest

from api import taxonomy as t


def test_every_family_claim_weights_sum_to_100():
    for family in t.family_keys():
        total = sum(t.default_claim_weights(family).values())
        assert total == pytest.approx(100.0), f"{family} sums to {total}"


def test_dimension_weights_sum_to_exactly_one_for_every_family():
    """Families override a subset of dimension weights; renormalisation must be
    exact or claim scores inflate in whichever family overrode upward."""
    for family in t.family_keys():
        total = sum(t.dimension_weights(family).values())
        assert total == pytest.approx(1.0, abs=1e-9), f"{family} sums to {total}"


def test_family_overrides_actually_change_the_weights():
    assert t.dimension_weights("bpo_operations") != t.dimension_weights("software_engineering")
    # BPO weights process understanding above the global default.
    assert t.dimension_weights("bpo_operations")["PROCESS"] > t.dimension_weights("general")["PROCESS"]


def test_family_detection():
    assert t.detect_family(
        "Team Lead handling 25 agents, AHT and shrinkage, roster planning, calibration"
    ) == "bpo_operations"
    assert t.detect_family(
        "Backend engineer, p95 latency, kubernetes, kafka, postgres, microservice deploys"
    ) == "software_engineering"
    assert t.detect_family("nothing recognisable here") == "general"


def test_claim_classification():
    assert t.classify_claim("Improved CSAT from 78 to 92", "bpo_operations") == "csat_improvement"
    assert t.classify_claim("Reduced p95 API latency", "software_engineering") == "performance_work"
    assert t.classify_claim("Managed a team of 35 agents", "bpo_operations") == "team_handling"


def test_invented_claim_types_are_reclassified_never_trusted():
    """The model can return anything; only taxonomy keys survive."""
    assert t.normalise_claim_type("bpo_operations", "vibes_management", "Improved CSAT") == "csat_improvement"
    assert t.normalise_claim_type("bpo_operations", "csat_improvement", "x") == "csat_improvement"


def test_fact_stability_split():
    """The distinction the whole consistency engine rests on."""
    assert t.fact_is_stable("bpo_operations", "team_size") is True
    assert t.fact_is_stable("bpo_operations", "csat_pct") is False
    assert t.fact_is_stable("bpo_operations", "not_a_key") is False


def test_unknown_fact_keys_are_rejected():
    assert t.is_known_fact_key("bpo_operations", "aht_seconds") is True
    assert t.is_known_fact_key("bpo_operations", "made_up_metric") is False
