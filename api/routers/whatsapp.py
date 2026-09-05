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
from api.ingest.parse import UnsupportedResume, extract_text
from api.models import (
    DEVELOPMENT_TENANT_ID,
    Candidate,
    ChatSession,
    Response as ResponseRow,
    utcnow,
)
from api.routers.candidates import _onboard
from api.schemas import Badge, Channel, InboundMessage, SessionState
from api.stt import transcribe_media_id
from api.tenancy import TenantScope

log = logging.getLogger("proofscreen.webhook")

router = APIRouter(prefix="/api/webhooks", tags=["whatsapp"])

DONE_MESSAGE = (
    "That's everything — thank you. Your verified profile is ready and the "
    "recruiter can see it now."
)
# G4 — this is now an instruction the system can actually honour. It could not
# before: documents were dropped in parse_inbound, so a candidate who followed
# it got silence. Ships after G3 for that reason, never before.
NO_SESSION_MESSAGE = (
    "Hi! I don't have a verification running for this number yet. "
    "Send me your resume as a PDF or Word document and I'll get started."
)
BAD_CODE_MESSAGE = "I don't recognise that code. Please check it and send it again."
ALREADY_DONE_MESSAGE = "This verification is already complete — nothing more to do."
VOICE_FAILED_MESSAGE = (
    "I couldn't make out that voice note. Could you type your answer instead?"
)
UNSUPPORTED_FILE_MESSAGE = (
    "I can read PDF, Word or plain-text resumes. Could you send one of those?"
)

# G7 — the two gaps between a resume arriving and the first question, each
# covered by the message that says what is happening in it.
#
# The silence is not 10 seconds. Onboarding is claim extraction (LLM #1) then
# question generation (LLM #2), and `complete_json` retries internally on a
# timeout as well as on a schema error, so each is up to two round-trips at a
# 25s client timeout. One question in four also fails validation and is
# regenerated (M7h = 25.5% over 519 live questions), which is a third call.
# Nothing about that is visible to a candidate holding a phone, and an audience
# watching a projector reads any of it as a crash.
#
# There is no third ack. "Ready, let us begin" would fire immediately before
# the question with no gap between them -- a notification buzz carrying no
# information. Two messages, two gaps.
RESUME_RECEIVED_MESSAGE = (
    "Resume received. I'm reading through your experience now — one moment."
)

# G3 — mime -> the suffix `ingest.parse.extract_text` dispatches on. Meta gives
# us a mime; `extract_text` keys on the file suffix, so one of them has to
# translate and it is not going to be the frozen parser. `application/msword`
# is deliberately absent: python-docx cannot read legacy .doc, and a mapped
# entry would turn a clear "send another format" into a confusing parse error.
_RESUME_SUFFIX = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "text/plain": ".txt",
    "text/markdown": ".md",
}


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


# D9 — THE TRUSTED PATH, and one of exactly two in the product.
#
# One WhatsApp business number serves every tenant. An inbound message carries
# a phone number and nothing else, so there is no tenant to scope by until the
# opt-in code or the phone resolves a session — and that session is then what
# supplies the tenant for every row written afterwards. Stated out loud here
# rather than implied by an unfiltered query: `grep -rn "TenantScope.system"
# api/` is the complete list of places this codebase crosses the boundary.
_INBOUND_SCOPE = TenantScope.system(
    "whatsapp inbound: one business number serves every tenant, and the "
    "session is what identifies which one"
)


# G8 — `_already_processed` above queries `responses`, and a resume upload
# writes NO Response row, so that guard is structurally blind to this path.
# Meta retries anything it thinks was slow, and onboarding is the slowest path
# in the product (it blocks on claim extraction), so the retry is likely rather
# than theoretical. Without this, one retry is a second candidate, a second
# session, and two interleaved interviews in one chat.
#
# An in-process set, deliberately. One process, one demo — and it says so
# rather than pretending to be durable. It does not survive a restart; that
# case is covered by `_resume_open_question` below, which is why both exist.
_CLAIMED_DOCS: set[str] = set()


def _claim_once(provider_message_id: str | None) -> bool:
    """True if this delivery is ours to process, False if already claimed."""
    if not provider_message_id:
        return True                 # nothing to key on; never collapse two uploads
    if provider_message_id in _CLAIMED_DOCS:
        log.info("ignoring retried document delivery of %s", provider_message_id)
        return False
    _CLAIMED_DOCS.add(provider_message_id)
    return True


async def _resume_open_question(db, phone: str) -> bool:
    """G8b — a resume arriving over a LIVE session must not start a second
    interview. Re-send the open question instead. True if handled here.

    Covers the three duplicate routes `_claim_once` cannot: a second upload
    with a different message id, a rehearsal that left a session open on the
    demo handset, and a process restart between two deliveries.
    """
    live = await orchestrator.find_active_session_by_phone(db, phone, _INBOUND_SCOPE)
    if live is None:
        return False
    # `ask_next` and not `_open_question`: it is idempotent by contract — an
    # already-open question comes back as-is and no budget is spent — and it
    # takes the RESOLVED SESSION, which is the invariant that lets the
    # orchestrator query without a tenant filter at all
    # (`test_the_orchestrator_is_entered_with_resolved_rows_not_ids`).
    open_q = await orchestrator.ask_next(db, live)
    await whatsapp_channel.send_text(
        phone,
        f"You already have an interview in progress — here's where we left "
        f"off:\n\n{open_q.text}" if open_q else ALREADY_DONE_MESSAGE,
    )
    return True


async def _try_resume_intake(db, phone: str, message: InboundMessage) -> bool:
    """A media message that turns out not to be audio is a resume.

    Returns True if this message was handled here; False to let the caller fall
    through to the voice/answer path.
    """
    if not _claim_once(message.provider_message_id):
        return True

    data, mime = await whatsapp_channel.download_media(message.media_id)

    # ORDER MATTERS, and this is the one trap in the whole path. In dry-run
    # `media_url()` returns (None, None) and `download_media()` then DEFAULTS
    # the mime to "audio/ogg" — so a nil body must be tested before the mime,
    # or every document looks like a voice note and the branch never runs.
    if data is None:
        _CLAIMED_DOCS.discard(message.provider_message_id or "")
        return False

    kind = (mime or "").split(";")[0].strip().lower()
    if kind.startswith("audio/"):
        _CLAIMED_DOCS.discard(message.provider_message_id or "")
        return False                                  # genuinely a voice note

    suffix = _RESUME_SUFFIX.get(kind)
    if not suffix:
        await whatsapp_channel.send_text(phone, UNSUPPORTED_FILE_MESSAGE)
        return True

    if await _resume_open_question(db, phone):        # G8b
        return True

    await whatsapp_channel.send_text(phone, RESUME_RECEIVED_MESSAGE)      # G7 #1

    try:
        resume_text = extract_text(f"resume{suffix}", data)
    except UnsupportedResume as exc:
        await whatsapp_channel.send_text(phone, f"I couldn't read that file — {exc}")
        return True

    result = await _onboard(
        db,
        # G3 — `_INBOUND_SCOPE` is a system scope and `require()` raises on it
        # by design, so it cannot be used for a WRITE. A WhatsApp-originated
        # candidate belongs to the NAMED development tenant. A second customer
        # needs a number-to-tenant resolver, and this line is where it goes.
        scope=TenantScope.of(DEVELOPMENT_TENANT_ID),
        name=message.profile_name or "WhatsApp candidate",
        phone=phone,
        resume_text=resume_text,
        filename=f"resume{suffix}",
    )

    # G7 #2. The claim count is free -- `_onboard` already returned it -- and it
    # is the better message: it proves the resume was READ, where "preparing
    # your question" only promises that something is happening.
    await whatsapp_channel.send_text(
        phone,
        (
            f"Got it — I've understood your background and found "
            f"{len(result.claims)} "
            f"{'claim' if len(result.claims) == 1 else 'claims'} worth "
            f"verifying. Preparing your first question..."
        )
        if result.claims
        else "Got it — I've read your background. Preparing your first question...",
    )

    session = await db.get(ChatSession, result.session_id)
    if session is None:
        return True

    # The candidate messaged US, unprompted, with their resume. The 24-hour
    # window is open and the upload is a stronger consent signal than a code,
    # so the opt-in gate does not apply. Same eight lines as the opt-in branch
    # below, duplicated on purpose: that branch is the demo's fallback path and
    # is not being touched this week.
    session.channel = Channel.whatsapp.value
    session.last_inbound_at = utcnow()
    if session.state == SessionState.AWAITING_OPT_IN.value:
        session.state = SessionState.CLAIMS_READY.value
    await db.commit()

    question = await orchestrator.ask_next(db, session)
    if question is None:
        await whatsapp_channel.send_text(phone, ALREADY_DONE_MESSAGE)
        return True

    await whatsapp_channel.send_text(phone, question.text)
    session.last_outbound_at = utcnow()
    await db.commit()
    return True


# G6 — the same words the dashboard prints. `Badge` carries the values and
# lib/api/format.ts carries the labels, so this is a second copy and it exists
# on purpose: without it the closing WhatsApp message and the recruiter's
# screen call the same candidate two different things, ninety seconds apart, in
# the same demo.
_BADGE_LABEL = {
    Badge.verified: "Verified",
    Badge.partial: "Partially verified",
    Badge.unverified: "Unverified",
}


async def _completion_summary(db, session) -> str:
    """What the candidate gets instead of one flat sentence.

    Everything here is already computed and committed: `submit_answer` calls
    `finalize()`, which recomputes the profile BEFORE it returns. This is a
    read, not a second scoring pass.

    WHAT IS DELIBERATELY LEFT OUT. `resume_score` -- the gap between it and the
    competence score is the recruiter's insight and the demo's punchline, and
    the product already withholds audit detail from candidates. `consistency`
    -- it is an int with no band, and inventing "High" here would be a word
    that appears nowhere else in the product.

    NEVER RAISES. This is the last message of the demo; a traceback here loses
    the ending, so it degrades to the flat sentence it replaces.
    """
    from api.engine import graph as graph_engine

    try:
        graph = await graph_engine.build_candidate_graph(
            db, session.candidate_id, scope=TenantScope.of(session.tenant_id)
        )
        if graph is None:
            return DONE_MESSAGE
        # `probed`, not `score > 0`. It is the field that means "we asked about
        # this", which is what "covered" claims -- and it is what the dashboard
        # counts, so the two cannot disagree on stage.
        probed = sum(1 for d in graph.dimension_profile if d.probed)
        claims = len(graph.claims)
        return (
            "That's everything — thank you.\n\n"
            f"*Competence score: {graph.competence_score}/100*\n"
            f"Status: {_BADGE_LABEL.get(graph.badge, graph.badge.value)}\n"
            f"Evidence covered {probed} of {len(graph.dimension_profile)} "
            f"dimensions across {claims} "
            f"{'claim' if claims == 1 else 'claims'}.\n\n"
            "Your verified profile is ready and the recruiter can see it now."
        )
    except Exception:  # noqa: BLE001
        log.exception("completion summary failed; sending the plain message")
        return DONE_MESSAGE


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
        session = await orchestrator.find_session_by_opt_in_code(db, code, _INBOUND_SCOPE)
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

    # --- 2. a document is a resume: onboard and start the interview --------
    if message.media_id and await _try_resume_intake(db, phone, message):
        return

    # --- 3. otherwise this is an answer to an open question ----------------
    session = await orchestrator.find_active_session_by_phone(db, phone, _INBOUND_SCOPE)
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

    reply = (
        next_question.text
        if next_question
        else await _completion_summary(db, session)      # G6
    )
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
