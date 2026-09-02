"""
WhatsApp Business Cloud API webhook.  Owned by Dev A.

GET  /api/webhooks/whatsapp   Meta's verification handshake
POST /api/webhooks/whatsapp   inbound messages

WHY THE WORK HAPPENS IN A BACKGROUND TASK
-----------------------------------------
Meta expects a 200 within a few seconds and RETRIES anything slower. Answering
a candidate involves transcription plus two model calls, which is comfortably
slower than that. Handling it inline would mean Meta retries, the retry is
processed as a second answer to the same question, and the interview desyncs
mid-demo.

So: validate, acknowledge with 200 immediately, and do the real work after.
Retries are additionally de-duplicated on the provider message id, because
"probably won't happen" is not a demo strategy.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import select

from api.channels.whatsapp_cloud import normalise_phone, whatsapp_channel
from api.config import settings
from api.db import SessionLocal
from api.engine import orchestrator
from api.engine.orchestrator import SessionClosed
from api.engine.voice import analyse
from api.models import Candidate, Response as ResponseRow, utcnow
from api.schemas import Channel, InboundMessage, SessionState
from api.stt import transcribe_media_id

log = logging.getLogger("proofscreen.webhook")

router = APIRouter(prefix="/api/webhooks", tags=["whatsapp"])

DONE_MESSAGE = (
    "That's everything — thank you. Your verified profile is ready and the "
    "recruiter can see it now."
)
NO_SESSION_MESSAGE = (
    "Hi! I couldn't find an active verification for this number. Upload your "
    "resume on ProofScreen and send me the 6-character code you get back to "
    "begin."
)
BAD_CODE_MESSAGE = "I don't recognise that code. Please check it and send it again."
ALREADY_DONE_MESSAGE = "This verification is already complete — nothing more to do."
VOICE_FAILED_MESSAGE = (
    "I couldn't make out that voice note. Could you type your answer instead?"
)


@router.get("/whatsapp", response_class=PlainTextResponse)
async def verify_webhook(request: Request) -> PlainTextResponse:
    """Meta calls this once when you save the callback URL in the App dashboard.
    It must echo hub.challenge as plain text, not JSON."""
    params = request.query_params
    challenge = whatsapp_channel.verify_challenge(
        params.get("hub.mode"),
        params.get("hub.verify_token"),
        params.get("hub.challenge"),
    )
    if challenge is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "verification failed")
    return PlainTextResponse(content=challenge)


@router.post("/whatsapp", status_code=status.HTTP_200_OK)
async def receive_webhook(
    request: Request, background: BackgroundTasks
) -> Response:
    """Acknowledge fast, process after. Always 200 unless the signature fails."""
    raw = await request.body()

    if not whatsapp_channel.validate_signature(
        raw, request.headers.get("X-Hub-Signature-256")
    ):
        log.warning("rejected inbound with a bad X-Hub-Signature-256")
        raise HTTPException(status.HTTP_403_FORBIDDEN, "invalid signature")

    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        log.warning("inbound webhook body was not JSON")
        return Response(status_code=status.HTTP_200_OK)

    messages = whatsapp_channel.parse_inbound(payload)
    if not messages:
        return Response(status_code=status.HTTP_200_OK)   # status-only delivery

    for message in messages:
        background.add_task(handle_message, message)

    return Response(status_code=status.HTTP_200_OK)


async def handle_message(message: InboundMessage) -> None:
    """One inbound message, end to end, in its own DB session."""
    async with SessionLocal() as db:
        try:
            await _handle(db, message)
        except Exception as exc:  # noqa: BLE001
            log.exception("whatsapp handler failed: %s", exc)
            phone = normalise_phone(message.external_id)
            if phone:
                await whatsapp_channel.send_text(
                    phone,
                    "Something went wrong on our side. Please send your answer "
                    "again in a moment.",
                )


async def _already_processed(db, provider_message_id: str | None) -> bool:
    if not provider_message_id:
        return False
    existing = (
        await db.execute(
            select(ResponseRow).where(
                ResponseRow.provider_message_id == provider_message_id
            )
        )
    ).scalars().first()
    return existing is not None


async def _handle(db, message: InboundMessage) -> None:
    phone = normalise_phone(message.external_id)
    if not phone:
        return

    if await _already_processed(db, message.provider_message_id):
        log.info("ignoring duplicate delivery of %s", message.provider_message_id)
        return

    if message.provider_message_id:
        await whatsapp_channel.mark_read(message.provider_message_id)

    # --- 1. a bare opt-in code binds this phone number to a session ---------
    code = _extract_code(message.text)
    if code:
        session = await orchestrator.find_session_by_opt_in_code(db, code)
        if session is None:
            await whatsapp_channel.send_text(phone, BAD_CODE_MESSAGE)
            return

        candidate = await db.get(Candidate, session.candidate_id)
        if candidate is not None:
            candidate.phone = phone
        session.channel = Channel.whatsapp.value
        session.last_inbound_at = utcnow()
        if session.state == SessionState.AWAITING_OPT_IN.value:
            session.state = SessionState.CLAIMS_READY.value
        await db.commit()

        question = await orchestrator.ask_next(db, session)
        if question is None:
            await whatsapp_channel.send_text(phone, ALREADY_DONE_MESSAGE)
            return

        first_name = (candidate.name.split()[0] if candidate and candidate.name else "there")
        await whatsapp_channel.send_text(
            phone,
            f"Hi {first_name} — I have a few questions about your resume. "
            f"Short answers are fine, and you can reply with a voice note.\n\n"
            f"{question.text}",
        )
        session.last_outbound_at = utcnow()
        await db.commit()
        return

    # --- 2. otherwise this is an answer to an open question ----------------
    session = await orchestrator.find_active_session_by_phone(db, phone)
    if session is None:
        await whatsapp_channel.send_text(phone, NO_SESSION_MESSAGE)
        return

    text = (message.text or "").strip()
    transcript = None
    voice = None

    if message.media_id:
        transcript, duration = await transcribe_media_id(message.media_id)
        if not transcript:
            await whatsapp_channel.send_text(phone, VOICE_FAILED_MESSAGE)
            return
        voice = analyse(transcript, duration)
        log.info(
            "voice note: %.1fs, %d words, effort %d",
            voice.duration_seconds, voice.word_count, voice.effort_score,
        )

    if not text and not transcript:
        await whatsapp_channel.send_text(phone, "Please send your answer as text.")
        return

    try:
        response, next_question, _ = await orchestrator.submit_answer(
            db,
            session,
            text=text or transcript,
            transcript=transcript,
            media_id=message.media_id,
            voice=voice,
            channel=Channel.whatsapp,
        )
    except SessionClosed:
        await whatsapp_channel.send_text(phone, ALREADY_DONE_MESSAGE)
        return

    if message.provider_message_id:
        response.provider_message_id = message.provider_message_id
        await db.commit()

    reply = next_question.text if next_question else DONE_MESSAGE
    await whatsapp_channel.send_text(phone, reply)
    session.last_outbound_at = utcnow()
    await db.commit()


def _extract_code(text: str | None) -> str | None:
    """A bare 6-character opt-in code, optionally prefixed with join/start/ps."""
    if not text:
        return None
    cleaned = text.strip()
    for prefix in ("join ", "start ", "ps ", "code "):
        if cleaned.lower().startswith(prefix):
            cleaned = cleaned[len(prefix):].strip()
            break
    if len(cleaned) != 6:
        return None
    upper = cleaned.upper()
    # Same alphabet ids.join_code() draws from: no O, I, 0 or 1.
    return upper if all(c in "ABCDEFGHJKLMNPQRSTUVWXYZ23456789" for c in upper) else None
