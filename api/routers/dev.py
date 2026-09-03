"""
Dev endpoints — how you test everything, and the demo fallback if WhatsApp
misbehaves on stage. Guarded by ENABLE_DEV_ENDPOINTS.

POST /api/dev/simulate                whole pipeline in one call
POST /api/dev/sessions/{id}/answer    step one answer into a live session
GET  /api/dev/fixture                 the hand-written sample graph
GET  /api/dev/detect?text=...         why a resume routed where it did
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

from fastapi import APIRouter, Depends, HTTPException, Query, status
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
from api.taxonomy import GENERAL, MIN_TERMS, family_label, match_family, resolve_family

log = logging.getLogger("proofscreen.dev")

router = APIRouter(prefix="/api/dev", tags=["dev"])

FIXTURE_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "sample_graph.json"

# SMOKE TEST ONLY — used when simulate is called with no answers, so a single
# curl produces a fully scored candidate.
#
# Deliberately uneven — a strong opening, a vague middle, one refusal — so the
# output is not uniformly good. Deliberately DOMAIN-LIGHT: ProofScreen verifies
# reasoning, not professions, and a default answer set written in one industry's
# vocabulary would score every other cohort's resume against the wrong nouns.
# Any real demo or evaluation must pass `answers` explicitly.
PLACEHOLDER_ANSWERS = [
    "I owned a group of 35 people across 4 units, each with a senior person "
    "reporting to me. I ran a daily check on the backlog and a weekly review "
    "with the quality group.",
    "About 40% of the failures traced back to one step in the intake process, "
    "so we redesigned that step and added a follow-up check. The score moved "
    "from 78 to 92 over about eleven weeks.",
    "I remember the week before a major deadline when three people left within "
    "days of each other and the backlog stretched to nine hours. I moved two "
    "people across from another workstream and personally handled the twelve "
    "most urgent items that weekend.",
    "We tracked everything in Jira and I pulled the throughput and utilisation "
    "report in Excel each morning before the stand-up.",
    "I'm not sure about the exact figures now.",
    "Afterwards the rework rate halved and we held the score above 90 for the "
    "next two quarters. I'd have started the coaching earlier.",
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


@router.get("/detect")
async def detect(text: str = Query(min_length=1, max_length=20_000)) -> dict:
    """Explain a routing decision. Deterministic, read-only, no model call.

    P1-08a. Routing decides which claim types a candidate is asked about and
    which rubric weights score them, so "why did this resume land here?" is a
    question someone asks the moment a result looks wrong. Answering it used to
    mean reading `data/claim_taxonomy.json` by eye.

    Returns a plain dict, like the other dev GETs. Deliberately NOT a schema:
    `api/schemas.py` is frozen and Phase 1 needs zero edits to it.
    """
    _guard()
    match = match_family(text)
    ranked = sorted(match.per_family_scores.items(), key=lambda kv: -kv[1])
    runner_up = next((k for k, _ in ranked if k != match.family), None)

    # Two different zeros reach this point and they mean opposite things. A
    # GENERAL route scores 0.0 because the winner fell under the two-term
    # floor, NOT because two families tied -- and `runner_up` there is the
    # family that led and was rejected, not a close second. Describing both as
    # a margin would make the explainability endpoint lie in the one case
    # somebody is most likely to be investigating.
    routed = match.family != GENERAL
    return {
        "family": match.family,
        "family_label": family_label(match.family),
        # A MARGIN, not a probability: how far clear the winner is of the
        # runner-up. It says whether the call was close, not whether it was
        # right, and presenting it as a likelihood would be a lie about what
        # was computed.
        "confidence": match.confidence,
        "confidence_is": (
            "margin (top1 - top2) / top1, against runner_up"
            if routed
            else f"0.0 — no family reached the {MIN_TERMS}-term floor"
        ),
        "runner_up": runner_up if routed else None,
        "rejected_leader": None if routed else runner_up,
        "matched_terms": list(match.matched_terms),
        "per_family_scores": dict(ranked),
        # GENERAL has to explain itself too. "We found npa and nothing else" is
        # a more useful answer than an empty result.
        "min_terms_required": MIN_TERMS,
        "chars_considered": len(text),
    }


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
