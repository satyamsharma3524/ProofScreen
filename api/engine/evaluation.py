"""
D6 — the Evaluation entity.  NO LLM CALL IN THIS FILE.

The write path for `evaluations`, and the ONLY one. Everything that creates or
finalizes an evaluation goes through `open_evaluation()` and
`finalize_evaluation()` — which is the plan's stated mitigation for the risk
that provenance gets stamped on one recompute site and not the next: there is
one site.

  open_evaluation()      a draft, opened with the interview. Idempotent per
                         session: called twice, it returns the same row.
  finalize_evaluation()  the interview is over. Reads the graph the recruiter
                         would see, stamps provenance, writes the record once,
                         and points the profile at it.

WHY IT READS `build_candidate_graph`

Because that is the number the recruiter sees. An evaluation computed by its
own arithmetic would be a second implementation of the score, and the first
time the two disagreed the product would have no defensible answer about which
one was real. Same function, same lens (the candidate's default role), same
result as `recompute_profile` — by construction, not by coincidence.

WHAT IT DOES NOT DO

It does not touch evidence, it does not recompute a claim, and it does not
call a model. A finalized evaluation is a photograph of rows that already
existed.
"""

from __future__ import annotations

import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api import ids
from api.engine import provenance as provenance_engine
from api.models import (
    Candidate,
    CandidateOutcome,
    ChatSession,
    ClaimScore,
    Evaluation,
    EvaluationFinalized,
    Profile,
    utcnow,
)
from api.schemas import (
    Badge,
    DimensionScore,
    EvaluationHistoryEntry,
    EvaluationHistoryOut,
    EvaluationOut,
    EvaluationStatus,
    EvaluationSummary,
    HistoryEntryKind,
    OutcomeDecision,
)
from api.taxonomy import family_label
from api.tenancy import TenantScope, get_owned, scoped

log = logging.getLogger("proofscreen.evaluation")

__all__ = [
    "EvaluationFinalized",
    "build_history",
    "decisions_for_evaluation",
    "finalize_evaluation",
    "get_evaluation",
    "latest_finalized_for_candidate",
    "list_for_candidate",
    "open_evaluation",
    "to_out",
    "to_summary",
]


# ---------------------------------------------------------------------------
# write
# ---------------------------------------------------------------------------


async def open_evaluation(
    db: AsyncSession, session: ChatSession, candidate: Candidate
) -> Evaluation:
    """The draft. Idempotent per session — a duplicate call NEVER overwrites.

    `session_id` is unique, so the second call finds the first row and returns
    it. That is the mechanism behind "duplicate creation does not overwrite":
    not a check that could be raced, a constraint.
    """
    existing = (
        await db.execute(
            select(Evaluation).where(Evaluation.session_id == session.id)
        )
    ).scalars().first()
    if existing is not None:
        return existing

    evaluation = Evaluation(
        id=ids.evaluation_id(),
        tenant_id=session.tenant_id,
        candidate_id=candidate.id,
        session_id=session.id,
        role_id=candidate.role_id,
        job_family=session.job_family,
        status=EvaluationStatus.draft.value,
    )
    db.add(evaluation)
    await db.flush()
    return evaluation


async def finalize_evaluation(
    db: AsyncSession, session: ChatSession, scope: TenantScope
) -> Evaluation | None:
    """draft -> finalized. Explicit, once, and irreversible.

    Returns the existing row unchanged if it is already finalized. NOT an
    error: `orchestrator.finalize()` is reachable twice (an idempotent
    background scoring pass, a re-entered dev flow), and turning a harmless
    repeat into a 500 would trade a real failure for an imaginary one. An
    attempt to CHANGE a finalized row is a different thing entirely and raises
    — see the listener in models.py.
    """
    from api.engine.graph import build_candidate_graph, resolve_weights

    candidate = await get_owned(db, Candidate, session.candidate_id, scope)
    if candidate is None:
        return None

    evaluation = await open_evaluation(db, session, candidate)
    if evaluation.status == EvaluationStatus.finalized.value:
        log.info("evaluation %s already finalized; leaving it alone", evaluation.id)
        return evaluation

    graph = await build_candidate_graph(db, candidate.id, scope=scope)
    if graph is None:                                        # pragma: no cover
        return None

    claim_weights, dimension_weights, _role_ref = await resolve_weights(
        db, graph.job_family, candidate.role_id, scope
    )
    scored = len(
        (
            await db.execute(
                scoped(
                    select(ClaimScore).where(
                        ClaimScore.claim_id.in_([c.id for c in graph.claims] or [""])
                    ),
                    ClaimScore,
                    scope,
                )
            )
        ).scalars().all()
    )

    evaluation.role_id = graph.scored_for.id if graph.scored_for else None
    evaluation.role_title = graph.scored_for.title if graph.scored_for else None
    evaluation.job_family = graph.job_family
    evaluation.resume_score = graph.resume_score
    evaluation.weighted_evidence_score = graph.weighted_evidence_score
    evaluation.competence_score = graph.competence_score
    evaluation.badge = graph.badge.value
    evaluation.consistency_score = graph.consistency.score
    evaluation.contradiction_count = len(graph.consistency.contradictions)
    evaluation.role_coverage = graph.role_coverage
    evaluation.claims_scored = scored
    evaluation.questions_asked = session.questions_asked
    evaluation.dimension_profile_json = json.dumps(
        [d.model_dump(mode="json") for d in graph.dimension_profile]
    )
    evaluation.claim_weights_json = json.dumps(claim_weights, sort_keys=True)
    evaluation.dimension_weights_json = json.dumps(dimension_weights, sort_keys=True)

    # D7 — stamped HERE, at the moment the result exists. A draft carries no
    # provenance because it has no result to explain; a configuration change
    # mid-interview is therefore attributed to the finalized stamp, which is
    # recorded as a known limitation rather than papered over.
    for column, value in provenance_engine.current().to_columns().items():
        setattr(evaluation, column, value)

    log.info(
        "final scoring: session=%s dimension_breakdown=%s claim_breakdown=%s",
        session.id,
        {d.dimension.value: d.score for d in graph.dimension_profile},
        [
            {
                "claim_id": c.id,
                "claim_type": c.claim_type,
                "weight": c.weight,
                "claim_score": c.claim_score,
                "probed_dimensions": c.probed_dimensions,
            }
            for c in graph.claims
        ],
    )

    evaluation.status = EvaluationStatus.finalized.value
    evaluation.finalized_at = utcnow()

    profile = (
        await db.execute(
            scoped(
                select(Profile).where(Profile.candidate_id == candidate.id),
                Profile,
                scope,
            )
        )
    ).scalar_one_or_none()
    if profile is not None:
        profile.latest_evaluation_id = evaluation.id

    await db.commit()
    log.info(
        "evaluation %s finalized — competence %d (%s), %s",
        evaluation.id, evaluation.competence_score, evaluation.badge,
        evaluation.evaluation_version,
    )
    return evaluation


# ---------------------------------------------------------------------------
# read
# ---------------------------------------------------------------------------


async def get_evaluation(
    db: AsyncSession, evaluation_id: str, scope: TenantScope
) -> Evaluation | None:
    return await get_owned(db, Evaluation, evaluation_id, scope)


async def list_for_candidate(
    db: AsyncSession, candidate_id: str, scope: TenantScope
) -> list[Evaluation]:
    """Newest first. `id` breaks a created_at tie so paging cannot repeat a row."""
    return list(
        (
            await db.execute(
                scoped(
                    select(Evaluation)
                    .where(Evaluation.candidate_id == candidate_id)
                    .order_by(Evaluation.created_at.desc(), Evaluation.id.desc()),
                    Evaluation,
                    scope,
                )
            )
        ).scalars().all()
    )


async def latest_finalized_for_candidate(
    db: AsyncSession, candidate_id: str, scope: TenantScope
) -> Evaluation | None:
    """The assessment a recruiter is looking at when they record a decision.

    Finalized only. Attaching a decision to a draft would tie it to numbers
    that were still moving.
    """
    return (
        await db.execute(
            scoped(
                select(Evaluation)
                .where(
                    Evaluation.candidate_id == candidate_id,
                    Evaluation.status == EvaluationStatus.finalized.value,
                )
                .order_by(Evaluation.finalized_at.desc(), Evaluation.id.desc()),
                Evaluation,
                scope,
            )
        )
    ).scalars().first()


# ---------------------------------------------------------------------------
# D10 — history
#
# THERE IS NO EVENTS TABLE, AND THAT IS THE DESIGN.
#
# An `evaluation_events` table was considered and rejected. Its entire content
# would have been a `created` row and a `finalized` row duplicating
# `evaluations.created_at` and `evaluations.finalized_at`, plus a pointer row
# per decision duplicating `candidate_outcomes` — which has been append-only by
# shape since P1-09 and is already correct. `PRODUCTION_READINESS.md` 5 argues
# exactly this: every question the event model would answer is answerable from
# timestamped rows, so derive the events and keep the write path thin.
#
# So the timeline is ASSEMBLED from the two sources that already hold the
# facts, ordered deterministically, with each entry naming its evaluation.
# ---------------------------------------------------------------------------


async def decisions_for_evaluation(
    db: AsyncSession, evaluation: Evaluation, scope: TenantScope
) -> list[CandidateOutcome]:
    """Every decision recorded against this evaluation, oldest first.

    Ordered by `(decided_at, id)`. The id tiebreaker is not decoration: two
    decisions can land in the same commit and therefore the same timestamp,
    and an audit trail whose order changes between reads is not an audit trail.
    """
    return list(
        (
            await db.execute(
                scoped(
                    select(CandidateOutcome)
                    .where(CandidateOutcome.evaluation_id == evaluation.id)
                    .order_by(CandidateOutcome.decided_at, CandidateOutcome.id),
                    CandidateOutcome,
                    scope,
                )
            )
        ).scalars().all()
    )


def _decision(value: str | None) -> OutcomeDecision | None:
    try:
        return OutcomeDecision(value) if value else None
    except ValueError:                                       # pragma: no cover
        return None


async def build_history(
    db: AsyncSession, evaluation: Evaluation, scope: TenantScope
) -> EvaluationHistoryOut:
    """What the evaluation concluded, and what a human then did about it.

    The two are kept visibly separate. Lifecycle entries carry the score;
    decision entries carry the decision and what it replaced. Nothing here
    lets a later decision restate, revise or overwrite the assessment — which
    is requirement 6, and the reason `why_ranked` still reads only evidence.
    """
    decisions = await decisions_for_evaluation(db, evaluation, scope)

    entries: list[EvaluationHistoryEntry] = [
        EvaluationHistoryEntry(
            kind=HistoryEntryKind.evaluation_created,
            at=evaluation.created_at,
            evaluation_id=evaluation.id,
        )
    ]
    if evaluation.finalized_at is not None:
        entries.append(
            EvaluationHistoryEntry(
                kind=HistoryEntryKind.evaluation_finalized,
                at=evaluation.finalized_at,
                evaluation_id=evaluation.id,
                competence_score=evaluation.competence_score,
                badge=Badge(evaluation.badge),
            )
        )
    for row in decisions:
        entries.append(
            EvaluationHistoryEntry(
                kind=HistoryEntryKind.decision,
                at=row.decided_at,
                evaluation_id=evaluation.id,
                outcome_id=row.id,
                decision=_decision(row.decision),
                previous_decision=_decision(row.previous_decision),
                decided_by=row.decided_by,
                stage=row.stage,
                note=row.note,
            )
        )

    # Deterministic to the last tiebreaker. `at` first; then lifecycle before
    # decisions when they share a timestamp (a decision cannot precede the
    # finalization it was made against); then the id, which is unique.
    rank = {
        HistoryEntryKind.evaluation_created: 0,
        HistoryEntryKind.evaluation_finalized: 1,
        HistoryEntryKind.decision: 2,
    }
    entries.sort(key=lambda e: (e.at, rank[e.kind], e.outcome_id or ""))

    return EvaluationHistoryOut(
        evaluation_id=evaluation.id,
        candidate_id=evaluation.candidate_id,
        status=EvaluationStatus(evaluation.status),
        finalized_at=evaluation.finalized_at,
        competence_score=evaluation.competence_score,
        badge=Badge(evaluation.badge),
        current_decision=_decision(decisions[-1].decision) if decisions else None,
        decisions_recorded=len(decisions),
        entries=entries,
    )


# ---------------------------------------------------------------------------
# serialisation
# ---------------------------------------------------------------------------


def _dimension_profile(payload: str | None) -> list[DimensionScore]:
    try:
        data = json.loads(payload or "[]")
    except (TypeError, ValueError):
        return []
    out: list[DimensionScore] = []
    for entry in data if isinstance(data, list) else []:
        try:
            out.append(DimensionScore.model_validate(entry))
        except Exception:  # noqa: BLE001
            continue
    return out


def _weights(payload: str | None) -> dict[str, float]:
    try:
        data = json.loads(payload or "{}")
    except (TypeError, ValueError):
        return {}
    return {str(k): float(v) for k, v in data.items()} if isinstance(data, dict) else {}


def to_out(evaluation: Evaluation, candidate_name: str = "") -> EvaluationOut:
    return EvaluationOut(
        id=evaluation.id,
        status=EvaluationStatus(evaluation.status),
        candidate_id=evaluation.candidate_id,
        candidate_name=candidate_name,
        session_id=evaluation.session_id,
        role_id=evaluation.role_id,
        role_title=evaluation.role_title,
        job_family=evaluation.job_family,
        job_family_label=family_label(evaluation.job_family),
        created_at=evaluation.created_at,
        finalized_at=evaluation.finalized_at,
        resume_score=evaluation.resume_score,
        weighted_evidence_score=evaluation.weighted_evidence_score,
        competence_score=evaluation.competence_score,
        badge=Badge(evaluation.badge),
        consistency_score=evaluation.consistency_score,
        contradiction_count=evaluation.contradiction_count,
        role_coverage=evaluation.role_coverage,
        claims_scored=evaluation.claims_scored,
        questions_asked=evaluation.questions_asked,
        dimension_profile=_dimension_profile(evaluation.dimension_profile_json),
        claim_weights=_weights(evaluation.claim_weights_json),
        dimension_weights=_weights(evaluation.dimension_weights_json),
        provenance=provenance_engine.from_row(evaluation).to_out(
            evaluation.evaluation_version
        ),
    )


def to_summary(evaluation: Evaluation) -> EvaluationSummary:
    return EvaluationSummary(
        id=evaluation.id,
        status=EvaluationStatus(evaluation.status),
        session_id=evaluation.session_id,
        role_id=evaluation.role_id,
        created_at=evaluation.created_at,
        finalized_at=evaluation.finalized_at,
        competence_score=evaluation.competence_score,
        weighted_evidence_score=evaluation.weighted_evidence_score,
        badge=Badge(evaluation.badge),
        evaluation_version=evaluation.evaluation_version,
    )
