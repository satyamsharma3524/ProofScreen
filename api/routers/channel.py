"""
Inbound message handling for both channels. Owned by Dev A.

POST /api/web/message        the always-works channel (Next.js candidate UI)
POST /api/webhooks/twilio    Twilio WhatsApp sandbox, form-encoded

Both funnel into orchestrator.submit_answer(). The WhatsApp handler replies
with TwiML, so the demo needs no outbound Twilio credentials.
"""

from __future__ import annotations

import logging
import re

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import Response as HTTPResponse
from sqlalchemy.ext.asyncio import AsyncSession

from api.channels.whatsapp_twilio import normalise_phone, twiml, whatsapp_channel
from api.config import settings
from api.db import SessionLocal, get_db
from api.engine import orchestrator
from api.engine.orchestrator import SessionClosed
from api.models import Candidate, ChatSession
from api.schemas import Channel, SessionState, WebMessageIn, WebMessageOut
from api.stt import transcribe_url

log = logging.getLogger("proofscreen.channel")

router = APIRouter(tags=["channel"])

DONE_MESSAGE = (
    "That's everything — thank you. Your verified profile is being finalised "
    "and is now visible to the recruiter."
)
NO_SESSION_MESSAGE = (
    "Hi! I could not find an active verification for this number. "
    "Upload your resume on ProofScreen and send me the 6-character code you "
    "get back to begin."
)
VOICE_FAILED_MESSAGE = (
    "I couldn't hear that voice note clearly. Could you type your answer instead?"
)

_CODE_RE = re.compile(r"^(?:join\s+|start\s+|ps\s+)?([A-Z2-9]{6})$", re.IGNORECASE)


def _extract_join_code(text: str | None) -> str | None:
    if not text:
        return None
    match = _CODE_RE.match(text.strip())
    return match.group(1).upper() if match else None


async def _resolve_answer_text(text: str | None, media_url: str | None) -> tuple[str, str | None]:
    """Returns (answer_text, transcript). Voice notes go through Whisper."""
    if media_url:
        transcript = await transcribe_url(media_url)
        if transcript:
            return transcript, transcript
        return (text or "").strip(), None
    return (text or "").strip(), None


# ---------------------------------------------------------------------------
# web chat
# ---------------------------------------------------------------------------


@router.post("/api/web/message", response_model=WebMessageOut, tags=["channel"])
async def web_message(
    payload: WebMessageIn,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> WebMessageOut:
    session = await db.get(ChatSession, payload.session_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")

    if session.state == SessionState.COMPLETE.value:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "this session is already complete"
        )

    answer_text, transcript = await _resolve_answer_text(payload.text, payload.audio_url)
    if not answer_text:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "send either `text` or an `audio_url` that transcribes to something",
        )

    try:
        _, next_question = await orchestrator.submit_answer(
            db,
            session,
            text=answer_text,
            audio_url=payload.audio_url,
            transcript=transcript,
            channel=Channel.web,
        )
    except SessionClosed as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    if not settings.score_inline:
        background.add_task(_score_in_background, session.id)

    await db.refresh(session)
    return WebMessageOut(
        session_id=session.id,
        state=SessionState(session.state),
        accepted_text=answer_text,
        questions_asked=session.questions_asked,
        next_question=next_question.text if next_question else None,
        done=next_question is None,
    )


async def _score_in_background(session_id: str) -> None:
    """Own DB session: the request's session is closed by the time this runs."""
    async with SessionLocal() as db:
        try:
            await orchestrator.score_pending(db, session_id)
        except Exception as exc:  # noqa: BLE001
            log.error("background scoring failed for %s: %s", session_id, exc)


# ---------------------------------------------------------------------------
# whatsapp
# ---------------------------------------------------------------------------


@router.post("/api/webhooks/twilio", tags=["channel"])
async def twilio_webhook(
    request: Request,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> HTTPResponse:
    """Always returns 200 with TwiML. A stack trace here is a silent demo death."""
    form = {k: str(v) for k, v in (await request.form()).items()}

    url = (
        f"{settings.public_base_url.rstrip('/')}{request.url.path}"
        if settings.public_base_url
        else str(request.url)
    )
    if not whatsapp_channel.validate_signature(
        url, form, request.headers.get("X-Twilio-Signature")
    ):
        log.warning("rejected inbound with bad Twilio signature")
        raise HTTPException(status.HTTP_403_FORBIDDEN, "invalid Twilio signature")

    inbound = whatsapp_channel.parse_inbound(form)
    phone = normalise_phone(inbound.external_id)
    log.info("whatsapp inbound from %s: %r media=%s", phone, inbound.text, bool(inbound.media_url))

    try:
        reply = await _handle_whatsapp(db, inbound.text, inbound.media_url, phone)
    except Exception as exc:  # noqa: BLE001
        log.exception("whatsapp handler failed: %s", exc)
        reply = (
            "Something went wrong on our side. Please send your answer again in "
            "a moment."
        )

    if not settings.score_inline:
        session = await orchestrator.find_active_session_by_phone(db, phone) if phone else None
        if session:
            background.add_task(_score_in_background, session.id)

    return HTTPResponse(content=twiml(reply), media_type="application/xml")


async def _handle_whatsapp(
    db: AsyncSession,
    text: str | None,
    media_url: str | None,
    phone: str | None,
) -> str:
    # 1. A bare 6-character code binds this phone to a session created on the web.
    code = _extract_join_code(text)
    if code:
        session = await orchestrator.find_session_by_join_code(db, code)
        if session is None:
            return "I don't recognise that code. Check it and send it again."
        candidate = await db.get(Candidate, session.candidate_id)
        if candidate is not None and phone:
            candidate.phone = phone
        session.channel = Channel.whatsapp.value
        await db.commit()

        question = await orchestrator.ask_next(db, session)
        if question is None:
            return "This verification is already complete. Nothing more to do."
        return (
            f"Hi {candidate.name.split()[0] if candidate else 'there'} — "
            f"I have {session.questions_asked} of {settings.max_questions} "
            f"questions about your resume.\n\n{question.text}"
        )

    # 2. Otherwise this is an answer to an open question.
    if not phone:
        return NO_SESSION_MESSAGE
    session = await orchestrator.find_active_session_by_phone(db, phone)
    if session is None:
        return NO_SESSION_MESSAGE

    answer_text, transcript = await _resolve_answer_text(text, media_url)
    if not answer_text:
        return VOICE_FAILED_MESSAGE if media_url else "Please send your answer as text."

    try:
        _, next_question = await orchestrator.submit_answer(
            db,
            session,
            text=answer_text,
            audio_url=media_url,
            transcript=transcript,
            channel=Channel.whatsapp,
        )
    except SessionClosed:
        return "This verification is already complete. Nothing more to do."

    if next_question is None:
        return DONE_MESSAGE
    return next_question.text
