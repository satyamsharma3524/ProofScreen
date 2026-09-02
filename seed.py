"""
seed.py — three fully-scored demo candidates with three different badges.

Run once and the recruiter dashboard has real-looking data from Day 1. On demo
day this is your fallback if the live WhatsApp flow dies on stage.

    python seed.py            # add the three candidates
    python seed.py --reset    # wipe every table first

No LLM calls. Every score here is computed by api/engine/scoring.py from the
verdicts below, so the seed data is arithmetically identical to what the live
pipeline would produce. Every quote is asserted to be verbatim inside its
answer before anything is written — the same rule the engine enforces.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys

from api import ids
from api.config import settings
from api.db import SessionLocal, drop_all, init_models
from api.engine import scoring
from api.models import (
    Candidate,
    ChatSession,
    Claim,
    ClaimScore,
    Evidence,
    Profile,
    Question,
    Response,
    Resume,
    utcnow,
)
from api.schemas import Dimension as D
from api.schemas import SessionState
from api.schemas import Verdict as V

_WS = re.compile(r"\s+")

# One job description per candidate, because resume_score is keyword overlap
# against the ROLE they applied for. Scoring a backend engineer against a
# support JD produces 0.0 and destroys the only thing resume_score is for:
# sitting next to the competence score and being visibly, embarrassingly
# different. Rohit is the money slide — a 0.9 resume next to a 0.05 competence.

JD_SUPPORT = (
    "Support operations lead responsible for a large customer support team, CSAT "
    "improvement, first-response time, escalation workflow design and escalation "
    "playbook ownership, reopen rate, refund process, SLA management, regional "
    "support centres, queue and workforce planning, new hire training, weekly "
    "stakeholder reporting to the COO, Zendesk, Looker and SQL."
)

JD_BACKEND = (
    "Backend engineer responsible for API latency and p95 performance on the "
    "checkout service, migrating microservices from EC2 to Kubernetes with zero "
    "downtime, building internal platform libraries such as a rate limiter used "
    "across teams, owning the on-call rotation for the payments domain, Python, "
    "FastAPI, PostgreSQL, Redis, Kafka and Terraform."
)

JD_DATA = (
    "Senior data analyst responsible for predictive modelling that drives campaign "
    "conversion, leading a company-wide data governance initiative across business "
    "units, delivering executive dashboards adopted by the leadership team, and "
    "storytelling with data. Python, SQL, Tableau, Power BI, machine learning."
)

# ---------------------------------------------------------------------------
# 1. VERIFIED — answers with ownership, mechanism and numbers
# ---------------------------------------------------------------------------

PRIYA = {
    "name": "Priya Raghavan",
    "role": "Support Lead",
    "jd": JD_SUPPORT,
    "phone": "+919810000001",
    "email": "priya.r@example.com",
    "resume": """Priya Raghavan — Support Operations Lead, Bengaluru

EXPERIENCE
Support Lead, Northwind Services (2021 - present)
- Managed a 50-member support team and improved CSAT from 78% to 92% in four quarters
- Cut average first-response time from 9 hours to 45 minutes across three queues
- Built the escalation playbook now used by 4 regional support centres
- Reported weekly on queue health, staffing and SLA breach risk to the COO

Senior Support Specialist, Northwind Services (2018 - 2021)
- Handled billing escalations for enterprise accounts
- Trained 14 new hires on the escalation and refund process

SKILLS
Escalation design, SLA management, workforce planning, Zendesk, Looker, SQL
""",
    "claims": [
        {
            "text": "Managed a 50-member support team and improved CSAT from 78% to 92% in four quarters",
            "metric": "CSAT 78 -> 92",
            "category": "support",
            "turns": [
                {
                    "question": "What were the top reasons behind the low CSAT, and which actions did you personally take to improve it?",
                    "answer": (
                        "Billing complaints were 40% of negative feedback. We redesigned "
                        "escalation workflows and introduced callback SLAs, and I owned the "
                        "rollout across all three shifts."
                    ),
                    "nodes": [
                        (D.OWNERSHIP, V.SUPPORTED, "I owned the rollout across all three shifts"),
                        (D.DEPTH, V.SUPPORTED, "Billing complaints were 40% of negative feedback"),
                        (D.SPECIFICITY, V.PARTIAL, "introduced callback SLAs"),
                        (D.OPERATIONAL, V.SUPPORTED, "We redesigned escalation workflows"),
                    ],
                }
            ],
        },
        {
            "text": "Cut average first-response time from 9 hours to 45 minutes across three queues",
            "metric": "9h -> 45m",
            "category": "support",
            "turns": [
                {
                    "question": "How did you get first-response time down that far, and what did you decide yourself?",
                    "answer": (
                        "I rebuilt the shift roster myself and moved four agents onto an early "
                        "shift covering 6am to 10am, which was where the backlog formed. "
                        "Response time fell to 45 minutes within six weeks."
                    ),
                    "nodes": [
                        (D.OWNERSHIP, V.SUPPORTED, "I rebuilt the shift roster myself"),
                        (D.DEPTH, V.PARTIAL, "which was where the backlog formed"),
                        (D.SPECIFICITY, V.SUPPORTED, "moved four agents onto an early shift covering 6am to 10am"),
                        (D.OPERATIONAL, V.PARTIAL, "Response time fell to 45 minutes within six weeks"),
                    ],
                }
            ],
        },
        {
            "text": "Built the escalation playbook now used by 4 regional support centres",
            "metric": "4 centres",
            "category": "support",
            "turns": [
                {
                    "question": "What was in the playbook, and why did the other centres adopt it?",
                    "answer": (
                        "I wrote it after auditing 200 escalations and finding that 60% were "
                        "reopened because nobody owned the handoff. The playbook assigns a "
                        "named owner at every handoff, and the other centres picked it up "
                        "after our reopen rate halved."
                    ),
                    "nodes": [
                        (D.OWNERSHIP, V.SUPPORTED, "I wrote it after auditing 200 escalations"),
                        (D.DEPTH, V.SUPPORTED, "60% were reopened because nobody owned the handoff"),
                        (D.SPECIFICITY, V.PARTIAL, "assigns a named owner at every handoff"),
                        (D.OPERATIONAL, V.UNSUPPORTED, ""),
                    ],
                }
            ],
        },
    ],
}

# ---------------------------------------------------------------------------
# 2. PARTIAL — plausible, but thin on mechanism and follow-through
# ---------------------------------------------------------------------------

ARJUN = {
    "name": "Arjun Mehta",
    "role": "Backend Engineer",
    "jd": JD_BACKEND,
    "phone": "+919810000002",
    "email": "arjun.m@example.com",
    "resume": """Arjun Mehta — Backend Engineer, Pune

EXPERIENCE
Backend Engineer, Meridian Labs (2022 - present)
- Reduced p95 API latency from 800ms to 120ms on the checkout service
- Migrated 18 microservices from EC2 to Kubernetes with zero downtime
- Built an internal rate limiter now used by 6 teams
- Owned on-call rotation for the payments domain

SKILLS
Python, FastAPI, PostgreSQL, Redis, Kubernetes, Kafka, Terraform
""",
    "claims": [
        {
            "text": "Reduced p95 API latency from 800ms to 120ms on the checkout service",
            "metric": "p95 800ms -> 120ms",
            "category": "engineering",
            "turns": [
                {
                    "question": "What was actually causing the 800ms p95, and what did you change?",
                    "answer": (
                        "We added Redis caching on the product lookup and the p95 came down to "
                        "around 120ms. It was mostly a database problem I think, the team had "
                        "been looking at it for a while before I joined that piece."
                    ),
                    "nodes": [
                        (D.OWNERSHIP, V.PARTIAL, "the team had been looking at it for a while before I joined that piece"),
                        (D.DEPTH, V.PARTIAL, "It was mostly a database problem I think"),
                        (D.SPECIFICITY, V.SUPPORTED, "We added Redis caching on the product lookup and the p95 came down to around 120ms"),
                        (D.OPERATIONAL, V.UNSUPPORTED, ""),
                    ],
                }
            ],
        },
        {
            "text": "Migrated 18 microservices from EC2 to Kubernetes with zero downtime",
            "metric": "18 services",
            "category": "engineering",
            "turns": [
                {
                    "question": "Walk me through how you did the migration without downtime.",
                    "answer": (
                        "I wrote the Helm charts for all of them and ran the cutover service by "
                        "service over two months. We kept both stacks live behind the load "
                        "balancer during each switch."
                    ),
                    "nodes": [
                        (D.OWNERSHIP, V.SUPPORTED, "I wrote the Helm charts for all of them"),
                        (D.DEPTH, V.UNSUPPORTED, ""),
                        (D.SPECIFICITY, V.PARTIAL, "ran the cutover service by service over two months"),
                        (D.OPERATIONAL, V.PARTIAL, "We kept both stacks live behind the load balancer during each switch"),
                    ],
                }
            ],
        },
        {
            "text": "Built an internal rate limiter now used by 6 teams",
            "metric": "6 teams",
            "category": "engineering",
            "turns": [
                {
                    "question": "Who adopted the rate limiter and what did you have to change for them?",
                    "answer": (
                        "A few teams use it now. I set up the initial library and they mostly "
                        "integrated it themselves."
                    ),
                    "nodes": [
                        (D.OWNERSHIP, V.PARTIAL, "I set up the initial library"),
                        (D.SPECIFICITY, V.PARTIAL, "A few teams use it now"),
                    ],
                }
            ],
        },
    ],
}

# ---------------------------------------------------------------------------
# 3. UNVERIFIED — a polished resume that does not survive one question
# ---------------------------------------------------------------------------

ROHIT = {
    "name": "Rohit Verma",
    "role": "Data Analyst",
    "jd": JD_DATA,
    "phone": "+919810000003",
    "email": "rohit.v@example.com",
    "resume": """Rohit Verma — Senior Data Analyst, Noida

PROFILE
Results-driven, detail-oriented analytics professional and passionate team player
with a strong work ethic and excellent communication skills.

EXPERIENCE
Senior Data Analyst, Vertex Retail (2021 - present)
- Drove a 34% increase in campaign conversion through advanced predictive modelling
- Led a company-wide data governance initiative across 9 business units
- Delivered executive dashboards adopted by the entire leadership team

SKILLS
Python, SQL, Tableau, Power BI, machine learning, predictive modelling, storytelling
""",
    "claims": [
        {
            "text": "Drove a 34% increase in campaign conversion through advanced predictive modelling",
            "metric": "34%",
            "category": "data",
            "turns": [
                {
                    "question": "What model did you use, and how did you measure the 34% increase?",
                    "answer": "I don't remember the details, it was a while ago.",
                    "nodes": [
                        (D.OWNERSHIP, V.UNSUPPORTED, ""),
                        (D.DEPTH, V.UNSUPPORTED, ""),
                        (D.SPECIFICITY, V.UNSUPPORTED, ""),
                        (D.OPERATIONAL, V.UNSUPPORTED, ""),
                    ],
                }
            ],
        },
        {
            "text": "Led a company-wide data governance initiative across 9 business units",
            "metric": "9 business units",
            "category": "data",
            "turns": [
                {
                    "question": "What was your role in the governance initiative, and what changed because of it?",
                    "answer": (
                        "It was mainly run by our consulting partner and the head of data. "
                        "I attended the working group and helped with two of the unit reviews."
                    ),
                    "nodes": [
                        (D.OWNERSHIP, V.CONTRADICTED, "It was mainly run by our consulting partner and the head of data"),
                        (D.DEPTH, V.UNSUPPORTED, ""),
                        (D.SPECIFICITY, V.PARTIAL, "helped with two of the unit reviews"),
                        (D.OPERATIONAL, V.UNSUPPORTED, ""),
                    ],
                }
            ],
        },
        {
            "text": "Delivered executive dashboards adopted by the entire leadership team",
            "metric": None,
            "category": "data",
            "turns": [
                {
                    "question": "Which dashboards did you build, and who actually uses them weekly?",
                    "answer": "I built the sales one in Tableau. I'm not sure how often people open it.",
                    "nodes": [
                        (D.OWNERSHIP, V.PARTIAL, "I built the sales one in Tableau"),
                        (D.DEPTH, V.UNSUPPORTED, ""),
                    ],
                }
            ],
        },
    ],
}

SEEDS = [PRIYA, ARJUN, ROHIT]


def _canon(text: str) -> str:
    return _WS.sub(" ", (text or "").lower()).strip()


def validate() -> None:
    """Every quote must be verbatim inside its answer. Fail loudly, not silently."""
    problems: list[str] = []
    for person in SEEDS:
        for claim in person["claims"]:
            for turn in claim["turns"]:
                for dimension, verdict, quote in turn["nodes"]:
                    if not quote:
                        continue
                    if _canon(quote) not in _canon(turn["answer"]):
                        problems.append(
                            f"{person['name']} / {dimension.value}: {quote!r} "
                            f"is not verbatim in the answer"
                        )
    if problems:
        for problem in problems:
            print(f"  SEED ERROR: {problem}", file=sys.stderr)
        raise SystemExit("seed data violates the verbatim-quote rule")


async def seed_person(db, person: dict) -> tuple[str, float, str, float]:
    candidate = Candidate(
        id=ids.candidate_id(),
        name=person["name"],
        role=person["role"],
        phone=person.get("phone"),
        email=person.get("email"),
    )
    resume = Resume(
        id=ids.resume_id(),
        candidate_id=candidate.id,
        raw_text=person["resume"].strip(),
        filename=f"{person['name'].split()[0].lower()}_resume.pdf",
        job_description=person["jd"],
    )
    session = ChatSession(
        id=ids.session_id(),
        candidate_id=candidate.id,
        channel="whatsapp",
        state=SessionState.COMPLETE.value,
        join_code=ids.join_code(),
        completed_at=utcnow(),
    )
    db.add_all([candidate, resume, session])

    order = 0
    confidences: list[float] = []

    for claim_index, spec in enumerate(person["claims"]):
        claim = Claim(
            id=ids.claim_id(),
            resume_id=resume.id,
            candidate_id=candidate.id,
            text=spec["text"],
            metric=spec["metric"],
            category=spec["category"],
            order_index=claim_index,
        )
        db.add(claim)

        claim_nodes: list[tuple[str, str]] = []
        for turn in spec["turns"]:
            question = Question(
                id=ids.question_id(),
                claim_id=claim.id,
                session_id=session.id,
                text=turn["question"],
                intent=turn["nodes"][0][0].value,
                order_index=order,
                answered=True,
            )
            response = Response(
                id=ids.response_id(),
                question_id=question.id,
                session_id=session.id,
                channel="whatsapp",
                raw_text=turn["answer"],
            )
            db.add_all([question, response])
            order += 1

            for dimension, verdict, quote in turn["nodes"]:
                db.add(
                    Evidence(
                        id=ids.evidence_id(),
                        response_id=response.id,
                        claim_id=claim.id,
                        dimension=dimension.value,
                        verdict=verdict.value,
                        quote=quote[:240],
                    )
                )
                claim_nodes.append({"dimension": dimension.value, "verdict": verdict.value})

        confidence = scoring.claim_confidence(claim_nodes)
        confidences.append(confidence)
        db.add(
            ClaimScore(
                id=ids.score_id(),
                claim_id=claim.id,
                confidence=confidence,
                rationale=f"{len(claim_nodes)} evidence nodes across the answers to this claim.",
            )
        )

    session.questions_asked = order
    competence = scoring.competence_score(confidences)
    badge = scoring.badge_for(competence)
    r_score = scoring.resume_score(resume.raw_text, person["jd"])
    db.add(
        Profile(
            id=ids.profile_id(),
            candidate_id=candidate.id,
            competence_score=competence,
            resume_score=r_score,
            badge=badge.value,
            status=SessionState.COMPLETE.value,
        )
    )

    await db.commit()
    return candidate.name, competence, badge.value, r_score


async def main(reset: bool) -> None:
    validate()
    if reset:
        print("resetting every table ...")
        await drop_all()
    else:
        await init_models()

    async with SessionLocal() as db:
        print(f"seeding into {settings.database_url.split('@')[-1]}")
        for person in SEEDS:
            name, competence, badge, resume = await seed_person(db, person)
            print(
                f"  {name:<20} resume_score={resume:<7} "
                f"competence={competence:<7} badge={badge}"
            )

    print("\ndone — GET /api/recruiter/candidates")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed demo candidates.")
    parser.add_argument(
        "--reset", action="store_true", help="drop and recreate all tables first"
    )
    args = parser.parse_args()
    asyncio.run(main(args.reset))
