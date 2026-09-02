"""
End-to-end tests through the HTTP API, in fixture mode (no LLM key, no Docker).

These prove the wiring: resume in -> claims -> questions -> answers -> evidence
-> score -> evidence graph out, plus both channels and the edge cases from the
7 September hardening list.
"""

from __future__ import annotations

import re

from tests.conftest import ANSWERS, RESUME

WS = re.compile(r"\s+")


def canon(text: str) -> str:
    return WS.sub(" ", (text or "").lower()).strip()


def onboard(client, name="Priya Raghavan", **extra) -> dict:
    payload = {
        "resume_text": RESUME,
        "name": name,
        "role": "Support Lead",
        **extra,
    }
    resp = client.post("/api/candidates/text", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def run_interview(client, session_id: str, answers=None) -> list[tuple[str, str]]:
    """Answer questions until the session says it is done."""
    answers = answers or ANSWERS
    transcript: list[tuple[str, str]] = []
    for i in range(10):                      # hard stop, MAX_QUESTIONS is 5
        state = client.get(f"/api/sessions/{session_id}").json()
        question = state["next_question"]
        if not question:
            break
        answer = answers[i % len(answers)]
        resp = client.post(
            "/api/web/message", json={"session_id": session_id, "text": answer}
        )
        assert resp.status_code == 200, resp.text
        transcript.append((question, answer))
        if resp.json()["done"]:
            break
    return transcript


# ---------------------------------------------------------------------------
# meta
# ---------------------------------------------------------------------------


def test_health_reports_fixture_mode(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["llm_mode"] == "fixture"      # no key in the test env
    assert body["max_questions"] == 5


def test_openapi_schema_is_the_contract(client):
    """The Next.js app generates its client from this. It must not 500."""
    schema = client.get("/openapi.json").json()
    paths = schema["paths"]
    for required in (
        "/api/candidates",
        "/api/sessions/{session_id}",
        "/api/web/message",
        "/api/webhooks/twilio",
        "/api/recruiter/candidates",
        "/api/recruiter/candidates/{candidate_id}",
        "/api/dev/simulate",
    ):
        assert required in paths, f"{required} missing from the OpenAPI schema"


# ---------------------------------------------------------------------------
# ingest
# ---------------------------------------------------------------------------


def test_onboarding_extracts_claims_and_opens_a_session(client):
    body = onboard(client)
    assert body["candidate_id"].startswith("c_")
    assert body["session_id"].startswith("s_")
    assert 1 <= len(body["claims"]) <= 3
    assert body["first_question"]
    assert len(body["join_code"]) == 6

    for claim in body["claims"]:
        assert claim["text"].strip()
        assert claim["category"]


def test_claims_are_verifiable_not_fluff(client):
    """The fluff line in the resume must not become a claim."""
    body = onboard(client, name="Fluff Check")
    texts = " ".join(c["text"].lower() for c in body["claims"])
    assert "team player" not in texts
    assert "passionate" not in texts


def test_short_resume_is_rejected_with_400(client):
    resp = client.post(
        "/api/candidates/text", json={"resume_text": "too short", "name": "X"}
    )
    assert resp.status_code == 400


def test_unsupported_file_type_is_rejected_with_400(client):
    resp = client.post(
        "/api/candidates",
        files={"file": ("resume.exe", b"MZ" + b"\x00" * 200, "application/octet-stream")},
        data={"name": "Bad Upload"},
    )
    assert resp.status_code == 400
    assert "unsupported" in resp.json()["detail"].lower()


def test_txt_upload_goes_through_the_multipart_path(client):
    resp = client.post(
        "/api/candidates",
        files={"file": ("resume.txt", RESUME.encode(), "text/plain")},
        data={"name": "Multipart Priya", "role": "Support Lead"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["claims"]


# ---------------------------------------------------------------------------
# the conversation
# ---------------------------------------------------------------------------


def test_session_state_machine_walks_to_complete(client):
    body = onboard(client, name="State Machine")
    session_id = body["session_id"]

    state = client.get(f"/api/sessions/{session_id}").json()
    assert state["state"] == "ASKING"
    assert state["questions_asked"] == 1

    transcript = run_interview(client, session_id)
    assert 1 <= len(transcript) <= 5

    final = client.get(f"/api/sessions/{session_id}").json()
    assert final["state"] == "COMPLETE"
    assert final["next_question"] is None


def test_no_question_is_ever_asked_twice(client):
    body = onboard(client, name="No Repeats")
    transcript = run_interview(client, body["session_id"])
    questions = [q for q, _ in transcript]
    assert len(questions) == len(set(questions)), questions


def test_answering_a_complete_session_is_a_409(client):
    body = onboard(client, name="Closed Session")
    run_interview(client, body["session_id"])
    resp = client.post(
        "/api/web/message",
        json={"session_id": body["session_id"], "text": "one more thing I forgot"},
    )
    assert resp.status_code == 409


def test_empty_answer_is_a_400(client):
    body = onboard(client, name="Empty Answer")
    resp = client.post(
        "/api/web/message", json={"session_id": body["session_id"], "text": "   "}
    )
    assert resp.status_code == 400


def test_unknown_session_is_a_404(client):
    assert client.get("/api/sessions/s_nope").status_code == 404
    assert (
        client.post("/api/web/message", json={"session_id": "s_nope", "text": "hello there"}).status_code
        == 404
    )


# ---------------------------------------------------------------------------
# the evidence graph
# ---------------------------------------------------------------------------


def test_graph_has_claims_qa_and_evidence_nodes(client):
    body = onboard(client, name="Graph Shape")
    run_interview(client, body["session_id"])

    graph = client.get(f"/api/recruiter/candidates/{body['candidate_id']}").json()
    assert graph["candidate"]["id"] == body["candidate_id"]
    assert 0.0 <= graph["competence_score"] <= 1.0
    assert 0.0 <= graph["resume_score"] <= 1.0
    assert graph["badge"] in {"verified", "partial", "unverified"}

    probed = [c for c in graph["claims"] if c["qa"]]
    assert probed, "no claim was probed"
    for claim in probed:
        assert claim["nodes"], f"claim {claim['id']} has Q&A but no evidence"
        assert claim["confidence"] is not None
        assert claim["rationale"]


def test_every_quote_is_verbatim_in_the_candidates_own_answer(client):
    """The guarantee the whole product rests on."""
    body = onboard(client, name="Verbatim Guarantee")
    run_interview(client, body["session_id"])

    graph = client.get(f"/api/recruiter/candidates/{body['candidate_id']}").json()
    checked = 0
    for claim in graph["claims"]:
        answers = canon(" ".join(qa["answer"] for qa in claim["qa"]))
        for evidence_node in claim["nodes"]:
            quote = canon(evidence_node["quote"])
            if not quote:
                continue
            assert quote in answers, f"{quote!r} was never said by the candidate"
            checked += 1
    assert checked > 0, "no quotes were checked, the test proved nothing"


def test_evidence_nodes_point_at_a_real_response(client):
    body = onboard(client, name="Node Provenance")
    run_interview(client, body["session_id"])
    graph = client.get(f"/api/recruiter/candidates/{body['candidate_id']}").json()

    for claim in graph["claims"]:
        response_ids = {qa["response_id"] for qa in claim["qa"]}
        for evidence_node in claim["nodes"]:
            assert evidence_node["source_response_id"] in response_ids


def test_unknown_candidate_graph_is_a_404(client):
    assert client.get("/api/recruiter/candidates/c_nope").status_code == 404


def test_ranked_list_is_sorted_by_competence(client):
    onboard(client, name="Ranking A")
    rows = client.get("/api/recruiter/candidates").json()
    assert rows
    scored = [r["competence_score"] for r in rows if r["competence_score"] is not None]
    assert scored == sorted(scored, reverse=True)
    for row in rows:
        assert row["name"]
        assert row["claims_count"] >= 0


# ---------------------------------------------------------------------------
# edge cases from the 7 September hardening list
# ---------------------------------------------------------------------------


def test_i_dont_know_scores_zero_not_an_error(client):
    body = onboard(client, name="Evasive Candidate")
    run_interview(client, body["session_id"], answers=["I don't know."] * 5)

    graph = client.get(f"/api/recruiter/candidates/{body['candidate_id']}").json()
    assert graph["competence_score"] == 0.0
    assert graph["badge"] == "unverified"
    for claim in graph["claims"]:
        if claim["qa"]:
            assert claim["confidence"] == 0.0
            assert all(n["verdict"] == "UNSUPPORTED" for n in claim["nodes"])


def test_single_claim_resume_ends_early_instead_of_repeating(client):
    """4 dimensions cannot fill 5 questions — the interview must stop, not loop."""
    resume = (
        "Ananya Iyer - Operations Analyst, Chennai\n\n"
        "EXPERIENCE\n"
        "- Reduced monthly vendor reconciliation time from 12 days to 3 days "
        "by automating the invoice match step\n\n"
        "SKILLS\nExcel, SQL, process design, vendor management\n"
    )
    body = client.post(
        "/api/candidates/text",
        json={"resume_text": resume, "name": "Single Claim", "role": "Ops Analyst"},
    ).json()

    transcript = run_interview(client, body["session_id"])
    assert len(transcript) <= 4
    assert len({q for q, _ in transcript}) == len(transcript)
    assert client.get(f"/api/sessions/{body['session_id']}").json()["state"] == "COMPLETE"


def test_partial_interview_still_produces_a_low_score(client):
    """An abandoned interview must not look like a good one."""
    body = onboard(client, name="Walked Away")
    client.post(
        "/api/web/message",
        json={"session_id": body["session_id"], "text": ANSWERS[0]},
    )
    graph = client.get(f"/api/recruiter/candidates/{body['candidate_id']}").json()
    assert graph["competence_score"] < 0.70
    assert graph["badge"] != "verified"


# ---------------------------------------------------------------------------
# whatsapp
# ---------------------------------------------------------------------------


def test_whatsapp_join_code_then_answer(client):
    body = onboard(client, name="WhatsApp Priya", phone="+919812340000")
    phone = "whatsapp:+919812340000"

    joined = client.post(
        "/api/webhooks/twilio", data={"From": phone, "Body": body["join_code"]}
    )
    assert joined.status_code == 200
    assert "<Message>" in joined.text

    answered = client.post(
        "/api/webhooks/twilio", data={"From": phone, "Body": ANSWERS[0]}
    )
    assert answered.status_code == 200
    assert "<Message>" in answered.text

    state = client.get(f"/api/sessions/{body['session_id']}").json()
    assert state["questions_asked"] >= 2


def test_whatsapp_unknown_number_gets_instructions_not_an_error(client):
    resp = client.post(
        "/api/webhooks/twilio",
        data={"From": "whatsapp:+919899999999", "Body": "hello?"},
    )
    assert resp.status_code == 200
    assert "could not find an active verification" in resp.text


def test_whatsapp_bad_join_code_is_handled(client):
    resp = client.post(
        "/api/webhooks/twilio", data={"From": "whatsapp:+919899999998", "Body": "ZZZZZZ"}
    )
    assert resp.status_code == 200
    assert "code" in resp.text.lower()


# ---------------------------------------------------------------------------
# /api/dev/simulate — the demo fallback
# ---------------------------------------------------------------------------


def test_simulate_runs_the_whole_pipeline_in_one_call(client):
    resp = client.post(
        "/api/dev/simulate",
        json={"resume_text": RESUME, "name": "Simulated Priya", "role": "Support Lead",
              "answers": ANSWERS},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["questions_asked"] >= 1
    assert body["transcript"]
    graph = body["graph"]
    assert graph["claims"]
    assert 0.0 <= graph["competence_score"] <= 1.0
    assert graph["badge"]

    # and it is persisted, so it shows up on the dashboard
    listed = client.get("/api/recruiter/candidates").json()
    assert body["candidate_id"] in {row["id"] for row in listed}


def test_simulate_works_with_no_answers_supplied(client):
    resp = client.post(
        "/api/dev/simulate", json={"resume_text": RESUME, "name": "Placeholder Answers"}
    )
    assert resp.status_code == 200
    assert resp.json()["graph"]["claims"]


def test_fixture_endpoint_serves_the_sample_graph(client):
    body = client.get("/api/dev/fixture").json()
    assert body["candidate"]["name"] == "Priya R."
    assert len(body["claims"]) == 3


def test_llm_diagnostics_reports_fallback_usage(client):
    body = client.get("/api/dev/llm").json()
    assert body["mode"] == "fixture"
    assert body["fallbacks"] > 0        # fixture mode served every call
    assert body["calls"] == 0           # and never touched the network
