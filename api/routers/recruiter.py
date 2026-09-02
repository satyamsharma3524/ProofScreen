"""
Recruiter API. Owned by Dev B.

GET /api/recruiter/candidates        ranked list, highest competence first
GET /api/recruiter/candidates/{id}   the full evidence graph the dashboard renders
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.db import get_db
from api.engine.graph import build_candidate_graph, list_candidate_summaries
from api.schemas import CandidateGraph, CandidateSummary

router = APIRouter(prefix="/api/recruiter", tags=["recruiter"])


@router.get("/candidates", response_model=list[CandidateSummary])
async def ranked_candidates(
    db: AsyncSession = Depends(get_db),
) -> list[CandidateSummary]:
    return await list_candidate_summaries(db)


@router.get("/candidates/{candidate_id}", response_model=CandidateGraph)
async def candidate_graph(
    candidate_id: str, db: AsyncSession = Depends(get_db)
) -> CandidateGraph:
    graph = await build_candidate_graph(db, candidate_id)
    if graph is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "candidate not found")
    return graph
