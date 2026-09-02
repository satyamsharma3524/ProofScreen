"""GET /api/sessions/{id} — state, progress, and the currently open question."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.db import get_db
from api.engine import orchestrator
from api.models import ChatSession
from api.schemas import SessionOut

router = APIRouter(prefix="/api/sessions", tags=["candidate"])


@router.get("/{session_id}", response_model=SessionOut)
async def get_session(
    session_id: str, db: AsyncSession = Depends(get_db)
) -> SessionOut:
    session = await db.get(ChatSession, session_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    return await orchestrator.session_out(db, session)
