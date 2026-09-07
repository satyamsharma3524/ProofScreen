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


def test_first_question_is_validation_on_the_heaviest_claim():
    states = [
        state("c1", "team_handling", 25.0),
        state("c2", "aht_control", 15.0, order=1),
    ]
    plan = plan_next(states, 0)
    assert plan.claim.id == "c1"
    assert plan.probe_level is ProbeLevel.VALIDATION


def test_every_claim_is_touched_before_any_is_deepened():
    """An unprobed claim scores zero and would silently sink the candidate, so
    breadth comes first once active claim momentum streak (MIN_STREAK=2) is satisfied."""
    states = [
        state("c1", "team_handling", 25.0, levels={ProbeLevel.VALIDATION}, answers=2, claim_score=20),
        state("c2", "aht_control", 15.0, order=1),
    ]
    plan = plan_next(states, 2)
    assert plan.claim.id == "c2"
    assert plan.probe_level is ProbeLevel.VALIDATION


def test_claim_momentum_maintains_focus_on_active_claim():
    """MIN_STREAK=2 maintains focus on an active claim after its first answer
    rather than hopping immediately to another untouched claim."""
    states = [
        state("c1", "team_handling", 25.0, levels={ProbeLevel.VALIDATION}, answers=1, claim_score=10),
        state("c2", "aht_control", 15.0, order=1),
    ]
    plan = plan_next(states, 1)
    assert plan.claim.id == "c1"
    assert "(1/2)" in plan.reason


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
    """Gaps are chased in weight order, not enum order: an unprobed PROCESS
    (0.238 in BPO) is worth more than an unprobed AUTHENTICITY (0.19), so it
    goes first. Weighting the tie-break is what stops the policy spending a
    question on the 0.05-weighted dimension while a heavy one sits at zero."""
    states = [
        state(
            "c1", "team_handling", 25.0,
            levels={ProbeLevel.VALIDATION},
            scores={Dimension.SPECIFICITY: 90, Dimension.METRIC_OWNERSHIP: 80},
            answers=1, claim_score=40,
        )
    ]
    plan = plan_next(states, 1)
    weights = scoring.dimension_weights_for("bpo_operations")
    assert plan.target_dimension is Dimension.PROCESS
    assert weights["PROCESS"] >= weights["AUTHENTICITY"]
    # and the level chosen is one that can actually elicit that dimension
    assert plan.target_dimension in signals.dimensions_for_level(plan.probe_level)


def test_authenticity_gap_selects_an_incident_probe():
    """Once the heavier gaps are covered, AUTHENTICITY is only reachable by an
    INCIDENT probe — the level whose whole job is 'tell me about one time'."""
    states = [
        state(
            "c1", "team_handling", 25.0,
            levels={ProbeLevel.VALIDATION},
            scores={
                Dimension.SPECIFICITY: 90,
                Dimension.METRIC_OWNERSHIP: 80,
                Dimension.PROCESS: 90,
                Dimension.CAUSAL_REASONING: 85,
                Dimension.TOOL_FAMILIARITY: 80,
                Dimension.KNOWLEDGE: 80,
                Dimension.EXECUTION: 80,
                Dimension.PROBLEM_SOLVING: 80,
                Dimension.JUDGMENT: 80,
                Dimension.OWNERSHIP: 80,
                Dimension.ADAPTABILITY: 80,
            },
            answers=1, claim_score=60,
        )
    ]
    plan = plan_next(states, 1)
    assert plan.target_dimension is Dimension.AUTHENTICITY
    assert plan.probe_level is ProbeLevel.INCIDENT


def test_the_gap_hint_always_matches_the_question_asked():
    """When the ideal level is spent, the hint must be re-pointed at what the
    chosen level can actually elicit — a mismatched hint produces a confused,
    hybrid question."""
    states = [
        state(
            "c1", "team_handling", 25.0,
            levels={ProbeLevel.VALIDATION, ProbeLevel.INCIDENT},
            scores={Dimension.SPECIFICITY: 90, Dimension.AUTHENTICITY: 0},
            answers=2, claim_score=40,
        )
    ]
    plan = plan_next(states, 2)
    covered = signals.dimensions_for_level(plan.probe_level)
    assert plan.target_dimension is None or plan.target_dimension in covered


def test_heavier_claims_are_deepened_first():
    states = [
        state("c1", "team_handling", 25.0, levels={ProbeLevel.VALIDATION}, answers=1, claim_score=30),
        state("c2", "aht_control", 15.0, levels={ProbeLevel.VALIDATION}, answers=1, claim_score=30, order=1),
    ]
    assert plan_next(states, 2).claim.id == "c1"


# ---------------------------------------------------------------------------
# the adaptive stop
# ---------------------------------------------------------------------------


def test_saturated_claims_are_left_alone():
    states = [
        state("c1", "team_handling", 25.0, levels={ProbeLevel.VALIDATION},
              answers=1, claim_score=scoring.SATURATION_AT),
        state("c2", "aht_control", 15.0, levels={ProbeLevel.VALIDATION},
              answers=1, claim_score=20, order=1),
    ]
    assert plan_next(states, 2).claim.id == "c2"


def _stalled_pair() -> list[ClaimState]:
    """c1 has stopped producing evidence; c2 is still healthy and lighter."""
    return [
        state("c1", "team_handling", 25.0, levels={ProbeLevel.VALIDATION},
              answers=2, last_signals=0, claim_score=10),
        state("c2", "aht_control", 15.0, levels={ProbeLevel.VALIDATION},
              answers=1, last_signals=6, claim_score=30, order=1),
    ]


def test_a_claim_that_stops_producing_signals_gets_one_transfer_then_is_abandoned():
    """MOVED BY P1-03, reviewed by hand — the old assertion was that a stalled
    claim is abandoned immediately, and it now buys exactly one more question.

    The original reasoning still holds for *more of the same*: asking a fifth
    recall question of someone who has said nothing for two answers wastes the
    budget. What changed is that a stall is the signal to change the KIND of
    question. The answers stopped adding evidence about what they did, which is
    exactly when asking about what they did NOT do separates a thin memory from
    a thin resume. One question, then the old behaviour resumes.
    """
    states = _stalled_pair()

    first = plan_next(states, 2)
    assert first.claim.id == "c1"
    assert first.probe_level is ProbeLevel.TRANSFER

    # Spend it, and the claim is abandoned exactly as it used to be.
    states[0].levels_used.add(ProbeLevel.TRANSFER)
    assert states[0].transfer_used
    assert states[0].exhausted
    assert plan_next(states, 3).claim.id == "c2"


def test_transfer_probe_false_reproduces_the_pre_phase_interview(monkeypatch):
    """The flag has to be a true off switch, question for question — otherwise
    there is no way to tell what the probe changed."""
    monkeypatch.setattr(settings, "transfer_probe", False)

    states = _stalled_pair()
    assert not states[0].transfer_available
    assert states[0].exhausted                      # stalled => done, as before
    assert plan_next(states, 2).claim.id == "c2"

    # And no transfer appears anywhere in a full interview.
    full = _stalled_pair()
    for index in range(2, settings.max_questions):
        plan = plan_next(full, index)
        if plan is None:
            break
        assert plan.probe_level is not ProbeLevel.TRANSFER
        assert plan.transfer is None
        next(s for s in full if s.claim.id == plan.claim.id).levels_used.add(
            plan.probe_level
        )


def test_transfer_is_selectable_but_is_not_a_rung_on_the_ladder():
    """The structural half of P1-03, and the guard that replaced the P1-00
    inertness pin. PROBE_ORDER is what makes a level selectable at all;
    LADDER_ORDER is what the ordinary walk climbs. TRANSFER must be in the
    first and absent from the second, or a claim that is still producing
    evidence gets handed a hypothetical as its "next unused level"."""
    assert ProbeLevel.TRANSFER in signals.PROBE_ORDER
    assert ProbeLevel.TRANSFER not in signals.LADDER_ORDER
    assert signals.dimensions_for_level(ProbeLevel.TRANSFER) == (
        Dimension.CAUSAL_REASONING,
        Dimension.PROCESS,
        Dimension.ADAPTABILITY,
    )

    # A healthy claim with every rung spent is finished, not transferred.
    healthy = state("c1", "team_handling", 25.0, levels=set(signals.LADDER_ORDER),
                    answers=5, last_signals=4, claim_score=40)
    assert healthy.levels_left == []
    assert not healthy.transfer_available
    assert healthy.exhausted


def test_transfer_never_opens_a_claim():
    """A claim nobody has asked about cannot be stalled, and an opening
    hypothetical would be absurd: there is no method of theirs to transfer yet.
    Belt and braces, because this is the failure that would embarrass us on the
    projector."""
    untouched = state("c1", "team_handling", 25.0, answers=0, last_signals=0)
    assert not untouched.stalled
    assert not untouched.transfer_available

    # Even with the stall counters forced, an unprobed claim is not eligible.
    forced = state("c1", "team_handling", 25.0, answers=2, last_signals=0)
    assert forced.levels_used == set()
    assert not forced.transfer_available

    states = [untouched, state("c2", "aht_control", 15.0, order=1)]
    for index in range(2):
        plan = plan_next(states, index)
        assert plan.probe_level is ProbeLevel.VALIDATION
        next(s for s in states if s.claim.id == plan.claim.id).levels_used.add(
            plan.probe_level
        )


def test_a_saturated_claim_gets_no_transfer():
    """Saturation means there is nothing left to learn. Stalling on a claim
    that already cleared the bar is not a warning sign, and spending a question
    on it takes one from a claim that still needs evidence."""
    saturated = state("c1", "team_handling", 25.0, levels={ProbeLevel.VALIDATION},
                      answers=2, last_signals=0, claim_score=scoring.SATURATION_AT)
    assert saturated.stalled
    assert not saturated.transfer_available
    assert saturated.exhausted

    states = [saturated, state("c2", "aht_control", 15.0,
                               levels={ProbeLevel.VALIDATION}, answers=1, order=1)]
    assert plan_next(states, 2).claim.id == "c2"


def test_a_stalled_claim_carries_a_spec_built_from_its_own_evidence():
    """The plan is only reproducible if the transfer spec comes out of the pure
    function too. A TRANSFER plan without one would leave `ask_next` inventing
    the substance at wording time."""
    states = _stalled_pair()
    plan = plan_next(states, 2)

    assert plan.probe_level is ProbeLevel.TRANSFER
    assert plan.transfer is not None
    # Two claims in the session, so the second one is the problem to substitute.
    assert plan.transfer.operator is TransferOperator.T1
    assert plan.transfer.target_claim_id == "c2"
    # And the hint matches what a transfer answer can actually contain.
    assert plan.target_dimension in signals.dimensions_for_level(ProbeLevel.TRANSFER)

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
    states = [state("c1", "team_handling", 25.0, levels={ProbeLevel.VALIDATION}, answers=1)]
    for _ in range(4):
        plan = plan_next(states, 1)
        assert plan is not None
        assert plan.probe_level not in states[0].levels_used
        states[0].levels_used.add(plan.probe_level)
    assert plan_next(states, 5) is None


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
