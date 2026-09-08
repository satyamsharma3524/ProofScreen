"""
ARTIFACT 3 — the question policy. Pure function of the session's evidence, so
it is testable without a database or a model.
"""

from __future__ import annotations

from dataclasses import dataclass

from api.config import settings
from api.engine import scoring, signals
from api.engine.orchestrator import ClaimState, plan_next
from api.engine.question import TransferOperator
from api.schemas import Dimension, DimensionScore, ProbeLevel

# P2-04's tests drive a real interview rather than a synthetic ClaimState, so
# they need the shared helpers. Everything above this line stays pure.
from tests.conftest import EVASIVE_ANSWERS, STRONG_ANSWERS, onboard, run_interview


@dataclass
class FakeClaim:
    id: str
    claim_type: str
    text: str = "a claim"
    metric: str | None = None
    order_index: int = 0


def state(
    claim_id: str,
    claim_type: str,
    weight: float,
    *,
    levels: set[ProbeLevel] | None = None,
    scores: dict[Dimension, int] | None = None,
    claim_score: int = 0,
    answers: int = 0,
    last_signals: int = 5,
    order: int = 0,
) -> ClaimState:
    dimensions = {
        d: DimensionScore(
            dimension=d,
            score=(scores or {}).get(d, 0),
            probed=d in (scores or {}),
        )
        for d in scoring.DIMENSION_ORDER
    }
    return ClaimState(
        claim=FakeClaim(claim_id, claim_type, order_index=order),
        weight=weight,
        claim_family="bpo_operations",
        levels_used=set(levels or set()),
        dimensions=dimensions,
        score=claim_score,
        answers=answers,
        last_answer_signals=last_signals,
    )


# ---------------------------------------------------------------------------
# phase 1 — breadth before depth
# ---------------------------------------------------------------------------


def test_first_question_is_operational_on_the_heaviest_claim():
    states = [
        state("c1", "team_handling", 25.0),
        state("c2", "aht_control", 15.0, order=1),
    ]
    plan = plan_next(states, 0)
    assert plan.claim.id == "c1"
    assert plan.probe_level is ProbeLevel.OPERATIONAL


def test_every_claim_is_touched_before_any_is_deepened():
    """An unprobed claim scores zero and would silently sink the candidate, so
    breadth comes first once active claim momentum streak (MIN_STREAK=2) is satisfied."""
    states = [
        state("c1", "team_handling", 25.0, levels={ProbeLevel.OPERATIONAL}, answers=2, claim_score=20),
        state("c2", "aht_control", 15.0, order=1),
    ]
    plan = plan_next(states, 2)
    assert plan.claim.id == "c2"
    assert plan.probe_level is ProbeLevel.OPERATIONAL


def test_claim_momentum_maintains_focus_on_active_claim():
    """MIN_STREAK=2 maintains focus on an active claim after its first answer
    rather than hopping immediately to another untouched claim."""
    states = [
        state("c1", "team_handling", 25.0, levels={ProbeLevel.OPERATIONAL}, answers=1, claim_score=10),
        state("c2", "aht_control", 15.0, order=1),
    ]
    plan = plan_next(states, 1)
    assert plan.claim.id == "c1"
    assert "1/2" in plan.reason


def test_plan_next_forensic_claim_momentum():
    from api.engine.orchestrator import plan_next_forensic

    s1 = state("c1", "team_handling", 25.0)
    s1.moves_used = {"OPERATING_CONTEXT"}
    s1.answers = 1

    s2 = state("c2", "aht_control", 15.0, order=1)
    s2.moves_used = set()

    states = [s1, s2]
    plan = plan_next_forensic(states, 1)
    assert plan is not None
    assert plan.claim.id == "c1"
    assert "claim momentum streak" in plan.reason


# ---------------------------------------------------------------------------
# phase 2 — gap-driven depth
# ---------------------------------------------------------------------------


def test_depth_targets_the_heaviest_unprobed_dimension():
    """Gaps are chased in weight order, not enum order."""
    states = [
        state(
            "c1", "team_handling", 25.0,
            levels={ProbeLevel.OPERATIONAL},
            scores={Dimension.EXECUTION: 90, Dimension.KNOWLEDGE: 80},
            answers=1, claim_score=40,
        )
    ]
    plan = plan_next(states, 1)
    assert plan.target_dimension is Dimension.PROBLEM_SOLVING
    assert plan.target_dimension in signals.dimensions_for_level(plan.probe_level)


def test_problem_solving_gap_selects_an_incident_probe():
    """Once the heavier gaps are covered, PROBLEM_SOLVING is only reachable by an
    INCIDENT probe."""
    states = [
        state(
            "c1", "team_handling", 25.0,
            levels={ProbeLevel.OPERATIONAL},
            scores={
                Dimension.EXECUTION: 90,
                Dimension.KNOWLEDGE: 90,
            },
            answers=2, claim_score=60,
        )
    ]
    plan = plan_next(states, 2)
    assert plan.target_dimension is Dimension.PROBLEM_SOLVING
    assert plan.probe_level is ProbeLevel.INCIDENT


def test_heavier_claims_are_deepened_first():
    states = [
        state("c1", "team_handling", 25.0, levels={ProbeLevel.OPERATIONAL}, answers=1, claim_score=30),
        state("c2", "aht_control", 15.0, levels={ProbeLevel.OPERATIONAL}, answers=1, claim_score=30, order=1),
    ]
    assert plan_next(states, 2).claim.id == "c1"


# ---------------------------------------------------------------------------
# the adaptive stop
# ---------------------------------------------------------------------------


def test_saturated_claims_are_left_alone():
    states = [
        state("c1", "team_handling", 25.0, levels={ProbeLevel.OPERATIONAL},
              answers=1, claim_score=scoring.SATURATION_AT),
        state("c2", "aht_control", 15.0, levels={ProbeLevel.OPERATIONAL},
              answers=1, claim_score=20, order=1),
    ]
    assert plan_next(states, 2).claim.id == "c2"


    # Every non-transfer plan leaves it unset.
    healthy = [state("c1", "team_handling", 25.0, levels={ProbeLevel.VALIDATION},
                     answers=1, last_signals=5)]
    assert plan_next(healthy, 1).transfer is None


def test_interview_ends_when_every_claim_is_done():
    all_levels = set(signals.PROBE_ORDER)
    states = [state("c1", "team_handling", 25.0, levels=all_levels, answers=5, claim_score=90)]
    assert plan_next(states, 5) is None


def test_budget_is_respected():
    states = [state("c1", "team_handling", 25.0)]
    assert plan_next(states, settings.max_questions) is None


def test_policy_is_deterministic():
    """The same session must always ask the same questions in the same order,
    or 'explainable' is a marketing word."""
    def fresh():
        return [
            state("c1", "team_handling", 25.0, levels={ProbeLevel.VALIDATION},
                  scores={Dimension.SPECIFICITY: 50}, answers=1, claim_score=30),
            state("c2", "aht_control", 15.0, levels={ProbeLevel.VALIDATION},
                  answers=1, claim_score=30, order=1),
        ]
    results = {
        (plan_next(fresh(), 2).claim.id, plan_next(fresh(), 2).probe_level)
        for _ in range(25)
    }
    assert len(results) == 1


def test_no_claim_and_level_pair_is_ever_asked_twice():
    states = [state("c1", "team_handling", 25.0, levels={ProbeLevel.OPERATIONAL}, answers=1)]
    for _ in range(5):
        plan = plan_next(states, 1)
        assert plan is not None
        assert plan.probe_level not in states[0].levels_used
        states[0].levels_used.add(plan.probe_level)
    assert plan_next(states, 6) is None


# ---------------------------------------------------------------------------
# P2-04 — the repair turn
#
# A non-answer earns ONE more go at the same probe, and that turn does not
# consume the interview budget. Spending a budgeted question on "ok" is how a
# 12-question interview becomes an 8-question one, and the claim it was about
# then scores zero for reasons that have nothing to do with competence.
# ---------------------------------------------------------------------------


def _questions(client, session_id: str):
    import asyncio

    from sqlalchemy import select

    from api.db import SessionLocal
    from api.models import Question

    async def rows():
        async with SessionLocal() as db:
            return list(
                (
                    await db.execute(
                        select(Question)
                        .where(Question.session_id == session_id)
                        .order_by(Question.order_index)
                    )
                ).scalars().all()
            )

    return asyncio.run(rows())


def test_a_non_answer_issues_a_repair_question(client, monkeypatch):
    monkeypatch.setattr(settings, "repair_turn", True)
    body = onboard(client, name="Repair Issued", phone="+919810090001")
    client.post(f"/api/dev/sessions/{body['session_id']}/start")
    before = client.get(f"/api/sessions/{body['session_id']}").json()

    client.post(
        f"/api/dev/sessions/{body['session_id']}/answer", json={"text": "ok"}
    )
    rows = _questions(client, body["session_id"])
    repairs = [q for q in rows if q.is_repair]

    assert len(repairs) == 1, f"expected one repair, got {len(repairs)}"
    assert repairs[0].probe_level == before["current_probe_level"], (
        "a repair must stay on the SAME probe level — it is the same question "
        "asked again, not a new one"
    )
    assert repairs[0].source == "repair"


def test_a_repair_does_not_consume_budget(client, monkeypatch):
    """The task, in one assertion."""
    monkeypatch.setattr(settings, "repair_turn", True)
    body = onboard(client, name="Repair Budget", phone="+919810090002")
    client.post(f"/api/dev/sessions/{body['session_id']}/start")
    before = client.get(f"/api/sessions/{body['session_id']}").json()["questions_asked"]

    client.post(f"/api/dev/sessions/{body['session_id']}/answer", json={"text": "ok"})
    after = client.get(f"/api/sessions/{body['session_id']}").json()["questions_asked"]

    assert after == before, f"the repair spent budget: {before} -> {after}"


def test_a_repair_makes_no_model_call(client, monkeypatch):
    """`REPAIR_PROMPTS` is a fixed table. The candidate has just demonstrated
    low engagement; there is nothing to word creatively, and a model call costs
    latency against the +20% guardrail."""
    monkeypatch.setattr(settings, "repair_turn", True)
    body = onboard(client, name="Repair No LLM", phone="+919810090003")
    client.post(f"/api/dev/sessions/{body['session_id']}/start")
    calls = client.get("/api/dev/llm").json()["calls"]

    client.post(f"/api/dev/sessions/{body['session_id']}/answer", json={"text": "ok"})

    assert client.get("/api/dev/llm").json()["calls"] == calls


def test_only_one_repair_per_question(client, monkeypatch):
    """Without the cap a disengaged candidate loops inside one probe forever and
    the interview never terminates — the same class of bug as unbounded
    regeneration, which is why that cap is structural too."""
    monkeypatch.setattr(settings, "repair_turn", True)
    body = onboard(client, name="Repair Cap", phone="+919810090004")
    client.post(f"/api/dev/sessions/{body['session_id']}/start")

    first = client.get(f"/api/sessions/{body['session_id']}").json()
    client.post(f"/api/dev/sessions/{body['session_id']}/answer", json={"text": "ok"})
    client.post(f"/api/dev/sessions/{body['session_id']}/answer", json={"text": "ok"})

    rows = _questions(client, body["session_id"])
    same_probe = [
        q for q in rows
        if q.claim_id == first["current_claim_id"]
        and q.probe_level == first["current_probe_level"]
    ]
    assert sum(1 for q in same_probe if q.is_repair) == 1, (
        "a second non-answer produced a second repair — the interview can no "
        "longer terminate for a disengaged candidate"
    )


def test_the_repair_answer_is_still_scored(client, monkeypatch):
    """Only BUDGET and the STALL COUNT treat a repair differently. The answer
    itself is a real answer from the candidate and suppressing its evidence
    would lose signal."""
    monkeypatch.setattr(settings, "repair_turn", True)
    body = onboard(client, name="Repair Scored", phone="+919810090005")
    client.post(f"/api/dev/sessions/{body['session_id']}/start")
    client.post(f"/api/dev/sessions/{body['session_id']}/answer", json={"text": "ok"})
    client.post(
        f"/api/dev/sessions/{body['session_id']}/answer",
        json={"text": STRONG_ANSWERS[0]},
    )

    graph = client.get(f"/api/recruiter/candidates/{body['candidate_id']}").json()
    scored = [c for c in graph["claims"] if (c.get("claim_score") or 0) > 0]
    assert scored, "the repair answer produced no evidence at all"


def test_repair_answers_do_not_count_toward_the_stall_signal(client, monkeypatch):
    """R5 in the phase plan. `stalled` is "answers >= 2 and the last produced
    nothing", and `stalled` is what makes a claim transfer_available. Counting
    repairs there means a candidate who says "ok" twice stalls a claim that was
    never properly probed, and TRANSFER fires on a claim with no evidence to
    transfer."""
    monkeypatch.setattr(settings, "repair_turn", True)
    import asyncio

    from api.db import SessionLocal
    from api.engine import orchestrator
    from api.models import ChatSession

    body = onboard(client, name="Repair Stall", phone="+919810090006")
    client.post(f"/api/dev/sessions/{body['session_id']}/start")
    client.post(f"/api/dev/sessions/{body['session_id']}/answer", json={"text": "ok"})
    client.post(f"/api/dev/sessions/{body['session_id']}/answer", json={"text": "ok"})

    async def states():
        async with SessionLocal() as db:
            session = await db.get(ChatSession, body["session_id"])
            return await orchestrator.build_claim_states(db, session)

    for state in asyncio.run(states()):
        assert state.answers <= 1, (
            f"{state.claim.id} counted {state.answers} answers after one probe "
            f"and one repair — the repair leaked into the stall signal"
        )


def test_order_index_stays_dense_and_unique_with_repairs(client, monkeypatch):
    """`order_index` used to mean two things — transcript position AND budget
    consumed — because it was set from `questions_asked`. A turn that does not
    consume budget splits them apart, so this asserts the half that stayed."""
    monkeypatch.setattr(settings, "repair_turn", True)
    body = onboard(client, name="Repair Ordering", phone="+919810090007")
    run_interview(client, body["session_id"], EVASIVE_ANSWERS)

    rows = _questions(client, body["session_id"])
    indexes = [q.order_index for q in rows]
    assert any(q.is_repair for q in rows), "no repairs fired, so this proves nothing"
    assert len(indexes) == len(set(indexes)), f"duplicate order_index: {indexes}"
    assert indexes == list(range(len(indexes))), f"gaps in the transcript: {indexes}"


def test_repair_flag_off_reproduces_the_phase_one_interview(client, monkeypatch):
    from api.config import settings

    monkeypatch.setattr(settings, "repair_turn", False)
    body = onboard(client, name="Repair Disabled", phone="+919810090008")
    run_interview(client, body["session_id"], EVASIVE_ANSWERS)

    rows = _questions(client, body["session_id"])
    assert not any(q.is_repair for q in rows)
    assert [q.order_index for q in rows] == list(range(len(rows)))
