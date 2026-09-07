"""`heuristic_claims()` in inventory mode — recall-first, no ranking.

Legacy mode (`claim_inventory=False`, the suite default) is exercised
incidentally by every other test that goes through the fixture-mode fallback
path and is deliberately not touched here. These tests turn the flag on to
pin the one behaviour docs/EXTRACTION_ARCHITECTURE_REVIEW.md's E3 was written
against: the offline fallback used to drop implementation/integration bullets
outright, not merely rank them low.
"""

import asyncio
import re

from api.config import settings
from api.engine import extract
from api.schemas import ClaimExtraction, ExtractedClaim
from tests.conftest import onboard

SE_RESUME = """
John Doe
Senior Frontend Developer

EXPERIENCE
Optimized platform performance by 40% through architecting the entire
front-end using ReactJS and Redux, cutting load times across the app.
Integrated Twilio's SDK to enable SMS, voice, and WhatsApp communications,
building a robust communication platform that scales with user needs.
Collaborated with backend teams and QA to integrate RESTful APIs across
three services, removing a manual handoff step from every release.
Delivered responsive designs using Material UI and Tailwind CSS across
the customer-facing dashboard and the internal admin console.
Python, SQL, Tableau, Power BI, machine learning, Docker, Kubernetes
"""


def test_inventory_mode_keeps_the_verb_less_integration_bullet(monkeypatch):
    """D2: "Integrated ... SMS, voice, and WhatsApp communications, building
    a robust..." scored -1 under the old rank-and-threshold path -- comma-heavy
    with no recognised verb, so the skills-list rejection fired on an
    achievement. `_is_claim_line` recognises "integrated" and keeps it."""
    monkeypatch.setattr(settings, "claim_inventory", True)
    claims = extract.heuristic_claims(SE_RESUME, "software_engineering")
    texts = [c.text for c in claims]
    assert any("Integrated Twilio" in t for t in texts)


def test_inventory_mode_still_rejects_a_bare_skills_list(monkeypatch):
    """The comma-count rejection still fires when there is genuinely no verb
    and no number -- a real skills list, not an unscored achievement."""
    monkeypatch.setattr(settings, "claim_inventory", True)
    claims = extract.heuristic_claims(SE_RESUME, "software_engineering")
    texts = [c.text for c in claims]
    assert not any("Python, SQL, Tableau" in t for t in texts)


def test_inventory_mode_does_not_drop_a_second_claim_of_the_same_type(monkeypatch):
    """Legacy mode's two-pass type-spread would drop a second `system_ownership`-
    typed bullet in favour of breadth. Inventory mode keeps both -- selection
    is a planning decision, not an extraction one."""
    monkeypatch.setattr(settings, "claim_inventory", True)
    claims = extract.heuristic_claims(SE_RESUME, "software_engineering")
    assert len(claims) >= 4


def test_inventory_mode_preserves_resume_order_not_score_order(monkeypatch):
    """Recall-first extraction has nothing to rank for; `Claim.order_index`
    should still mean "where this appeared on the page", not "how it scored"."""
    monkeypatch.setattr(settings, "claim_inventory", True)
    claims = extract.heuristic_claims(SE_RESUME, "software_engineering")
    texts = [c.text for c in claims]
    positions = {i: t for i, t in enumerate(texts)}
    optimized_idx = next(i for i, t in positions.items() if t.startswith("Optimized platform"))
    integrated_idx = next(i for i, t in positions.items() if t.startswith("Integrated Twilio"))
    delivered_idx = next(i for i, t in positions.items() if t.startswith("Delivered responsive"))
    assert optimized_idx < integrated_idx < delivered_idx


def _capturing_stub(claims: list[ExtractedClaim]):
    """A fake `complete_json` that records the rendered prompt and returns a
    fixed claim list, regardless of the schema requested -- fine here because
    `job_family` is always supplied explicitly below, so `classify_role`
    (which asks for a different schema) is never on the call path (rung 1 of
    the routing precedence in `extract_claims`)."""
    captured: dict[str, str] = {}

    async def complete_json(prompt, model, **kwargs):
        captured["prompt"] = prompt
        return ClaimExtraction(job_family="software_engineering", claims=claims)

    return complete_json, captured


def test_inventory_mode_prompt_never_asks_for_a_claim_type(monkeypatch):
    """Phase 1: discovery is family-agnostic. The model is not shown the
    per-family CLAIM TYPES menu, not told to assign one, and the worked JSON
    example carries no `claim_type` key -- typing happens entirely after the
    fact via `normalise_claim_type`/`classify_claim` (extract.py:577,
    unchanged)."""
    monkeypatch.setattr(settings, "claim_inventory", True)
    stub, captured = _capturing_stub(
        [ExtractedClaim(text="Built a thing that did a thing for real.",
                         claim_type=None, verifiable=True)]
    )
    monkeypatch.setattr(extract, "complete_json", stub)
    asyncio.run(extract.extract_claims(SE_RESUME, job_family="software_engineering"))
    prompt = captured["prompt"]
    assert "claim_type" not in prompt
    assert "CLAIM TYPES" not in prompt


def test_legacy_mode_prompt_still_asks_for_a_claim_type(monkeypatch):
    """Legacy mode is untouched: the per-family menu, the labelling
    instruction and the JSON example's `claim_type` key all still render
    exactly as before."""
    assert settings.claim_inventory is False
    stub, captured = _capturing_stub(
        [ExtractedClaim(text="Built a thing that did a thing for real.",
                         claim_type=None, verifiable=True)]
    )
    monkeypatch.setattr(extract, "complete_json", stub)
    asyncio.run(extract.extract_claims(SE_RESUME, job_family="software_engineering"))
    prompt = captured["prompt"]
    assert "CLAIM TYPES for the family you picked" in prompt
    assert '"claim_type": "string"' in prompt


def test_inventory_mode_prompt_carries_no_numeric_cap(monkeypatch):
    """The prompt-side half of the fix: in inventory mode the model is never
    told a number at all, not even as a soft ceiling."""
    monkeypatch.setattr(settings, "claim_inventory", True)
    stub, captured = _capturing_stub(
        [ExtractedClaim(text="Built a thing that did a thing for real.",
                         claim_type=None, verifiable=True)]
    )
    monkeypatch.setattr(extract, "complete_json", stub)
    asyncio.run(extract.extract_claims(SE_RESUME, job_family="software_engineering"))
    prompt = captured["prompt"]
    assert "no fixed number" in prompt
    assert not re.search(r"\bStop at \d+\b", prompt)


def test_legacy_mode_prompt_still_carries_a_numeric_cap(monkeypatch):
    """Legacy mode (the suite default) is untouched: the model is still told
    a stop count, exactly as it was before this change."""
    assert settings.claim_inventory is False
    stub, captured = _capturing_stub(
        [ExtractedClaim(text="Built a thing that did a thing for real.",
                         claim_type=None, verifiable=True)]
    )
    monkeypatch.setattr(extract, "complete_json", stub)
    asyncio.run(extract.extract_claims(SE_RESUME, job_family="software_engineering"))
    assert re.search(r"\bStop at \d+\b", captured["prompt"])


def test_inventory_mode_python_ceiling_does_not_truncate_a_real_inventory(monkeypatch):
    """The defect the prompt fix alone would not have caught: a Python-side
    top-N of 12 would silently reproduce the same cap even with no number in
    the prompt. 17 (measured real-resume saturation,
    docs/EXTRACTION_ARCHITECTURE_REVIEW.md D1) must all survive."""
    monkeypatch.setattr(settings, "claim_inventory", True)
    many = [
        ExtractedClaim(text=f"Built and shipped feature number {i} end to end for real.",
                        claim_type=None, verifiable=True)
        for i in range(17)
    ]
    stub, _ = _capturing_stub(many)
    monkeypatch.setattr(extract, "complete_json", stub)
    _, kept, _ = asyncio.run(extract.extract_claims(SE_RESUME, job_family="software_engineering"))
    assert len(kept) == 17


def test_inventory_mode_python_ceiling_still_bites_on_a_runaway_reply(monkeypatch):
    """Not "nowhere": one backstop remains for a pathological reply, logged
    rather than silent (docs/EXTRACTION_ARCHITECTURE_REVIEW.md D1/E1)."""
    monkeypatch.setattr(settings, "claim_inventory", True)
    monkeypatch.setattr(settings, "max_inventory_claims", 5)
    many = [
        ExtractedClaim(text=f"Built and shipped feature number {i} end to end for real.",
                        claim_type=None, verifiable=True)
        for i in range(9)
    ]
    stub, _ = _capturing_stub(many)
    monkeypatch.setattr(extract, "complete_json", stub)
    _, kept, _ = asyncio.run(extract.extract_claims(SE_RESUME, job_family="software_engineering"))
    assert len(kept) == 5


def test_legacy_mode_is_unchanged_by_the_new_predicate(monkeypatch):
    """`claim_inventory=False` (the suite default) must reproduce the
    pre-inventory heuristic path exactly: score, rank, spread across types,
    cap at `settings.max_claims`."""
    assert settings.claim_inventory is False
    claims = extract.heuristic_claims(SE_RESUME, "software_engineering")
    assert len(claims) <= settings.max_claims
    texts = [c.text for c in claims]
    assert not any("Python, SQL, Tableau" in t for t in texts)


def test_a_claim_type_of_none_is_typed_by_classify_claim_not_the_literal_delivery(
    client, monkeypatch
):
    """Required regression test: with Phase 1 landed, a model response with no
    `claim_type` at all becomes the normal case in inventory mode, not the rare
    one. `orchestrator.py:774` (`claim_type=item.claim_type or "delivery"`) is
    a literal, non-family-aware fallback -- it is dead code today only because
    `normalise_claim_type` (extract.py:577) already resolves every claim
    before `extract_claims()` returns. This drives a claim with
    `claim_type=None` all the way through the real `/api/candidates/text`
    endpoint and asserts the PERSISTED type is the family-aware
    `classify_claim()` answer, not the orchestrator's literal fallback --
    picking resume text whose keywords deterministically classify as
    `reliability` in `software_engineering`, which is neither `delivery` (the
    literal fallback) nor `system_ownership` (the family's heaviest type, what
    a *type-blind* fallback would produce), so a regression to either wrong
    path is caught.
    """
    from api.taxonomy import classify_claim

    text = "Owned on-call rotations and cut incident response time during outages."
    expected_type = classify_claim(text, "software_engineering")
    assert expected_type == "reliability"
    assert expected_type != "delivery"

    stub, _ = _capturing_stub(
        [ExtractedClaim(text=text, claim_type=None, verifiable=True)]
    )
    monkeypatch.setattr(extract, "complete_json", stub)

    body = onboard(
        client,
        name="Claim Type None Regression",
        phone="+919810080099",
        job_family="software_engineering",
    )
    claim_types = [c["claim_type"] for c in body["claims"]]
    assert claim_types == [expected_type]
    assert "delivery" not in claim_types
