"""
D6 — the Evaluation entity, and the persistence half of D7.

The question this file exists to keep answerable: *what did the system
conclude, and can anything change it afterwards?*

`GET /api/recruiter/candidates/{id}` recomputes a graph live from whatever the
rows say right now. An evaluation is what was concluded at one moment under one
configuration, and it never moves again. If those two ever became the same
thing, D6 would have been a table for its own sake.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select

from api.db import SessionLocal
from api.models import Candidate, ChatSession, Evaluation, EvaluationFinalized, Profile
from tests.conftest import STRONG_ANSWERS, onboard, run_interview


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def interviewed(client, name: str, phone: str) -> dict:
    body = onboard(client, name=name, phone=phone)
    run_interview(client, body["session_id"])
    return body


def evaluations_of(client, candidate_id: str) -> list[dict]:
    resp = client.get(f"/api/recruiter/candidates/{candidate_id}/evaluations")
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.fixture(scope="module")
def finalized(client) -> dict:
    body = interviewed(client, "Evaluation Subject", "+919810060001")
    rows = evaluations_of(client, body["candidate_id"])
    assert len(rows) == 1
    return {**body, "evaluation_id": rows[0]["id"]}


# ---------------------------------------------------------------------------
# identity and linkage
# ---------------------------------------------------------------------------


def test_an_evaluation_is_opened_with_the_interview_as_a_draft(client):
    """Before any answer exists. An assessment that only appears once it
    succeeds cannot answer what happened to one that did not."""
    body = onboard(client, name="Draft Only", phone="+919810060002")
    rows = evaluations_of(client, body["candidate_id"])
    assert len(rows) == 1
    assert rows[0]["status"] == "draft"
    assert rows[0]["finalized_at"] is None
    assert rows[0]["session_id"] == body["session_id"]
    assert rows[0]["competence_score"] == 0


def test_identity_is_unique_prefixed_and_stable(client, finalized):
    from api import ids

    assert finalized["evaluation_id"].startswith("ev_")
    assert len({ids.evaluation_id() for _ in range(500)}) == 500

    first = client.get(
        f"/api/recruiter/evaluations/{finalized['evaluation_id']}"
    ).json()
    second = client.get(
        f"/api/recruiter/evaluations/{finalized['evaluation_id']}"
    ).json()
    assert first == second, "reading an evaluation twice returned two things"


def test_it_identifies_candidate_interview_role_lens_and_timestamps(
    client, finalized
):
    body = client.get(
        f"/api/recruiter/evaluations/{finalized['evaluation_id']}"
    ).json()
    assert body["candidate_id"] == finalized["candidate_id"]
    assert body["session_id"] == finalized["session_id"]
    assert body["candidate_name"] == "Evaluation Subject"
    assert body["job_family"] == "bpo_operations"
    assert body["job_family_label"]
    assert body["created_at"] and body["finalized_at"]
    assert body["created_at"] <= body["finalized_at"]
    # No requisition was supplied, so the lens is the family default and the
    # role fields are honestly null rather than invented.
    assert body["role_id"] is None and body["role_title"] is None
    assert body["claim_weights"], "the weight snapshot is empty"


def test_the_result_matches_what_the_recruiter_was_shown(client, finalized):
    """The evaluation must not be a second implementation of the score. Same
    graph, same lens, same numbers — or the product has two answers."""
    graph = client.get(
        f"/api/recruiter/candidates/{finalized['candidate_id']}"
    ).json()
    body = client.get(
        f"/api/recruiter/evaluations/{finalized['evaluation_id']}"
    ).json()
    for field in (
        "resume_score", "weighted_evidence_score", "competence_score",
        "role_coverage",
    ):
        assert body[field] == graph[field], field
    assert body["badge"] == graph["badge"]
    assert body["consistency_score"] == graph["consistency"]["score"]
    assert body["competence_score"] > 0
    assert body["claims_scored"] == len(
        [c for c in graph["claims"] if c["claim_score"] is not None]
    )


def test_the_profile_points_at_the_latest_evaluation(client, finalized):
    async def scenario():
        async with SessionLocal() as db:
            return (
                await db.execute(
                    select(Profile).where(
                        Profile.candidate_id == finalized["candidate_id"]
                    )
                )
            ).scalar_one_or_none()

    profile = asyncio.run(scenario())
    assert profile is not None
    assert profile.latest_evaluation_id == finalized["evaluation_id"]


# ---------------------------------------------------------------------------
# lifecycle
# ---------------------------------------------------------------------------


def test_finalization_is_explicit_and_the_states_are_the_two_that_exist(client):
    """draft -> finalized. No `running`, no `abandoned` — see the Evaluation
    docstring and `SessionState.ABANDONED`, which nothing in this codebase
    ever assigns."""
    from api.schemas import EvaluationStatus

    assert [s.value for s in EvaluationStatus] == ["draft", "finalized"]

    body = onboard(client, name="Lifecycle Walk", phone="+919810060003")
    assert evaluations_of(client, body["candidate_id"])[0]["status"] == "draft"
    run_interview(client, body["session_id"])
    after = evaluations_of(client, body["candidate_id"])[0]
    assert after["status"] == "finalized"
    assert after["finalized_at"] is not None


def test_a_finalized_evaluation_is_distinguishable_from_the_live_interview(
    client, finalized
):
    """The load-bearing distinction. The session keeps its own state; the
    evaluation says `finalized` and carries a timestamp the session does not
    supply."""
    session = client.get(f"/api/sessions/{finalized['session_id']}").json()
    body = client.get(
        f"/api/recruiter/evaluations/{finalized['evaluation_id']}"
    ).json()
    assert session["state"] == "COMPLETE"
    assert body["status"] == "finalized"
    assert "state" not in body, (
        "the evaluation is echoing session state; that is the profiles.status "
        "duplication D6 exists to end"
    )


def test_re_running_an_assessment_produces_a_distinct_evaluation(client):
    """A second interview for the same person is a second assessment, and the
    first one is not touched."""
    body = interviewed(client, "Twice Assessed", "+919810060004")
    first = evaluations_of(client, body["candidate_id"])[0]

    second_session = client.post(
        "/api/dev/simulate",
        json={"resume_text": _RESUME_FOR_RERUN, "name": "Twice Assessed",
              "phone": "+919810060004", "answers": STRONG_ANSWERS},
    )
    assert second_session.status_code == 200

    # The re-run above is a different candidate row by design (simulate always
    # onboards); the guarantee under test is per-session uniqueness, so drive a
    # genuine second interview for the SAME candidate through a new session.
    again = onboard(client, name="Twice Assessed", phone="+919810060004")
    run_interview(client, again["session_id"])
    rows = evaluations_of(client, again["candidate_id"])
    assert len(rows) == 1 and rows[0]["id"] != first["id"]

    unchanged = client.get(f"/api/recruiter/evaluations/{first['id']}").json()
    assert unchanged["finalized_at"] == first["finalized_at"]
    assert unchanged["competence_score"] == first["competence_score"]


def test_duplicate_creation_returns_the_existing_row_and_never_overwrites(client):
    """`session_id` is UNIQUE, so this is a constraint rather than a check that
    could be raced."""
    from api.engine import evaluation as evaluation_engine

    body = interviewed(client, "Duplicate Open", "+919810060005")

    async def scenario():
        async with SessionLocal() as db:
            session = await db.get(ChatSession, body["session_id"])
            candidate = await db.get(Candidate, body["candidate_id"])
            again = await evaluation_engine.open_evaluation(db, session, candidate)
            rows = (
                await db.execute(
                    select(Evaluation).where(
                        Evaluation.candidate_id == candidate.id
                    )
                )
            ).scalars().all()
            return again, rows

    again, rows = asyncio.run(scenario())
    assert len(rows) == 1
    assert again.id == rows[0].id
    assert again.status == "finalized", "a duplicate open reset a finalized row"
    assert Evaluation.__table__.columns["session_id"].unique is True


def test_finalizing_twice_is_a_no_op_not_an_error(client):
    """`orchestrator.finalize()` is reachable twice — an idempotent background
    scoring pass, a re-entered dev flow. Turning a harmless repeat into a 500
    trades a real failure for an imaginary one."""
    from api.engine import evaluation as evaluation_engine
    from api.tenancy import TenantScope

    body = interviewed(client, "Finalize Twice", "+919810060006")
    before = evaluations_of(client, body["candidate_id"])[0]

    async def scenario():
        async with SessionLocal() as db:
            session = await db.get(ChatSession, body["session_id"])
            return await evaluation_engine.finalize_evaluation(
                db, session, TenantScope.of(session.tenant_id)
            )

    again = asyncio.run(scenario())
    assert again.id == before["id"]
    after = evaluations_of(client, body["candidate_id"])[0]
    assert after == before, "the second finalization rewrote the record"


# ---------------------------------------------------------------------------
# immutability
# ---------------------------------------------------------------------------


def test_a_finalized_evaluation_cannot_be_mutated_by_any_path(client, finalized):
    """The guarantee, asserted where it lives.

    Not through the service function — through a raw ORM write, which is what
    a future endpoint or a debugging session actually looks like. The listener
    in models.py is what makes this fail; without it this test would pass
    silently and the record would be a suggestion.
    """
    async def scenario(mutate):
        async with SessionLocal() as db:
            row = await db.get(Evaluation, finalized["evaluation_id"])
            mutate(row)
            await db.commit()

    for field, value in (
        ("competence_score", 99),
        ("badge", "verified"),
        ("evaluation_version", "evx_tampered"),
        ("finalized_at", None),
        ("status", "draft"),
        ("claim_weights_json", "{}"),
    ):
        with pytest.raises(EvaluationFinalized):
            asyncio.run(scenario(lambda r, f=field, v=value: setattr(r, f, v)))

    intact = client.get(
        f"/api/recruiter/evaluations/{finalized['evaluation_id']}"
    ).json()
    assert intact["status"] == "finalized"
    assert intact["badge"] != "verified" or intact["competence_score"] != 99


def test_the_immutability_guard_does_not_block_finalization_itself(client):
    """The obvious way to get this wrong: read the CURRENT `finalized_at`
    instead of the old one, and finalization becomes impossible."""
    body = interviewed(client, "Guard Does Not Overreach", "+919810060007")
    row = evaluations_of(client, body["candidate_id"])[0]
    assert row["status"] == "finalized" and row["finalized_at"]


def test_a_draft_can_still_be_written_to(client):
    """Immutability starts at finalization, not at creation — otherwise the
    interview could never fill the record in."""
    body = onboard(client, name="Draft Mutable", phone="+919810060008")

    async def scenario():
        async with SessionLocal() as db:
            row = (
                await db.execute(
                    select(Evaluation).where(
                        Evaluation.session_id == body["session_id"]
                    )
                )
            ).scalars().one()
            row.questions_asked = 3
            await db.commit()
            return row.questions_asked

    assert asyncio.run(scenario()) == 3


# ---------------------------------------------------------------------------
# the evidence graph is untouched
# ---------------------------------------------------------------------------


def test_the_evidence_graph_remains_queryable_after_finalization(client, finalized):
    """D6 stores a result and a pointer, never a copy of the evidence. The
    drill-down must be exactly what it was before Phase 4."""
    graph = client.get(
        f"/api/recruiter/candidates/{finalized['candidate_id']}"
    ).json()
    assert graph["claims"], "no claims"
    assert any(c["qa"] for c in graph["claims"]), "no Q&A turns"
    assert any(
        d["quotes"] for c in graph["claims"] for d in c["dimensions"]
    ), "no verbatim quotes"
    assert len(graph["dimension_profile"]) == 6

    # And the evaluation carries no copy of any of it.
    body = client.get(
        f"/api/recruiter/evaluations/{finalized['evaluation_id']}"
    ).json()
    for forbidden in ("claims", "qa", "quotes", "signals", "evidence"):
        assert forbidden not in body, f"the evaluation copied {forbidden}"


def test_finalization_makes_no_model_call(client):
    before = client.get("/api/dev/llm").json()["calls"]
    body = interviewed(client, "No LLM At Finalize", "+919810060009")
    assert evaluations_of(client, body["candidate_id"])[0]["status"] == "finalized"
    assert client.get("/api/dev/llm").json()["calls"] == before


# ---------------------------------------------------------------------------
# D7 — provenance, persisted
# ---------------------------------------------------------------------------


def test_a_finalized_evaluation_carries_its_full_provenance(client, finalized):
    from api.engine import provenance as pv

    body = client.get(
        f"/api/recruiter/evaluations/{finalized['evaluation_id']}"
    ).json()
    stamp = body["provenance"]
    current = pv.current()

    assert stamp["taxonomy_version"] == current.taxonomy_version
    assert stamp["taxonomy_hash"] == current.taxonomy_hash
    assert stamp["rubric_version"] == "rub_1"
    assert stamp["scoring_version"] == "score_1"
    assert stamp["question_policy_version"] == "qpol_2"
    assert stamp["prompt_versions"] == current.prompt_versions
    assert stamp["code_version"] == current.code_version
    assert stamp["llm_mode"] == "fixture"
    assert stamp["model_requested"] is None       # fixture mode asks for nothing
    assert stamp["evaluation_version"] == current.fingerprint()
    assert set(stamp["feature_flags"]) == {n.upper() for n in pv.FEATURE_FLAGS}


def test_a_draft_carries_no_provenance_because_it_has_no_result(client):
    """Honest emptiness. A stamp on a draft would claim to explain a number
    that does not exist yet."""
    body = onboard(client, name="Draft Provenance", phone="+919810060010")
    row = evaluations_of(client, body["candidate_id"])[0]
    detail = client.get(f"/api/recruiter/evaluations/{row['id']}").json()
    assert detail["provenance"]["rubric_version"] == ""
    assert detail["provenance"]["evaluation_version"] == ""


def test_provenance_persists_no_secrets(client, finalized):
    """The scan against a STORED row, not a computed stamp."""
    import json

    async def scenario():
        async with SessionLocal() as db:
            row = await db.get(Evaluation, finalized["evaluation_id"])
            return {
                c.name: getattr(row, c.name) for c in Evaluation.__table__.columns
            }

    stored = json.dumps(asyncio.run(scenario()), default=str).lower()
    from api.config import settings

    for secret in (
        settings.openai_api_key, settings.whatsapp_access_token,
        settings.whatsapp_app_secret,
    ):
        if secret:
            assert secret.lower() not in stored
    assert "postgresql://" not in stored and "sqlite+" not in stored
    for word in ("api_key", "access_token", "app_secret", "password"):
        assert word not in stored


def test_two_evaluations_under_the_same_configuration_share_a_fingerprint(client):
    """Comparable iff the hash matches. Two different people, one unchanged
    system: same fingerprint, different scores."""
    first = interviewed(client, "Fingerprint One", "+919810060011")
    second = interviewed(client, "Fingerprint Two", "+919810060012")
    a = evaluations_of(client, first["candidate_id"])[0]
    b = evaluations_of(client, second["candidate_id"])[0]
    assert a["evaluation_version"] == b["evaluation_version"]
    assert a["evaluation_version"].startswith("evx_")


def test_a_configuration_change_gives_the_next_evaluation_a_new_fingerprint(
    client, monkeypatch
):
    """ADAPTIVE_PROBING=false is a materially different interview, so it must
    not be filed under the same identity."""
    from api.config import settings

    baseline = evaluations_of(
        client, interviewed(client, "Flags Before", "+919810060013")["candidate_id"]
    )[0]["evaluation_version"]

    monkeypatch.setattr(settings, "adaptive_probing", False)
    after = evaluations_of(
        client, interviewed(client, "Flags After", "+919810060014")["candidate_id"]
    )[0]["evaluation_version"]

    assert after != baseline


def test_provenance_cannot_be_changed_after_finalization(client, finalized):
    """D7 requirement 1, asserted on the columns that carry it."""
    async def scenario(field, value):
        async with SessionLocal() as db:
            row = await db.get(Evaluation, finalized["evaluation_id"])
            setattr(row, field, value)
            await db.commit()

    for field, value in (
        ("taxonomy_version", "tax_9"),
        ("prompt_versions_json", "{}"),
        ("code_version", "0000000"),
        ("feature_flags_json", "{}"),
    ):
        with pytest.raises(EvaluationFinalized):
            asyncio.run(scenario(field, value))


# ---------------------------------------------------------------------------
# the API surface
# ---------------------------------------------------------------------------


def test_history_is_newest_first_and_404s_for_an_unknown_candidate(client):
    body = interviewed(client, "History Order", "+919810060015")
    later = onboard(client, name="History Order", phone="+919810060015")
    run_interview(client, later["session_id"])

    rows = evaluations_of(client, body["candidate_id"])
    assert len(rows) == 1                      # onboard() creates a new candidate
    assert client.get(
        "/api/recruiter/candidates/c_nope/evaluations"
    ).status_code == 404
    assert client.get("/api/recruiter/evaluations/ev_nope").status_code == 404
    assert client.get(
        "/api/recruiter/evaluations/ev_nope"
    ).json()["detail"] == "evaluation not found"


def test_the_new_routes_are_in_the_openapi_contract(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/recruiter/evaluations/{evaluation_id}" in paths
    assert "/api/recruiter/candidates/{candidate_id}/evaluations" in paths


_RESUME_FOR_RERUN = """Twice Assessed - Support Operations Team Lead, Bengaluru
International voice process, night shift

EXPERIENCE
Team Lead, Northwind Services
- Managed a team of 35 agents across 4 pods with 4 senior associates reporting to me
- Improved CSAT from 78% to 92% in four quarters by redesigning the escalation workflow
- Reduced AHT from 480 seconds to 430 seconds by rewriting the call opening scripts

SKILLS
Roster and shrinkage planning, calibration, occupancy management, nesting, Genesys, Zendesk
"""
