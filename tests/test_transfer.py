"""
D1 — the TRANSFER probe.

A memorised resume can be recited but not transferred. TRANSFER holds the
candidate's own reasoning constant and substitutes the problem, so the material
never comes from a per-cohort scenario library — it comes from their own claims.

Selection (P1-02) is pure Python and family-blind by signature; wording (P1-01,
P1-04) is the only place a job family is allowed to appear. These tests hold
that line: `tests/test_policy.py` owns when a transfer is asked.
"""

from __future__ import annotations

import asyncio
import inspect
import re
from dataclasses import dataclass

from api.config import settings
from api.engine.orchestrator import NO_METHOD, select_transfer
from api.engine.question import (
    FALLBACK_QUESTIONS,
    _brief_for,
    PROBE_BRIEFS,
    TRANSFER_FALLBACKS,
    TRANSFER_INSTRUCTIONS,
    TransferOperator,
    TransferSpec,
    fallback_question,
    generate_question,
)
from tests.conftest import EVASIVE_ANSWERS, onboard, run_interview
from api.schemas import (
    AnswerSignals,
    CausalLink,
    MetricDefinition,
    ProbeLevel,
    ProcessStep,
)


@dataclass
class FakeClaim:
    id: str
    text: str
    claim_type: str = "team_handling"
    metric: str | None = None
    order_index: int = 0


# ---------------------------------------------------------------------------
# P1-01 — brief and offline fallback
# ---------------------------------------------------------------------------


def test_transfer_question_poses_an_unseen_situation():
    """The whole mechanism: the question must be about something the candidate
    has NOT described. Every path — spec-less, T1 and T3 — has to supply the
    counterfactual, because a transfer question that restates their own story
    is just a sixth recall probe."""
    claim = "Improved CSAT from 78% to 92% by redesigning the escalation workflow"

    plain = fallback_question(ProbeLevel.TRANSFER, claim).question
    assert "Suppose" in plain

    t1 = fallback_question(
        ProbeLevel.TRANSFER,
        claim,
        transfer=TransferSpec(
            operator=TransferOperator.T1,
            their_method="redesigning the escalation workflow",
            other_problem="AHT",
            target_claim_id="cl_2",
        ),
    ).question
    # The unseen situation is the OTHER claim's subject, and their own method
    # is carried across intact.
    assert "taken on AHT instead" in t1
    assert "redesigning the escalation workflow" in t1

    t3 = fallback_question(
        ProbeLevel.TRANSFER,
        claim,
        transfer=TransferSpec(
            operator=TransferOperator.T3,
            their_method="the escalation redesign",
        ),
    ).question
    assert "worse instead of better" in t3

    # All three are anchored to the claim, like every other fallback: "suppose
    # that had gone the other way" is unanswerable on WhatsApp if the candidate
    # cannot tell which of their three resume lines "that" is.
    for text in (plain, t1, t3):
        assert text.startswith('On "Improved CSAT')

    # And none of them asks for a number about something that never happened.
    for text in (plain, t1, t3):
        lowered = text.lower()
        assert "how many" not in lowered
        assert "what number" not in lowered


def test_transfer_question_works_with_no_api_key():
    """Fixture mode is the mode the demo falls back to. Both TRANSFER lookups
    are bare dict subscripts on the offline path, so a missing entry is a
    KeyError on the projector, not a degraded question."""
    assert settings.openai_api_key in (None, "")

    assert ProbeLevel.TRANSFER in PROBE_BRIEFS
    assert ProbeLevel.TRANSFER in FALLBACK_QUESTIONS
    assert set(TRANSFER_FALLBACKS) == set(TransferOperator)
    assert set(TRANSFER_INSTRUCTIONS) == set(TransferOperator)

    spec = TransferSpec(
        operator=TransferOperator.T1,
        their_method="the weekly calibration",
        other_problem="shrinkage running at 18%",
        target_claim_id="cl_3",
    )
    generated = asyncio.run(
        generate_question(
            "Managed a team of 35 agents across 4 pods",
            ProbeLevel.TRANSFER,
            claim_type="team_handling",
            job_family="bpo_operations",
            transfer=spec,
        )
    )
    # The policy owns the level even when the model is absent.
    assert generated.probe_level is ProbeLevel.TRANSFER
    assert "shrinkage running at 18%" in generated.question


def test_the_transfer_brief_forbids_asking_for_numbers():
    """A transfer answer legitimately contains no quantities and no tools used
    (docs/TRANSFER_DESIGN_AUDIT.md §3). The brief must say so, or the model asks for
    figures about a hypothetical and invites invention."""
    brief = PROBE_BRIEFS[ProbeLevel.TRANSFER]
    assert "Do NOT ask for numbers" in brief
    assert "has NOT solved" in brief


def test_transfer_wording_never_scores_presentation():
    """Guardrail. The transfer probe adds new prompt text, and new prompt text
    is where a presentation judgement would slip in."""
    corpus = " ".join(
        [PROBE_BRIEFS[ProbeLevel.TRANSFER], FALLBACK_QUESTIONS[ProbeLevel.TRANSFER]]
        + [t.template for t in TRANSFER_FALLBACKS.values()]
        + [t.template for t in TRANSFER_INSTRUCTIONS.values()]
    ).lower()
    for banned in (
        "accent", "fluen", "grammar", "confiden", "personality", "articulate",
        "communication skill", "professionally",
    ):
        assert banned not in corpus


# ---------------------------------------------------------------------------
# P1-02 — select_transfer()
# ---------------------------------------------------------------------------


def signals(
    *,
    causal: list[tuple[str | None, str | None, str | None]] | None = None,
    steps: list[str] | None = None,
    metrics: list[tuple[str, str | None]] | None = None,
) -> AnswerSignals:
    return AnswerSignals(
        causal_links=[
            CausalLink(cause=c, action=a, outcome=o) for c, a, o in (causal or [])
        ],
        process_steps=[ProcessStep(step=s) for s in (steps or [])],
        metric_definitions=[
            MetricDefinition(metric=m, how_measured=h) for m, h in (metrics or [])
        ],
    )


def test_t1_used_when_a_second_claim_exists():
    claim = FakeClaim("cl_1", "Improved CSAT from 78% to 92%")
    others = [
        FakeClaim("cl_2", "Reduced AHT from 480 to 430 seconds", order_index=1),
        FakeClaim("cl_3", "Managed a team of 35 agents", order_index=2),
    ]
    spec = select_transfer(
        claim,
        signals(causal=[("billing complaints", "redesigned the escalation workflow", "CSAT rose")]),
        others,
    )
    assert spec.operator is TransferOperator.T1
    assert spec.their_method == "redesigned the escalation workflow"
    # Both halves come from the candidate's own resume — that is the point.
    assert spec.target_claim_id == "cl_2"
    # And the substituted half is the SUBJECT of that claim, not the claim
    # line: swapping in "Reduced AHT from 480 to 430 seconds" would hand the
    # candidate an already-solved problem complete with its own solution.
    assert spec.other_problem == "AHT"


def test_t3_used_when_it_does_not():
    claim = FakeClaim("cl_1", "Improved CSAT from 78% to 92%")
    spec = select_transfer(claim, signals(steps=["ran a weekly calibration"]), [])
    assert spec.operator is TransferOperator.T3
    assert spec.their_method == "ran a weekly calibration"
    assert spec.other_problem == ""
    assert spec.target_claim_id is None

    # The claim itself is not its own second problem.
    assert select_transfer(claim, signals(), [claim]).operator is TransferOperator.T3


def test_transfer_selection_is_family_invariant():
    """The architectural guarantee. Identical evidence in two unrelated
    industries must produce a byte-identical operator and target: `job_family`
    is absent from the signature, so a family branch would have to change the
    contract to exist. Family may change the wording; never the question."""
    evidence = signals(
        causal=[("the queue backed up", "moved two people off email onto voice", "it cleared")],
        steps=["reviewed the backlog every morning"],
    )

    bpo = select_transfer(
        FakeClaim("cl_1", "Cut the backlog", claim_type="team_handling"),
        evidence,
        [FakeClaim("cl_2", "Held shrinkage at 8%", claim_type="workforce_planning", order_index=1)],
    )
    swe = select_transfer(
        FakeClaim("cl_1", "Cut the backlog", claim_type="system_ownership"),
        evidence,
        [FakeClaim("cl_2", "Held shrinkage at 8%", claim_type="reliability", order_index=1)],
    )

    assert bpo == swe
    assert "job_family" not in inspect.signature(select_transfer).parameters


def test_transfer_selection_is_deterministic_and_order_blind():
    """Same inputs, same spec, every run — including when the caller hands the
    other claims over in a different order, since the target must be a function
    of the claims and not of the list they arrived in."""
    claim = FakeClaim("cl_1", "Improved CSAT from 78% to 92%")
    evidence = signals(causal=[(None, "redesigned the workflow", "CSAT rose")])
    a = FakeClaim("cl_2", "Reduced AHT", order_index=1)
    b = FakeClaim("cl_3", "Managed 35 agents", order_index=2)

    specs = {select_transfer(claim, evidence, [a, b]) for _ in range(25)}
    assert len(specs) == 1
    assert select_transfer(claim, evidence, [b, a]) == select_transfer(claim, evidence, [a, b])


def test_method_falls_back_when_a_claim_produced_no_method():
    """A stalled claim may have produced nothing usable. The probe still has to
    be askable, because stalling is exactly when it is offered."""
    spec = select_transfer(FakeClaim("cl_1", "Improved CSAT"), signals(), [])
    assert spec.their_method == "the approach you described"
    assert fallback_question(
        ProbeLevel.TRANSFER, "Improved CSAT", transfer=spec
    ).question.count("Suppose") == 1


def test_a_complete_causal_chain_outranks_a_partial_one():
    """Evidential strength, not list order: the strongest statement that they
    actually did the thing is the one worth transferring."""
    spec = select_transfer(
        FakeClaim("cl_1", "Improved CSAT"),
        signals(causal=[(None, "sent a survey", None), ("complaints", "rewrote the script", "CSAT rose")]),
        [],
    )
    assert spec.their_method == "rewrote the script"


def test_a_method_that_is_not_a_phrase_is_rejected_not_truncated():
    """The method slot sits in a fixed frame — "Using X, where would you
    start?" — so a value that does not fit there grammatically has to be
    refused. Truncating instead produced "Using Billing complaints were about
    40% of our negative feedback, so we, where would you start?".

    This is the COMMON path offline: the heuristic extractor that runs in
    fixture mode returns whole sentences in `causal_links[].action`. Referring
    to the method is honest; quoting a severed clause is not.
    """
    unusable = [
        # Too long to be a phrase.
        "rebuilt the entire escalation and callback workflow across all four pods "
        "including the weekend roster and the quality calibration cadence",
        # A clause with its own subject.
        "I had 35 agents in four pods and each pod had a senior associate",
        # Two clauses joined.
        "complaints rose, so we redesigned it",
    ]
    for action in unusable:
        spec = select_transfer(
            FakeClaim("cl_1", "Improved CSAT"),
            signals(causal=[(None, action, None)]),
            [],
        )
        assert spec.their_method == NO_METHOD, action

    # A real method phrase is taken verbatim, untruncated.
    spec = select_transfer(
        FakeClaim("cl_1", "Improved CSAT"),
        signals(causal=[(None, "moved two people off email onto voice", None)]),
        [],
    )
    assert spec.their_method == "moved two people off email onto voice"


def test_every_slot_reads_correctly_in_the_frame_it_lands_in():
    """The two slots have different jobs and different rules: the subject is
    the material, so it is trimmed; the method is a quote, so it is refused if
    it does not fit. Both must produce a question with no dangling fragment."""
    spec = select_transfer(
        FakeClaim("cl_1", "Improved CSAT from 78% to 92% by redesigning the workflow"),
        signals(causal=[("complaints", "redesigned the escalation workflow", "CSAT rose")]),
        [FakeClaim("cl_2", "Reduced AHT from 480 to 430 seconds by rewriting scripts", order_index=1)],
    )
    question = fallback_question(
        ProbeLevel.TRANSFER, "Improved CSAT from 78% to 92%", transfer=spec
    ).question
    assert question.endswith("?")
    assert ", ," not in question
    assert "  " not in question
    assert "Suppose you had taken on AHT instead." in question
    assert "Using redesigned the escalation workflow, where would you start?" in question



# ---------------------------------------------------------------------------
# P1-04 — selection wired into question generation
# ---------------------------------------------------------------------------


def test_the_transfer_brief_carries_the_planners_choice_not_the_planners_reasoning():
    """The wording call is handed the filled slots and nothing else. `basis` is
    for the log and the dashboard: telling the model how the planner decided
    invites it to relitigate the decision, and the planner owns what is asked."""
    spec = TransferSpec(
        operator=TransferOperator.T1,
        their_method="the weekly calibration",
        other_problem="shrinkage running at 18%",
        target_claim_id="cl_3",
        basis="T1 substitute-the-problem: their method on cl_1 applied to cl_3",
    )
    brief = _brief_for(ProbeLevel.TRANSFER, spec)
    assert "the weekly calibration" in brief
    assert "shrinkage running at 18%" in brief
    assert spec.basis not in brief
    assert "T1 substitute" not in brief

    # Every other level is untouched, and TRANSFER without a spec degrades to
    # the bare brief rather than raising.
    for level in ProbeLevel:
        assert _brief_for(level, None) == PROBE_BRIEFS[level]
    assert _brief_for(ProbeLevel.OUTCOME, spec) == PROBE_BRIEFS[ProbeLevel.OUTCOME]


def test_a_stalled_claim_produces_a_transfer_question_about_another_claim(client):
    """End to end, in fixture mode. A candidate who goes evasive stalls their
    heaviest claim, and the interview responds by asking about a problem they
    never described — sourced from another line of their own resume.

    This is the demo moment: the question is unanswerable from a memorised
    resume, and nobody authored a scenario for it.
    """
    body = onboard(client, name="Stalling Candidate", phone="+919810000077")
    run_interview(client, body["session_id"], answers=EVASIVE_ANSWERS)
    graph = client.get(f"/api/recruiter/candidates/{body['candidate_id']}").json()

    claims = graph["claims"]
    assert len(claims) >= 2, "need a second claim for T1 to be selectable"

    transfers = [
        (claim, turn)
        for claim in claims
        for turn in claim["qa"]
        if turn["probe_level"] == ProbeLevel.TRANSFER.value
    ]
    asked = [t["probe_level"] for c in claims for t in c["qa"]]
    assert transfers, f"no transfer probe was ever asked: {asked}"

    # Exactly one per claim, never more — the stall exemption is spent, not a
    # licence to keep asking.
    probed_ids = [claim["id"] for claim, _ in transfers]
    assert len(probed_ids) == len(set(probed_ids))

    probed_claim, turn = transfers[0]
    question = turn["question"]
    assert "Suppose" in question

    # The substituted problem is another claim of this candidate's, not an
    # authored scenario: some claim other than the one being probed has to be
    # recognisable in the question.
    others = [c["text"] for c in claims if c["id"] != probed_claim["id"]]
    assert any(
        _significant_words(other) & _significant_words(question) for other in others
    ), f"{question!r} borrowed nothing from {others!r}"

    # A transfer answer carries no quantities and no tools used, and that is
    # correct rather than a deficiency. It must not have cost the claim
    # anything: scoring runs the rubric over the UNION of a claim's signals, so
    # a transfer answer can only add.
    assert probed_claim["claim_score"] is not None
    assert probed_claim["claim_score"] >= 0


def _significant_words(text: str) -> set[str]:
    """Content words only — the transfer wording rephrases around the borrowed
    fragment, so an exact-substring assertion would be testing the template."""
    stop = {
        "the", "a", "an", "of", "to", "and", "in", "on", "for", "with", "from",
        "by", "at", "as", "was", "were", "is", "are", "it", "that", "this",
        "you", "your", "my", "i", "we", "would", "suppose", "but", "not",
        "described", "one", "where", "start", "using", "wasn't", "problem",
    }
    # >2, not >3: the borrowed fragment is often a short metric acronym — AHT,
    # CSAT, SLA, p95 — and filtering those out would make this vacuous.
    words = re.findall(r"[a-z0-9%]+", text.lower())
    return {w for w in words if len(w) > 2 and w not in stop}


def test_the_substituted_subject_carries_no_outcome_and_no_method():
    """A resume line is a RESULT: "<verb> <subject> from <A> to <B> by
    <method>". Substituting the whole line asks the candidate to take on a
    problem that is already solved, in a sentence that hands them the solution.
    Only the subject survives — and the trim reads the claim's own text, so no
    job family is needed to do it."""
    cases = {
        "Improved CSAT from 78% to 92% in four quarters by redesigning the workflow": "CSAT",
        "Reduced AHT from 480 seconds to 430 seconds by rewriting the scripts": "AHT",
        "Cut p95 latency by 40% by adding a read replica": "p95 latency",
        "Grew ARR from $2M to $5M": "ARR",
        "Led the payments migration": "the payments migration",
    }
    for text, expected in cases.items():
        spec = select_transfer(
            FakeClaim("cl_1", "Something else"),
            signals(),
            [FakeClaim("cl_2", text, order_index=1)],
        )
        assert spec.other_problem == expected, text


def test_a_long_subject_is_cut_on_a_clause_boundary():
    """Slot values are read mid-sentence. A word-boundary cut is not a
    clause-boundary cut: "by rewriting the" is a dangling fragment that reads
    as a broken string, which is worse than a shorter question."""
    long_claim = (
        "Managed a team of 35 agents across 4 pods with 4 senior associates "
        "reporting to me and a floor of 200 during the peak season"
    )
    spec = select_transfer(
        FakeClaim("cl_1", "Something else"),
        signals(),
        [FakeClaim("cl_2", long_claim, order_index=1)],
    )
    assert len(spec.other_problem) <= 70
    assert "..." not in spec.other_problem
    assert spec.other_problem.split()[-1].lower() not in {
        "a", "an", "the", "and", "or", "by", "for", "from", "to", "of", "in",
        "on", "at", "with", "during",
    }


def test_a_trailing_appositive_is_not_part_of_the_subject():
    """"Owned the payments service reliability, holding error budget under
    0.1%" is a subject plus the result they got on it. Substituting the whole
    thing tells the candidate how it went before asking them to reason."""
    spec = select_transfer(
        FakeClaim("cl_1", "Something else"),
        signals(),
        [
            FakeClaim(
                "cl_2",
                "Owned the payments service reliability, holding error budget under 0.1%",
                order_index=1,
            )
        ],
    )
    assert spec.other_problem == "the payments service reliability"
