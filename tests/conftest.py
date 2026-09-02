"""Test config. Env is set BEFORE api.config is imported anywhere.

The suite runs against in-memory SQLite with no OPENAI_API_KEY, so
`pytest` needs neither Docker nor a network. That is deliberate: a test suite
you cannot run in 3 seconds is a test suite you stop running on day four.
"""

from __future__ import annotations

import os

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["OPENAI_API_KEY"] = ""          # forces fixture mode
os.environ["ENABLE_DEV_ENDPOINTS"] = "true"
os.environ["ADAPTIVE_FOLLOWUPS"] = "true"
os.environ["SCORE_INLINE"] = "true"
os.environ["MAX_QUESTIONS"] = "5"
os.environ["MAX_CLAIMS"] = "3"
os.environ["TWILIO_VALIDATE_SIGNATURE"] = "false"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

RESUME = """Priya Raghavan - Support Operations Lead, Bengaluru

EXPERIENCE
Support Lead, Northwind Services (2021 - present)
- Managed a 50-member support team and improved CSAT from 78% to 92% in four quarters
- Cut average first-response time from 9 hours to 45 minutes across three queues
- Built the escalation playbook now used by 4 regional support centres
- Trained 14 new hires on the escalation and refund process

SKILLS
Escalation design, SLA management, workforce planning, Zendesk, Looker, SQL
"""

ANSWERS = [
    "I owned this end to end. I rebuilt the shift roster myself and moved four "
    "agents onto an early shift because that is where the backlog formed.",
    "Billing complaints were 40% of negative feedback, so we redesigned the "
    "escalation workflow and introduced callback SLAs.",
    "I audited 200 escalations and found 60% were reopened because nobody owned "
    "the handoff, so the playbook assigns a named owner at each handoff.",
    "We rolled it out over six weeks and monitored the reopen rate on a weekly "
    "dashboard. It halved by the end of the quarter.",
    "The numbers came from Zendesk exports that I reconciled against Looker "
    "every Monday for eleven weeks.",
]


@pytest.fixture(scope="session")
def client():
    from api.main import app

    with TestClient(app) as test_client:
        yield test_client
