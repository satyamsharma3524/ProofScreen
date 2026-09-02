"""Test config. Env is set BEFORE api.config is imported anywhere.

The suite runs against in-memory SQLite with no OpenAI key and no WhatsApp
credentials, so `pytest` needs neither Docker nor a network. Deliberate: a
suite you cannot run in two seconds is a suite you stop running on day four.
"""

from __future__ import annotations

import os

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["OPENAI_API_KEY"] = ""              # fixture mode
os.environ["ENABLE_DEV_ENDPOINTS"] = "true"
os.environ["ADAPTIVE_PROBING"] = "true"
os.environ["SCORE_INLINE"] = "true"
os.environ["MAX_QUESTIONS"] = "12"
os.environ["MAX_CLAIMS"] = "3"
os.environ["VOICE_WEIGHT"] = "0.10"
os.environ["WHATSAPP_VERIFY_TOKEN"] = "test-verify-token"
os.environ["WHATSAPP_VALIDATE_SIGNATURE"] = "false"
os.environ["WHATSAPP_ACCESS_TOKEN"] = ""       # dry-run outbound

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

# A BPO resume whose three strongest lines classify as three distinct claim
# types, so the breadth phase of the policy has something to spread across.
# NOTE: the vocabulary here is load-bearing. detect_family() scores by keyword
# hits, and an earlier version of this resume classified as `customer_support`
# — correctly, since it said "support / escalation / Zendesk" and almost
# nothing BPO-specific. customer_support has no `team_handling` or
# `aht_control` claim type, so every weight-based assertion below silently
# collapsed. The BPO terms are here to pin the family.
RESUME = """Priya Raghavan - Support Operations Team Lead, Bengaluru
International voice process, night shift

EXPERIENCE
Team Lead, Northwind Services
- Managed a team of 35 agents across 4 pods with 4 senior associates reporting to me
- Improved CSAT from 78% to 92% in four quarters by redesigning the escalation workflow
- Reduced AHT from 480 seconds to 430 seconds by rewriting the call opening scripts

SKILLS
Roster and shrinkage planning, calibration, occupancy management, nesting, Genesys, Zendesk
"""

# Rich answers: quantities, process steps, a complete causal chain, a specific
# incident, a defined metric, and a tool with described usage.
STRONG_ANSWERS = [
    "I had 35 agents in four pods, and each pod had a senior associate reporting to me. "
    "I ran daily attendance tracking and a weekly calibration with the quality team.",

    "Billing complaints were about 40% of our negative feedback, so we redesigned the "
    "escalation workflow and introduced callback SLAs, and CSAT moved from 78 to 92 "
    "over about eleven weeks.",

    "I remember the week before month-end when three agents resigned on the same day "
    "and the queue backed up to nine hours. I moved two people off email onto voice and "
    "personally handled the top twelve escalations that Saturday.",

    "CSAT is measured from the post-interaction survey, as the percentage of 4 and 5 "
    "ratings out of all responses. I reviewed it in Zendesk every Monday against the "
    "reopen report.",

    "We tracked everything in Genesys and I pulled the AHT and occupancy report each "
    "morning before the huddle.",

    "Afterwards the reopen rate halved and we held CSAT above 90 for two quarters. "
    "Looking back I would have started the coaching cadence a month earlier.",
]

EVASIVE_ANSWERS = ["I don't know.", "It was a while ago.", "I don't remember the details."]


@pytest.fixture(scope="session")
def client():
    from api.main import app

    with TestClient(app) as test_client:
        yield test_client


def onboard(client, name: str = "Priya Raghavan", phone: str = "+919810000001", **extra) -> dict:
    payload = {
        "resume_text": RESUME,
        "name": name,
        "phone": phone,
        "role": "Support Team Lead",
        **extra,
    }
    resp = client.post("/api/candidates/text", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def run_interview(client, session_id: str, answers: list[str] | None = None) -> list[dict]:
    """Drive a session to completion through the dev endpoints.

    The start call matters: after onboarding a session sits in AWAITING_OPT_IN
    with no open question, because WhatsApp Business API will not let us message
    a candidate who has not messaged us first.
    """
    answers = answers or STRONG_ANSWERS
    started = client.post(f"/api/dev/sessions/{session_id}/start")
    assert started.status_code == 200, started.text

    turns: list[dict] = []
    for index in range(20):                       # hard stop; budget is 12
        state = client.get(f"/api/sessions/{session_id}").json()
        if not state["next_question"]:
            break
        resp = client.post(
            f"/api/dev/sessions/{session_id}/answer",
            json={"text": answers[index % len(answers)]},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        turns.append(body)
        if body["done"]:
            break
    return turns
