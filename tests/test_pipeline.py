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
