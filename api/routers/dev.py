"""
POST /api/dev/simulate — the most valuable endpoint in this repo.

Runs ingest -> claims -> questions -> evidence -> score with no WhatsApp, no
browser and no waiting. It is how you test everything for the rest of the
build, and it is the demo fallback if Twilio dies on stage.

Guarded by ENABLE_DEV_ENDPOINTS so it can be switched off in one env var.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from api import ids
from api.config import settings
from api.db import drop_all, get_db
from api.engine import orchestrator
from api.engine.graph import build_candidate_graph
from api.ingest.parse import normalise
from api.llm import cache_stats
from api.models import Candidate, Resume
from api.schemas import Channel, QAPair, SimulateIn, SimulateOut

log = logging.getLogger("proofscreen.dev")

router = APIRouter(prefix="/api/dev", tags=["dev"])

FIXTURE_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "sample_graph.json"

# Used when simulate is called with no answers, so a single curl produces a
# fully scored candidate. Deliberately mediocre answers — they should NOT all
# come back SUPPORTED.
PLACEHOLDER_ANSWERS = [
    "I led that work end to end. I owned the plan and reviewed every change "
    "before it went out, and two analysts reported to me on it.",
    "The root cause was that billing complaints were 40% of negative feedback, "
    "so we redesigned the escalation workflow and added callback SLAs.",
    "We ran it for one quarter with a weekly review. The number moved from 78 "
    "to 92 over about eleven weeks.",
    "I'm not sure about the exact figures now.",
    "We monitored it on a dashboard and rolled it back once when the queue "
    "backed up, then reshipped it with a staffing change.",
]


def _guard() -> None:
    if not settings.enable_dev_endpoints:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "dev endpoints are disabled"
        )


@router.post("/simulate", response_model=SimulateOut)
async def simulate(
    payload: SimulateIn, db: AsyncSession = Depends(get_db)
) -> SimulateOut:
    """Whole pipeline, one call. Persists by default so it lands on the dashboard."""
    _guard()

    if len(payload.resume_text.strip()) < 80:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "resume_text is too short to extract claims from"
        )

    candidate = Candidate(
        id=ids.candidate_id(), name=payload.name, role=payload.role
    )
    resume = Resume(
        id=ids.resume_id(),
        candidate_id=candidate.id,
        raw_text=normalise(payload.resume_text),
        filename="simulated.txt",
        job_description=payload.job_description,
    )
    db.add(candidate)
    db.add(resume)
    await db.commit()

    session, claims = await orchestrator.create_session(
        db, candidate, resume, Channel.web
    )

    answers = payload.answers or PLACEHOLDER_ANSWERS
    transcript: list[QAPair] = []

    for answer in answers[: settings.max_questions]:
        question = await orchestrator.ask_next(db, session)
        if question is None:
            break
        response, _ = await orchestrator.submit_answer(
            db, session, text=answer, channel=Channel.web
        )
        transcript.append(
            QAPair(
                question=question.text,
                answer=answer,
                question_id=question.id,
                response_id=response.id,
            )
        )

    # If the caller supplied fewer answers than MAX_QUESTIONS, close the session
    # anyway — an abandoned interview should still produce a (low) score.
    await db.refresh(session)
    if session.completed_at is None:
        await orchestrator.finalize(db, session)

    graph = await build_candidate_graph(db, candidate.id)
    if graph is None:  # pragma: no cover
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "graph assembly failed")

    log.info(
        "simulated %s: %d claims, %d answers, competence %.2f",
        candidate.id, len(claims), len(transcript), graph.competence_score or 0.0,
    )
    return SimulateOut(
        candidate_id=candidate.id,
        session_id=session.id,
        questions_asked=session.questions_asked,
        transcript=transcript,
        graph=graph,
    )


@router.get("/fixture")
async def fixture() -> dict:
    """The hand-written sample graph, so the dashboard has data before the DB does."""
    _guard()
    if not FIXTURE_PATH.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "fixtures/sample_graph.json missing")
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@router.get("/llm")
async def llm_diagnostics() -> dict:
    """Cache hits, call count, fallbacks used. Check this after a rehearsal."""
    _guard()
    return {"mode": settings.llm_mode, "model": settings.openai_model, **cache_stats()}


@router.post("/reset", status_code=status.HTTP_200_OK)
async def reset() -> dict:
    """Drop and recreate every table. Run this before a rehearsal, not during one."""
    _guard()
    await drop_all()
    log.warning("database reset via /api/dev/reset")
    return {"status": "reset"}
