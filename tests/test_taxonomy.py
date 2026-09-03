"""P1-06 — deterministic family routing.

Developer A owns this file. Family-detection tests live here rather than in
`test_pipeline.py`, which is Developer B's.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from api.taxonomy import GENERAL, FamilyMatch, detect_family, match_family

GOLDEN = json.loads(
    (Path(__file__).parent / "data" / "routing_golden.json").read_text(encoding="utf-8")
)["resumes"]

LABELLED = [r for r in GOLDEN if "family" in r]
AMBIGUOUS = [r for r in GOLDEN if r.get("ambiguous")]

# M5b. Not 100%: a router that scores perfectly on its own golden set has
# usually been tuned until it did.
MIN_ACCURACY = 0.95
# Above this a recruiter is entitled to read the routing as settled.
AMBIGUITY_CEILING = 0.35


def test_routing_accuracy_on_golden_set():
    misses = [
        (r["id"], r["family"], detect_family(r["text"]))
        for r in LABELLED
        if detect_family(r["text"]) != r["family"]
    ]
    accuracy = (len(LABELLED) - len(misses)) / len(LABELLED)
    assert accuracy >= MIN_ACCURACY, f"{accuracy:.1%} — misses: {misses}"


def test_ambiguous_resume_returns_low_confidence():
    """A resume that is genuinely two families must SAY it is uncertain.

    The family it picks is not asserted — for these there is no right answer,
    which is the point. What is asserted is that it lands inside the plausible
    set and does not claim to be sure.
    """
    for r in AMBIGUOUS:
        m = match_family(r["text"])
        assert m.family in r["plausible"], f"{r['id']} routed to {m.family}"
        assert m.confidence <= AMBIGUITY_CEILING, (
            f"{r['id']} claimed {m.confidence:.2f} confidence between "
            f"{r['plausible']} — a close call reported as a certainty"
        )


def test_confident_routing_is_actually_confident():
    """Guardrail against over-correcting the test above: if the ceiling were
    the whole story, a router returning 0.0 always would pass it."""
    m = match_family(
        "Backend engineer. Python and Java services on Kubernetes, deployed to AWS."
    )
    assert m.family == "software_engineering"
    assert m.confidence > AMBIGUITY_CEILING


def test_detection_is_deterministic():
    """Routing is replayable: same text, same taxonomy, same answer, forever.
    No model call, no dict ordering, no clock."""
    text = "Team lead for an inbound voice process. Owned AHT, shrinkage and roster."
    first = match_family(text)
    for _ in range(25):
        again = match_family(text)
        assert again.family == first.family
        assert again.confidence == first.confidence
        assert again.matched_terms == first.matched_terms
        assert again.per_family_scores == first.per_family_scores


@pytest.mark.parametrize(
    "text,wrongly",
    [
        # "hr" inside "through" — one of the most common words in resume prose.
        ("Drove client engagement through structured quarterly reviews.", "hr_recruitment"),
        # "arr" inside "arranged", "deal" inside "dealt".
        ("Arranged vendor contracts and dealt with escalations.", "sales"),
        # "api" inside "rapid" and "capital".
        ("Rapid capital deployment reviewed by the risk committee.", "software_engineering"),
        # "react" inside "reacted".
        ("Reacted quickly to shifting priorities across the team.", "software_engineering"),
    ],
)
def test_keywords_do_not_match_inside_unrelated_words(text, wrongly):
    """The regression P1-06 actually fixes.

    Substring matching routed ordinary English into technical families. IDF does
    not help here — every one of these terms belongs to a single family, so IDF
    scores them as maximally distinctive.
    """
    assert detect_family(text) != wrongly


@pytest.mark.parametrize(
    "text,expected",
    [
        # "recruit" twice is still ONE distinct keyword, so this needs a second
        # one ("sourcing") to clear the two-term floor.
        ("Recruiter owning the recruiting funnel from sourcing onward.", "hr_recruitment"),
        ("Handled recruitment and onboarding for two business units.", "hr_recruitment"),
        ("Triaged tickets and drove escalations to resolution time targets.", "customer_support"),
        ("Owned deployments and API latency for the payments service.", "software_engineering"),
    ],
)
def test_stems_still_match_their_inflections(text, expected):
    """The other half of the boundary fix. The taxonomy stores stems, so
    "recruit" must keep reaching recruiter/recruiting/recruitment. A plain
    `\\b...\\b` would pass the test above and silently break every family."""
    assert detect_family(text) == expected


def test_thin_evidence_routes_to_general():
    """One keyword is a coincidence. "npa" alone does not make a banking
    resume, and guessing from it would put a candidate in front of the wrong
    rubric with no signal that anything was uncertain."""
    m = match_family("Worked on NPA recovery for a finance company.")
    assert m.family == GENERAL
    assert m.confidence == 0.0
    # The terms seen are still reported: "we found npa and nothing else" is
    # more useful to a recruiter than silence.
    assert "npa" in m.matched_terms


def test_family_match_is_the_cross_stream_contract():
    """P1-08b (Developer B) reads `confidence` off this. Changing the shape is
    a conversation, not a solo edit."""
    m = match_family("Built dashboards in Tableau and ETL pipelines with dbt.")
    assert isinstance(m, FamilyMatch)
    assert m._fields == ("family", "confidence", "matched_terms", "per_family_scores")
    assert isinstance(m.family, str)
    assert 0.0 <= m.confidence <= 1.0
    assert isinstance(m.matched_terms, tuple)
    assert set(m.per_family_scores) <= set(
        __import__("api.taxonomy", fromlist=["family_keys"]).family_keys()
    )


def test_routing_never_scores_presentation():
    """Structural. Two resumes with identical evidence and different fluency
    must route identically — routing reads vocabulary, never how well it is
    written."""
    fluent = "I led a team of 42 agents in an inbound voice process, owning AHT and shrinkage."
    plain = "i led team 42 agent inbound voice process. aht and shrinkage was mine."
    assert match_family(fluent).family == match_family(plain).family
