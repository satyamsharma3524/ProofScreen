"""
D10 — evaluation history and decision audit.

The audit trail has to answer six questions in one call: what the evaluation
concluded, when it was finalized, what decision was made, when, whether it was
later changed, and what it was changed from.

Two design choices are under test as much as the behaviour is.

  * THERE IS NO EVENTS TABLE. `candidate_outcomes` has been append-only by
    shape since P1-09 and is already correct; the evaluation's lifecycle is
    two columns that already exist. An `evaluation_events` table would have
    duplicated both, which is what PRODUCTION_READINESS 5 warns against.
  * A LATER DECISION NEVER TOUCHES THE ASSESSMENT. The score, the badge and
    `why_ranked` must read exactly the same after a rejection as before it —
    otherwise M4a would correlate the system with itself, which is the
    circularity guard P1-10 already exists to protect.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from api.db import SessionLocal
from api.models import CandidateOutcome
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


def decide(client, candidate_id: str, **payload):
    resp = client.post(
        f"/api/recruiter/candidates/{candidate_id}/outcome", json=payload
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def history(client, evaluation_id: str) -> dict:
    resp = client.get(f"/api/recruiter/evaluations/{evaluation_id}/history")
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# the first decision
# ---------------------------------------------------------------------------


def test_a_first_decision_creates_history_linked_to_the_evaluation(client):
    subject = interviewed(client, "Audit First", "+919810080001")
    before = history(client, subject["evaluation_id"])
    assert before["decisions_recorded"] == 0
    assert before["current_decision"] is None
    assert [e["kind"] for e in before["entries"]] == [
        "evaluation_created", "evaluation_finalized"
    ]

    written = decide(
        client, subject["candidate_id"],
        decision="shortlisted", stage="phone screen",
        decided_by="recruiter@example.com", note="strong on ownership",
    )
    assert written["evaluation_id"] == subject["evaluation_id"]

    after = history(client, subject["evaluation_id"])
    assert after["decisions_recorded"] == 1
    assert after["current_decision"] == "shortlisted"
    entry = after["entries"][-1]
    assert entry["kind"] == "decision"
    assert entry["decision"] == "shortlisted"
    assert entry["previous_decision"] is None
    assert entry["decided_by"] == "recruiter@example.com"
    assert entry["stage"] == "phone screen"
    assert entry["outcome_id"] == written["id"]
    assert entry["evaluation_id"] == subject["evaluation_id"]


def test_the_history_answers_all_six_audit_questions(client):
    """One call, not a reconstruction from three."""
    subject = interviewed(client, "Audit Complete", "+919810080002")
    decide(client, subject["candidate_id"], decision="shortlisted")
    decide(client, subject["candidate_id"], decision="rejected", note="budget")

    body = history(client, subject["evaluation_id"])
    assert body["competence_score"] > 0                       # what it concluded
    assert body["finalized_at"]                               # when
    assert body["current_decision"] == "rejected"             # what was decided
    assert body["entries"][-1]["at"]                          # when
    assert body["entries"][-1]["previous_decision"] == "shortlisted"  # changed from
    assert body["decisions_recorded"] == 2                    # changed at all


# ---------------------------------------------------------------------------
# changing a decision
# ---------------------------------------------------------------------------


def test_changing_a_decision_preserves_the_previous_one(client):
    """The previous state is never destroyed — a new row is added beside it."""
    subject = interviewed(client, "Audit Change", "+919810080003")
    first = decide(client, subject["candidate_id"], decision="shortlisted")
    second = decide(client, subject["candidate_id"], decision="rejected",
                    note="withdrew")

    assert second["id"] != first["id"]
    # `previous_decision` is deliberately NOT on OutcomeOut: the outcome
    # endpoints are the Phase 1 contract and stay exactly as they were. The
    # audit surface is the history route, and that is where it is asserted
    # below.
    assert "previous_decision" not in second

    rows = client.get(
        f"/api/recruiter/candidates/{subject['candidate_id']}/outcomes"
    ).json()
    assert [r["decision"] for r in rows] == ["shortlisted", "rejected"]
    assert rows[0]["id"] == first["id"], "the earlier decision was rewritten"

    body = history(client, subject["evaluation_id"])
    decisions = [e for e in body["entries"] if e["kind"] == "decision"]
    assert [d["decision"] for d in decisions] == ["shortlisted", "rejected"]
    assert decisions[0]["previous_decision"] is None
    assert decisions[1]["previous_decision"] == "shortlisted"


def test_a_repeated_identical_decision_creates_no_duplicate_record(client):
    """Idempotence, not an audit gap. A double-clicked button is not a second
    decision; a changed note IS, because the reason is what a later reader
    needs."""
    subject = interviewed(client, "Audit Idempotent", "+919810080004")
    first = decide(client, subject["candidate_id"], decision="shortlisted",
                   stage="phone screen")
    again = decide(client, subject["candidate_id"], decision="shortlisted",
                   stage="phone screen")
    assert again["id"] == first["id"]
    assert history(client, subject["evaluation_id"])["decisions_recorded"] == 1

    # A different note is a different decision record.
    changed = decide(client, subject["candidate_id"], decision="shortlisted",
                     stage="phone screen", note="second look")
    assert changed["id"] != first["id"]
    assert history(client, subject["evaluation_id"])["decisions_recorded"] == 2


def test_a_genuine_progression_always_appends(client):
    """shortlisted -> interviewed -> offered is three rows. The dedupe must not
    swallow the ladder M4a rank-correlates against."""
    subject = interviewed(client, "Audit Ladder", "+919810080005")
    for decision in ("shortlisted", "interviewed", "offered", "hired"):
        decide(client, subject["candidate_id"], decision=decision)

    body = history(client, subject["evaluation_id"])
    assert body["decisions_recorded"] == 4
    assert body["current_decision"] == "hired"
    decisions = [e["decision"] for e in body["entries"] if e["kind"] == "decision"]
    assert decisions == ["shortlisted", "interviewed", "offered", "hired"]


# ---------------------------------------------------------------------------
# ordering and separation
# ---------------------------------------------------------------------------


def test_history_ordering_is_deterministic(client):
    """Read three times, get the same order three times — including when
    several decisions land in the same commit and share a timestamp."""
    subject = interviewed(client, "Audit Ordering", "+919810080006")
    for decision in ("shortlisted", "interviewed", "rejected"):
        decide(client, subject["candidate_id"], decision=decision)

    reads = [history(client, subject["evaluation_id"]) for _ in range(3)]
    orders = {tuple((e["kind"], e.get("outcome_id")) for e in r["entries"])
              for r in reads}
    assert len(orders) == 1, "the audit trail reordered between reads"

    first = reads[0]["entries"]
    assert first[0]["kind"] == "evaluation_created"
    assert first[1]["kind"] == "evaluation_finalized"
    assert all(e["kind"] == "decision" for e in first[2:])
    assert [e["at"] for e in first] == sorted(e["at"] for e in first)


def test_lifecycle_and_decisions_stay_distinguishable(client):
    """Requirement 6. Finalized evidence is one kind of fact; what a human
    later decided is another, and the response must never blur them."""
    subject = interviewed(client, "Audit Separation", "+919810080007")
    decide(client, subject["candidate_id"], decision="rejected")

    body = history(client, subject["evaluation_id"])
    finalized = next(e for e in body["entries"] if e["kind"] == "evaluation_finalized")
    decision = next(e for e in body["entries"] if e["kind"] == "decision")

    assert finalized["competence_score"] is not None
    assert finalized["decision"] is None and finalized["outcome_id"] is None
    assert decision["competence_score"] is None
    assert decision["badge"] is None
    # The headline on the response is the EVALUATION's, not the decision's.
    detail = client.get(
        f"/api/recruiter/evaluations/{subject['evaluation_id']}"
    ).json()
    assert body["competence_score"] == detail["competence_score"]
    assert body["badge"] == detail["badge"]


def test_a_later_decision_changes_no_score_and_no_explanation(client):
    """THE CIRCULARITY GUARD, extended to `why_ranked`.

    P1-10 already asserts a decision moves no score. D10 adds the sentence the
    recruiter reads on the ranked list: an explanation that started citing
    outcomes would be the system explaining itself with its own consequences.
    """
    subject = interviewed(client, "Audit No Feedback", "+919810080008")

    def summary():
        rows = client.get("/api/recruiter/candidates").json()["candidates"]
        return next(r for r in rows if r["id"] == subject["candidate_id"])

    before_graph = client.get(
        f"/api/recruiter/candidates/{subject['candidate_id']}"
    ).json()
    before_summary = summary()
    before_eval = client.get(
        f"/api/recruiter/evaluations/{subject['evaluation_id']}"
    ).json()

    decide(client, subject["candidate_id"], decision="hired", note="should move nothing")

    after_graph = client.get(
        f"/api/recruiter/candidates/{subject['candidate_id']}"
    ).json()
    assert after_graph["competence_score"] == before_graph["competence_score"]
    assert summary()["why_ranked"] == before_summary["why_ranked"]
    assert "hired" not in (summary()["why_ranked"] or "")
    assert client.get(
        f"/api/recruiter/evaluations/{subject['evaluation_id']}"
    ).json() == before_eval


# ---------------------------------------------------------------------------
# compatibility and isolation
# ---------------------------------------------------------------------------


def test_the_existing_outcome_endpoints_are_unchanged(client):
    """Same paths, same payloads, same status codes, same ordering. The only
    difference is one optional field that defaults to null."""
    subject = interviewed(client, "Audit Compat", "+919810080009")
    resp = client.post(
        f"/api/recruiter/candidates/{subject['candidate_id']}/outcome",
        json={"decision": "shortlisted", "stage": "phone screen"},
    )
    assert resp.status_code == 201
    body = resp.json()
    for field in ("id", "candidate_id", "role_id", "decision", "stage",
                  "decided_by", "note", "decided_at"):
        assert field in body
    assert body["id"].startswith("o_")

    listed = client.get(
        f"/api/recruiter/candidates/{subject['candidate_id']}/outcomes"
    )
    assert listed.status_code == 200
    assert [r["decision"] for r in listed.json()] == ["shortlisted"]


def test_a_decision_without_a_finished_interview_links_to_nothing(client):
    """Null, not an error. Recording a decision for a candidate who never
    completed an interview is a real case, and refusing it would push
    recruiters back out of the one table that falsifies the product."""
    body = onboard(client, name="Never Interviewed", phone="+919810080010")
    written = decide(client, body["candidate_id"], decision="rejected")
    assert written["evaluation_id"] is None


def test_outcome_rows_remain_append_only_in_the_database(client):
    """The P1-09 guarantee, re-asserted through the endpoint rather than
    through direct writes, now that the endpoint denormalises a field."""
    subject = interviewed(client, "Audit Append Only", "+919810080011")
    decide(client, subject["candidate_id"], decision="shortlisted")
    decide(client, subject["candidate_id"], decision="rejected")

    async def scenario():
        async with SessionLocal() as db:
            return (
                await db.execute(
                    select(CandidateOutcome)
                    .where(CandidateOutcome.candidate_id == subject["candidate_id"])
                    .order_by(CandidateOutcome.decided_at, CandidateOutcome.id)
                )
            ).scalars().all()

    rows = asyncio.run(scenario())
    assert [r.decision for r in rows] == ["shortlisted", "rejected"]
    assert rows[0].previous_decision is None
    assert rows[1].previous_decision == "shortlisted"
    assert rows[0].evaluation_id == rows[1].evaluation_id == subject["evaluation_id"]


def test_cross_tenant_history_access_is_denied(client):
    subject = interviewed(client, "Audit Isolation", "+919810080012")
    decide(client, subject["candidate_id"], decision="offered")

    other = client.post(
        "/api/dev/tenants", json={"slug": "audit-isolation", "name": "Other"}
    ).json()
    resp = client.get(
        f"/api/recruiter/evaluations/{subject['evaluation_id']}/history",
        headers={"X-API-Key": other["api_key"]},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "evaluation not found"


def test_the_finalized_evaluation_stays_immutable_through_all_of_it(client):
    """A decision is recorded against an evaluation and changes nothing about
    it — asserted on every column, not on the response."""
    from api.models import Evaluation

    subject = interviewed(client, "Audit Immutable", "+919810080013")

    async def snapshot():
        async with SessionLocal() as db:
            row = await db.get(Evaluation, subject["evaluation_id"])
            db.expunge_all()
            return {c.name: getattr(row, c.name) for c in Evaluation.__table__.columns}

    before = asyncio.run(snapshot())
    for decision in ("shortlisted", "interviewed", "rejected"):
        decide(client, subject["candidate_id"], decision=decision)
    assert asyncio.run(snapshot()) == before


def test_the_history_route_is_in_the_openapi_contract(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/recruiter/evaluations/{evaluation_id}/history" in paths
