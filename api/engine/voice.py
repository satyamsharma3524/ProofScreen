"""
Voice evidence.  NO LLM IN THIS FILE.

What we measure: how long they spoke, and how much they said.
What we refuse to measure: accent, fluency, grammar, pause pattern, "speech
confidence", emotion.

That refusal is a product decision, not an oversight. In India those signals
track region, first language, schooling and class far more strongly than they
track competence, and a Team Lead from Jaipur must not score below one from
Bangalore for the sound of their voice. The transcript carries the evidence;
the audio only tells us whether they engaged with the question at all.

Voice therefore contributes a small, fixed share of a claim's score
(VOICE_WEIGHT, default 10%), and only for claims answered by voice.
"""

from __future__ import annotations

import re

from api.schemas import VoiceSignals

# A considered spoken answer to "tell me about a time..." runs about half a
# minute and about sixty words. These are the saturation points, not minimums.
TARGET_SECONDS = 30.0
TARGET_WORDS = 60

_WORD = re.compile(r"[^\s]+")


def word_count(text: str) -> int:
    return len(_WORD.findall(text or ""))


def effort_score(duration_seconds: float, words: int) -> int:
    """0-100 from duration and word count, weighted equally.

    Both halves matter: 40 seconds of silence is not evidence, and neither is a
    three-second "yes I did that". Someone who says a lot in 15 seconds scores
    well on one half and is not punished on the other.
    """
    duration_part = min(1.0, max(0.0, duration_seconds) / TARGET_SECONDS)
    words_part = min(1.0, max(0, words) / TARGET_WORDS)
    return int(round(100 * (0.5 * duration_part + 0.5 * words_part)))


def analyse(transcript: str, duration_seconds: float | None) -> VoiceSignals:
    words = word_count(transcript)
    duration = float(duration_seconds or 0.0)
    wpm = round(words / (duration / 60.0), 1) if duration >= 1.0 else None
    return VoiceSignals(
        duration_seconds=round(duration, 2),
        word_count=words,
        words_per_minute=wpm,
        effort_score=effort_score(duration, words),
    )
