"""
The state machine.  Owned by Dev A.

    NEW -> CLAIMS_READY -> ASKING -> SCORING -> COMPLETE

QUESTION POLICY — deliberately in code, not in a prompt. It is deterministic,
reproducible, and explainable on stage, which is what makes "adaptive" a real
claim instead of a marketing word.

    Q1 -> claim 1, OWNERSHIP probe
    Q2 -> claim 1 follow-up on the weakest uncovered dimension
    Q3 -> claim 2, OWNERSHIP probe
    Q4 -> claim 2 follow-up  OR  claim 3 if claim 2 is already well covered
    Q5 -> the single dimension with the least coverage across all claims

Set ADAPTIVE_FOLLOWUPS=false to fall back to a fixed order (cut-list item #2).
Nobody watching can tell, and it removes evidence extraction from the critical
path of asking the next question.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api import ids
from api.config import settings
from api.engine import evidence as evidence_engine
from api.engine import graph as graph_engine
from api.engine import question as question_engine
from api.engine import scoring
from api.engine.extract import extract_claims
from api.models import (
    Candidate,
    ChatSession,
    Claim,
    ClaimScore,
    Evidence,
    Question,
    Response,
    Resume,
    utcnow,
)
from api.schemas import (
    Channel,
    ClaimOut,
    Dimension,
    ScoreRequest,
    SessionOut,
    SessionState,
)

log = logging.getLogger("proofscreen.orchestrator")

# Fixed plan used when ADAPTIVE_FOLLOWUPS=false. (claim index, dimension)
FIXED_PLAN: list[tuple[int, Dimension]] = [
    (0, Dimension.OWNERSHIP),
    (0, Dimension.DEPTH),
    (1, Dimension.OWNERSHIP),
    (1, Dimension.DEPTH),
    (2, Dimension.OWNERSHIP),
]


class SessionClosed(RuntimeError):
    """The candidate answered after the interview was already complete."""


# ---------------------------------------------------------------------------
# small db helpers
# ---------------------------------------------------------------------------


async def _claims_of(db: AsyncSession, candidate_id: str) -> list[Claim]:
    return list(
        (
            await db.execute(
                select(Claim)
                .where(Claim.candidate_id == candidate_id)
                .order_by(Claim.order_index)
            )
        ).scalars().all()
    )


async def _evidence_by_claim(
    db: AsyncSession, claim_ids: list[str]
) -> dict[str, list[Evidence]]:
    if not claim_ids:
        return {}
    rows = (
        await db.execute(select(Evidence).where(Evidence.claim_id.in_(claim_ids)))
    ).scalars().all()
    out: dict[str, list[Evidence]] = {cid: [] for cid in claim_ids}
    for row in rows:
        out.setdefault(row.claim_id, []).append(row)
    return out


async def _questions_of(db: AsyncSession, session_id: str) -> list[Question]:
    return list(
        (
            await db.execute(
                select(Question)
                .where(Question.session_id == session_id)
                .order_by(Question.order_index)
            )
        ).scalars().all()
    )


async def _open_question(db: AsyncSession, session_id: str) -> Question | None:
    return (
        await db.execute(
            select(Question)
            .where(Question.session_id == session_id, Question.answered.is_(False))
            .order_by(Question.order_index)
        )
    ).scalars().first()


async def _prior_qa(db: AsyncSession, session_id: str) -> list[tuple[str, str]]:
    rows = (
        await db.execute(
            select(Question, Response)
            .join(Response, Response.question_id == Question.id)
            .where(Question.session_id == session_id)
            .order_by(Question.order_index)
        )
    ).all()
    return [(q.text, r.answer_text) for q, r in rows]


def _claim_out(claim: Claim) -> ClaimOut:
    return ClaimOut(
        id=claim.id, text=claim.text, metric=claim.metric, category=claim.category
    )


# ---------------------------------------------------------------------------
# the policy
# ---------------------------------------------------------------------------


def plan_next(
    index: int,
    claims: list[Claim],
    evidence_by_claim: dict[str, list[Evidence]],
    asked_pairs: set[tuple[str, Dimension]],
) -> tuple[Claim, Dimension] | None:
    """Decide (claim, dimension) for question number `index` (0-based).

    Pure function of the session's current evidence — no LLM, no randomness.
    Returns None when the interview is over.
    """
    if index >= settings.max_questions or not claims:
        return None

    def nodes_for(claim: Claim) -> list[Evidence]:
        return evidence_by_claim.get(claim.id, [])

    def pick(claim: Claim, dimension: Dimension) -> tuple[Claim, Dimension] | None:
        """Never ask the same (claim, dimension) twice — walk to the next
        weakest dimension on that claim, then to any other claim.

        Returns None when every (claim, dimension) pair has been asked. That
        happens on a resume that yielded one claim: 4 dimensions cannot fill 5
        questions, so the interview ends early rather than repeating itself.
        """
        if (claim.id, dimension) not in asked_pairs:
            return claim, dimension
        cov = scoring.coverage(nodes_for(claim))
        for candidate_dim in sorted(
            scoring.DIMENSION_ORDER,
            key=lambda d: (cov[d] * scoring.DIMENSION_WEIGHT[d],
                           scoring.DIMENSION_ORDER.index(d)),
        ):
            if (claim.id, candidate_dim) not in asked_pairs:
                return claim, candidate_dim
        for other in claims:
            for candidate_dim in scoring.DIMENSION_ORDER:
                if (other.id, candidate_dim) not in asked_pairs:
                    return other, candidate_dim
        return None

    if not settings.adaptive_followups:
        claim_index, dimension = FIXED_PLAN[min(index, len(FIXED_PLAN) - 1)]
        return pick(claims[min(claim_index, len(claims) - 1)], dimension)

    first = claims[0]
    second = claims[1] if len(claims) > 1 else claims[0]
    third = claims[2] if len(claims) > 2 else second

    if index == 0:
        return pick(first, Dimension.OWNERSHIP)

    if index == 1:
        return pick(first, scoring.weakest_dimension(nodes_for(first)))

    if index == 2:
        return pick(second, Dimension.OWNERSHIP)

    if index == 3:
        if len(claims) > 2 and scoring.is_well_covered(nodes_for(second)):
            return pick(third, Dimension.OWNERSHIP)
        return pick(second, scoring.weakest_dimension(nodes_for(second)))

    # Q5 (and any further question if MAX_QUESTIONS is raised): the single
    # least-covered dimension across the whole session, on the weakest claim.
    dimension = scoring.weakest_dimension_across(nodes_for(c) for c in claims)
    weakest_claim = min(
        claims,
        key=lambda c: (scoring.claim_confidence(nodes_for(c)), c.order_index),
    )
    return pick(weakest_claim, dimension)


# ---------------------------------------------------------------------------
# lifecycle
# ---------------------------------------------------------------------------


async def create_session(
    db: AsyncSession,
    candidate: Candidate,
    resume: Resume,
    channel: Channel = Channel.web,
) -> tuple[ChatSession, list[Claim]]:
    """NEW -> CLAIMS_READY. Runs LLM call #1."""
    session = ChatSession(
        id=ids.session_id(),
        candidate_id=candidate.id,
        channel=channel.value,
        state=SessionState.NEW.value,
        join_code=ids.join_code(),
    )
    db.add(session)

    extracted = await extract_claims(resume.raw_text)
    claims: list[Claim] = []
    for order, item in enumerate(extracted):
        claim = Claim(
            id=ids.claim_id(),
            resume_id=resume.id,
            candidate_id=candidate.id,
            text=item.text.strip(),
            metric=item.metric,
            category=item.category,
            order_index=order,
        )
        db.add(claim)
        claims.append(claim)

    session.state = SessionState.CLAIMS_READY.value
    await db.commit()
    log.info("session %s ready with %d claims", session.id, len(claims))
    return session, claims


async def ask_next(db: AsyncSession, session: ChatSession) -> Question | None:
    """Generate, persist and return the next question. None => interview over.

    Idempotent: if a question is already open and unanswered, that one is
    returned. A candidate double-tapping send on WhatsApp must not burn a
    question.
    """
    if session.state == SessionState.COMPLETE.value:
        return None

    existing = await _open_question(db, session.id)
    if existing is not None:
        return existing

    claims = await _claims_of(db, session.candidate_id)
    evidence_map = await _evidence_by_claim(db, [c.id for c in claims])
    asked = {
        (q.claim_id, Dimension(q.intent)) for q in await _questions_of(db, session.id)
    }

    plan = plan_next(session.questions_asked, claims, evidence_map, asked)
    if plan is None:
        return None
    claim, dimension = plan

    generated = await question_engine.generate_question(
        claim_text=claim.text,
        dimension=dimension,
        claim_metric=claim.metric,
        prior_qa=await _prior_qa(db, session.id),
    )

    question = Question(
        id=ids.question_id(),
        claim_id=claim.id,
        session_id=session.id,
        text=generated.question,
        intent=dimension.value,
        order_index=session.questions_asked,
    )
    db.add(question)

    session.questions_asked += 1
    session.current_claim_id = claim.id
    session.state = SessionState.ASKING.value
    await db.commit()

    log.info(
        "session %s Q%d -> claim %s / %s",
        session.id, question.order_index + 1, claim.id, dimension.value,
    )
    return question


async def _persist_evidence(
    db: AsyncSession, claim: Claim, response: Response, question: Question
) -> None:
    """Runs B's engine over one answer and stores the nodes + claim score."""
    result = await evidence_engine.score_response(
        ScoreRequest(
            claim=_claim_out(claim),
            question_text=question.text,
            answer_text=response.answer_text,
            response_id=response.id,
        )
    )

    for node in result.nodes:
        db.add(
            Evidence(
                id=ids.evidence_id(),
                response_id=response.id,
                claim_id=claim.id,
                dimension=node.dimension.value,
                verdict=node.verdict.value,
                quote=node.quote[:240],
                        )
        )
    await db.flush()

    # Recompute this claim's confidence over ALL its evidence, not just this
    # answer's — a follow-up must be able to raise a claim's score.
    all_nodes = (
        await db.execute(select(Evidence).where(Evidence.claim_id == claim.id))
    ).scalars().all()
    confidence = scoring.claim_confidence(all_nodes)

    score = (
        await db.execute(select(ClaimScore).where(ClaimScore.claim_id == claim.id))
    ).scalar_one_or_none()
    if score is None:
        score = ClaimScore(id=ids.score_id(), claim_id=claim.id)
        db.add(score)
    score.confidence = confidence
    score.rationale = result.rationale[:280]
    score.computed_at = utcnow()

    await db.commit()


async def submit_answer(
    db: AsyncSession,
    session: ChatSession,
    text: str | None = None,
    audio_url: str | None = None,
    transcript: str | None = None,
    channel: Channel | None = None,
) -> tuple[Response, Question | None]:
    """ASKING -> (score) -> ASKING | SCORING -> COMPLETE.

    Returns (the stored response, the next question or None if finished).
    """
    if session.state == SessionState.COMPLETE.value:
        raise SessionClosed("this session is already complete")

    question = await _open_question(db, session.id)
    if question is None:
        # No open question — either the session never started or we finished.
        question = await ask_next(db, session)
        if question is None:
            raise SessionClosed("no open question and no question left to ask")

    response = Response(
        id=ids.response_id(),
        question_id=question.id,
        session_id=session.id,
        channel=(channel or Channel(session.channel)).value,
        raw_text=(text or "").strip(),
        audio_url=audio_url,
        transcript=(transcript or None),
    )
    db.add(response)
    question.answered = True
    await db.commit()

    claim = await db.get(Claim, question.claim_id)

    if settings.score_inline and claim is not None:
        await _persist_evidence(db, claim, response, question)
        await graph_engine.recompute_profile(db, session.candidate_id)

    next_question = None
    if session.questions_asked < settings.max_questions:
        next_question = await ask_next(db, session)

    if next_question is None:
        await finalize(db, session)

    return response, next_question


async def score_pending(db: AsyncSession, session_id: str) -> None:
    """Background-task entry point for SCORE_INLINE=false.

    Scores every answered question that has no evidence yet, then refreshes the
    profile. Safe to call repeatedly.
    """
    session = await db.get(ChatSession, session_id)
    if session is None:
        return

    rows = (
        await db.execute(
            select(Question, Response)
            .join(Response, Response.question_id == Question.id)
            .where(Question.session_id == session_id)
            .order_by(Question.order_index)
        )
    ).all()

    for question, response in rows:
        already = (
            await db.execute(
                select(Evidence).where(Evidence.response_id == response.id)
            )
        ).scalars().first()
        if already is not None:
            continue
        claim = await db.get(Claim, question.claim_id)
        if claim is not None:
            await _persist_evidence(db, claim, response, question)

    await graph_engine.recompute_profile(db, session.candidate_id)


async def finalize(db: AsyncSession, session: ChatSession) -> None:
    """SCORING -> COMPLETE. Arithmetic only, so this is instant."""
    session.state = SessionState.SCORING.value
    await db.commit()

    if not settings.score_inline:
        await score_pending(db, session.id)

    session.state = SessionState.COMPLETE.value
    session.completed_at = utcnow()
    await db.commit()

    await graph_engine.recompute_profile(db, session.candidate_id)
    log.info("session %s complete", session.id)


async def session_out(db: AsyncSession, session: ChatSession) -> SessionOut:
    open_question = await _open_question(db, session.id)
    return SessionOut(
        session_id=session.id,
        candidate_id=session.candidate_id,
        state=SessionState(session.state),
        channel=Channel(session.channel),
        questions_asked=session.questions_asked,
        max_questions=settings.max_questions,
        current_claim_id=session.current_claim_id,
        next_question=open_question.text if open_question else None,
        join_code=session.join_code,
    )


async def find_session_by_join_code(
    db: AsyncSession, code: str
) -> ChatSession | None:
    return (
        await db.execute(
            select(ChatSession).where(ChatSession.join_code == code.strip().upper())
        )
    ).scalars().first()


async def find_active_session_by_phone(
    db: AsyncSession, phone: str
) -> ChatSession | None:
    """Most recent not-yet-complete session for a phone number."""
    return (
        await db.execute(
            select(ChatSession)
            .join(Candidate, Candidate.id == ChatSession.candidate_id)
            .where(
                Candidate.phone == phone,
                ChatSession.state != SessionState.COMPLETE.value,
            )
            .order_by(ChatSession.started_at.desc())
        )
    ).scalars().first()
