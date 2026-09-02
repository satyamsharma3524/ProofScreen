"""
seed.py — demo candidates and two recruiter weight profiles.

Run once and the dashboard has real data from Day 1. On demo day this is the
fallback if the live WhatsApp flow dies on stage.

    python seed.py            # add candidates and roles
    python seed.py --reset    # wipe every table first

HOW THIS SEED WORKS, AND WHY IT MATTERS
---------------------------------------
It does NOT insert hand-written scores. It drives the REAL engine over
hand-written answers, so every number in the database is produced by the same
code path a live candidate goes through. If a rubric changes, the seed changes
with it, and a seeded score can never disagree with a live one.

The model is force-disabled here, so seeding is free, instant and offline:
claims and signals come from the deterministic heuristics. Scoring, weighting
and consistency are identical either way — those never involve the model.

THE POINT OF THE THREE CANDIDATES
    Priya   strong everywhere — the honest senior operator
    Arjun   strong on process and tooling, thin on people and outcomes
    Rohit   a polished resume that does not survive questioning, AND he
            contradicts himself on team size, so the consistency multiplier
            visibly drags his competence score down

THE POINT OF THE TWO ROLES
    Same three candidates, same stored evidence, two different rankings.
    That is Artifact 5, and it is the strongest 20 seconds of the demo.
"""

from __future__ import annotations

import argparse
import asyncio

from api.config import settings

# Force fixture mode BEFORE any engine import reads it: seeding must never
# spend money or wait on a network round trip.
settings.openai_api_key = None

from api import ids  # noqa: E402
from api.db import SessionLocal, drop_all, init_models  # noqa: E402
from api.engine import graph as graph_engine  # noqa: E402
from api.engine import orchestrator  # noqa: E402
from api.ingest.parse import normalise  # noqa: E402
from api.models import Candidate, Resume  # noqa: E402
from api.schemas import Channel  # noqa: E402

JD_BPO = (
    "Team Lead for a customer support operation: own CSAT and AHT for a team of "
    "agents, run daily huddles and weekly calibration, manage roster and "
    "shrinkage, handle escalations, control attrition, coach the bottom quartile, "
    "and report SLA attainment to operations leadership. Genesys, Zendesk, Excel."
)

# Answers are keyed by CLAIM TYPE, not by question number, because the adaptive
# policy decides which claim gets probed next — a flat list would attach a
# people answer to an AHT question and the seed would be nonsense.
#
# The three candidates deliberately overlap on claim type but differ in WHICH
# claims they can evidence. That overlap is what lets two role profiles produce
# two different rankings instead of just two different numbers.

PRIYA = {
    "name": "Priya Raghavan",
    "role": "Support Team Lead",
    "phone": "+919810000001",
    "email": "priya.r@example.com",
    "resume": """Priya Raghavan - Support Operations Team Lead, Bengaluru

EXPERIENCE
Team Lead, Northwind Services
- Managed a team of 35 agents across 4 pods with 4 senior associates reporting to me
- Improved CSAT from 78% to 92% in four quarters by redesigning the escalation workflow
- Reduced AHT from 480 seconds to 430 seconds by rewriting the call opening scripts

SKILLS
Escalation design, workforce planning, coaching, Genesys, Zendesk, Excel
""",
    # STRONG on people and CSAT, THIN on AHT.
    "answers": {
        "team_handling": [
            "I had 35 agents in four pods, and each pod had a senior associate reporting "
            "to me. I ran daily attendance tracking and a weekly calibration with the "
            "quality team.",
            "Every morning I pulled the queue report, then ran a fifteen minute huddle, "
            "then reviewed the previous day's escalations with the two pod seniors before "
            "assigning coaching slots.",
            "I remember the week before month-end when three agents resigned on the same "
            "day and the queue backed up to nine hours. I moved two people off email onto "
            "voice and personally handled the top twelve escalations that Saturday.",
            "I decided not to hire replacements immediately because onboarding takes six "
            "weeks, so instead I cross-trained four email agents onto voice, which meant "
            "we covered the gap without new headcount.",
            "Attrition came down from 34% to 19% over the year, and I tracked it monthly "
            "against the coaching log so I could see which pods were improving.",
        ],
        "csat_improvement": [
            "Billing complaints were about 40% of our negative feedback, so we redesigned "
            "the escalation workflow and introduced callback SLAs, and CSAT moved from 78 "
            "to 92 over about eleven weeks.",
            "CSAT is measured from the post-interaction survey, as the percentage of 4 and "
            "5 ratings out of all responses. I reviewed it in Zendesk every Monday against "
            "the reopen report.",
            "The worst month was when a billing system change went out unannounced and CSAT "
            "dropped nine points in a week. I had agents log every affected account so we "
            "could call them back before they escalated.",
            "Afterwards the reopen rate halved and we held CSAT above 90 for the next two "
            "quarters. Looking back I would have started the coaching cadence a month "
            "earlier because the retraining only paid off once calibration was consistent.",
        ],
        "aht_control": [
            "AHT came down a bit after the script rewrite but I don't have the exact "
            "numbers in front of me now.",
            "I don't remember the details of how we measured it.",
        ],
    },
}

ARJUN = {
    "name": "Arjun Mehta",
    "role": "Process and Quality Lead",
    "phone": "+919810000002",
    "email": "arjun.m@example.com",
    "resume": """Arjun Mehta - Process and Quality Lead, Pune

EXPERIENCE
Process Lead, Meridian Support
- Reduced AHT from 520 seconds to 430 seconds through script standardisation and coaching
- Held SLA attainment at 97% across four queues by rebuilding the roster model
- Managed a team of 22 agents and ran the daily huddle

SKILLS
Genesys, Zendesk, Excel, workforce management, quality audit, Six Sigma
""",
    # STRONG on AHT and SLA, THIN on people.
    "answers": {
        "aht_control": [
            "AHT was 520 seconds when I took over and 430 when I left, measured as talk "
            "time plus hold plus after call work, averaged per agent per day in Genesys.",
            "I segmented calls by issue type first, because the average was hiding the "
            "problem. Password resets were 90 seconds and billing disputes were 14 minutes, "
            "so I rewrote only the billing script and left the rest alone.",
            "There was one Tuesday in March when AHT spiked to 700 seconds and I found a "
            "new hire batch had come off nesting two weeks early. I put them back into "
            "side-by-side support for ten days.",
            "I considered adding an IVR menu to route billing away, but rejected it because "
            "our abandon rate was already at 3% and another menu layer would have pushed it "
            "up, so I fixed the script instead.",
            "AHT settled at 430 seconds and stayed there for two quarters, and importantly "
            "CSAT did not drop, which was the risk with shortening calls.",
        ],
        "sla_adherence": [
            "SLA is the percentage of calls answered within 30 seconds. We held 97% across "
            "four queues and I reported it daily on the operations dashboard.",
            "I rebuilt the roster in Excel with a 12% shrinkage buffer and reviewed it every "
            "Monday against the forecast, then adjusted the interval-level staffing for the "
            "6pm to 9pm peak.",
            "The Diwali week was the hardest — volume was up 60% and two agents were out "
            "sick, so I ran a split shift and moved the email team onto voice for four days "
            "to protect the SLA.",
            "The abandon rate rule was mine: if abandon crossed 3% in any interval we pulled "
            "agents off email, because a missed call costs more than a delayed email.",
        ],
        "team_handling": [
            "It was a team effort across the floor, I supported the initiative on the "
            "quality side.",
            "I don't remember the specifics of the team structure now.",
        ],
    },
}

ROHIT = {
    "name": "Rohit Verma",
    "role": "Senior Team Lead",
    "phone": "+919810000003",
    "email": "rohit.v@example.com",
    "resume": """Rohit Verma - Senior Team Lead, Noida

PROFILE
Results-driven, detail-oriented operations professional and passionate team player
with a strong work ethic and excellent communication skills.

EXPERIENCE
Senior Team Lead, Vertex Contact Solutions
- Managed a team of 45 agents and consistently exceeded all CSAT targets
- Drove a 30% improvement in CSAT scores across the entire process
- Delivered a 30% improvement in AHT through advanced process optimisation

SKILLS
Team management, leadership, communication, CSAT improvement, AHT reduction,
SLA attainment, roster management, shrinkage control, escalation handling,
attrition control, coaching the bottom quartile, daily huddle, weekly
calibration, operations leadership reporting, Genesys, Zendesk, Excel
""",
    # A polished resume that does not survive questioning — and he contradicts
    # himself on team size, which the consistency engine catches deterministically.
    "answers": {
        "team_handling": [
            "I had a team of 45 agents and we always hit our numbers. Team management is "
            "really about leadership and communication.",
            "We focused on quality and made sure standards were maintained at all times.",
            # The contradiction: 45 earlier, 20 now, on a `stable` fact key.
            "There were 20 agents reporting to me on that team, and we reviewed "
            "performance monthly.",
            "I don't remember the details, it was a while ago.",
        ],
        "csat_improvement": [
            "We improved customer satisfaction significantly through better ways of working.",
            "The initiative was mainly run by our consulting partner and the head of "
            "operations. I attended the working group.",
            "I don't remember the exact figures now.",
        ],
        "aht_control": [
            "AHT improved because of process optimisation and overall efficiency gains.",
            "I'm not sure how it was calculated.",
        ],
    },
}

SEEDS = [PRIYA, ARJUN, ROHIT]

ROLE_PEOPLE_FIRST = {
    "title": "Team Lead — People First",
    "job_family": "bpo_operations",
    "claim_weights": {
        "team_handling": 40,
        "csat_improvement": 30,
        "coaching_quality": 10,
        "attrition_control": 10,
        "aht_control": 5,
        "sla_adherence": 5,
    },
}

ROLE_OPS_EXCELLENCE = {
    "title": "Operations Excellence Lead",
    "job_family": "bpo_operations",
    "claim_weights": {
        "aht_control": 40,
        "sla_adherence": 30,
        "csat_improvement": 20,
        "team_handling": 10,
    },
}


async def seed_person(db, person: dict) -> dict:
    """Run the real pipeline over hand-written answers."""
    candidate = Candidate(
        id=ids.candidate_id(),
        name=person["name"],
        role=person["role"],
        phone=person["phone"],
        email=person["email"],
        job_family="bpo_operations",
    )
    resume = Resume(
        id=ids.resume_id(),
        candidate_id=candidate.id,
        raw_text=normalise(person["resume"]),
        filename=f"{person['name'].split()[0].lower()}_resume.pdf",
        job_description=JD_BPO,
    )
    db.add(candidate)
    db.add(resume)
    await db.commit()

    session, claims = await orchestrator.create_session(
        db, candidate, resume, Channel.simulated
    )

    # The policy chooses the claim; we answer as that claim's persona would.
    pools: dict[str, list[str]] = {k: list(v) for k, v in person["answers"].items()}
    used: dict[str, int] = {}
    claim_types = {c.id: c.claim_type for c in claims}

    for _index in range(settings.max_questions):
        question = await orchestrator.ask_next(db, session)
        if question is None:
            break
        claim_type = claim_types.get(question.claim_id, "")
        pool = pools.get(claim_type) or ["I don't remember the details."]
        cursor = used.get(claim_type, 0)
        answer = pool[min(cursor, len(pool) - 1)]
        used[claim_type] = cursor + 1

        await orchestrator.submit_answer(
            db, session, text=answer, channel=Channel.simulated
        )
        await db.refresh(session)
        if session.completed_at is not None:
            break

    await db.refresh(session)
    if session.completed_at is None:
        await orchestrator.finalize(db, session)

    graph = await graph_engine.build_candidate_graph(db, candidate.id)
    return {
        "id": candidate.id,
        "name": candidate.name,
        "claims": [(c.claim_type, c.claim_score or 0) for c in graph.claims],
        "questions": session.questions_asked,
        "resume": graph.resume_score,
        "evidence": graph.weighted_evidence_score,
        "consistency": graph.consistency.score,
        "competence": graph.competence_score,
        "badge": graph.badge.value,
        "contradictions": len(graph.consistency.contradictions),
    }


async def main(reset: bool) -> None:
    if reset:
        print("resetting every table ...")
        await drop_all()
    else:
        await init_models()

    async with SessionLocal() as db:
        print(f"seeding into {settings.database_url.split('@')[-1]}\n")

        roles = []
        for spec in (ROLE_PEOPLE_FIRST, ROLE_OPS_EXCELLENCE):
            role = await graph_engine.create_role(
                db,
                title=spec["title"],
                job_family=spec["job_family"],
                claim_weights=spec["claim_weights"],
            )
            roles.append(role)
            print(f"  role  {role.id}  {role.title}")
        print()

        rows = []
        for person in SEEDS:
            rows.append(await seed_person(db, person))

        header = f"  {'candidate':<18}{'Q':>3}{'resume':>8}{'evidence':>10}{'consist':>9}{'competence':>12}  badge"
        print(header)
        print("  " + "-" * (len(header) - 2))
        for r in rows:
            flag = f"  ({r['contradictions']} contradiction)" if r["contradictions"] else ""
            print(
                f"  {r['name']:<18}{r['questions']:>3}{r['resume']:>8}"
                f"{r['evidence']:>10}{r['consistency']:>9}{r['competence']:>12}"
                f"  {r['badge']}{flag}"
            )

        print("\n  Same evidence, two recruiters:")
        for role in roles:
            _, ranked = await graph_engine.rank_candidates(db, role.id)
            order = " > ".join(f"{c.name.split()[0]} ({c.competence_score})" for c in ranked)
            print(f"    {role.title:<32} {order}")

    print("\ndone — GET /api/recruiter/candidates?role_id=<id>")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed demo candidates and roles.")
    parser.add_argument("--reset", action="store_true", help="drop and recreate all tables")
    asyncio.run(main(parser.parse_args().reset))
