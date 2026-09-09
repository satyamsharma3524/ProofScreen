"""
Job Fit API Router.  Owned by Dev A.

POST /api/job-fit          Single candidate Job Fit calculation against a JD
POST /api/job-fit/rank     Multi-candidate ranking by Job Fit Score against a JD
POST /api/rank-candidates  Alias for multi-candidate Job Fit ranking
"""

from __future__ import annotations

import logging
from typing import Sequence
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.db import get_db
from api.engine.graph import build_candidate_graph
from api.engine.job_fit import (
    CandidateJobFitRanking,
    JobFitResult,
    calculate_job_fit,
)
from api.engine.job_requirements import (
    JobRequirement,
    extract_job_requirements,
    normalise_requirement_weights,
)
from api.tenancy import TenantScope, current_tenant

log = logging.getLogger("proofscreen.job_fit_api")

router = APIRouter(prefix="/api", tags=["job-fit"])


class RequirementIn(BaseModel):
    name: str
    category: str = Field(default="SKILL", description="SKILL, COMPETENCY, or DOMAIN")
    weight: float = Field(default=0.15, ge=0.01, le=1.0)


class SingleCandidateJobFitRequest(BaseModel):
    candidate_id: str
    job_description: str | None = None
    role_id: str | None = None
    requirements: list[RequirementIn] | None = None


class MultiCandidateJobFitRankRequest(BaseModel):
    candidate_ids: list[str] = Field(..., min_length=1)
    job_description: str | None = None
    role_id: str | None = None
    requirements: list[RequirementIn] | None = None


class JobFitRankingsOut(BaseModel):
    rankings: list[CandidateJobFitRanking]
    extracted_requirements: list[JobRequirement]


async def _resolve_requirements(
    jd_text: str | None,
    provided_reqs: list[RequirementIn] | None,
) -> list[JobRequirement]:
    if provided_reqs:
        reqs = [
            JobRequirement(
                name=r.name.strip(),
                category=r.category.upper().strip(),
                weight=float(r.weight),
            )
            for r in provided_reqs
            if r.name.strip()
        ]
        return normalise_requirement_weights(reqs)
    return await extract_job_requirements(jd_text or "")


@router.post("/job-fit", response_model=JobFitResult, status_code=status.HTTP_200_OK)
async def evaluate_single_job_fit(
    payload: SingleCandidateJobFitRequest,
    db: AsyncSession = Depends(get_db),
    scope: TenantScope = Depends(current_tenant),
) -> JobFitResult:
    """Calculate explainable Job Fit Score for a candidate against a Job Description or Requirement set."""
    graph = await build_candidate_graph(
        db, payload.candidate_id, role_id=payload.role_id, scope=scope
    )
    if graph is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"candidate {payload.candidate_id!r} not found"
        )

    reqs = await _resolve_requirements(payload.job_description, payload.requirements)
    return calculate_job_fit(graph, reqs)


@router.post("/job-fit/rank", response_model=JobFitRankingsOut, status_code=status.HTTP_200_OK)
async def rank_candidates_by_job_fit(
    payload: MultiCandidateJobFitRankRequest,
    db: AsyncSession = Depends(get_db),
    scope: TenantScope = Depends(current_tenant),
) -> JobFitRankingsOut:
    """Rank multiple candidates against a Job Description based on Job Fit Score."""
    reqs = await _resolve_requirements(payload.job_description, payload.requirements)

    results: list[tuple[str, str, str, JobFitResult, int]] = []

    for cid in payload.candidate_ids:
        graph = await build_candidate_graph(db, cid, role_id=payload.role_id, scope=scope)
        if graph is None:
            continue

        fit_res = calculate_job_fit(graph, reqs)
        total_reqs = len(fit_res.requirement_details)
        verified_count = len(fit_res.verified_requirements)

        cname = graph.candidate.name if (hasattr(graph, "candidate") and graph.candidate) else getattr(graph, "candidate_name", cid)

        results.append((cid, cname, graph.badge.value, fit_res, verified_count))

    # Sort descending by job_fit_score
    results.sort(key=lambda item: item[3].job_fit_score, reverse=True)

    rankings: list[CandidateJobFitRanking] = []
    for idx, (cid, name, badge, fit_res, v_count) in enumerate(results, start=1):
        rankings.append(
            CandidateJobFitRanking(
                rank=idx,
                candidate_id=cid,
                candidate_name=name,
                job_fit_score=fit_res.job_fit_score,
                skill_fit=fit_res.skill_fit,
                competence_fit=fit_res.competence_fit,
                verified_requirements_count=v_count,
                total_requirements_count=len(fit_res.requirement_details),
                badge=badge,
                details=fit_res,
            )
        )

    return JobFitRankingsOut(rankings=rankings, extracted_requirements=reqs)


@router.post("/rank-candidates", response_model=JobFitRankingsOut, status_code=status.HTTP_200_OK)
async def rank_candidates_alias(
    payload: MultiCandidateJobFitRankRequest,
    db: AsyncSession = Depends(get_db),
    scope: TenantScope = Depends(current_tenant),
) -> JobFitRankingsOut:
    """Alias for POST /api/job-fit/rank to satisfy user specification."""
    return await rank_candidates_by_job_fit(payload, db, scope)
