"""
Voice notes: WhatsApp media id -> transcript + duration.

Duration comes from Whisper's verbose_json response rather than a separate
audio library: it is exact, it costs nothing extra, and it removes a native
dependency from the Docker image. Duration matters because it is half of the
voice effort signal (see engine/voice.py).

Nothing in here raises. A failed voice note must never 500 the webhook — the
candidate simply gets asked to type instead.
"""

from __future__ import annotations

import io
import logging

from api.channels.whatsapp_cloud import whatsapp_channel
from api.config import settings

log = logging.getLogger("proofscreen.stt")

MAX_AUDIO_BYTES = 25 * 1024 * 1024   # Whisper's own limit

_EXTENSIONS = {
    "audio/ogg": "voice.ogg",
    "audio/opus": "voice.ogg",
    "audio/mpeg": "voice.mp3",
    "audio/mp4": "voice.m4a",
    "audio/x-m4a": "voice.m4a",
    "audio/aac": "voice.aac",
    "audio/amr": "voice.amr",
    "audio/wav": "voice.wav",
    "audio/x-wav": "voice.wav",
    "audio/webm": "voice.webm",
}


def _filename_for(mime: str) -> str:
    return _EXTENSIONS.get((mime or "").split(";")[0].strip().lower(), "voice.ogg")


async def transcribe(audio: bytes, mime: str = "audio/ogg") -> tuple[str, float]:
    """Returns (transcript, duration_seconds). ("", 0.0) on any failure."""
    if not settings.llm_enabled:
        log.info("fixture mode: skipping transcription")
        return "", 0.0
    if not audio:
        return "", 0.0
    if len(audio) > MAX_AUDIO_BYTES:
        log.error("audio too large to transcribe (%d bytes)", len(audio))
        return "", 0.0

    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            timeout=settings.llm_timeout_seconds * 2,
        )
        buffer = io.BytesIO(audio)
        buffer.name = _filename_for(mime)
        result = await client.audio.transcriptions.create(
            model=settings.openai_stt_model,
            file=buffer,
            response_format="verbose_json",
        )
        text = (getattr(result, "text", "") or "").strip()
        duration = float(getattr(result, "duration", 0.0) or 0.0)
        log.info("transcribed %d bytes -> %d chars, %.1fs", len(audio), len(text), duration)
        return text, duration
    except Exception as exc:  # noqa: BLE001
        log.error("transcription failed: %s", exc)
        return "", 0.0


async def transcribe_media_id(media_id: str) -> tuple[str, float]:
    """Full WhatsApp path: two-step media download, then Whisper."""
    audio, mime = await whatsapp_channel.download_media(media_id)
    if not audio:
        return "", 0.0
    return await transcribe(audio, mime)
