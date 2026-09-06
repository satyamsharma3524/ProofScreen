"""
Voice notes: WhatsApp media id -> transcript + duration.

Transcription is Groq's hosted Whisper (whisper-large-v3-turbo) over its
OpenAI-compatible /audio/transcriptions route, called with raw httpx rather
than the OpenAI SDK -- there is no Groq SDK dependency to add for one endpoint.
Chat completions (extraction/question/evidence, api/llm.py) stay on OpenAI;
only this file's provider differs.

No `language` is sent, deliberately: this candidate population code-switches
Hindi/English/Hinglish mid-answer, and forcing a single language hurts
accuracy rather than helping it. `temperature=0` for determinism.

Duration comes from the verbose_json response rather than a separate audio
library: it is exact, it costs nothing extra, and it removes a native
dependency from the Docker image. Duration matters because it is half of the
voice effort signal (see engine/voice.py).

Nothing in here raises. A failed voice note must never 500 the webhook — the
candidate simply gets asked to type instead.

LIVE_INTERVIEW_QUALITY_AUDIT F1/P1 — a low-confidence transcription is treated
as a failed one, not scored as the candidate's words. Two real interviews
found Whisper returning garbled Hindi with no error and no empty string,
scored as if it were a real answer, silently lowering the candidate's
dimension scores. `verbose_json`'s per-segment `no_speech_prob` /
`avg_logprob` (Whisper's own decoding-time confidence signals, already free in
the response this file requests) catch that case: below threshold, `transcribe`
returns `("", 0.0)` exactly as it does for a genuine STT failure, which routes
through the SAME existing "please resend" path in `routers/whatsapp.py` rather
than reaching `engine/evidence` as if it were real words. No language check —
that would penalise the Hindi/English code-switching this file is deliberately
tolerant of; low confidence is measured from the model's own uncertainty, not
from which language it thinks it heard.
"""

from __future__ import annotations

import logging
import statistics

import httpx

from api.channels.whatsapp_cloud import whatsapp_channel
from api.config import settings

log = logging.getLogger("proofscreen.stt")

MAX_AUDIO_BYTES = 25 * 1024 * 1024   # Whisper's own limit

# Whisper's own CLI defaults for "this segment is probably not real speech" /
# "the model was guessing". Averaged across segments rather than applied
# per-segment, so one confident sentence in an otherwise-clean answer does not
# get thrown out over a single mumbled word.
_NO_SPEECH_THRESHOLD = 0.6
_LOGPROB_THRESHOLD = -1.0

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


def _low_confidence(segments: list[dict] | None) -> bool:
    """True when Whisper's own decoding signals say it was guessing.

    No `segments` (a provider that omits them) means no signal to gate on —
    fail open rather than reject every transcript for a field the response
    simply didn't include.
    """
    if not segments:
        return False
    no_speech = [float(s.get("no_speech_prob", 0.0)) for s in segments]
    logprob = [float(s.get("avg_logprob", 0.0)) for s in segments]
    return (
        statistics.fmean(no_speech) > _NO_SPEECH_THRESHOLD
        or statistics.fmean(logprob) < _LOGPROB_THRESHOLD
    )


async def transcribe(audio: bytes, mime: str = "audio/ogg") -> tuple[str, float]:
    """Returns (transcript, duration_seconds). ("", 0.0) on any failure."""
    if not settings.llm_enabled:
        log.info("fixture mode: skipping transcription")
        return "", 0.0
    if not settings.groq_api_key:
        log.error("GROQ_API_KEY not set: skipping transcription")
        return "", 0.0
    if not audio:
        return "", 0.0
    if len(audio) > MAX_AUDIO_BYTES:
        log.error("audio too large to transcribe (%d bytes)", len(audio))
        return "", 0.0

    try:
        async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds * 2) as client:
            response = await client.post(
                f"{settings.groq_api_base}/audio/transcriptions",
                headers={"Authorization": f"Bearer {settings.groq_api_key}"},
                files={"file": (_filename_for(mime), audio, mime)},
                data={
                    "model": settings.groq_stt_model,
                    "response_format": "verbose_json",
                    "temperature": "0",
                    # No `language`: this population code-switches
                    # Hindi/English/Hinglish mid-answer, and forcing one
                    # language hurts accuracy rather than helping it.
                },
            )
            response.raise_for_status()
            result = response.json()
        text = (result.get("text") or "").strip()
        duration = float(result.get("duration") or 0.0)
        if text and _low_confidence(result.get("segments")):
            log.error(
                "low-confidence transcription discarded: %d bytes -> %d chars, %.1fs",
                len(audio), len(text), duration,
            )
            return "", 0.0
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
