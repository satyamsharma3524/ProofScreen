"""
Short, prefixed, human-readable ids.

Deliberate choice: `cl_9f3a21` is greppable in logs and readable on a slide.
`f47ac10b-58cc-4372-a567-0e02b2c3d479` is neither, and on demo day you will be
reading ids off a screen out loud.
"""

from __future__ import annotations

import random
import secrets
import string
import uuid

_ALPHABET = string.ascii_uppercase + string.digits


def _short(n: int = 6) -> str:
    return uuid.uuid4().hex[:n]


# MEASURED, not guessed. 6 hex chars is 16.7M values, and the birthday bound
# over a whole test-suite run is not small: at ~2,000 generated ids the chance
# of at least one collision is 11.2%, and at 5,000 it is 52.5%. It fired for
# real -- `UNIQUE constraint failed: session_facts.id` on an otherwise green
# suite, once, and then not again on three re-runs. A flake that vanishes is
# still a defect; the same collision mid-interview on demo day is an
# IntegrityError in front of an audience.
#
# The split below is the fix, and it keeps the reason 6 chars was chosen in the
# first place. Ids a human reads off a screen or types into a support chat stay
# short. Ids that only ever appear in a foreign key go to 10 chars (1.1 trillion
# values, 0.0002% at 2,000), because nobody has ever read an evidence id aloud.
#
# `session_id` was already 10 for the same reason.
_MACHINE = 10


def candidate_id() -> str:
    return f"c_{_short()}"


def resume_id() -> str:
    return f"rs_{_short()}"


def session_id() -> str:
    return f"s_{_short(10)}"


def claim_id() -> str:
    return f"cl_{_short()}"


def question_id() -> str:
    return f"q_{_short(_MACHINE)}"


def response_id() -> str:
    return f"r_{_short()}"


def evidence_id() -> str:
    # Machine-only: appears in foreign keys, never on a slide. See _MACHINE.
    return f"e_{_short(_MACHINE)}"


def fact_id() -> str:
    # Machine-only: appears in foreign keys, never on a slide. See _MACHINE.
    return f"f_{_short(_MACHINE)}"


def contradiction_id() -> str:
    # Machine-only: appears in foreign keys, never on a slide. See _MACHINE.
    return f"x_{_short(_MACHINE)}"


def role_id() -> str:
    return f"jr_{_short()}"


def score_id() -> str:
    # Machine-only: appears in foreign keys, never on a slide. See _MACHINE.
    return f"sc_{_short(_MACHINE)}"


def profile_id() -> str:
    # Machine-only: appears in foreign keys, never on a slide. See _MACHINE.
    return f"p_{_short(_MACHINE)}"


def outcome_id() -> str:
    return f"o_{_short()}"


def tenant_id() -> str:
    # Few of these ever exist and a human names them, so 6 is plenty. The
    # DEVELOPMENT tenant does not use this: it is the fixed literal `t_dev`
    # (models.DEVELOPMENT_TENANT_ID), because a random id for the one tenant
    # every default write lands in would make seeds and fixtures unstable.
    return f"t_{_short()}"


def api_key_id() -> str:
    # Machine-only. See _MACHINE.
    return f"ak_{_short(_MACHINE)}"


def evaluation_id() -> str:
    # 10, not 6, and deliberately against the "humans read it" rule. An
    # evaluation id is a URL path segment and a support-ticket reference, and
    # there is one per interview — the most numerous recruiter-facing entity
    # there will ever be. At 6 chars the birthday bound bites at a few thousand
    # rows; at 10 it does not. See the _MACHINE note above.
    return f"ev_{_short(_MACHINE)}"


def api_key_secret() -> str:
    """The raw API key. Returned once, stored only as a sha256 hash.

    `secrets`, not `random`: this is a credential, and `random` is a Mersenne
    Twister whose state is recoverable from its own output.
    """
    return f"psk_{secrets.token_urlsafe(32)}"


def join_code() -> str:
    """6 chars, no lookalikes — a candidate types this into WhatsApp."""
    safe = "".join(c for c in _ALPHABET if c not in "OI01")
    return "".join(random.choice(safe) for _ in range(6))
