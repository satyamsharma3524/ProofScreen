"""Voice notes: media url -> transcript. Whisper, three lines of real work."""

from __future__ import annotations

import io
import logging

import httpx

from api.config import settings

log = logging.getLogger("proofscreen.stt")

MAX_AUDIO_BYTES = 25 * 1024 * 1024   # Whisper's own limit


async def fetch_media(url: str) -> tuple[bytes, str]:
    """Download an audio attachment.

    Twilio media URLs require HTTP basic auth with the account SID and auth
    token. Getting this wrong is a 401 that looks like a bug in your code —
    it is the single most common Twilio surprise, so it is handled here.
    """
    auth = None
    if "twilio.com" in url and settings.twilio_enabled:
        auth = (settings.twilio_account_sid, settings.twilio_auth_token)

    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
        resp = await client.get(url, auth=auth)
        resp.raise_for_status()

    content_type = resp.headers.get("content-type", "audio/ogg")
    if len(resp.content) > MAX_AUDIO_BYTES:
        raise ValueError("audio file too large to transcribe")
    return resp.content, content_type


def _filename_for(content_type: str) -> str:
    mapping = {
        "audio/ogg": "voice.ogg",
        "audio/opus": "voice.ogg",
        "audio/mpeg": "voice.mp3",
        "audio/mp4": "voice.m4a",
        "audio/x-m4a": "voice.m4a",
        "audio/wav": "voice.wav",
        "audio/x-wav": "voice.wav",
        "audio/webm": "voice.webm",
    }
    return mapping.get(content_type.split(";")[0].strip().lower(), "voice.ogg")


async def transcribe(audio: bytes, content_type: str = "audio/ogg") -> str:
    if not settings.llm_enabled:
        log.info("fixture mode: skipping transcription")
        return ""

    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        api_key=settings.openai_api_key, timeout=settings.llm_timeout_seconds * 2
    )
    buf = io.BytesIO(audio)
    buf.name = _filename_for(content_type)
    result = await client.audio.transcriptions.create(
        model=settings.openai_stt_model, file=buf
    )
    text = (getattr(result, "text", "") or "").strip()
    log.info("transcribed %d bytes -> %d chars", len(audio), len(text))
    return text


async def transcribe_url(url: str) -> str:
    """Full path, and it never raises — a failed voice note must not 500 the
    webhook. Returns "" and lets the orchestrator ask the candidate to retype."""
    try:
        audio, content_type = await fetch_media(url)
        return await transcribe(audio, content_type)
    except Exception as exc:  # noqa: BLE001
        log.error("transcription failed for %s: %s", url, exc)
        return ""
