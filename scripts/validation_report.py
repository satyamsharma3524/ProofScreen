"""
P1-11 — the validation report.  NO MODEL CALL IN THIS FILE.

    python scripts/validation_report.py

Computes every metric in `docs/PHASE_1_SUCCESS_METRICS.md` from stored rows,
per cohort and overall.

WHY THIS SCRIPT IS THE POINT OF PHASE 1
---------------------------------------
Everything else ProofScreen produces is the system measuring itself.
`resume_score` 59 beside `competence_score` 14 is *divergence*, and divergence
is a demo — it shows the two numbers disagree, never which one was right.
M4 is the only metric that answers that, because it is the only one that
correlates against a decision a human made.

TWO RULES THIS FILE ENFORCES AGAINST ITSELF
-------------------------------------------
1. **Withhold, never estimate.** Below `MINIMUM_N` decided candidates a cohort
   prints `insufficient data` and no correlation. A Spearman coefficient over
   four candidates is worse than no number: it looks like evidence.

2. **Publish whichever way it points.** The metrics document pre-commits to
   publishing M4a before seeing it. A negative correlation is a finding about
   the method and must be reported as one — a number you only publish when it
   flatters you is not a metric. This script has no branch that hides a result.

Spearman is implemented here rather than imported: scipy is not a dependency
and one rank correlation does not earn one.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from api.engine import evidence as evidence_engine  # noqa: E402
from api.engine import signals as signal_rubrics  # noqa: E402
from api.models import (  # noqa: E402
    Candidate,
    CandidateOutcome,
    ChatSession,
    Claim,
    ClaimScore,
    Profile,
    Question,
    Response,
)
from api.schemas import (  # noqa: E402
    OutcomeDecision,
    ProbeLevel,
    ValidationCohort,
    ValidationOut,
)
from api.taxonomy import MIN_TERMS, match_family  # noqa: E402

MINIMUM_N = 30
GOLDEN_PATH = Path(__file__).resolve().parents[1] / "tests" / "data" / "routing_golden.json"

# The ordinal the whole of M4 rests on. Index in OutcomeDecision, worst to best.
DECISION_RANK = {d.value: i for i, d in enumerate(OutcomeDecision)}
SHORTLISTED_OR_BETTER = DECISION_RANK["shortlisted"]


# ---------------------------------------------------------------------------
# pure statistics
# ---------------------------------------------------------------------------


def _ranks(values: list[float]) -> list[float]:
    """Fractional ranks, ties averaged. Ties matter here: competence scores
    cluster, and integer ranking would invent an order the data does not have."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        shared = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = shared
        i = j + 1
    return ranks


def spearman(xs: list[float], ys: list[float]) -> float | None:
    """Rank correlation. None when undefined rather than 0.0 — a flat variable
    has no correlation, and reporting 0.0 would read as "no relationship found"
    when the truth is "not computable"."""
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    rx, ry = _ranks(xs), _ranks(ys)
    n = len(rx)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    dy = math.sqrt(sum((b - my) ** 2 for b in ry))
    if dx == 0 or dy == 0:
        return None
    return round(num / (dx * dy), 4)


def median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def quantile(values: list[float], q: float) -> float | None:
    """Linear-interpolation quantile, so the IQR of a small pool is not lumpy."""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    pos = q * (len(ordered) - 1)
    low = math.floor(pos)
    high = math.ceil(pos)
    if low == high:
        return float(ordered[int(pos)])
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


def precision_at_k(ranked_ids: list[str], positives: set[str], k: int = 5) -> float | None:
    """Of the top k by a score, how many were shortlisted or better.

    None when fewer than k candidates have a decision: precision@5 over three
    candidates is a different metric wearing the same name.
    """
    if len(ranked_ids) < k:
        return None
    top = ranked_ids[:k]
    return round(sum(1 for cid in top if cid in positives) / k, 4)


# ---------------------------------------------------------------------------
# the snapshot
# ---------------------------------------------------------------------------


@dataclass
class Snapshot:
    candidates: dict[str, Candidate] = field(default_factory=dict)
    profiles: dict[str, Profile] = field(default_factory=dict)
    sessions: dict[str, ChatSession] = field(default_factory=dict)
    claims_by_candidate: dict[str, list[Claim]] = field(default_factory=dict)
    claim_scores: dict[str, ClaimScore] = field(default_factory=dict)
    questions: list[Question] = field(default_factory=list)
    responses_by_question: dict[str, Response] = field(default_factory=dict)
    outcomes_by_candidate: dict[str, list[CandidateOutcome]] = field(default_factory=dict)

    def candidate_of_session(self, session_id: str) -> str | None:
        for candidate_id, session in self.sessions.items():
            if session.id == session_id:
                return candidate_id
        return None

    def answered_in_order(self, claim_id: str) -> list[Response]:
        """This claim's answers, in the order they were given."""
        out: list[Response] = []
        for question in sorted(self.questions, key=lambda q: q.order_index):
            if question.claim_id != claim_id:
                continue
            response = self.responses_by_question.get(question.id)
            if response is not None:
                out.append(response)
        return out

    def stalled_claims(self) -> set[str]:
        """Claims the adaptive stop gave up on, by the ORCHESTRATOR's rule:
        at least two answers, and the last one produced no signals.

        Deliberately not `claim_scores.score == 0` — a claim can earn signals
        early and stall later, so the score-based proxy under-counts and makes
        M1b (a correctness invariant) measure the wrong denominator.
        """
        stalled: set[str] = set()
        for claim_id in {q.claim_id for q in self.questions}:
            answers = self.answered_in_order(claim_id)
            if len(answers) >= 2 and (answers[-1].signals_found or 0) == 0:
                stalled.add(claim_id)
        return stalled

    def latest_decision(self, candidate_id: str) -> str | None:
        """A candidate's FINAL position, not their best.

        Someone shortlisted and then rejected was rejected — taking the maximum
        would score the system against an outcome that got reversed.
        """
        rows = self.outcomes_by_candidate.get(candidate_id) or []
        if not rows:
            return None
        return sorted(rows, key=lambda r: (r.decided_at, r.id))[-1].decision


async def collect(db: AsyncSession) -> Snapshot:
    """One batched read of everything the report needs. No model call."""
    snap = Snapshot()
    snap.candidates = {
        c.id: c for c in (await db.execute(select(Candidate))).scalars().all()
    }
    if not snap.candidates:
        return snap

    snap.profiles = {
        p.candidate_id: p for p in (await db.execute(select(Profile))).scalars().all()
    }
    for session in (
        await db.execute(select(ChatSession).order_by(ChatSession.started_at))
    ).scalars().all():
        snap.sessions[session.candidate_id] = session
    for claim in (await db.execute(select(Claim))).scalars().all():
        snap.claims_by_candidate.setdefault(claim.candidate_id, []).append(claim)
    snap.claim_scores = {
        s.claim_id: s for s in (await db.execute(select(ClaimScore))).scalars().all()
    }
    snap.questions = list(
        (await db.execute(select(Question).order_by(Question.order_index))).scalars().all()
    )
    for response in (await db.execute(select(Response))).scalars().all():
        snap.responses_by_question[response.question_id] = response
    for outcome in (await db.execute(select(CandidateOutcome))).scalars().all():
        snap.outcomes_by_candidate.setdefault(outcome.candidate_id, []).append(outcome)
    return snap


# ---------------------------------------------------------------------------
# M4 — the metric Phase 1 exists to produce.  SHARED WITH THE ENDPOINT.
# ---------------------------------------------------------------------------


def _cohort_m4(
    snap: Snapshot, candidate_ids: list[str], job_family: str, minimum_n: int
) -> ValidationCohort:
    decided = [cid for cid in candidate_ids if snap.latest_decision(cid) is not None]
    n = len(decided)

    if n < minimum_n:
        # WITHHOLD, never estimate. A correlation over a handful of candidates
        # looks like evidence and is not.
        return ValidationCohort(job_family=job_family, n_decided=n, sufficient=False)

    competence = [float(snap.profiles[c].competence_score) for c in decided if c in snap.profiles]
    resume = [float(snap.profiles[c].resume_score) for c in decided if c in snap.profiles]
    decisions = [
        float(DECISION_RANK[snap.latest_decision(c)])
        for c in decided
        if c in snap.profiles
    ]

    positives = {
        c for c in decided
        if DECISION_RANK[snap.latest_decision(c)] >= SHORTLISTED_OR_BETTER
    }
    by_competence = sorted(
        (c for c in decided if c in snap.profiles),
        key=lambda c: -snap.profiles[c].competence_score,
    )
    by_resume = sorted(
        (c for c in decided if c in snap.profiles),
        key=lambda c: -snap.profiles[c].resume_score,
    )

    # M4c — the case study. Top-quartile by resume, bottom-quartile by
    # competence, and the recruiter rejected them: the candidate ProofScreen
    # exists to catch, counted rather than anecdoted.
    resume_cut = quantile([float(snap.profiles[c].resume_score) for c in decided if c in snap.profiles], 0.75)
    comp_cut = quantile(competence, 0.25)
    inversions = 0
    if resume_cut is not None and comp_cut is not None:
        for c in decided:
            profile = snap.profiles.get(c)
            if profile is None:
                continue
            if (
                profile.resume_score >= resume_cut
                and profile.competence_score <= comp_cut
                and snap.latest_decision(c) == OutcomeDecision.rejected.value
            ):
                inversions += 1

    return ValidationCohort(
        job_family=job_family,
        n_decided=n,
        sufficient=True,
        competence_correlation=spearman(competence, decisions),
        resume_correlation=spearman(resume, decisions),
        competence_precision_at_5=precision_at_k(by_competence, positives),
        resume_precision_at_5=precision_at_k(by_resume, positives),
        inversions_caught=inversions,
    )


def build_report(snap: Snapshot, minimum_n: int = MINIMUM_N) -> ValidationOut:
    """M4, per cohort and overall. The single implementation P1-12 also serves."""
    by_family: dict[str, list[str]] = {}
    for cid, candidate in snap.candidates.items():
        by_family.setdefault(candidate.job_family or "general", []).append(cid)

    return ValidationOut(
        generated_at=datetime.now(timezone.utc),
        minimum_n=minimum_n,
        overall=_cohort_m4(snap, list(snap.candidates), "ALL", minimum_n),
        cohorts=[
            _cohort_m4(snap, ids_, family, minimum_n)
            for family, ids_ in sorted(by_family.items())
        ],
    )


# ---------------------------------------------------------------------------
# M1, M2, M3, M5 — printed by the script; not part of ValidationOut
# ---------------------------------------------------------------------------


def compute_m1(snap: Snapshot) -> dict:
    """Transfer reach and completion. M1b is a correctness invariant, not a
    target: below 100% the probe is not reaching the population it exists for
    and every other transfer number is measuring the wrong candidates."""
    transfer_qs = [q for q in snap.questions if q.probe_level == ProbeLevel.TRANSFER.value]
    completed = [s for s in snap.sessions.values() if s.completed_at is not None]
    sessions_with_transfer = {q.session_id for q in transfer_qs}

    substantive = 0
    for question in transfer_qs:
        response = snap.responses_by_question.get(question.id)
        if response and not evidence_engine.is_non_answer(response.answer_text):
            substantive += 1

    stalled = snap.stalled_claims()
    stalled_with_transfer = {q.claim_id for q in transfer_qs if q.claim_id in stalled}

    return {
        "transfer_questions": len(transfer_qs),
        "completed_sessions": len(completed),
        "m1a_reach_pct": round(
            100 * len(sessions_with_transfer & {s.id for s in completed})
            / max(len(completed), 1), 1
        ),
        "m1b_stalled_claims": len(stalled),
        "m1b_reach_on_stalled_pct": (
            round(100 * len(stalled_with_transfer) / len(stalled), 1) if stalled else None
        ),
        "m1c_completion_pct": (
            round(100 * substantive / len(transfer_qs), 1) if transfer_qs else None
        ),
    }


def compute_m2(snap: Snapshot) -> dict:
    """Marginal contribution and separation.

    M2b is the real success measure. A probe producing equal evidence from
    strong and weak candidates adds cost and no signal, whatever its volume —
    which is why C1 forbids optimising M2a.
    """
    transfer_qs = {
        q.id: q for q in snap.questions if q.probe_level == ProbeLevel.TRANSFER.value
    }
    by_claim: dict[str, list[Question]] = {}
    for question in snap.questions:
        by_claim.setdefault(question.claim_id, []).append(question)

    deltas: list[float] = []
    for claim_id, questions in by_claim.items():
        if not any(q.id in transfer_qs for q in questions):
            continue
        with_transfer, without = [], []
        for question in questions:
            response = snap.responses_by_question.get(question.id)
            if response is None:
                continue
            sig = evidence_engine.signals_of(response.signals_json)
            with_transfer.append(sig)
            if question.id not in transfer_qs:
                without.append(sig)
        if not without:
            continue
        base = signal_rubrics.total_signals(signal_rubrics.merge_signals(without))
        full = signal_rubrics.total_signals(signal_rubrics.merge_signals(with_transfer))
        if base > 0:
            deltas.append(100.0 * (full - base) / base)

    # M2b: mean transfer signals_found, top vs bottom tercile by competence.
    scored = sorted(
        ((snap.profiles[c].competence_score, c) for c in snap.candidates if c in snap.profiles),
        key=lambda pair: pair[0],
    )
    ratio = None
    if len(scored) >= 3:
        cut = max(1, len(scored) // 3)
        bottom = {c for _, c in scored[:cut]}
        top = {c for _, c in scored[-cut:]}

        # session -> candidate, resolved once rather than per question.
        owner = {s.id: cid for cid, s in snap.sessions.items()}

        def mean_transfer(group: set[str]) -> float | None:
            counts = [
                snap.responses_by_question[q.id].signals_found or 0
                for q in transfer_qs.values()
                if q.id in snap.responses_by_question
                and owner.get(q.session_id) in group
            ]
            return sum(counts) / len(counts) if counts else None

        top_mean, bottom_mean = mean_transfer(top), mean_transfer(bottom)
        if top_mean is None or bottom_mean is None:
            # No transfer probe reached one of the terciles, so there is nothing
            # to compare. Reported as n/a rather than as a ratio of zero.
            return {
                "m2a_marginal_signal_pct": median(deltas),
                "m2a_claims_measured": len(deltas),
                "m2b_separation_ratio": None,
                "m2b_note": "no transfer probe in one tercile",
            }
        if bottom_mean > 0:
            ratio = round(top_mean / bottom_mean, 2)
        elif top_mean > 0:
            ratio = math.inf

    return {
        "m2a_marginal_signal_pct": median(deltas),
        "m2a_claims_measured": len(deltas),
        "m2b_separation_ratio": ratio,
    }


def compute_m3(snap: Snapshot) -> dict:
    """Score separation. A scoring system that cannot separate candidates is
    useless even when it is correct, which is why "non-zero" was the wrong
    target and spread is the right one."""
    competence = [float(p.competence_score) for p in snap.profiles.values()]
    resume = [float(p.resume_score) for p in snap.profiles.values()]
    if not competence:
        return {"m3a_iqr": None, "m3b_tie_rate_pct": None, "m3c_divergence_pct": None}

    q1, q3 = quantile(competence, 0.25), quantile(competence, 0.75)
    pairs = [
        (a, b)
        for i, a in enumerate(competence)
        for b in competence[i + 1 :]
    ]
    ties = sum(1 for a, b in pairs if abs(a - b) <= 3)

    ids_ = [c for c in snap.candidates if c in snap.profiles]
    by_comp = sorted(ids_, key=lambda c: -snap.profiles[c].competence_score)
    by_res = sorted(ids_, key=lambda c: -snap.profiles[c].resume_score)
    comp_rank = {c: i for i, c in enumerate(by_comp)}
    res_rank = {c: i for i, c in enumerate(by_res)}
    diverged = sum(1 for c in ids_ if abs(comp_rank[c] - res_rank[c]) >= 2)

    return {
        "m3a_iqr": round((q3 or 0) - (q1 or 0), 1),
        "m3b_tie_rate_pct": round(100 * ties / len(pairs), 1) if pairs else None,
        "m3c_divergence_pct": round(100 * diverged / len(ids_), 1) if ids_ else None,
        "candidates_scored": len(competence),
        "mean_competence": round(sum(competence) / len(competence), 1),
        "mean_resume": round(sum(resume) / len(resume), 1) if resume else None,
    }


def compute_m5() -> dict:
    """Routing quality against A's labelled golden set. No model call.

    NOTE ON M5a. The metrics document defines it as "% of resumes routed above
    the margin threshold", but P1-06 ships no margin threshold — `match_family`
    falls back to `general` on a two-TERM floor, not on a margin. So M5a is
    reported here as the floor-based routed rate, and the margin distribution
    is printed beside it so the number is not mistaken for something it is not.
    Configuring a margin threshold is a change to A's `taxonomy.py` and is not
    P1-11's to make.
    """
    if not GOLDEN_PATH.exists():
        return {"available": False}

    payload = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    entries = payload["resumes"] if isinstance(payload, dict) else payload

    routed = wrong = confident_wrong = labelled = 0
    margins: list[float] = []
    for entry in entries:
        label = entry.get("family")
        match = match_family(entry.get("text") or "")
        is_routed = match.family != "general"
        if is_routed:
            routed += 1
            margins.append(match.confidence)
        if not label or label == "ambiguous":
            continue
        labelled += 1
        if match.family != label:
            wrong += 1
            if is_routed:
                confident_wrong += 1

    total = len(entries)
    ambiguous = total - labelled
    routed_labelled = 0
    for entry in entries:
        label = entry.get("family")
        if not label or label == "ambiguous":
            continue
        if match_family(entry.get("text") or "").family != "general":
            routed_labelled += 1
    return {
        "available": True,
        "entries": total,
        "labelled": labelled,
        "ambiguous": ambiguous,
        "m5a_routed_pct_labelled": (
            round(100 * routed_labelled / labelled, 1) if labelled else None
        ),
        "m5a_routed_pct": round(100 * routed / total, 1) if total else None,
        "m5b_accuracy_pct": round(100 * (labelled - wrong) / labelled, 1) if labelled else None,
        "m5c_confident_wrong_pct": round(100 * confident_wrong / labelled, 1) if labelled else None,
        "median_margin": median(margins),
        "min_terms_floor": MIN_TERMS,
    }


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------


def _fmt(value, suffix: str = "") -> str:
    if value is None:
        return "n/a"
    if value == math.inf:
        return "inf"
    if isinstance(value, float):
        return f"{value:g}{suffix}"
    return f"{value}{suffix}"


def _verdict(actual, target, comparator=lambda a, t: a >= t) -> str:
    if actual is None:
        return "     "
    return "  OK " if comparator(actual, target) else "  ** "


def render(snap: Snapshot, report: ValidationOut) -> str:
    m1, m2, m3, m5 = compute_m1(snap), compute_m2(snap), compute_m3(snap), compute_m5()
    out: list[str] = []
    add = out.append

    add("=" * 78)
    add("ProofScreen — Phase 1 validation report")
    add(f"generated {report.generated_at.isoformat(timespec='seconds')}   "
        f"minimum n = {report.minimum_n}   model calls = 0")
    add("=" * 78)

    add("")
    add("M1  Transfer probe reach and completion")
    add(f"    transfer questions asked            {_fmt(m1['transfer_questions'])}")
    add(f"    completed sessions                  {_fmt(m1['completed_sessions'])}")
    add(f"{_verdict(m1['m1a_reach_pct'], 80)}M1a reach                           "
        f"{_fmt(m1['m1a_reach_pct'], '%')}   target >= 80%")
    add(f"{_verdict(m1['m1b_reach_on_stalled_pct'], 100)}M1b reach on stalled claims         "
        f"{_fmt(m1['m1b_reach_on_stalled_pct'], '%')}   target 100% (invariant, "
        f"{m1['m1b_stalled_claims']} stalled)")
    add(f"{_verdict(m1['m1c_completion_pct'], 70)}M1c completion                      "
        f"{_fmt(m1['m1c_completion_pct'], '%')}   target >= 70%")

    add("")
    add("M2  Marginal evidence from the transfer probe")
    add(f"{_verdict(m2['m2a_marginal_signal_pct'], 15)}M2a marginal signals (median)       "
        f"{_fmt(m2['m2a_marginal_signal_pct'], '%')}   target >= +15%  "
        f"({m2['m2a_claims_measured']} claims)")
    add(f"{_verdict(m2['m2b_separation_ratio'], 2.0)}M2b separation top:bottom tercile   "
        f"{_fmt(m2['m2b_separation_ratio'], 'x')}   target >= 2.0x")
    add("    C1: do not optimise M2a. A fabricator SHOULD produce near-zero")
    add("        signals on a transfer probe — that is the probe working.")

    add("")
    add("M3  Score separation")
    add(f"    candidates scored                   {_fmt(m3.get('candidates_scored'))}")
    add(f"{_verdict(m3['m3a_iqr'], 20)}M3a competence IQR                  "
        f"{_fmt(m3['m3a_iqr'])} pts   target >= 20")
    add(f"{_verdict(m3['m3b_tie_rate_pct'], 15, lambda a, t: a < t)}M3b tie rate (within 3 pts)         "
        f"{_fmt(m3['m3b_tie_rate_pct'], '%')}   target < 15%")
    add(f"{_verdict(m3['m3c_divergence_pct'], 40)}M3c rank divergence from resume     "
        f"{_fmt(m3['m3c_divergence_pct'], '%')}   target >= 40%")
    add(f"    mean competence {_fmt(m3.get('mean_competence'))} · "
        f"mean resume {_fmt(m3.get('mean_resume'))}   (C3: do not optimise upward)")

    add("")
    add("M4  Signal quality vs resume screening   ***  the metric Phase 1 exists to produce")
    add("")
    add(f"    {'cohort':<24}{'n':>5}  {'competence':>11}{'resume':>9}   verdict")
    add("    " + "-" * 66)
    for cohort in [report.overall, *report.cohorts]:
        name = cohort.job_family
        if not cohort.sufficient:
            add(f"    {name:<24}{cohort.n_decided:>5}  "
                f"{'insufficient data (n < ' + str(report.minimum_n) + ')':>32}")
            continue
        comp, res = cohort.competence_correlation, cohort.resume_correlation
        verdict = "—"
        if comp is not None and res is not None:
            margin = comp - res
            verdict = (
                f"competence +{margin:.2f}" if margin >= 0.15
                else f"NOT MET ({margin:+.2f})"
            )
        add(f"    {name:<24}{cohort.n_decided:>5}  {_fmt(comp):>11}{_fmt(res):>9}   {verdict}")
        add(f"    {'':<24}{'':>5}  p@5 {_fmt(cohort.competence_precision_at_5):>7}"
            f"{_fmt(cohort.resume_precision_at_5):>9}   "
            f"M4c inversions caught: {cohort.inversions_caught}")

    if not report.overall.sufficient:
        add("")
        add("    M4a IS NOT YET COMPUTABLE, and that is reported rather than estimated.")
        add(f"    {report.overall.n_decided} decided candidate(s) against a floor of "
            f"{report.minimum_n}. Record decisions via")
        add("    POST /api/recruiter/candidates/{id}/outcome, or run the blind panel in")
        add("    PHASE_1_EXECUTION_PLAN.md's risk register. Do not estimate.")

    add("")
    add("M5  Routing quality")
    if not m5.get("available"):
        add("    golden set not found")
    else:
        add(f"    golden entries                      {m5['entries']} "
            f"({m5['labelled']} labelled, {m5['ambiguous']} deliberately ambiguous)")
        add(f"{_verdict(m5['m5a_routed_pct_labelled'], 90)}M5a routed, labelled only           "
            f"{_fmt(m5['m5a_routed_pct_labelled'], '%')}   target >= 90%")
        add(f"     M5a routed, all entries            "
            f"{_fmt(m5['m5a_routed_pct'], '%')}   (the ambiguous ones SHOULD fall back)")
        add(f"{_verdict(m5['m5b_accuracy_pct'], 95)}M5b accuracy vs human label         "
            f"{_fmt(m5['m5b_accuracy_pct'], '%')}   target >= 95%")
        add(f"{_verdict(m5['m5c_confident_wrong_pct'], 2, lambda a, t: a <= t)}"
            f"M5c confident and wrong             "
            f"{_fmt(m5['m5c_confident_wrong_pct'], '%')}   target <= 2%  (the dangerous quadrant)")
        add(f"    median margin {_fmt(m5['median_margin'])} · "
            f"floor {m5['min_terms_floor']} terms")
        add("    M5a is FLOOR-based, not margin-based: match_family() falls back on a")
        add("    two-term floor and no margin threshold is configured. Reported as it is")
        add("    computed, not as the metrics doc assumes.")

    add("")
    add("=" * 78)
    add("Every number above is arithmetic over stored rows. No model was called.")
    add("=" * 78)
    return "\n".join(out)


async def main(minimum_n: int = MINIMUM_N) -> str:
    from api.db import SessionLocal, init_models

    await init_models()
    async with SessionLocal() as db:
        snap = await collect(db)
        return render(snap, build_report(snap, minimum_n))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Phase 1 validation report.")
    parser.add_argument(
        "--minimum-n", type=int, default=MINIMUM_N,
        help="Sample-size floor below which correlations are withheld.",
    )
    print(asyncio.run(main(parser.parse_args().minimum_n)))
