"""
Evidence graph assembly — claim -> Q&A -> evidence nodes.

This shape is what the recruiter dashboard renders and what
fixtures/sample_graph.json mirrors exactly. One function, used by both the
recruiter router and /api/dev/simulate, so the demo path and the live path can
never disagree about the shape.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import settings
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
)
from api.schemas import (
    Badge,
    CandidateGraph,
    CandidateRef,
    CandidateSummary,
    ClaimGraph,
    EvidenceNode,
    QAPair,
    SessionState,
)


async def build_candidate_graph(
    db: AsyncSession, candidate_id: str
) -> CandidateGraph | None:
    candidate = await db.get(Candidate, candidate_id)
    if candidate is None:
        return None

    claims = (
        await db.execute(
            select(Claim)
            .where(Claim.candidate_id == candidate_id)
            .order_by(Claim.order_index)
        )
    ).scalars().all()

    claim_ids = [c.id for c in claims]

    scores = {
        s.claim_id: s
        for s in (
            await db.execute(select(ClaimScore).where(ClaimScore.claim_id.in_(claim_ids)))
        ).scalars().all()
    } if claim_ids else {}

    evidence_rows = (
        (
            await db.execute(
                select(Evidence)
                .where(Evidence.claim_id.in_(claim_ids))
                .order_by(Evidence.created_at)
            )
        ).scalars().all()
        if claim_ids
        else []
    )

    qa_rows = (
        (
            await db.execute(
                select(Question, Response)
                .join(Response, Response.question_id == Question.id)
                .where(Question.claim_id.in_(claim_ids))
                .order_by(Question.order_index)
            )
        ).all()
        if claim_ids
        else []
    )

    evidence_by_claim: dict[str, list[Evidence]] = {}
    for row in evidence_rows:
        evidence_by_claim.setdefault(row.claim_id, []).append(row)

    qa_by_claim: dict[str, list[QAPair]] = {}
    for question, response in qa_rows:
        qa_by_claim.setdefault(question.claim_id, []).append(
            QAPair(
                question=question.text,
                answer=response.answer_text,
                question_id=question.id,
                response_id=response.id,
            )
        )

    claim_graphs: list[ClaimGraph] = []
    for claim in claims:
        score = scores.get(claim.id)
        nodes = [
            EvidenceNode(
                dimension=e.dimension,
                verdict=e.verdict,
                quote=e.quote,
                source_response_id=e.response_id,
            )
            for e in evidence_by_claim.get(claim.id, [])
        ]
        claim_graphs.append(
            ClaimGraph(
                id=claim.id,
                text=claim.text,
                metric=claim.metric,
                confidence=score.confidence if score else None,
                rationale=score.rationale if score else None,
                qa=qa_by_claim.get(claim.id, []),
                nodes=nodes,
            )
        )

    profile = (
        await db.execute(select(Profile).where(Profile.candidate_id == candidate_id))
    ).scalar_one_or_none()

    return CandidateGraph(
        candidate=CandidateRef(
            id=candidate.id, name=candidate.name, role=candidate.role
        ),
        resume_score=profile.resume_score if profile else None,
        competence_score=profile.competence_score if profile else None,
        badge=Badge(profile.badge) if profile else None,
        claims=claim_graphs,
    )


async def recompute_profile(db: AsyncSession, candidate_id: str) -> Profile | None:
    """Recompute competence_score / resume_score / badge for one candidate.

    Called after every answer, so the dashboard climbs live during a demo
    instead of jumping from nothing to a final number.
    """
    from api.ids import profile_id

    claims = (
        await db.execute(select(Claim).where(Claim.candidate_id == candidate_id))
    ).scalars().all()
    if not claims:
        return None

    scores = {
        s.claim_id: s.confidence
        for s in (
            await db.execute(
                select(ClaimScore).where(ClaimScore.claim_id.in_([c.id for c in claims]))
            )
        ).scalars().all()
    }

    # One entry per CLAIM: an unprobed claim contributes 0.0.
    competence = scoring.competence_score([scores.get(c.id, 0.0) for c in claims])
    badge = scoring.badge_for(competence)

    resume = (
        await db.execute(
            select(Resume)
            .where(Resume.candidate_id == candidate_id)
            .order_by(Resume.created_at.desc())
        )
    ).scalars().first()
    r_score = (
        scoring.resume_score(
            resume.raw_text, resume.job_description or settings.default_job_description
        )
        if resume
        else 0.0
    )

    session = (
        await db.execute(
            select(ChatSession)
            .where(ChatSession.candidate_id == candidate_id)
            .order_by(ChatSession.started_at.desc())
        )
    ).scalars().first()
    status = session.state if session else SessionState.NEW.value

    profile = (
        await db.execute(select(Profile).where(Profile.candidate_id == candidate_id))
    ).scalar_one_or_none()

    if profile is None:
        profile = Profile(id=profile_id(), candidate_id=candidate_id)
        db.add(profile)

    profile.competence_score = competence
    profile.resume_score = r_score
    profile.badge = badge.value
    profile.status = status
    from api.models import utcnow

    profile.computed_at = utcnow()

    await db.commit()
    return profile


async def list_candidate_summaries(db: AsyncSession) -> list[CandidateSummary]:
    """Ranked list for GET /api/recruiter/candidates. Highest competence first."""
    candidates = (
        await db.execute(select(Candidate).order_by(Candidate.created_at.desc()))
    ).scalars().all()
    if not candidates:
        return []

    ids = [c.id for c in candidates]

    profiles = {
        p.candidate_id: p
        for p in (
            await db.execute(select(Profile).where(Profile.candidate_id.in_(ids)))
        ).scalars().all()
    }

    claim_counts: dict[str, int] = {}
    for claim in (
        await db.execute(select(Claim).where(Claim.candidate_id.in_(ids)))
    ).scalars().all():
        claim_counts[claim.candidate_id] = claim_counts.get(claim.candidate_id, 0) + 1

    sessions: dict[str, ChatSession] = {}
    for session in (
        await db.execute(
            select(ChatSession)
            .where(ChatSession.candidate_id.in_(ids))
            .order_by(ChatSession.started_at)
        )
    ).scalars().all():
        sessions[session.candidate_id] = session   # last one wins

    out: list[CandidateSummary] = []
    for candidate in candidates:
        profile = profiles.get(candidate.id)
        session = sessions.get(candidate.id)
        out.append(
            CandidateSummary(
                id=candidate.id,
                name=candidate.name,
                role=candidate.role,
                resume_score=profile.resume_score if profile else None,
                competence_score=profile.competence_score if profile else None,
                badge=Badge(profile.badge) if profile else None,
                state=SessionState(session.state) if session else None,
                claims_count=claim_counts.get(candidate.id, 0),
                questions_asked=session.questions_asked if session else 0,
                computed_at=profile.computed_at if profile else None,
            )
        )

    # Ranked by competence, unscored candidates last, newest first within ties.
    out.sort(
        key=lambda c: (
            c.competence_score is None,
            -(c.competence_score or 0.0),
        )
    )
    return out
