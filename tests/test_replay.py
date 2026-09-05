"""
D8 — deterministic replay.

The contract under test is narrower than the word "replay", and the narrowing
is the deliverable: *extraction is recorded; everything downstream of
extraction is replayable.* These tests hold that line from both sides — they
prove the downstream half really does reproduce, and they prove the upstream
half is never attempted.

The most important test in the file is the last kind: missing historical state
must fail loudly. A replay that scores what happens to be there produces a
confident lower number caused by absent data, which is worse than no replay at
all.
"""

from __future__ import annotations

import asyncio
import inspect

import pytest
from sqlalchemy import select

from api import llm
from api.db import SessionLocal
from api.engine import replay as replay_module
from api.models import Claim, ClaimScore, Evaluation, Question, Response
from tests.conftest import onboard, run_interview


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def interviewed(client, name: str, phone: str) -> dict:
    body = onboard(client, name=name, phone=phone)
    run_interview(client, body["session_id"])
    rows = client.get(
        f"/api/recruiter/candidates/{body['candidate_id']}/evaluations"
    ).json()
    return {**body, "evaluation_id": rows[0]["id"]}


def replay(client, evaluation_id: str):
    return client.post(f"/api/dev/replay/{evaluation_id}")


@pytest.fixture(scope="module")
def subject(client) -> dict:
    return interviewed(client, "Replay Subject", "+919810070001")


# ---------------------------------------------------------------------------
# it reproduces
# ---------------------------------------------------------------------------


def test_replay_reproduces_the_finalized_result_exactly(client, subject):
    """Acceptance criterion 1 of the phase plan, and the whole point."""
    body = replay(client, subject["evaluation_id"]).json()
    assert body["status"] == "MATCH", body["differences"]
    assert body["differences"] == []
    assert body["claims_replayed"] >= 1
    assert body["answers_replayed"] >= 1
    assert body["evaluation_id"] == subject["evaluation_id"]


def test_replay_is_stable_across_repeated_executions(client, subject):
    """Determinism means the same answer every time, not the right answer
    once. Three runs, and the differences list must stay empty each time."""
    results = [replay(client, subject["evaluation_id"]).json() for _ in range(3)]
    assert {r["status"] for r in results} == {"MATCH"}
    assert all(r["differences"] == [] for r in results)
    assert len({r["claims_replayed"] for r in results}) == 1
    assert len({r["answers_replayed"] for r in results}) == 1


def test_replay_reproduces_every_claim_score_not_just_the_headline(client):
    """A headline that matches while a claim underneath moved would be two
    errors cancelling. The diff covers each claim by id."""
    subject = interviewed(client, "Per Claim Replay", "+919810070002")
    body = replay(client, subject["evaluation_id"]).json()
    assert body["status"] == "MATCH"

    async def scenario():
        async with SessionLocal() as db:
            claims = (
                await db.execute(
                    select(Claim).where(
                        Claim.candidate_id == subject["candidate_id"]
                    )
                )
            ).scalars().all()
            scores = (
                await db.execute(
                    select(ClaimScore).where(
                        ClaimScore.claim_id.in_([c.id for c in claims])
                    )
                )
            ).scalars().all()
            return len(scores)

    assert asyncio.run(scenario()) >= 1


# ---------------------------------------------------------------------------
# it makes no model call
# ---------------------------------------------------------------------------


def test_replay_never_imports_the_llm():
    """Structural, in the style of `test_scoring_modules_never_import_the_llm`.

    The module-level import list is what a reviewer reads. `api.llm` is
    imported INSIDE the function purely to read its call counter, which is why
    the assertion below is about module scope rather than the whole file.
    """
    tree = inspect.getsource(replay_module)
    module_ast = __import__("ast").parse(tree)
    top_level_imports: list[str] = []
    for node in module_ast.body:
        if isinstance(node, __import__("ast").ImportFrom):
            top_level_imports.append(node.module or "")
        elif isinstance(node, __import__("ast").Import):
            top_level_imports.extend(a.name for a in node.names)
    assert not any("llm" in name for name in top_level_imports)
    assert not any("openai" in name.lower() for name in top_level_imports)
    assert "engine.evidence" not in " ".join(top_level_imports)


def test_replay_performs_zero_llm_calls(client, subject):
    """The counter, before and after. Asserted on the response too, so a
    future refactor that started calling the model shows up in the payload a
    support engineer is reading."""
    before = client.get("/api/dev/llm").json()
    body = replay(client, subject["evaluation_id"]).json()
    after = client.get("/api/dev/llm").json()

    assert body["llm_calls"] == 0
    assert after["calls"] == before["calls"]
    assert after["fallbacks"] == before["fallbacks"], (
        "replay reached the fixture fallback, which means it tried to extract"
    )


def test_replay_works_with_the_model_wrapper_poisoned(client, monkeypatch):
    """The strongest version of the claim: make every path into the provider
    raise, then replay anyway."""
    subject = interviewed(client, "Poisoned Wrapper", "+919810070003")

    async def explode(*args, **kwargs):
        raise AssertionError("replay called the model")

    def explode_sync(*args, **kwargs):
        raise AssertionError("replay built a model client")

    monkeypatch.setattr(llm, "complete_json", explode)
    monkeypatch.setattr(llm, "_raw_completion", explode)
    monkeypatch.setattr(llm, "_get_client", explode_sync)

    body = replay(client, subject["evaluation_id"]).json()
    assert body["status"] == "MATCH"
    assert body["llm_calls"] == 0


# ---------------------------------------------------------------------------
# it detects a real change
# ---------------------------------------------------------------------------


def test_mutating_a_deterministic_input_causes_a_detectable_mismatch(client):
    """The test that proves MATCH means something.

    Blanks the stored signals for EVERY answer about one claim — the exact
    input replay is defined over. One answer is not enough and that is a real
    property of the engine, not a weakness of the test: `score_claim` runs the
    rubric over the UNION of a claim's answers, so removing one of several
    overlapping contributions can legitimately change nothing. Removing all of
    them cannot.

    Without this test, a replay that always returned MATCH would pass every
    other test in this file.
    """
    subject = interviewed(client, "Mismatch Detection", "+919810070004")
    assert replay(client, subject["evaluation_id"]).json()["status"] == "MATCH"

    async def blank_one_claim():
        async with SessionLocal() as db:
            rows = (
                await db.execute(
                    select(Question, Response)
                    .join(Response, Response.question_id == Question.id)
                    .where(Question.session_id == subject["session_id"])
                )
            ).all()
            scored = [
                (q, r) for q, r in rows if (r.signals_json or "").count("quote") > 1
            ]
            assert scored, "the interview produced no signals to remove"
            claim_id = scored[0][0].claim_id
            touched = []
            for question, response in rows:
                if question.claim_id == claim_id:
                    touched.append((response.id, response.signals_json))
                    response.signals_json = "{}"      # valid, empty AnswerSignals
            await db.commit()
            return claim_id, touched

    claim_id, touched = asyncio.run(blank_one_claim())
    try:
        body = replay(client, subject["evaluation_id"]).json()
        assert body["status"] == "MISMATCH", body
        moved = {d["field"] for d in body["differences"]}
        assert f"claim.{claim_id}.score" in moved, moved
        assert "No provenance input moved" in body["note"], (
            "the note should say the difference is not explained by a version change"
        )
        replayed = next(
            d for d in body["differences"] if d["field"] == f"claim.{claim_id}.score"
        )
        assert int(replayed["replayed"]) < int(replayed["stored"])
    finally:
        async def restore():
            async with SessionLocal() as db:
                for response_id, original in touched:
                    row = await db.get(Response, response_id)
                    row.signals_json = original
                await db.commit()

        asyncio.run(restore())

    assert replay(client, subject["evaluation_id"]).json()["status"] == "MATCH"


def test_a_version_change_is_reported_as_drift(client, subject, monkeypatch):
    """Drift is reported whether or not the numbers moved: it is the
    explanation for a MISMATCH and the reassurance behind a MATCH."""
    from api.engine import provenance as pv

    monkeypatch.setattr(pv, "APP_VERSION", "9.9.9")
    body = replay(client, subject["evaluation_id"]).json()
    drift = {d["field"]: (d["stored"], d["replayed"]) for d in body["provenance_drift"]}
    assert drift["app_version"][1] == "9.9.9"
    # An app version bump alone changes no arithmetic, so the result still
    # matches. Drift and mismatch are separate facts.
    assert body["status"] == "MATCH"


# ---------------------------------------------------------------------------
# it never mutates
# ---------------------------------------------------------------------------


def test_replay_does_not_mutate_the_finalized_evaluation(client, subject):
    """Column by column, before and after. Not a spot check: the whole row."""
    async def snapshot():
        async with SessionLocal() as db:
            row = await db.get(Evaluation, subject["evaluation_id"])
            db.expunge_all()
            return {c.name: getattr(row, c.name) for c in Evaluation.__table__.columns}

    before = asyncio.run(snapshot())
    for _ in range(3):
        assert replay(client, subject["evaluation_id"]).status_code == 200
    assert asyncio.run(snapshot()) == before


def test_replay_does_not_overwrite_historical_scores(client, subject):
    """`claim_scores` is what the recruiter's drill-down reads. Replay
    recomputes those numbers in memory and must not write them back — a replay
    that "fixed" a historical score would destroy the evidence of the drift it
    was run to investigate."""
    async def claim_scores():
        async with SessionLocal() as db:
            claims = (
                await db.execute(
                    select(Claim).where(
                        Claim.candidate_id == subject["candidate_id"]
                    )
                )
            ).scalars().all()
            rows = (
                await db.execute(
                    select(ClaimScore).where(
                        ClaimScore.claim_id.in_([c.id for c in claims])
                    )
                )
            ).scalars().all()
            return {r.claim_id: (r.score, r.dimensions_json, r.computed_at) for r in rows}

    before = asyncio.run(claim_scores())
    replay(client, subject["evaluation_id"])
    assert asyncio.run(claim_scores()) == before


# ---------------------------------------------------------------------------
# missing state fails loudly
# ---------------------------------------------------------------------------


def test_a_draft_cannot_be_replayed(client):
    """There is no finalized result to diff against, so there is nothing to
    say. 409 with a reason, not a number."""
    body = onboard(client, name="Draft Replay", phone="+919810070005")
    row = client.get(
        f"/api/recruiter/candidates/{body['candidate_id']}/evaluations"
    ).json()[0]
    resp = replay(client, row["id"])
    assert resp.status_code == 409
    assert "draft" in resp.json()["detail"]


def test_missing_signals_fail_clearly_rather_than_scoring_what_is_left(client):
    """THE MOST IMPORTANT FAILURE MODE IN THIS MODULE.

    An answer with no stored signals is an unanswerable question, not zero
    evidence. Scoring the rest would produce a confident lower number caused by
    missing data — which in a dispute is exactly the wrong answer, delivered
    with exactly the wrong confidence.
    """
    subject = interviewed(client, "Missing Signals", "+919810070006")

    async def erase():
        async with SessionLocal() as db:
            row = (
                await db.execute(
                    select(Response).where(
                        Response.session_id == subject["session_id"]
                    )
                )
            ).scalars().first()
            original = row.signals_json
            row.signals_json = None
            await db.commit()
            return row.id, original

    response_id, original = asyncio.run(erase())
    try:
        resp = replay(client, subject["evaluation_id"])
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert "no stored signals" in detail
        assert response_id in detail, "the error must name what is missing"
    finally:
        async def restore():
            async with SessionLocal() as db:
                row = await db.get(Response, response_id)
                row.signals_json = original
                await db.commit()

        asyncio.run(restore())


def test_a_missing_recorded_voice_weight_is_refused_not_defaulted():
    """The hidden configuration dependency, made explicit.

    `recompute_claim` reads `settings.voice_weight` live. Replay must use the
    RECORDED value, and when there is none it must refuse — defaulting would
    silently substitute today's behaviour for the recorded one and call the
    result a faithful replay.
    """
    from api.engine.replay import ReplayUnavailable, _recorded_voice_weight

    class Row:
        id = "ev_test"
        feature_flags_json = '{"ADAPTIVE_PROBING": "True"}'

    with pytest.raises(ReplayUnavailable, match="VOICE_WEIGHT"):
        _recorded_voice_weight(Row())

    Row.feature_flags_json = '{"VOICE_WEIGHT": "banana"}'
    with pytest.raises(ReplayUnavailable, match="not a number"):
        _recorded_voice_weight(Row())

    Row.feature_flags_json = '{"VOICE_WEIGHT": "0.25"}'
    assert _recorded_voice_weight(Row()) == 0.25


def test_replay_uses_the_recorded_voice_weight_not_the_live_setting(
    client, subject, monkeypatch
):
    """Change the live setting and replay anyway: the result must not move."""
    from api.config import settings

    monkeypatch.setattr(settings, "voice_weight", 0.85)
    body = replay(client, subject["evaluation_id"]).json()
    assert body["status"] == "MATCH", body["differences"]


def test_the_required_state_is_documented_in_code():
    """A support engineer reading a 409 should be able to find the full list."""
    required = replay_module.required_state()
    assert any("signals_json" in item for item in required)
    assert any("VOICE_WEIGHT" in item for item in required)
    assert any("claim_weights_json" in item for item in required)


def test_replay_of_an_unknown_or_foreign_evaluation_is_404(client):
    assert replay(client, "ev_nothing").status_code == 404
    other = client.post(
        "/api/dev/tenants", json={"slug": "replay-isolation", "name": "R"}
    ).json()
    assert client.post(
        f"/api/dev/replay/{interviewed(client, 'Replay Iso', '+919810070007')['evaluation_id']}",
        headers={"X-API-Key": other["api_key"]},
    ).status_code == 404
