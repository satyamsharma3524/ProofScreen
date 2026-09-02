"""
Dev endpoints — how you test everything, and the demo fallback if WhatsApp
misbehaves on stage. Guarded by ENABLE_DEV_ENDPOINTS.

POST /api/dev/simulate                whole pipeline in one call
POST /api/dev/sessions/{id}/answer    step one answer into a live session
GET  /api/dev/fixture                 the hand-written sample graph
GET  /api/dev/llm                     cache hits, calls, fallbacks
POST /api/dev/reset                   drop and recreate every table

The step-answer endpoint is what the retired web-chat channel used to do. It is
explicitly a dev tool, not a second candidate channel: it takes a session id
directly with no opt-in and no phone number, so it must never be exposed to
real candidates. That is the whole reason it lives behind the dev flag.
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
from api.engine.voice import analyse
from api.ingest.parse import normalise
from api.llm import cache_stats
from api.models import Candidate, ChatSession, Resume
from api.schemas import (
    Channel,
    DevAnswerIn,
    DevAnswerOut,
    ProbeLevel,
    SessionOut,
    SessionState,
    SimulateIn,
    SimulateOut,
)
from api.taxonomy import resolve_family

log = logging.getLogger("proofscreen.dev")

router = APIRouter(prefix="/api/dev", tags=["dev"])

FIXTURE_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "sample_graph.json"

# Used when simulate is called with no answers, so a single curl produces a
# fully scored candidate. Deliberately uneven — a strong opening, a vague
# middle, one refusal — so the output is not uniformly good.
PLACEHOLDER_ANSWERS = [
    "I had 35 agents across 4 pods, each with a senior associate. I ran daily "
    "attendance tracking and weekly calibration with the quality team.",
    "Billing complaints were about 40% of negative feedback, so we redesigned "
    "the escalation workflow and added callback SLAs. CSAT moved from 78 to 92 "
    "over about eleven weeks.",
    "I remember the week before month-end when three agents resigned and the "
    "queue backed up to nine hours. I pulled two people off email onto voice "
    "and personally handled the top twelve escalations that Saturday.",
    "We tracked everything in Genesys and I pulled the AHT and occupancy report "
    "each morning before the huddle.",
    "I'm not sure about the exact figures now.",
    "Afterwards the reopen rate halved and we held CSAT above 90 for the next "
    "two quarters. I'd have started the coaching earlier.",
]


def _guard() -> None:
    if not settings.enable_dev_endpoints:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "dev endpoints are disabled")


@router.post("/simulate", response_model=SimulateOut)
async def simulate(
    payload: SimulateIn, db: AsyncSession = Depends(get_db)
) -> SimulateOut:
    """Ingest -> claims -> adaptive probes -> signals -> scores, in one call.

    Persists, so the result appears on the recruiter dashboard immediately.
    """
    _guard()
    if len(payload.resume_text.strip()) < 80:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "resume_text is too short to extract claims from"
        )

    candidate = Candidate(
        id=ids.candidate_id(),
        name=payload.name,
        role=payload.role,
        phone=payload.phone,
        job_family=resolve_family(payload.job_family) if payload.job_family else "general",
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

    # Channel.simulated skips the WhatsApp opt-in wait entirely.
    session, _claims = await orchestrator.create_session(
        db, candidate, resume, Channel.simulated
    )

    answers = payload.answers or PLACEHOLDER_ANSWERS
    for index in range(settings.max_questions):
        question = await orchestrator.ask_next(db, session)
        if question is None:
            break
        answer = answers[index % len(answers)]
        await orchestrator.submit_answer(
            db, session, text=answer, channel=Channel.simulated
        )
        await db.refresh(session)
        if session.state == SessionState.COMPLETE.value:
            break

    await db.refresh(session)
    if session.completed_at is None:
        await orchestrator.finalize(db, session)

    graph = await build_candidate_graph(db, candidate.id)
    if graph is None:  # pragma: no cover
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "graph assembly failed")

    log.info(
        "simulated %s: %d questions, evidence %d, competence %d (%s)",
        candidate.id, session.questions_asked, graph.weighted_evidence_score,
        graph.competence_score, graph.badge.value,
    )
    return SimulateOut(
        candidate_id=candidate.id,
        session_id=session.id,
        questions_asked=session.questions_asked,
        graph=graph,
    )


@router.post("/sessions/{session_id}/start", response_model=SessionOut)
async def start_session(
    session_id: str, db: AsyncSession = Depends(get_db)
) -> SessionOut:
    """Ask the first question without waiting for a WhatsApp opt-in.

    Mirrors exactly what the opt-in handler does, minus the phone binding, so a
    session can be driven from tests or from the booth without a real handset.
    Dev-only for the same reason as the answer endpoint: it skips the consent
    step that opting in represents.
    """
    _guard()
    session = await db.get(ChatSession, session_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    if session.state == SessionState.COMPLETE.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "this session is already complete")

    if session.state == SessionState.AWAITING_OPT_IN.value:
        session.state = SessionState.CLAIMS_READY.value
        await db.commit()

    await orchestrator.ask_next(db, session)
    await db.refresh(session)
    return await orchestrator.session_out(db, session)


@router.post("/sessions/{session_id}/answer", response_model=DevAnswerOut)
async def answer_session(
    session_id: str, payload: DevAnswerIn, db: AsyncSession = Depends(get_db)
) -> DevAnswerOut:
    """Step one answer in without WhatsApp. Dev tool — no opt-in, no phone."""
    _guard()

    session = await db.get(ChatSession, session_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    if session.state == SessionState.COMPLETE.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "this session is already complete")

    text = (payload.text or "").strip()
    if not text:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "text is required")

    # A stated duration lets you exercise the voice path without real audio.
    voice = analyse(text, payload.audio_seconds) if payload.audio_seconds else None

    try:
        response, next_question, contradictions = await orchestrator.submit_answer(
            db,
            session,
            text=text,
            transcript=text if voice else None,
            voice=voice,
            channel=Channel.simulated,
        )
    except orchestrator.SessionClosed as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    await db.refresh(session)
    return DevAnswerOut(
        session_id=session.id,
        state=SessionState(session.state),
        questions_asked=session.questions_asked,
        accepted_text=text,
        answer_score=response.answer_score or 0,
        next_question=next_question.text if next_question else None,
        next_probe_level=(
            ProbeLevel(next_question.probe_level) if next_question else None
        ),
        contradictions=contradictions,
        done=next_question is None,
    )


@router.get("/fixture")
async def fixture() -> dict:
    """The hand-written sample graph, so the dashboard has data before the DB does."""
    _guard()
    if not FIXTURE_PATH.exists():
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "fixtures/sample_graph.json missing"
        )
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@router.get("/llm")
async def llm_diagnostics() -> dict:
    """Cache hits, call count, fallbacks used. Check after every rehearsal."""
    _guard()
    return {"mode": settings.llm_mode, "model": settings.openai_model, **cache_stats()}


@router.post("/reset", status_code=status.HTTP_200_OK)
async def reset() -> dict:
    """Drop and recreate every table. Before a rehearsal, not during one."""
    _guard()
    await drop_all()
    log.warning("database reset via /api/dev/reset")
    return {"status": "reset"}
