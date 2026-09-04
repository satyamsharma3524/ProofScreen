"""
Recruiter API. Owned by Dev B.

GET  /api/recruiter/candidates?role_id=      ranked list
GET  /api/recruiter/candidates/{id}?role_id= full evidence graph
GET  /api/recruiter/roles                    weight profiles
POST /api/recruiter/roles                    create one
GET  /api/recruiter/taxonomy                 families, claim types, default weights
POST /api/recruiter/candidates/{id}/outcome  record a hiring decision
GET  /api/recruiter/candidates/{id}/outcomes decision history, oldest first

The `role_id` parameter is the product. Every dimension score is already
stored, so passing a different role recomputes the ranking from rows we
already have — no model calls, no re-interviewing. Two requests, two orders,
same evidence.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db import get_db
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
    OutcomeIn,
    OutcomeOut,
    RankedCandidates,
    RoleOut,
    RoleWeightsIn,
)
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
) -> RankedCandidates:
    role_ref, rows = await rank_candidates(db, role_id)
    return RankedCandidates(scored_for=role_ref, candidates=rows)


@router.get("/candidates/{candidate_id}", response_model=CandidateGraph)
async def candidate_graph(
    candidate_id: str,
    role_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> CandidateGraph:
    graph = await build_candidate_graph(db, candidate_id, role_id)
    if graph is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "candidate not found")
    return graph


@router.get("/roles", response_model=list[RoleOut])
async def list_roles(db: AsyncSession = Depends(get_db)) -> list[RoleOut]:
    rows = (
        await db.execute(select(JobRole).order_by(JobRole.created_at))
    ).scalars().all()
    return [role_to_out(r) for r in rows]


@router.post("/roles", response_model=RoleOut, status_code=status.HTTP_201_CREATED)
async def create_role_profile(
    payload: RoleWeightsIn, db: AsyncSession = Depends(get_db)
) -> RoleOut:
    """Weights are rescaled to sum to 100, so 40/30/20/20 is accepted as typed."""
    role = await create_role(
        db,
        title=payload.title,
        job_family=payload.job_family,
        claim_weights=payload.claim_weights or None,
        dimension_weights_override=payload.dimension_weights or None,
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
    candidate = await db.get(Candidate, candidate_id)
    if candidate is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "candidate not found")

    # An unknown lens is an error, not a null. "Rejected under the Ops lens"
    # and "rejected" are different facts, and quietly degrading the first into
    # the second corrupts how the validation report groups decisions, with
    # nothing surfacing to say so.
    if payload.role_id is not None:
        if await db.get(JobRole, payload.role_id) is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, f"role_id {payload.role_id!r} not found"
            )

    outcome = CandidateOutcome(
        id=ids.outcome_id(),
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
    candidate_id: str, db: AsyncSession = Depends(get_db)
) -> list[OutcomeOut]:
    """A candidate's decision history, OLDEST FIRST.

    Chronological on purpose. The validation report reads these as a
    progression, so this is the order the data is consumed in. Newest-first
    would be the better default for a UI feed and the wrong one for P1-11.
    """
    if await db.get(Candidate, candidate_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "candidate not found")

    rows = (
        await db.execute(
            select(CandidateOutcome)
            .where(CandidateOutcome.candidate_id == candidate_id)
            .order_by(CandidateOutcome.decided_at, CandidateOutcome.id)
        )
    ).scalars().all()
    return [OutcomeOut.model_validate(r, from_attributes=True) for r in rows]


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
