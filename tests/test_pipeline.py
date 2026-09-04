"""
End-to-end through HTTP, in fixture mode (no model key, no WhatsApp
credentials, no Docker). Proves the wiring: resume -> claims -> adaptive probes
-> signals -> dimension scores -> role-weighted ranking, plus the Meta webhook
and the edge cases that eat demo days.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from pathlib import Path

from api.engine import scoring, signals
from api.schemas import Dimension, DimensionScore
from tests.conftest import EVASIVE_ANSWERS, RESUME, STRONG_ANSWERS, onboard, run_interview

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "sample_graph.json"
WS = re.compile(r"\s+")


def canon(text: str) -> str:
    return WS.sub(" ", (text or "").lower()).strip()


# ---------------------------------------------------------------------------
# meta
# ---------------------------------------------------------------------------


def test_health_reports_fixture_and_dry_run(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["llm_mode"] == "fixture"
    assert body["whatsapp"] == "dry-run"
    assert body["max_questions"] == 12
    assert body["job_families"] >= 7


def test_p1_00_field_additions_are_still_inert():
    """P1-00 added the Phase 1 contract surface; this pins what has not been
    acted on yet.

    The TRANSFER half of this pin has been DISCHARGED by P1-03, which is the
    task it was waiting for — its docstring said "unreachable until then", and
    then has arrived. Activation is now asserted where it belongs, in
    `test_policy.py`: TRANSFER is in `signals.PROBE_ORDER` (selectable) and
    deliberately absent from `signals.LADDER_ORDER` (never walked to, never
    opens a claim). Do not re-add a "TRANSFER is unreachable" assertion here.

    The two optional schema fields below are still genuinely inert.
    """
    from api.schemas import CandidateGraph, CandidateRef, CandidateSummary, ProbeLevel

    assert ProbeLevel.TRANSFER.value == "TRANSFER"

    # Both default to None until P1-08 / P1-13 fill them.
    assert CandidateSummary(id="c_inert", name="Inert").why_ranked is None
    graph = CandidateGraph(
        candidate=CandidateRef(id="c_inert", name="Inert"),
        job_family="general",
        job_family_label="General",
    )
    assert graph.routing_confidence is None


def test_openapi_is_the_contract(client):
    """The Next.js app generates its client from this; it must not 500."""
    paths = client.get("/openapi.json").json()["paths"]
    for required in (
        "/api/candidates",
        "/api/sessions/{session_id}",
        "/api/webhooks/whatsapp",
        "/api/recruiter/candidates",
        "/api/recruiter/candidates/{candidate_id}",
        "/api/recruiter/roles",
        "/api/recruiter/taxonomy",
        "/api/dev/simulate",
    ):
        assert required in paths, f"{required} missing from the OpenAPI schema"


# ---------------------------------------------------------------------------
# ingest and typing
# ---------------------------------------------------------------------------


def test_onboarding_types_claims_and_weights_them(client):
    body = onboard(client)
    assert body["job_family"] == "bpo_operations"
    assert body["state"] == "AWAITING_OPT_IN"          # WhatsApp needs opt-in
    assert len(body["opt_in_code"]) == 6
    assert 1 <= len(body["claims"]) <= 3

    types = {c["claim_type"] for c in body["claims"]}
    assert len(types) == len(body["claims"]), "claim types must be distinct"
    for claim in body["claims"]:
        assert claim["weight"] > 0, "an unweighted claim cannot be ranked"
        assert claim["claim_type_label"]


def test_fluff_and_headings_never_become_claims(client):
    body = onboard(client, name="Fluff Check", phone="+919810009999")
    texts = " ".join(c["text"].lower() for c in body["claims"])
    assert "team player" not in texts
    assert "passionate" not in texts
    assert "skills" not in texts


def test_phone_is_required_because_whatsapp_is_the_channel(client):
    resp = client.post(
        "/api/candidates/text",
        json={"resume_text": RESUME, "name": "No Phone", "phone": "   "},
    )
    assert resp.status_code == 400
    assert "phone" in resp.json()["detail"].lower()


def test_short_resume_is_rejected(client):
    resp = client.post(
        "/api/candidates/text",
        json={"resume_text": "too short", "name": "X", "phone": "+919810001111"},
    )
    assert resp.status_code == 400


def test_unsupported_file_type_is_rejected(client):
    resp = client.post(
        "/api/candidates",
        files={"file": ("cv.exe", b"MZ" + b"\x00" * 200, "application/octet-stream")},
        data={"name": "Bad Upload", "phone": "+919810002222"},
    )
    assert resp.status_code == 400
    assert "unsupported" in resp.json()["detail"].lower()


def test_txt_upload_goes_through_the_multipart_path(client):
    resp = client.post(
        "/api/candidates",
        files={"file": ("cv.txt", RESUME.encode(), "text/plain")},
        data={"name": "Multipart Priya", "phone": "+919810003333"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["claims"]


# ---------------------------------------------------------------------------
# the interview
# ---------------------------------------------------------------------------


def test_interview_walks_the_probe_levels_and_completes(client):
    body = onboard(client, name="Interview Walk", phone="+919810004444")
    session_id = body["session_id"]

    # The dev endpoint bypasses opt-in, which is why it is dev-only.
    turns = run_interview(client, session_id)
    assert 3 <= len(turns) <= 12

    final = client.get(f"/api/sessions/{session_id}").json()
    assert final["state"] == "COMPLETE"
    assert final["next_question"] is None

    graph = client.get(f"/api/recruiter/candidates/{body['candidate_id']}").json()
    levels = {qa["probe_level"] for claim in graph["claims"] for qa in claim["qa"]}
    assert "VALIDATION" in levels
    assert len(levels) >= 2, "the interview never went past the opening probe"


def test_no_question_is_asked_twice(client):
    body = onboard(client, name="No Repeats", phone="+919810005555")
    run_interview(client, body["session_id"])
    graph = client.get(f"/api/recruiter/candidates/{body['candidate_id']}").json()
    asked = [qa["question"] for claim in graph["claims"] for qa in claim["qa"]]
    assert len(asked) == len(set(asked))


def test_evasive_candidate_gets_a_shorter_interview(client):
    """The adaptive stop: no point asking a twelfth question of someone who has
    said nothing for three."""
    strong = onboard(client, name="Strong Answers", phone="+919810006666")
    weak = onboard(client, name="Evasive Answers", phone="+919810007777")
    strong_turns = run_interview(client, strong["session_id"], STRONG_ANSWERS)
    weak_turns = run_interview(client, weak["session_id"], EVASIVE_ANSWERS)
    assert len(weak_turns) < len(strong_turns)


def test_evasive_candidate_scores_zero_not_an_error(client):
    body = onboard(client, name="Evasive Scoring", phone="+919810008888")
    run_interview(client, body["session_id"], EVASIVE_ANSWERS)
    graph = client.get(f"/api/recruiter/candidates/{body['candidate_id']}").json()
    assert graph["competence_score"] == 0
    assert graph["badge"] == "unverified"


def test_answering_a_complete_session_is_a_409(client):
    body = onboard(client, name="Closed Session", phone="+919810009000")
    run_interview(client, body["session_id"])
    resp = client.post(
        f"/api/dev/sessions/{body['session_id']}/answer",
        json={"text": "one more thing I forgot to mention earlier"},
    )
    assert resp.status_code == 409


def test_unknown_session_is_a_404(client):
    assert client.get("/api/sessions/s_nope").status_code == 404
    assert client.post(
        "/api/dev/sessions/s_nope/answer", json={"text": "hello there friend"}
    ).status_code == 404


# ---------------------------------------------------------------------------
# the evidence graph
# ---------------------------------------------------------------------------


def test_graph_carries_six_dimensions_with_a_stated_basis(client):
    body = onboard(client, name="Graph Shape", phone="+919810010000")
    run_interview(client, body["session_id"])
    graph = client.get(f"/api/recruiter/candidates/{body['candidate_id']}").json()

    assert 0 <= graph["resume_score"] <= 100
    assert 0 <= graph["weighted_evidence_score"] <= 100
    assert 0 <= graph["competence_score"] <= 100
    assert graph["badge"] in {"verified", "partial", "unverified"}
    assert len(graph["dimension_profile"]) == 6

    probed = [c for c in graph["claims"] if c["qa"]]
    assert probed
    for claim in probed:
        assert len(claim["dimensions"]) == 6
        assert claim["claim_score"] is not None
        for dimension in claim["dimensions"]:
            assert 0 <= dimension["score"] <= 100
            assert dimension["basis"], "every score must state what it came from"
            if not dimension["probed"]:
                assert dimension["basis"] == "not probed"


def test_every_quote_is_verbatim_in_the_candidates_own_answer(client):
    """The guarantee the whole product rests on."""
    body = onboard(client, name="Verbatim Guarantee", phone="+919810011000")
    run_interview(client, body["session_id"])
    graph = client.get(f"/api/recruiter/candidates/{body['candidate_id']}").json()

    checked = 0
    for claim in graph["claims"]:
        said = canon(" ".join(qa["answer"] for qa in claim["qa"]))
        for dimension in claim["dimensions"]:
            for quote in dimension["quotes"]:
                assert canon(quote) in said, f"{quote!r} was never said"
                checked += 1
    assert checked > 0, "no quotes were checked, the test proved nothing"


def test_claim_scores_are_reproducible_from_stored_dimension_scores(client):
    """The arithmetic must be re-derivable from what the API returns, or
    'the score is arithmetic' is unverifiable from outside."""
    body = onboard(client, name="Reproducible", phone="+919810012000")
    run_interview(client, body["session_id"])
    graph = client.get(f"/api/recruiter/candidates/{body['candidate_id']}").json()

    for claim in graph["claims"]:
        if claim["claim_score"] is None:
            continue
        rebuilt = {
            Dimension(d["dimension"]): DimensionScore.model_validate(d)
            for d in claim["dimensions"]
        }
        expected = scoring.claim_score(rebuilt, graph["job_family"])
        assert abs(expected - claim["claim_score"]) <= 1, claim["claim_type"]


def test_unknown_candidate_is_a_404(client):
    assert client.get("/api/recruiter/candidates/c_nope").status_code == 404


# ---------------------------------------------------------------------------
# ARTIFACT 5 — same evidence, different recruiter, different ranking
# ---------------------------------------------------------------------------


def test_role_weights_re_rank_identical_evidence(client):
    """The strongest twenty seconds of the demo, as a test."""
    people = client.post(
        "/api/recruiter/roles",
        json={
            "title": "People First",
            "job_family": "bpo_operations",
            "claim_weights": {"team_handling": 70, "csat_improvement": 20, "aht_control": 10},
        },
    )
    ops = client.post(
        "/api/recruiter/roles",
        json={
            "title": "Ops Excellence",
            "job_family": "bpo_operations",
            "claim_weights": {"aht_control": 70, "csat_improvement": 20, "team_handling": 10},
        },
    )
    assert people.status_code == 201 and ops.status_code == 201
    people_id, ops_id = people.json()["id"], ops.json()["id"]

    # Weights are rescaled to sum to 100, as typed.
    assert sum(people.json()["claim_weights"].values()) == 100

    default = client.get("/api/recruiter/candidates").json()
    assert default["scored_for"] is None
    assert default["candidates"]

    under_people = client.get(f"/api/recruiter/candidates?role_id={people_id}").json()
    under_ops = client.get(f"/api/recruiter/candidates?role_id={ops_id}").json()

    assert under_people["scored_for"]["title"] == "People First"
    assert under_ops["scored_for"]["title"] == "Ops Excellence"

    by_people = {c["id"]: c["competence_score"] for c in under_people["candidates"]}
    by_ops = {c["id"]: c["competence_score"] for c in under_ops["candidates"]}
    assert by_people.keys() == by_ops.keys()
    assert by_people != by_ops, "role weights did not change any score"


def test_role_dimension_weights_actually_change_the_score(client):
    """Regression: dimension_weights were accepted, stored, returned — and then
    dropped on the floor (`claim_weights, _dim_weights, role_ref = ...`), so a
    recruiter could configure a lens, see it persisted, and observe no effect
    on any ranking. Same claim weights in both roles here, so ONLY the dimension
    lens can move these numbers.
    """
    shared_claims = {"team_handling": 40, "csat_improvement": 30, "aht_control": 30}
    depth = client.post(
        "/api/recruiter/roles",
        json={
            "title": "Reasoning First",
            "job_family": "bpo_operations",
            "claim_weights": shared_claims,
            "dimension_weights": {"CAUSAL_REASONING": 70, "PROCESS": 20, "SPECIFICITY": 10},
        },
    )
    tools = client.post(
        "/api/recruiter/roles",
        json={
            "title": "Tooling First",
            "job_family": "bpo_operations",
            "claim_weights": shared_claims,
            "dimension_weights": {"TOOL_FAMILIARITY": 70, "SPECIFICITY": 20, "PROCESS": 10},
        },
    )
    assert depth.status_code == 201 and tools.status_code == 201
    depth_id, tools_id = depth.json()["id"], tools.json()["id"]

    by_depth = {
        c["id"]: c["competence_score"]
        for c in client.get(f"/api/recruiter/candidates?role_id={depth_id}").json()["candidates"]
    }
    by_tools = {
        c["id"]: c["competence_score"]
        for c in client.get(f"/api/recruiter/candidates?role_id={tools_id}").json()["candidates"]
    }
    assert by_depth.keys() == by_tools.keys()
    assert by_depth != by_tools, "dimension weights had no effect on the ranked list"

    # And the detail view must agree with the list view, or a recruiter who
    # clicks through sees a different number than the one they ranked on.
    candidate_id = next(iter(by_depth))
    graph = client.get(
        f"/api/recruiter/candidates/{candidate_id}?role_id={depth_id}"
    ).json()
    assert graph["competence_score"] == by_depth[candidate_id]


def test_ranked_list_is_sorted_by_competence(client):
    rows = client.get("/api/recruiter/candidates").json()["candidates"]
    scores = [r["competence_score"] for r in rows]
    assert scores == sorted(scores, reverse=True)


def test_role_coverage_is_reported_separately_from_the_score(client):
    """'Evidenced badly' and 'never claimed it' must stay distinguishable."""
    narrow = client.post(
        "/api/recruiter/roles",
        json={
            "title": "Attrition Only",
            "job_family": "bpo_operations",
            "claim_weights": {"attrition_control": 100},
        },
    ).json()
    rows = client.get(f"/api/recruiter/candidates?role_id={narrow['id']}").json()["candidates"]
    assert any(r["role_coverage"] < 100 for r in rows)


def test_taxonomy_endpoint_feeds_the_weight_editor(client):
    body = client.get("/api/recruiter/taxonomy?job_family=bpo_operations").json()
    assert body["job_family"] == "bpo_operations"
    assert sum(body["default_claim_weights"].values()) == 100
    assert abs(sum(body["dimension_weights"].values()) - 1.0) < 1e-6
    assert client.get("/api/recruiter/taxonomy").json()["families"]


# ---------------------------------------------------------------------------
# the Meta WhatsApp Cloud API webhook
# ---------------------------------------------------------------------------


def _delivery(phone: str, *, text: str | None = None, wamid: str = "wamid.TEST") -> dict:
    message: dict = {"from": phone.lstrip("+"), "id": wamid, "timestamp": "1757000000"}
    if text is not None:
        message |= {"type": "text", "text": {"body": text}}
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": "WABA", "changes": [{"field": "messages", "value": {
            "messaging_product": "whatsapp",
            "metadata": {"display_phone_number": "911234567890", "phone_number_id": "PNID"},
            "contacts": [{"profile": {"name": "Test Candidate"}, "wa_id": phone.lstrip("+")}],
            "messages": [message],
        }}]}],
    }


def test_webhook_verification_handshake(client):
    resp = client.get(
        "/api/webhooks/whatsapp",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "test-verify-token",
            "hub.challenge": "CHALLENGE123",
        },
    )
    assert resp.status_code == 200
    assert resp.text == "CHALLENGE123"     # plain text, not JSON


def test_webhook_verification_rejects_a_wrong_token(client):
    resp = client.get(
        "/api/webhooks/whatsapp",
        params={"hub.mode": "subscribe", "hub.verify_token": "nope", "hub.challenge": "X"},
    )
    assert resp.status_code == 403


def test_status_only_delivery_is_acknowledged_not_an_error(client):
    """Most webhook traffic is delivery receipts. They must be a quiet 200."""
    resp = client.post(
        "/api/webhooks/whatsapp",
        json={"object": "whatsapp_business_account", "entry": [{"id": "W", "changes": [
            {"field": "messages", "value": {
                "messaging_product": "whatsapp",
                "statuses": [{"id": "wamid.X", "status": "delivered"}]}}]}]},
    )
    assert resp.status_code == 200


def test_opt_in_code_binds_the_phone_and_starts_the_interview(client):
    phone = "+919810013000"
    body = onboard(client, name="OptIn Flow", phone=phone)
    assert body["state"] == "AWAITING_OPT_IN"

    resp = client.post(
        "/api/webhooks/whatsapp",
        json=_delivery(phone, text=body["opt_in_code"], wamid="wamid.OPTIN"),
    )
    assert resp.status_code == 200

    state = client.get(f"/api/sessions/{body['session_id']}").json()
    assert state["state"] == "ASKING"
    assert state["questions_asked"] == 1
    assert state["next_question"]


def test_an_answer_over_whatsapp_is_scored(client):
    phone = "+919810014000"
    body = onboard(client, name="WhatsApp Answer", phone=phone)
    client.post("/api/webhooks/whatsapp",
                json=_delivery(phone, text=body["opt_in_code"], wamid="wamid.OI2"))
    client.post("/api/webhooks/whatsapp",
                json=_delivery(phone, text=STRONG_ANSWERS[0], wamid="wamid.ANS1"))

    state = client.get(f"/api/sessions/{body['session_id']}").json()
    assert state["questions_asked"] >= 2
    graph = client.get(f"/api/recruiter/candidates/{body['candidate_id']}").json()
    assert any(claim["qa"] for claim in graph["claims"])


def test_a_webhook_retry_does_not_become_a_second_answer(client):
    """Meta retries anything it thinks failed. Without de-duplication one retry
    desyncs the whole interview."""
    phone = "+919810015000"
    body = onboard(client, name="Retry Safety", phone=phone)
    client.post("/api/webhooks/whatsapp",
                json=_delivery(phone, text=body["opt_in_code"], wamid="wamid.OI3"))

    payload = _delivery(phone, text=STRONG_ANSWERS[1], wamid="wamid.DUPLICATE")
    client.post("/api/webhooks/whatsapp", json=payload)
    after_first = client.get(f"/api/sessions/{body['session_id']}").json()["questions_asked"]

    client.post("/api/webhooks/whatsapp", json=payload)      # the retry
    after_retry = client.get(f"/api/sessions/{body['session_id']}").json()["questions_asked"]

    assert after_retry == after_first


def test_unknown_number_is_handled_quietly(client):
    resp = client.post(
        "/api/webhooks/whatsapp",
        json=_delivery("+919899999999", text="hello?", wamid="wamid.STRANGER"),
    )
    assert resp.status_code == 200


def test_bad_signature_is_rejected_when_validation_is_on(client):
    from api.config import settings

    settings.whatsapp_validate_signature = True
    settings.whatsapp_app_secret = "test-secret"
    try:
        body = json.dumps(_delivery("+919810016000", text="hi", wamid="wamid.SIG")).encode()
        good = "sha256=" + hmac.new(b"test-secret", body, hashlib.sha256).hexdigest()

        bad = client.post(
            "/api/webhooks/whatsapp", content=body,
            headers={"X-Hub-Signature-256": "sha256=deadbeef", "content-type": "application/json"},
        )
        assert bad.status_code == 403

        ok = client.post(
            "/api/webhooks/whatsapp", content=body,
            headers={"X-Hub-Signature-256": good, "content-type": "application/json"},
        )
        assert ok.status_code == 200
    finally:
        settings.whatsapp_validate_signature = False
        settings.whatsapp_app_secret = None


# ---------------------------------------------------------------------------
# voice
# ---------------------------------------------------------------------------


def test_voice_answers_carry_measured_signals_only(client):
    """Duration and word count. No accent, no fluency, no confidence."""
    body = onboard(client, name="Voice Answer", phone="+919810017000")
    resp = client.post(
        f"/api/dev/sessions/{body['session_id']}/answer",
        json={"text": STRONG_ANSWERS[0], "audio_seconds": 34.5},
    )
    assert resp.status_code == 200

    graph = client.get(f"/api/recruiter/candidates/{body['candidate_id']}").json()
    voiced = [qa for claim in graph["claims"] for qa in claim["qa"] if qa["answered_by"] == "voice"]
    assert voiced
    voice = voiced[0]["voice"]
    assert voice["duration_seconds"] == 34.5
    assert voice["word_count"] > 0
    assert 0 <= voice["effort_score"] <= 100
    assert set(voice) == {"duration_seconds", "word_count", "words_per_minute", "effort_score"}


# ---------------------------------------------------------------------------
# /api/dev/simulate and the fixture
# ---------------------------------------------------------------------------


def test_simulate_runs_the_whole_pipeline_in_one_call(client):
    resp = client.post(
        "/api/dev/simulate",
        json={
            "resume_text": RESUME,
            "name": "Simulated Priya",
            "role": "Support Team Lead",
            "answers": STRONG_ANSWERS,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["questions_asked"] >= 3
    graph = body["graph"]
    assert graph["claims"]
    assert graph["job_family"] == "bpo_operations"
    assert 0 <= graph["competence_score"] <= 100

    listed = client.get("/api/recruiter/candidates").json()["candidates"]
    assert body["candidate_id"] in {row["id"] for row in listed}


def test_simulate_works_with_no_answers_supplied(client):
    resp = client.post(
        "/api/dev/simulate", json={"resume_text": RESUME, "name": "Placeholder Answers"}
    )
    assert resp.status_code == 200
    assert resp.json()["graph"]["claims"]


def test_fixture_matches_the_live_response_shape(client):
    """Dev B builds the dashboard against the fixture; if its shape drifts from
    the API the dashboard breaks on the day it is wired up."""
    from api.schemas import CandidateGraph

    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    fixture.pop("_note", None)
    CandidateGraph.model_validate(fixture)     # raises if the shape drifted


def test_fixture_numbers_are_what_scoring_recomputes():
    """The fixture is generated from the engine; assert it stayed that way."""
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for claim in fixture["claims"]:
        if claim["claim_score"] is None:
            continue
        rebuilt = {
            Dimension(d["dimension"]): DimensionScore.model_validate(d)
            for d in claim["dimensions"]
        }
        expected = scoring.claim_score(rebuilt, fixture["job_family"])
        assert abs(expected - claim["claim_score"]) <= 1, (
            f"fixture claim {claim['claim_type']} says {claim['claim_score']} "
            f"but scoring.py computes {expected} — regenerate with "
            f"scripts/dump_fixture.py"
        )


def test_fixture_quotes_are_verbatim():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for claim in fixture["claims"]:
        said = canon(" ".join(qa["answer"] for qa in claim["qa"]))
        for dimension in claim["dimensions"]:
            for quote in dimension["quotes"]:
                assert canon(quote) in said


def test_llm_diagnostics_prove_no_network_calls_were_made(client):
    body = client.get("/api/dev/llm").json()
    assert body["mode"] == "fixture"
    assert body["calls"] == 0
    assert body["fallbacks"] > 0


# ---------------------------------------------------------------------------
# P1-09 — candidate_outcomes
# ---------------------------------------------------------------------------


def test_outcome_table_exists():
    """12 -> 13 tables. The table is inert until P1-10 writes to it."""
    from api.models import Base, CandidateOutcome

    assert "candidate_outcomes" in Base.metadata.tables
    assert CandidateOutcome.__tablename__ == "candidate_outcomes"


def test_outcome_ids_use_the_o_prefix():
    """Short prefixed ids, because on demo day you read them off a screen."""
    from api import ids

    assert ids.outcome_id().startswith("o_")


def test_outcome_rows_are_append_only():
    """A candidate's decision history must accumulate, not overwrite.

    Append-only is enforced by SHAPE — deliberately no unique constraint on
    `candidate_id` — because `create_all()` cannot express a trigger. So the
    guarantee needs a test or it is only a comment: two decisions for one
    candidate coexist, and recording the second leaves the first exactly as it
    was. Overwriting would destroy the history M4a is computed over.
    """
    import asyncio

    from sqlalchemy import select

    from api import ids
    from api.db import SessionLocal
    from api.models import Candidate, CandidateOutcome

    async def scenario() -> tuple[int, str, str | None]:
        async with SessionLocal() as db:
            candidate = Candidate(
                id=ids.candidate_id(), name="Outcome History", phone="+919810099001"
            )
            db.add(candidate)
            await db.commit()

            first = CandidateOutcome(
                id=ids.outcome_id(),
                candidate_id=candidate.id,
                decision="shortlisted",
                stage="phone screen",
                decided_by="recruiter@example.com",
            )
            db.add(first)
            await db.commit()
            first_id = first.id

            db.add(
                CandidateOutcome(
                    id=ids.outcome_id(),
                    candidate_id=candidate.id,
                    decision="rejected",
                    stage="panel",
                )
            )
            await db.commit()

            rows = (
                await db.execute(
                    select(CandidateOutcome).where(
                        CandidateOutcome.candidate_id == candidate.id
                    )
                )
            ).scalars().all()
            earlier = next(r for r in rows if r.id == first_id)
            return len(rows), earlier.decision, earlier.stage

    count, earlier_decision, earlier_stage = asyncio.run(scenario())

    assert count == 2, "the second decision replaced the first instead of appending"
    assert earlier_decision == "shortlisted", "the earlier decision was mutated"
    assert earlier_stage == "phone screen"


def test_role_id_is_declared_set_null_and_the_outcome_survives():
    """Deleting a scoring lens must not delete the record that someone was
    rejected.

    Asserts the DECLARATION, not the runtime. Measured: SQLite runs with
    `PRAGMA foreign_keys = 0`, so all 17 `ondelete` clauses in models.py (15
    CASCADE, 2 SET NULL) are inert under this suite and enforced only on
    Postgres. A test that asserted the nulling would be asserting SQLite's
    default rather than our design, and would pass for the wrong reason if
    somebody later changed the clause to CASCADE.
    """
    import asyncio

    from sqlalchemy import select

    from api import ids
    from api.db import SessionLocal
    from api.models import Candidate, CandidateOutcome, JobRole

    fk = next(
        f for f in CandidateOutcome.__table__.foreign_keys if f.parent.name == "role_id"
    )
    assert fk.ondelete == "SET NULL", (
        "role_id must be SET NULL — CASCADE would destroy hiring decisions when "
        "a recruiter deletes a lens"
    )
    candidate_fk = next(
        f
        for f in CandidateOutcome.__table__.foreign_keys
        if f.parent.name == "candidate_id"
    )
    assert candidate_fk.ondelete == "CASCADE"

    async def scenario() -> bool:
        async with SessionLocal() as db:
            role = JobRole(
                id=ids.role_id(), title="Disposable Lens", job_family="bpo_operations"
            )
            candidate = Candidate(
                id=ids.candidate_id(), name="Lens Deleted", phone="+919810099002"
            )
            db.add_all([role, candidate])
            await db.commit()

            outcome = CandidateOutcome(
                id=ids.outcome_id(),
                candidate_id=candidate.id,
                role_id=role.id,
                decision="rejected",
            )
            db.add(outcome)
            await db.commit()
            outcome_id = outcome.id

            await db.delete(role)
            await db.commit()

            return (
                await db.execute(
                    select(CandidateOutcome).where(CandidateOutcome.id == outcome_id)
                )
            ).scalar_one_or_none() is not None

    assert asyncio.run(scenario()), "deleting a lens destroyed the hiring decision"


# ---------------------------------------------------------------------------
# P1-10 — outcome endpoints
# ---------------------------------------------------------------------------


def _decided_candidate(client, name: str, phone: str) -> str:
    """A candidate who has been through an interview, so their scores exist and
    can be compared before and after an outcome is recorded."""
    body = onboard(client, name=name, phone=phone)
    run_interview(client, body["session_id"])
    return body["candidate_id"]


def test_outcome_can_be_recorded_and_retrieved(client):
    """Round trip, against a candidate AND a role lens — the lens is what makes
    a decision interpretable later."""
    candidate_id = _decided_candidate(client, "Outcome Round Trip", "+919810020001")
    role_id = client.post(
        "/api/recruiter/roles",
        json={"title": "Outcome Lens", "job_family": "bpo_operations",
              "claim_weights": {"team_handling": 60, "csat_improvement": 40}},
    ).json()["id"]

    resp = client.post(
        f"/api/recruiter/candidates/{candidate_id}/outcome",
        json={"decision": "shortlisted", "stage": "phone screen",
              "role_id": role_id, "decided_by": "recruiter@example.com",
              "note": "strong on ownership"},
    )
    assert resp.status_code == 201, resp.text
    written = resp.json()
    assert written["id"].startswith("o_")
    assert written["decision"] == "shortlisted"
    assert written["role_id"] == role_id
    assert written["decided_at"]

    history = client.get(f"/api/recruiter/candidates/{candidate_id}/outcomes").json()
    assert [o["id"] for o in history] == [written["id"]]
    assert history[0]["note"] == "strong on ownership"


def test_outcome_history_is_ordered_oldest_first(client):
    """The validation report reads these as a progression, so chronological is
    the order the data is consumed in."""
    candidate_id = _decided_candidate(client, "Outcome Ordering", "+919810020002")
    for decision in ("shortlisted", "interviewed", "offered"):
        assert client.post(
            f"/api/recruiter/candidates/{candidate_id}/outcome",
            json={"decision": decision},
        ).status_code == 201

    history = client.get(f"/api/recruiter/candidates/{candidate_id}/outcomes").json()
    assert [o["decision"] for o in history] == ["shortlisted", "interviewed", "offered"]

    # And the ordinal the report depends on survives the round trip.
    from api.schemas import OutcomeDecision

    ladder = [d.value for d in OutcomeDecision]
    positions = [ladder.index(o["decision"]) for o in history]
    assert positions == sorted(positions), "the decision ladder inverted in storage"


def test_invalid_decision_is_rejected(client):
    """The ordinal scale is load-bearing for M4a, so an off-scale value must
    never reach the table."""
    candidate_id = _decided_candidate(client, "Bad Decision", "+919810020003")
    resp = client.post(
        f"/api/recruiter/candidates/{candidate_id}/outcome",
        json={"decision": "vibes"},
    )
    assert resp.status_code == 422


def test_outcome_against_an_unknown_candidate_or_role_is_404(client):
    """An orphan outcome is invisible to ranking but would still inflate
    n_decided, and an unknown lens must not degrade into a null column.

    Asserts the DETAIL, not just the status. A missing route also returns 404,
    so a bare status check here passed before the routes existed — recording
    nothing. The detail string is what distinguishes "we looked and there is no
    such candidate" from "there is no such endpoint".
    """
    missing = client.post(
        "/api/recruiter/candidates/c_nope/outcome", json={"decision": "rejected"}
    )
    assert missing.status_code == 404
    assert missing.json()["detail"] == "candidate not found"

    history = client.get("/api/recruiter/candidates/c_nope/outcomes")
    assert history.status_code == 404
    assert history.json()["detail"] == "candidate not found"

    candidate_id = _decided_candidate(client, "Unknown Lens", "+919810020004")
    bad_lens = client.post(
        f"/api/recruiter/candidates/{candidate_id}/outcome",
        json={"decision": "rejected", "role_id": "jr_nope"},
    )
    assert bad_lens.status_code == 404
    assert "jr_nope" in bad_lens.json()["detail"]


def test_recording_an_outcome_changes_no_score(client):
    """THE CIRCULARITY GUARD. A recruiter's decision is the independent
    variable in M4a. If recording one fed back into any score, the headline
    metric would correlate the system with itself and mean nothing."""
    candidate_id = _decided_candidate(client, "No Feedback Loop", "+919810020005")
    before = client.get(f"/api/recruiter/candidates/{candidate_id}").json()

    assert client.post(
        f"/api/recruiter/candidates/{candidate_id}/outcome",
        json={"decision": "hired", "note": "should not move a number"},
    ).status_code == 201

    after = client.get(f"/api/recruiter/candidates/{candidate_id}").json()
    for field in (
        "resume_score", "weighted_evidence_score", "competence_score",
        "badge", "role_coverage",
    ):
        assert before[field] == after[field], f"{field} moved when an outcome was recorded"
    assert [c["claim_score"] for c in before["claims"]] == [
        c["claim_score"] for c in after["claims"]
    ]


def test_recording_an_outcome_makes_no_model_call(client):
    """Asserts the write SUCCEEDED before checking the counter. A 404 also
    spends no tokens, so without the 201 assertion this test passed against a
    repo with no outcome routes at all."""
    candidate_id = _decided_candidate(client, "Outcome No LLM", "+919810020006")
    before = client.get("/api/dev/llm").json()["calls"]

    written = client.post(
        f"/api/recruiter/candidates/{candidate_id}/outcome",
        json={"decision": "rejected"},
    )
    assert written.status_code == 201, "nothing was written, so nothing is proven"
    read_back = client.get(f"/api/recruiter/candidates/{candidate_id}/outcomes")
    assert read_back.status_code == 200 and read_back.json()

    assert client.get("/api/dev/llm").json()["calls"] == before


# ---------------------------------------------------------------------------
# P1-13 — why_ranked
# ---------------------------------------------------------------------------


def test_every_ranked_candidate_explains_itself(client):
    """Phase acceptance criterion 9: 100% of ranked rows carry a reason."""
    onboard(client, name="Explains Itself", phone="+919810031001")
    rows = client.get("/api/recruiter/candidates").json()["candidates"]
    assert rows
    missing = [r["name"] for r in rows if not (r["why_ranked"] or "").strip()]
    assert not missing, f"no explanation for: {missing}"


def test_why_ranked_cites_evidence_not_the_score(client):
    """B's contract requires it cite stored evidence rather than restate the
    score in words. "competence 56" in prose is a row of text carrying no
    information a recruiter did not already have from the number beside it."""
    body = onboard(client, name="Cites Evidence", phone="+919810031002")
    run_interview(client, body["session_id"])

    row = next(
        r for r in client.get("/api/recruiter/candidates").json()["candidates"]
        if r["id"] == body["candidate_id"]
    )
    sentence = row["why_ranked"].lower()

    assert "evidence signal" in sentence
    assert "dimensions probed" in sentence
    for restatement in ("competence", "badge", "verified", "partial score"):
        assert restatement not in sentence, (
            f"the sentence restates the score ({restatement!r}) instead of citing evidence"
        )


def test_why_ranked_distinguishes_candidates(client):
    """A sentence that reads the same for everybody is decoration."""
    strong = onboard(client, name="Strong Reason", phone="+919810031003")
    run_interview(client, strong["session_id"], STRONG_ANSWERS)
    weak = onboard(client, name="Evasive Reason", phone="+919810031004")
    run_interview(client, weak["session_id"], EVASIVE_ANSWERS)

    rows = {r["id"]: r["why_ranked"] for r in
            client.get("/api/recruiter/candidates").json()["candidates"]}
    assert rows[strong["candidate_id"]] != rows[weak["candidate_id"]]
    # And the evasive candidate's sentence names the diagnostic absence.
    assert "no concrete figures" in rows[weak["candidate_id"]]
    assert "stalled" in rows[weak["candidate_id"]]


def test_why_ranked_changes_with_the_role_lens(client):
    """Same evidence, different lens, different explanation. A list view whose
    reasoning ignored the lens would contradict the ranking beside it."""
    body = onboard(client, name="Lens Reason", phone="+919810031005")
    run_interview(client, body["session_id"], STRONG_ANSWERS)

    people = client.post("/api/recruiter/roles", json={
        "title": "People Reason", "job_family": "bpo_operations",
        "claim_weights": {"team_handling": 80, "aht_control": 20}}).json()["id"]
    ops = client.post("/api/recruiter/roles", json={
        "title": "Ops Reason", "job_family": "bpo_operations",
        "claim_weights": {"aht_control": 80, "team_handling": 20}}).json()["id"]

    def reason(role_id: str) -> str:
        rows = client.get(f"/api/recruiter/candidates?role_id={role_id}").json()["candidates"]
        return next(r["why_ranked"] for r in rows if r["id"] == body["candidate_id"])

    under_people, under_ops = reason(people), reason(ops)
    assert under_people != under_ops, "the explanation ignored the lens"
    assert "Team handling" in under_people
    assert "AHT" in under_ops


def test_why_ranked_makes_no_model_calls(client):
    """Rule 12: traceable without another model call."""
    body = onboard(client, name="Reason No LLM", phone="+919810031006")
    run_interview(client, body["session_id"])

    before = client.get("/api/dev/llm").json()["calls"]
    rows = client.get("/api/recruiter/candidates").json()["candidates"]
    assert any(r["why_ranked"] for r in rows), "nothing rendered, nothing proven"
    assert client.get("/api/dev/llm").json()["calls"] == before


# ---------------------------------------------------------------------------
# P1-11 — validation report
# ---------------------------------------------------------------------------


def test_spearman_and_quantiles_match_known_values():
    """The stats are hand-rolled because scipy is not a dependency, so they
    need pinning against values computable by hand."""
    from scripts.validation_report import median, precision_at_k, quantile, spearman

    assert spearman([1, 2, 3, 4, 5], [1, 2, 3, 4, 5]) == 1.0
    assert spearman([1, 2, 3, 4, 5], [5, 4, 3, 2, 1]) == -1.0
    # Ties averaged, not broken arbitrarily — competence scores cluster.
    assert spearman([1, 1, 2], [1, 1, 2]) == 1.0
    # Undefined, not zero: a flat variable has no correlation, and 0.0 would
    # read as "no relationship found" when the truth is "not computable".
    assert spearman([1, 1, 1], [1, 2, 3]) is None
    assert spearman([1, 2], [1, 2]) is None

    assert median([]) is None
    assert median([3, 1, 2]) == 2
    assert quantile([0, 10, 20, 30, 40], 0.25) == 10
    assert precision_at_k(["a", "b", "c"], {"a"}, k=5) is None
    assert precision_at_k(["a", "b", "c", "d", "e"], {"a", "c"}, k=5) == 0.4


def test_stalled_claim_definition_matches_the_orchestrator():
    """M1b's denominator. The orchestrator stalls a claim on >= 2 answers whose
    LAST produced no signals; `claim_scores.score == 0` is a different thing —
    a claim can earn signals early and stall later. Using the score proxy
    reported 0 stalled while 3 transfer probes had fired, which made a
    correctness invariant unmeasurable."""
    from api.models import Question, Response
    from scripts.validation_report import Snapshot

    snap = Snapshot()
    snap.questions = [
        Question(id="q1", claim_id="cl_1", session_id="s", text="", probe_level="VALIDATION", order_index=0),
        Question(id="q2", claim_id="cl_1", session_id="s", text="", probe_level="INCIDENT", order_index=1),
        Question(id="q3", claim_id="cl_2", session_id="s", text="", probe_level="VALIDATION", order_index=2),
    ]
    snap.responses_by_question = {
        # cl_1: earned signals, then produced none -> stalled
        "q1": Response(id="r1", question_id="q1", session_id="s", signals_found=7),
        "q2": Response(id="r2", question_id="q2", session_id="s", signals_found=0),
        # cl_2: only one answer -> not stalled, however thin
        "q3": Response(id="r3", question_id="q3", session_id="s", signals_found=0),
    }
    assert snap.stalled_claims() == {"cl_1"}


def test_latest_decision_wins_not_the_best_one():
    """Someone shortlisted and then rejected was rejected. Taking the maximum
    would score the system against an outcome that got reversed."""
    from datetime import datetime, timedelta, timezone

    from api.models import CandidateOutcome
    from scripts.validation_report import Snapshot

    now = datetime.now(timezone.utc)
    snap = Snapshot()
    snap.outcomes_by_candidate = {
        "c_1": [
            CandidateOutcome(id="o1", candidate_id="c_1", decision="shortlisted", decided_at=now),
            CandidateOutcome(
                id="o2", candidate_id="c_1", decision="rejected",
                decided_at=now + timedelta(hours=1),
            ),
        ]
    }
    assert snap.latest_decision("c_1") == "rejected"


def test_validation_report_runs_and_prints_every_metric(client):
    """Acceptance: runs clean and prints every metric in the metrics doc."""
    import asyncio

    from api.db import SessionLocal
    from scripts.validation_report import build_report, collect, render

    body = onboard(client, name="Report Runs", phone="+919810040001")
    run_interview(client, body["session_id"])

    async def run() -> str:
        async with SessionLocal() as db:
            snap = await collect(db)
            return render(snap, build_report(snap))

    text = asyncio.run(run())
    for label in ("M1a", "M1b", "M1c", "M2a", "M2b", "M3a", "M3b", "M3c",
                  "M4", "M5a", "M5b", "M5c"):
        assert label in text, f"{label} missing from the report"
    assert "No model was called" in text


def test_report_withholds_below_minimum_n(client):
    """Withhold, never estimate. A Spearman coefficient over four candidates
    looks like evidence and is not."""
    import asyncio

    from api.db import SessionLocal
    from scripts.validation_report import build_report, collect

    body = onboard(client, name="Withhold Me", phone="+919810040002")
    run_interview(client, body["session_id"])
    client.post(
        f"/api/recruiter/candidates/{body['candidate_id']}/outcome",
        json={"decision": "hired"},
    )

    async def run():
        async with SessionLocal() as db:
            return build_report(await collect(db))

    report = asyncio.run(run())
    assert report.minimum_n == 30
    assert report.overall.sufficient is False
    assert report.overall.competence_correlation is None
    assert report.overall.resume_correlation is None
    assert report.overall.n_decided >= 1, "the decision was not counted"


def test_report_computes_m4_once_n_is_met(client):
    """The maths must work when data exists, proven with a LOWERED floor rather
    than by seeding synthetic decisions into the real report. Asserts the
    numbers are computed and in range — never their direction, because
    asserting a direction would be asserting a finding."""
    import asyncio

    from api.db import SessionLocal
    from scripts.validation_report import build_report, collect

    decisions = ["rejected", "shortlisted", "interviewed", "offered"]
    for index in range(4):
        body = onboard(client, name=f"M4 Sample {index}", phone=f"+91981005{index:04d}")
        run_interview(
            client,
            body["session_id"],
            STRONG_ANSWERS if index % 2 else EVASIVE_ANSWERS,
        )
        client.post(
            f"/api/recruiter/candidates/{body['candidate_id']}/outcome",
            json={"decision": decisions[index]},
        )

    async def run():
        async with SessionLocal() as db:
            return build_report(await collect(db), minimum_n=3)

    report = asyncio.run(run())
    assert report.minimum_n == 3
    assert report.overall.sufficient is True
    assert report.overall.n_decided >= 4
    for value in (report.overall.competence_correlation, report.overall.resume_correlation):
        assert value is None or -1.0 <= value <= 1.0
    assert report.overall.inversions_caught >= 0


def test_report_makes_no_model_calls(client):
    """Every number is arithmetic over stored rows."""
    import asyncio

    from api.db import SessionLocal
    from scripts.validation_report import build_report, collect, render

    body = onboard(client, name="Report No LLM", phone="+919810040003")
    run_interview(client, body["session_id"])

    before = client.get("/api/dev/llm").json()["calls"]

    async def run() -> str:
        async with SessionLocal() as db:
            snap = await collect(db)
            return render(snap, build_report(snap))

    assert "ProofScreen" in asyncio.run(run())
    assert client.get("/api/dev/llm").json()["calls"] == before


# ---------------------------------------------------------------------------
# P1-12 — GET /api/recruiter/validation
# ---------------------------------------------------------------------------


def test_validation_endpoint_matches_the_script(client):
    """One implementation, two surfaces. If these drift, one of them is lying."""
    import asyncio

    from api.db import SessionLocal
    from scripts.validation_report import build_report, collect

    body = onboard(client, name="Endpoint Parity", phone="+919810060001")
    run_interview(client, body["session_id"])
    client.post(
        f"/api/recruiter/candidates/{body['candidate_id']}/outcome",
        json={"decision": "shortlisted"},
    )

    served = client.get("/api/recruiter/validation").json()

    async def run():
        async with SessionLocal() as db:
            return build_report(await collect(db))

    direct = asyncio.run(run())

    assert served["minimum_n"] == direct.minimum_n
    assert served["overall"]["n_decided"] == direct.overall.n_decided
    assert served["overall"]["sufficient"] is direct.overall.sufficient
    assert served["overall"]["competence_correlation"] == direct.overall.competence_correlation
    assert served["overall"]["resume_correlation"] == direct.overall.resume_correlation
    assert served["overall"]["inversions_caught"] == direct.overall.inversions_caught
    assert {c["job_family"] for c in served["cohorts"]} == {
        c.job_family for c in direct.cohorts
    }


def test_validation_endpoint_withholds_below_the_floor(client):
    """The default floor is 30 and it is echoed, so a number computed under a
    lowered floor can never be mistaken for the real M4a."""
    body = onboard(client, name="Endpoint Withhold", phone="+919810060002")
    run_interview(client, body["session_id"])
    client.post(
        f"/api/recruiter/candidates/{body['candidate_id']}/outcome",
        json={"decision": "hired"},
    )

    default = client.get("/api/recruiter/validation").json()
    assert default["minimum_n"] == 30
    assert default["overall"]["sufficient"] is False
    assert default["overall"]["competence_correlation"] is None
    assert default["overall"]["n_decided"] >= 1

    lowered = client.get("/api/recruiter/validation?minimum_n=1").json()
    assert lowered["minimum_n"] == 1, "the response must state the floor it used"
    assert lowered["overall"]["sufficient"] is True


def test_validation_out_is_now_published_in_openapi(client):
    """P1-00's verification note: FastAPI publishes only schemas reachable from
    a route, so ValidationOut was correctly absent until this endpoint landed."""
    spec = client.get("/openapi.json").json()
    assert "/api/recruiter/validation" in spec["paths"]
    assert "ValidationOut" in spec["components"]["schemas"]
    assert "ValidationCohort" in spec["components"]["schemas"]


def test_validation_endpoint_makes_no_model_call(client):
    before = client.get("/api/dev/llm").json()["calls"]
    resp = client.get("/api/recruiter/validation")
    assert resp.status_code == 200 and resp.json()["generated_at"]
    assert client.get("/api/dev/llm").json()["calls"] == before


# ---------------------------------------------------------------------------
# P1-08b — routing_confidence
# ---------------------------------------------------------------------------

# No family vocabulary at all, but long enough to pass the ingest floor. Used
# to exercise the fallback path rather than the happy one.
UNROUTABLE_RESUME = """Jordan Ellis - Generalist, Remote

EXPERIENCE
- Looked after a variety of assorted matters for several different groups
- Handled the usual things that came up from week to week without much fuss
- Wrote up the outcomes afterwards so everyone knew what had happened

INTERESTS
Reading, walking, cooking
"""


def test_routing_confidence_is_populated_in_the_graph(client):
    """The field existed since P1-00 and was always null."""
    body = onboard(client, name="Routing Confidence", phone="+919810070001")
    graph = client.get(f"/api/recruiter/candidates/{body['candidate_id']}").json()
    assert graph["routing_confidence"] is not None
    assert 0.0 <= graph["routing_confidence"] <= 1.0


def test_routing_confidence_matches_match_family(client):
    """Parity with A's published contract. If these drift, the candidate record
    is reporting a margin the router did not compute."""
    from api.taxonomy import match_family

    body = onboard(client, name="Routing Parity", phone="+919810070002")
    graph = client.get(f"/api/recruiter/candidates/{body['candidate_id']}").json()
    assert graph["routing_confidence"] == match_family(RESUME).confidence
    assert graph["job_family"] == match_family(RESUME).family


def test_low_confidence_routing_is_visible_in_the_graph(client):
    """A resume that clears no family's two-term floor must not be silently
    filed under a confident guess. `general` plus 0.0 is the visible form of
    "we could not tell" — and the PAIR of fields is what distinguishes it from
    an exact tie, since CandidateGraph carries one float and schemas.py is
    frozen."""
    body = client.post(
        "/api/candidates/text",
        json={
            "resume_text": UNROUTABLE_RESUME,
            "name": "Unroutable Jordan",
            "phone": "+919810070003",
        },
    )
    assert body.status_code == 201, body.text
    graph = client.get(
        f"/api/recruiter/candidates/{body.json()['candidate_id']}"
    ).json()
    assert graph["job_family"] == "general"
    assert graph["routing_confidence"] == 0.0


def test_routing_confidence_is_not_decorative(client):
    """B's contract: if every candidate reads 1.00 the field tells a recruiter
    nothing. Measured on the seeded personas as 0.17 / 0.40 / 0.72."""
    for index, (name, resume) in enumerate(
        [("Discriminate BPO", RESUME), ("Discriminate None", UNROUTABLE_RESUME)]
    ):
        client.post(
            "/api/candidates/text",
            json={"resume_text": resume, "name": name,
                  "phone": f"+919810071{index:03d}"},
        )
    values = {
        c["id"]: client.get(f"/api/recruiter/candidates/{c['id']}").json()[
            "routing_confidence"
        ]
        for c in client.get("/api/recruiter/candidates").json()["candidates"]
    }
    present = {v for v in values.values() if v is not None}
    assert len(present) > 1, f"routing_confidence collapsed to {present} — decorative"


def test_routing_confidence_makes_no_model_call(client):
    """match_family is a pure function of the text and the taxonomy file, and
    the resume was already loaded for resume_score."""
    body = onboard(client, name="Routing No LLM", phone="+919810070004")
    before = client.get("/api/dev/llm").json()["calls"]
    graph = client.get(f"/api/recruiter/candidates/{body['candidate_id']}").json()
    assert graph["routing_confidence"] is not None
    assert client.get("/api/dev/llm").json()["calls"] == before

