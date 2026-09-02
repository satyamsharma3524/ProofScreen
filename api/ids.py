"""
Short, prefixed, human-readable ids.

Deliberate choice: `cl_9f3a21` is greppable in logs and readable on a slide.
`f47ac10b-58cc-4372-a567-0e02b2c3d479` is neither, and on demo day you will be
reading ids off a screen out loud.
"""

from __future__ import annotations

import random
import string
import uuid

_ALPHABET = string.ascii_uppercase + string.digits


def _short(n: int = 6) -> str:
    return uuid.uuid4().hex[:n]


def candidate_id() -> str:
    return f"c_{_short()}"


def resume_id() -> str:
    return f"rs_{_short()}"


def session_id() -> str:
    return f"s_{_short(10)}"


def claim_id() -> str:
    return f"cl_{_short()}"


def question_id() -> str:
    return f"q_{_short()}"


def response_id() -> str:
    return f"r_{_short()}"


def evidence_id() -> str:
    return f"e_{_short()}"


def fact_id() -> str:
    return f"f_{_short()}"


def contradiction_id() -> str:
    return f"x_{_short()}"


def role_id() -> str:
    return f"jr_{_short()}"


def score_id() -> str:
    return f"sc_{_short()}"


def profile_id() -> str:
    return f"p_{_short()}"


def join_code() -> str:
    """6 chars, no lookalikes — a candidate types this into WhatsApp."""
    safe = "".join(c for c in _ALPHABET if c not in "OI01")
    return "".join(random.choice(safe) for _ in range(6))
