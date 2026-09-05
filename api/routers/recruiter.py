"""
Recruiter API. Owned by Dev B.

GET  /api/recruiter/candidates?role_id=      ranked list
GET  /api/recruiter/candidates/{id}?role_id= full evidence graph
GET  /api/recruiter/roles                    weight profiles
POST /api/recruiter/roles                    create one
GET  /api/recruiter/taxonomy                 families, claim types, default weights
POST /api/recruiter/candidates/{id}/outcome  record a hiring decision
GET  /api/recruiter/candidates/{id}/outcomes decision history, oldest first
GET  /api/recruiter/validation               M4 — score vs recruiter decision
GET  /api/recruiter/candidates/{id}/evaluations  assessment history, newest first
GET  /api/recruiter/evaluations/{id}         one finalized assessment + provenance

The `role_id` parameter is the product. Every dimension score is already
stored, so passing a different role recomputes the ranking from rows we
already have — no model calls, no re-interviewing. Two requests, two orders,
same evidence.

D9 — every route here depends on `current_tenant` and passes the resulting
scope down. No handler writes a tenant predicate itself; a cross-tenant id
comes back as 404, never 403, because 403 would confirm the row exists.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db import get_db
from api.engine import evaluation as evaluation_engine
from api.engine.graph import (
    build_candidate_graph,
    create_role,
    rank_candidates,
    role_to_out,
)
from api import ids
from api.models import Candidate, CandidateOutcome, JobRole
from api.schemas import (
    CandidateGraph,
    EvaluationOut,
    EvaluationSummary,
    OutcomeIn,
    OutcomeOut,
    RankedCandidates,
    RoleOut,
    RoleWeightsIn,
    ValidationOut,
)
from api.tenancy import TenantScope, current_tenant, get_owned, scoped
from api.taxonomy import (
    claim_types,
    default_claim_weights,
    dimension_weights,
    families,
)

router = APIRouter(prefix="/api/recruiter", tags=["recruiter"])


@router.get("/candidates", response_model=RankedCandidates)
async def ranked_candidates(
    role_id: str | None = Query(
        None, description="Rank under this role's weights instead of the family defaults"
    ),
    db: AsyncSession = Depends(get_db),
    scope: TenantScope = Depends(current_tenant),
) -> RankedCandidates:
    role_ref, rows = await rank_candidates(db, role_id, scope=scope)
    return RankedCandidates(scored_for=role_ref, candidates=rows)


@router.get("/candidates/{candidate_id}", response_model=CandidateGraph)
async def candidate_graph(
    candidate_id: str,
    role_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    scope: TenantScope = Depends(current_tenant),
) -> CandidateGraph:
    graph = await build_candidate_graph(db, candidate_id, role_id, scope=scope)
    if graph is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "candidate not found")
    return graph


@router.get("/roles", response_model=list[RoleOut])
async def list_roles(
    db: AsyncSession = Depends(get_db),
    scope: TenantScope = Depends(current_tenant),
) -> list[RoleOut]:
    rows = (
        await db.execute(
            scoped(
                select(JobRole).order_by(JobRole.created_at, JobRole.id),
                JobRole,
                scope,
            )
        )
    ).scalars().all()
    return [role_to_out(r) for r in rows]


@router.post("/roles", response_model=RoleOut, status_code=status.HTTP_201_CREATED)
async def create_role_profile(
    payload: RoleWeightsIn,
    db: AsyncSession = Depends(get_db),
    scope: TenantScope = Depends(current_tenant),
) -> RoleOut:
    """Weights are rescaled to sum to 100, so 40/30/20/20 is accepted as typed."""
    role = await create_role(
        db,
        title=payload.title,
        job_family=payload.job_family,
        claim_weights=payload.claim_weights or None,
        dimension_weights_override=payload.dimension_weights or None,
        scope=scope,
    )
    return role_to_out(role)


# ---------------------------------------------------------------------------
# Outcomes — the independent variable
#
# Everything else this router returns is ProofScreen's opinion. These two
# routes are the only place a HUMAN's decision enters the system, which is what
# makes the product's central claim falsifiable rather than self-referential.
#
# Note what these handlers deliberately do NOT do: they never call into
# `engine/`. An outcome endpoint that recomputed a profile would make M4a
# correlate the system with itself.
# ---------------------------------------------------------------------------


@router.post(
    "/candidates/{candidate_id}/outcome",
    response_model=OutcomeOut,
    status_code=status.HTTP_201_CREATED,
)
async def record_outcome(
    candidate_id: str,
    payload: OutcomeIn,
    db: AsyncSession = Depends(get_db),
    scope: TenantScope = Depends(current_tenant),
) -> OutcomeOut:
    """Record what a recruiter decided.

    ONE CALL, ONE REQUIRED FIELD. The phase risk register's top entry is that
    recruiters never record outcomes and the objective stays unproven; its
    mitigation is that recording is a click, not a workflow. `OutcomeIn` asks
    only for `decision` — resist adding to that.

    Append-only: a candidate moving shortlisted -> interviewed -> offered is
    three rows, not one row updated three times, because the progression is
    what M4a rank-correlates against.
    """
    candidate = await get_owned(db, Candidate, candidate_id, scope)
    if candidate is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "candidate not found")

    # An unknown lens is an error, not a null. "Rejected under the Ops lens"
    # and "rejected" are different facts, and quietly degrading the first into
    # the second corrupts how the validation report groups decisions, with
    # nothing surfacing to say so. Another tenant's lens is "unknown" here.
    if payload.role_id is not None:
        if await get_owned(db, JobRole, payload.role_id, scope) is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, f"role_id {payload.role_id!r} not found"
            )

    outcome = CandidateOutcome(
        id=ids.outcome_id(),
        tenant_id=scope.require(),
        candidate_id=candidate_id,
        role_id=payload.role_id,
        decision=payload.decision.value,
        stage=payload.stage,
        decided_by=payload.decided_by,
        note=payload.note,
    )
    db.add(outcome)
    await db.commit()
    await db.refresh(outcome)
    return OutcomeOut.model_validate(outcome, from_attributes=True)


@router.get("/candidates/{candidate_id}/outcomes", response_model=list[OutcomeOut])
async def outcome_history(
    candidate_id: str,
    db: AsyncSession = Depends(get_db),
    scope: TenantScope = Depends(current_tenant),
) -> list[OutcomeOut]:
    """A candidate's decision history, OLDEST FIRST.

    Chronological on purpose. The validation report reads these as a
    progression, so this is the order the data is consumed in. Newest-first
    would be the better default for a UI feed and the wrong one for P1-11.
    """
    if await get_owned(db, Candidate, candidate_id, scope) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "candidate not found")

    rows = (
        await db.execute(
            scoped(
                select(CandidateOutcome)
                .where(CandidateOutcome.candidate_id == candidate_id)
                .order_by(CandidateOutcome.decided_at, CandidateOutcome.id),
                CandidateOutcome,
                scope,
            )
        )
    ).scalars().all()
    return [OutcomeOut.model_validate(r, from_attributes=True) for r in rows]


# ---------------------------------------------------------------------------
# Evaluations — D6
#
# The difference between these routes and `/candidates/{id}` is the whole
# point of the deliverable. `/candidates/{id}` recomputes the graph live from
# whatever the rows say right now, under whatever lens you pass. An evaluation
# is what the system concluded at one moment, under one configuration, and it
# never changes again.
#
# The drill-down is unchanged: an evaluation names its candidate and its
# session, and the evidence is read where it has always been read.
# ---------------------------------------------------------------------------


@router.get(
    "/candidates/{candidate_id}/evaluations", response_model=list[EvaluationSummary]
)
async def candidate_evaluations(
    candidate_id: str,
    db: AsyncSession = Depends(get_db),
    scope: TenantScope = Depends(current_tenant),
) -> list[EvaluationSummary]:
    """A candidate's assessment history, NEWEST FIRST.

    Newest first, unlike `/outcomes`, and the difference is not an
    inconsistency: outcomes are read as a progression by the validation report,
    while this is a feed a human scrolls.
    """
    if await get_owned(db, Candidate, candidate_id, scope) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "candidate not found")
    rows = await evaluation_engine.list_for_candidate(db, candidate_id, scope)
    return [evaluation_engine.to_summary(r) for r in rows]


@router.get("/evaluations/{evaluation_id}", response_model=EvaluationOut)
async def evaluation_detail(
    evaluation_id: str,
    db: AsyncSession = Depends(get_db),
    scope: TenantScope = Depends(current_tenant),
) -> EvaluationOut:
    """One assessment, retrievable independently of the live interview.

    Carries its provenance. Nothing here is a secret: the stamp is eight
    allowlisted flag names and a set of version strings, by construction.
    """
    evaluation = await evaluation_engine.get_evaluation(db, evaluation_id, scope)
    if evaluation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "evaluation not found")
    candidate = await get_owned(db, Candidate, evaluation.candidate_id, scope)
    return evaluation_engine.to_out(evaluation, candidate.name if candidate else "")


@router.get("/validation", response_model=ValidationOut)
async def validation(
    minimum_n: int = Query(
        30,
        ge=1,
        le=10_000,
        description=(
            "Sample-size floor below which correlations are WITHHELD, never "
            "estimated. The response echoes the value used."
        ),
    ),
    db: AsyncSession = Depends(get_db),
    scope: TenantScope = Depends(current_tenant),
) -> ValidationOut:
    """M4 — score against recruiter decision. The metric Phase 1 exists to produce.

    ONE IMPLEMENTATION, TWO SURFACES. This calls the same `build_report()` that
    `scripts/validation_report.py` prints, so the number on a screen and the
    number in a terminal cannot disagree. Re-implementing the maths here would
    guarantee they eventually do.

    `minimum_n` is adjustable so a reviewer can inspect the arithmetic on thin
    data deliberately rather than by accident. The response carries the floor it
    used, so a correlation computed under a lowered one can never be quoted as
    the real M4a.

    Below the floor: `sufficient=false`, both correlations `null`. A Spearman
    coefficient over four candidates looks like evidence and is not.
    """
    # Imported here rather than at module scope: the report pulls in the whole
    # engine, and this router is imported at app startup.
    from scripts.validation_report import build_report, collect

    # D9 — one tenant's report. A cross-tenant correlation would leak the shape
    # of another customer's candidate pool, which PRODUCTION_READINESS.md 4
    # flags as a decision rather than a default. This is the decision.
    return build_report(await collect(db, scope), minimum_n)


@router.get("/taxonomy")
async def taxonomy(job_family: str | None = Query(None)) -> dict:
    """What the dashboard's weight editor renders. Read-only view of Artifact 1."""
    if job_family:
        return {
            "job_family": job_family,
            "claim_types": {
                key: {"label": cfg["label"], "default_weight": cfg["weight"]}
                for key, cfg in claim_types(job_family).items()
            },
            "default_claim_weights": default_claim_weights(job_family),
            "dimension_weights": dimension_weights(job_family),
        }
    return {
        "families": {
            key: {
                "label": cfg["label"],
                "claim_types": {
                    ck: {"label": cc["label"], "default_weight": cc["weight"]}
                    for ck, cc in cfg["claim_types"].items()
                },
                "dimension_weights": dimension_weights(key),
            }
            for key, cfg in families().items()
        }
    }
