"""P1-06 — deterministic family routing.

Developer A owns this file. Family-detection tests live here rather than in
`test_pipeline.py`, which is Developer B's.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from api.engine import extract
from api.schemas import ClaimExtraction, ExtractedClaim
from api.taxonomy import (
    GENERAL,
    MARGIN_FLOOR,
    FamilyMatch,
    classify_claim,
    detect_family,
    is_low_confidence,
    match_family,
)

GOLDEN = json.loads(
    (Path(__file__).parent / "data" / "routing_golden.json").read_text(encoding="utf-8")
)["resumes"]

LABELLED = [r for r in GOLDEN if "family" in r]
AMBIGUOUS = [r for r in GOLDEN if r.get("ambiguous")]

# M5b. Not 100%: a router that scores perfectly on its own golden set has
# usually been tuned until it did.
MIN_ACCURACY = 0.95
# Above this a recruiter is entitled to read the routing as settled. It lived
# here as a local literal until P1-06a promoted it into `taxonomy.py`; the tests
# now assert against the same constant the API and the report read, so the three
# cannot drift apart.
AMBIGUITY_CEILING = MARGIN_FLOOR


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
        # y -> ies replaces the stem's y rather than following it, so it cannot
        # live in the suffix group: "story" + "ies" is not a word.
        ("Wrote user stories and ran discovery for the checkout roadmap.", "product"),
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


# ---------------------------------------------------------------------------
# P1-07 — routing precedence. Requisition > detection. The model has no vote.
# ---------------------------------------------------------------------------

SE_RESUME = (
    "Backend engineer. Built REST APIs in Python on Postgres, deployed to "
    "Kubernetes on AWS, and cut p95 latency from 900ms to 180ms."
)


def _stub_model(job_family: str):
    """A model that confidently returns the wrong family."""

    async def complete_json(prompt, model, **kwargs):
        return ClaimExtraction(
            job_family=job_family,
            claims=[
                ExtractedClaim(
                    text="Cut p95 latency from 900ms to 180ms on the checkout service.",
                    claim_type=None,
                    verifiable=True,
                )
            ],
        )

    return complete_json


def test_supplied_family_always_wins(monkeypatch):
    """The requisition is a fact about the JOB. Detection is an inference about
    the candidate, and the model's opinion is neither. A recruiter hiring for
    support gets the support rubric even when the resume reads like engineering
    — otherwise the score answers a question nobody asked."""
    monkeypatch.setattr(extract, "complete_json", _stub_model("sales"))
    family, _ = asyncio.run(
        extract.extract_claims(SE_RESUME, job_family="customer_support")
    )
    assert family == "customer_support"


def test_model_cannot_override_detected_family(monkeypatch):
    """Closes the deviation logged in docs/ARCHITECTURE_LOCK_v1.md §2.

    extract.py used to accept the model's family whenever it resolved to a real
    one, which made routing non-deterministic: the same resume could land in two
    different rubrics on two runs, and nothing recorded that it had happened.
    """
    # ROLE_CLASSIFIER now defaults true, and `_stub_model` answers every
    # complete_json call with a ClaimExtraction -- including the classifier's,
    # which reads `.family`. This test is about rung 3 (keyword detection vs
    # the model's opinion), so the classifier is pinned off rather than stubbed.
    monkeypatch.setattr(settings, "role_classifier", False)
    monkeypatch.setattr(extract, "complete_json", _stub_model("hr_recruitment"))
    family, _ = asyncio.run(extract.extract_claims(SE_RESUME))
    assert family == "software_engineering" == detect_family(SE_RESUME)


def test_routing_is_stable_across_disagreeing_model_runs(monkeypatch):
    """Two runs over one resume route identically however the model wanders —
    the acceptance criterion for P1-07."""
    # ROLE_CLASSIFIER now defaults true, and `_stub_model` answers every
    # complete_json call with a ClaimExtraction -- including the classifier's,
    # which reads `.family`. This test is about rung 3 (keyword detection vs
    # the model's opinion), so the classifier is pinned off rather than stubbed.
    monkeypatch.setattr(settings, "role_classifier", False)
    seen = set()
    for proposal in ("sales", "banking_operations", "general", None):
        monkeypatch.setattr(extract, "complete_json", _stub_model(proposal))
        family, _ = asyncio.run(extract.extract_claims(SE_RESUME))
        seen.add(family)
    assert seen == {"software_engineering"}


# ---------------------------------------------------------------------------
# P1-08a — GET /api/dev/detect. Routing has to be explainable without a token.
# ---------------------------------------------------------------------------

PRODUCT_RESUME = (
    "Product manager for a payments app. Owned the roadmap and ran a/b tests, "
    "lifting activation from 34% to 46%."
)


def test_detect_endpoint_explains_without_a_model_call(client):
    """The acceptance criterion: terms hit, per-family scores and the margin,
    with no model call. Routing is a pure function, so this holds by
    construction — the assertion exists to keep it that way."""
    before = client.get("/api/dev/llm").json()["calls"]

    body = client.get("/api/dev/detect", params={"text": PRODUCT_RESUME}).json()

    assert client.get("/api/dev/llm").json()["calls"] == before

    assert body["family"] == "product"
    assert body["matched_terms"], "a routed resume must show the terms that routed it"
    assert body["per_family_scores"]["product"] > 0
    assert 0.0 <= body["confidence"] <= 1.0


def test_detect_names_the_family_the_margin_is_measured_against(client):
    """`confidence` is meaningless without knowing what it is a margin over.
    Reporting 0.03 without naming the runner-up tells a recruiter a decision was
    close but not what it was close to."""
    body = client.get("/api/dev/detect", params={"text": PRODUCT_RESUME}).json()
    assert body["runner_up"] is not None
    assert body["runner_up"] != body["family"]
    assert body["rejected_leader"] is None
    assert body["confidence_is"].startswith("margin")


def test_detect_explains_a_general_route(client):
    """GENERAL has to explain itself too. "We saw npa and nothing else, and the
    floor is two terms" is actionable; an empty result is not."""
    body = client.get(
        "/api/dev/detect", params={"text": "Worked on NPA recovery for a finance company."}
    ).json()
    assert body["family"] == GENERAL
    assert body["confidence"] == 0.0
    assert body["min_terms_required"] == 2
    assert body["matched_terms"] == ["npa"]
    # Two different zeros reach this endpoint. GENERAL's is the floor, not a
    # tie, and the leading family was REJECTED rather than narrowly beaten —
    # calling it a runner-up would misdescribe the one case someone is most
    # likely to be investigating.
    assert body["runner_up"] is None
    assert body["rejected_leader"] == "banking_operations"
    assert "floor" in body["confidence_is"]


def test_detect_rejects_empty_text(client):
    assert client.get("/api/dev/detect", params={"text": ""}).status_code == 422


def test_detect_is_hidden_when_dev_endpoints_are_off(client, monkeypatch):
    """It exposes how routing works and takes arbitrary text. It belongs behind
    the same flag as the rest of /api/dev, not open on a deployed instance."""
    from api.config import settings

    monkeypatch.setattr(settings, "enable_dev_endpoints", False)
    assert (
        client.get("/api/dev/detect", params={"text": PRODUCT_RESUME}).status_code == 404
    )


def test_routing_never_scores_presentation():
    """Structural. Two resumes with identical evidence and different fluency
    must route identically — routing reads vocabulary, never how well it is
    written."""
    fluent = "I led a team of 42 agents in an inbound voice process, owning AHT and shrinkage."
    plain = "i led team 42 agent inbound voice process. aht and shrinkage was mine."
    assert match_family(fluent).family == match_family(plain).family


# ---------------------------------------------------------------------------
# P1-06a — the low-confidence flag D2 specified and P1-06 did not ship
# ---------------------------------------------------------------------------


def test_every_ambiguous_resume_is_flagged_low_confidence():
    """The acceptance criterion in PHASE_1_EXECUTION_PLAN 5: an ambiguous resume
    returns low confidence rather than a confident wrong answer, and the low
    confidence is visible. Asserted over the whole ambiguous set, not one case,
    because one is an anecdote."""
    for r in AMBIGUOUS:
        m = match_family(r["text"])
        assert is_low_confidence(m), (
            f"{r['id']} routed to {m.family} at {m.confidence:.3f} and was NOT "
            f"flagged — a genuinely two-family resume presented as settled"
        )


def test_no_confident_route_is_flagged_low_confidence():
    """The other half, and the one that makes the first meaningful: a floor set
    too high would flag everything and pass the test above while destroying the
    signal. Measured band on this set — confident routes bottom out at 0.397,
    ambiguous ones top out at 0.321."""
    misflagged = [
        (r["id"], round(match_family(r["text"]).confidence, 3))
        for r in LABELLED
        if r["family"] != GENERAL
        and match_family(r["text"]).family == r["family"]
        and is_low_confidence(match_family(r["text"]))
    ]
    assert not misflagged, f"correct routes flagged as uncertain: {misflagged}"


def test_the_flag_does_not_change_routing():
    """P1-06a ships the FLAG, not the demotion D2 also described. Every labelled
    resume must route exactly where it routed before the constant existed —
    an under-route to GENERAL strips the family's claim types and weights, and
    is not the safe direction."""
    for r in LABELLED:
        m = match_family(r["text"])
        if is_low_confidence(m) and m.family != GENERAL:
            assert m.family == r["family"], (
                f"{r['id']} is flagged but still routed to {m.family}; if this "
                f"ever becomes a demotion, this assertion is where it shows"
            )
    # The constant is a classifier over `confidence`, so it cannot move
    # `family` at all. Pinned structurally rather than by inspection.
    m = match_family("Worked on NPA recovery for a finance company.")
    assert m.family == GENERAL and is_low_confidence(m)


def test_detect_endpoint_surfaces_the_flag_and_the_floor(client):
    """Visible in the API response, per the acceptance criterion — and it
    publishes the floor beside the flag, so nobody has to guess which line a
    0.30 fell on the wrong side of."""
    ambiguous = next(r for r in AMBIGUOUS)
    body = client.get("/api/dev/detect", params={"text": ambiguous["text"]}).json()
    assert body["low_confidence"] is True
    assert body["margin_floor"] == MARGIN_FLOOR

    confident = client.get("/api/dev/detect", params={"text": PRODUCT_RESUME}).json()
    assert confident["low_confidence"] is False



# ---------------------------------------------------------------------------
# role classification — the LLM rung above the keyword scorer
#
# Every test here is deterministic and makes NO model call. The classifier's
# accuracy is measured outside the suite, against real resumes, and recorded in
# docs/ROLE_ROUTING_PROPOSAL.md; a suite that asserted on model output would be
# asserting on the weather.
# ---------------------------------------------------------------------------

import asyncio  # noqa: E402

from api.config import settings  # noqa: E402
from api.engine.extract import (  # noqa: E402
    classify_role,
    extract_claims,
    header_slice,
)

_PM_RESUME = """Arshad Latif Saikia
arshad@example.com | +91-9678463786

PROFESSIONAL SUMMARY
Product leader delivering strategic impact across Product, Experience and Design.

Product Lead - Pync (Lifestyle Services Platform)
Apr 2025 - Present | Bangalore, India
- Scaled platform to 10,000 DAU in 6 months, driving 125% conversion improvement.
- Scaled revenue to 40 Lakhs in 6 months through targeted acquisition.

Sales & Analytics - ExxonMobil
Jul 2017 - Aug 2021 | Mumbai, India
- Managed B2B accounts with $40M yearly revenue, ensuring 20% margin growth.
- Closed 4 new rebate contracts securing $7.8M in new business.

CORE SKILLS
Product Strategy | GTM Strategy | Cross-functional Leadership
"""


def test_header_slice_keeps_the_titles_and_drops_the_achievement_bullets():
    """The bullets are where revenue/pipeline/conversion live, and that
    vocabulary is exactly what routes a PM to sales. Excluding it is the fix."""
    sliced = header_slice(_PM_RESUME)

    assert "Product Lead - Pync" in sliced
    assert "Sales & Analytics - ExxonMobil" in sliced
    assert "Product leader delivering strategic impact" in sliced

    for bullet_term in ("10,000 DAU", "125% conversion", "$40M yearly revenue",
                        "$7.8M in new business", "20% margin growth"):
        assert bullet_term not in sliced, f"achievement bullet leaked: {bullet_term}"


def test_header_slice_of_a_resume_with_no_titles_is_too_thin_to_route_on():
    """A file with a career objective and no job title -- a real shape in the
    Shine corpus. There is nothing here a recruiter could route on either."""
    from api.engine.extract import MIN_HEADER_CHARS

    assert len(header_slice("")) < MIN_HEADER_CHARS
    assert len(header_slice("   \n\n  \n")) < MIN_HEADER_CHARS


def test_header_slice_is_bounded():
    assert len(header_slice(_PM_RESUME * 40)) <= 1800


def test_the_classifier_is_a_no_op_while_the_flag_is_off(monkeypatch):
    """ROLE_CLASSIFIER=false must reproduce prior routing exactly -- it is the
    rollback lever, so it has to be a true no-op and not merely a quiet one."""
    monkeypatch.setattr(settings, "role_classifier", False)
    assert asyncio.run(classify_role(_PM_RESUME, "sales")) == "sales"


def test_a_thin_header_keeps_the_taxonomy_answer(monkeypatch):
    monkeypatch.setattr(settings, "role_classifier", True)
    assert asyncio.run(classify_role("", "bpo_operations")) == "bpo_operations"


def test_fixture_mode_routes_exactly_as_the_taxonomy_does(monkeypatch):
    """No key means complete_json serves the fallback, and the fallback IS the
    taxonomy answer. The whole suite therefore routes as it did before."""
    monkeypatch.setattr(settings, "role_classifier", True)
    monkeypatch.setattr(settings, "openai_api_key", None)
    for family in ("sales", "product", "software_engineering", "general"):
        assert asyncio.run(classify_role(_PM_RESUME, family)) == family


def test_a_requisition_family_outranks_the_classifier(monkeypatch):
    """P1-07 rung 1 is unchanged and still absolute. If this breaks, a recruiter
    hiring for support stops getting the support rubric."""
    monkeypatch.setattr(settings, "role_classifier", True)
    called = False

    async def _never(*args, **kwargs):
        nonlocal called
        called = True
        return "product"

    monkeypatch.setattr("api.engine.extract.classify_role", _never)
    family, _claims = asyncio.run(
        extract_claims(_PM_RESUME, job_family="customer_support")
    )
    assert family == "customer_support"
    assert not called, "rung 1 must short-circuit before the model is consulted"


def test_a_family_the_model_invents_becomes_general(monkeypatch):
    """resolve_family() is the guard. A hallucinated key must not reach
    claim_type_menu(), which would hand the extractor an empty menu."""
    from api.engine import extract as extract_module

    monkeypatch.setattr(settings, "role_classifier", True)

    async def _hallucinate(*args, **kwargs):
        return extract_module.RoleClassification(family="astronaut")

    monkeypatch.setattr(extract_module, "complete_json", _hallucinate)
    assert asyncio.run(classify_role(_PM_RESUME, "sales")) == "general"


def test_the_classifier_confidence_is_never_branched_on():
    """CLAUDE.md rule 1: no rating, confidence or percentage parsed out of a
    model response may drive a decision. The classifier RECORDS confidence and
    seniority for later analysis, and routing must never read them.

    Structural, like test_scoring_modules_never_import_the_llm -- a comment
    saying 'we do not branch on this' is not a guarantee.
    """
    import ast
    import pathlib as _pathlib

    tree = ast.parse(_pathlib.Path("api/engine/extract.py").read_text())
    offenders = []

    for node in ast.walk(tree):
        # `x.confidence > 0.8`, `x.seniority == "senior"`
        if isinstance(node, ast.Compare):
            for operand in [node.left, *node.comparators]:
                if isinstance(operand, ast.Attribute) and operand.attr in (
                    "confidence", "seniority"
                ):
                    offenders.append(ast.unparse(node))
        # `if x.confidence:` / `if not x.confidence:`
        if isinstance(node, ast.If) and isinstance(node.test, ast.Attribute):
            if node.test.attr in ("confidence", "seniority"):
                offenders.append(ast.unparse(node.test))

    assert not offenders, (
        "routing branched on a model-reported confidence or seniority: "
        f"{offenders}"
    )


# ---------------------------------------------------------------------------
# software_engineering claim-type keyword coverage (taxonomy Phase 2, C1)
#
# docs/EXTRACTION_ARCHITECTURE_REVIEW.md's fallback-collapse measurement found
# `delivery` and `performance_work` missing their own name-verb: a claim
# literally saying "Delivered..." or "...performance issues" fell all the way
# through to `fallback_claim_type`'s heaviest type (`system_ownership`)
# instead of the type it names. These are regression tests against real
# claim text measured on the traced resumes, not synthetic examples.
# ---------------------------------------------------------------------------


def test_delivery_recognises_its_own_name_verb():
    assert classify_claim(
        "Delivered responsive designs using Material UI and Tailwind CSS.",
        "software_engineering",
    ) == "delivery"
    assert classify_claim(
        "Deployment of components in CloudFoundry environment using NodeJS.",
        "software_engineering",
    ) == "delivery"


def test_performance_work_recognises_its_own_name():
    assert classify_claim(
        "Collaborate with DBAs to troubleshoot performance issues.",
        "software_engineering",
    ) == "performance_work"
    assert classify_claim(
        "Drove a 40% performance boost and a 35% increase in user engagement.",
        "software_engineering",
    ) == "performance_work"


# ---------------------------------------------------------------------------
# tech_depth (C2): 0% hit rate on both traced resumes before this fix,
# despite one resume's stack being entirely Spring/Hibernate/OAuth/JWT and
# the other's being React/Redux/TypeScript. `tech_depth` is also the only
# software_engineering type whose probe_focus (TOOL_FAMILIARITY, SPECIFICITY)
# no other type carries -- at 0% those two interview dimensions were
# unreachable for this family regardless of what a candidate actually did.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Design scalable, maintainable, and secure microservices architecture using Spring Boot.",
        "Used Hibernate to write CRUD operations for retrieving and updating data.",
        "Implementing OAuth token and JWT request handling for authentication flows.",
        "Wrote Junit tests to cover the payment reconciliation flow.",
        "Wrote the checkout flow in TypeScript across the whole application.",
        "Design and development of Microservices using REST API and swagger.",
        "Authentication was handled by Node and React JS.",
    ],
)
def test_tech_depth_recognises_the_mainstream_stack(text):
    assert classify_claim(text, "software_engineering") == "tech_depth"


def test_a_measured_tie_resolves_to_the_other_new_keyword_not_tech_depth():
    """Not every added keyword wins its claim outright. This exact sentence,
    from the traced Sathiya resume, ties `hibernate` (tech_depth) against
    `performance` (performance_work, shipped in the prior commit) 1-1;
    `classify_claim`'s tie-break returns the first type in `claim_types()`'s
    iteration order, and `performance_work` precedes `tech_depth` there. Both
    answers are defensible for this claim -- pinned so a future keyword edit
    that shifts this outcome is a deliberate decision, not a silent one."""
    assert classify_claim(
        "Responsible for hibernate-mapping and involved in performance of code.",
        "software_engineering",
    ) == "performance_work"


def test_bare_react_is_not_a_keyword():
    """`react` was deliberately shipped as the two-word phrase "react js", not
    bare "react": the shared inflection suffixes (`ed`, `ing`) mean a bare
    "react" keyword would also match "reacted"/"reacting" as an ordinary
    English verb, with no relation to the framework
    (docs/CLASSIFICATION_PHASE2_REVIEW.md). This pins the negative case so a
    future edit can't silently reintroduce the bare form."""
    assert classify_claim(
        "Reacted quickly and calmly during the sprint planning meeting.",
        "software_engineering",
    ) != "tech_depth"
