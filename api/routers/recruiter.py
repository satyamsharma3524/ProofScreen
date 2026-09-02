"""
Recruiter API. Owned by Dev B.

GET  /api/recruiter/candidates?role_id=      ranked list
GET  /api/recruiter/candidates/{id}?role_id= full evidence graph
GET  /api/recruiter/roles                    weight profiles
POST /api/recruiter/roles                    create one
GET  /api/recruiter/taxonomy                 families, claim types, default weights

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
from api.models import JobRole
from api.schemas import (
    CandidateGraph,
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
