"""GET /api/sessions/{id} — state, progress, and the currently open question."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.db import get_db
from api.engine import orchestrator
from api.models import ChatSession
from api.schemas import SessionOut
from api.tenancy import TenantScope, current_tenant, get_owned

router = APIRouter(prefix="/api/sessions", tags=["candidate"])


@router.get("/{session_id}", response_model=SessionOut)
async def get_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    scope: TenantScope = Depends(current_tenant),
) -> SessionOut:
    session = await get_owned(db, ChatSession, session_id, scope)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    return await orchestrator.session_out(db, session)
