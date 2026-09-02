"""
ARTIFACT 3 (the policy half) — the state machine.  Owned by Dev A.

    NEW -> CLAIMS_READY -> AWAITING_OPT_IN -> ASKING -> SCORING -> COMPLETE

QUESTION POLICY — in code, not in a prompt, so it is deterministic,
reproducible and explainable on stage. Budget is MAX_QUESTIONS (default 12).

  Phase 1 — BREADTH
      One VALIDATION probe on every claim, heaviest claim first. Nobody gets
      deepened before every claim has been touched, because an unprobed claim
      scores zero and would silently sink the candidate.

  Phase 2 — DEPTH
      Repeatedly take the heaviest claim that is not yet saturated, and ask the
      probe level that covers its weakest un-probed dimension:

          SPECIFICITY / METRIC_OWNERSHIP  -> VALIDATION
          PROCESS / TOOL_FAMILIARITY      -> OPERATIONAL
          AUTHENTICITY                    -> INCIDENT
          CAUSAL_REASONING                -> DECISION
          METRIC_OWNERSHIP (recheck)      -> OUTCOME

  ADAPTIVE STOP
      A claim stops being probed when it saturates (score >= 80), when all five
      levels are spent, or when the last answer produced no new signals at all.
      When every claim has stopped, the interview ends early rather than
      burning the budget — which is why a typical session lands at 8-10
      questions rather than always 12.

Set ADAPTIVE_PROBING=false for a strict VALIDATION..OUTCOME sweep instead.
Nobody watching can tell, and it takes evidence extraction off the critical
path of choosing the next question.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api import ids
from api.config import settings
from api.engine import evidence as evidence_engine
from api.engine import question as question_engine
from api.engine import scoring
from api.engine import signals as signal_rubrics
from api.engine.extract import extract_claims
from api.models import (
    Candidate,
    ChatSession,
    Claim,
    ClaimScore,
    ContradictionRow,
    Evidence,
    Question,
    Response,
    Resume,
    SessionFact,
    utcnow,
)
from api.schemas import (
    AnswerSignals,
    Channel,
    ClaimOut,
    Dimension,
    DimensionScore,
    ExtractedFact,
    ProbeLevel,
    ScoreRequest,
    SessionOut,
    SessionState,
    VoiceSignals,
)
from api.taxonomy import claim_type_label, default_claim_weights

log = logging.getLogger("proofscreen.orchestrator")


class SessionClosed(RuntimeError):
    """The candidate answered after the interview was already complete."""


@dataclass
class Plan:
    claim: Claim
    probe_level: ProbeLevel
    target_dimension: Dimension | None = None
    reason: str = ""


@dataclass
class ClaimState:
    claim: Claim
    weight: float
    claim_family: str = "general"
    levels_used: set[ProbeLevel] = field(default_factory=set)
    answer_signals: list[AnswerSignals] = field(default_factory=list)
    dimensions: dict[Dimension, DimensionScore] = field(default_factory=dict)
    score: int = 0
    answers: int = 0
    last_answer_signals: int = 0

    @property
    def saturated(self) -> bool:
        return scoring.is_saturated(self.score)

    @property
    def stalled(self) -> bool:
        """The last answer added nothing — more of the same will not help."""
        return self.answers >= 2 and self.last_answer_signals == 0

    @property
    def levels_left(self) -> list[ProbeLevel]:
        return [lv for lv in signal_rubrics.PROBE_ORDER if lv not in self.levels_used]

    @property
    def exhausted(self) -> bool:
        return self.saturated or self.stalled or not self.levels_left

    def weakest_dimension(self) -> Dimension | None:
        """Lowest-scoring dimension, un-probed ones first, heaviest weight as
        the tie-break so a gap in a 0.25-weighted dimension is chased before a
        gap in a 0.05-weighted one."""
        if not self.dimensions:
            return None
        weights = scoring.dimension_weights_for(self.claim_family)
        return min(
            scoring.DIMENSION_ORDER,
            key=lambda d: (
                self.dimensions.get(d).probed if self.dimensions.get(d) else False,
                self.dimensions[d].score if d in self.dimensions else 0,
                -weights.get(d.value, 0.0),
            ),
        )


# ---------------------------------------------------------------------------
# loading state
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


async def _qa_rows(db: AsyncSession, session_id: str) -> list[tuple[Question, Response]]:
    return list(
        (
            await db.execute(
                select(Question, Response)
                .join(Response, Response.question_id == Question.id)
                .where(Question.session_id == session_id)
                .order_by(Question.order_index)
            )
        ).all()
    )


async def known_facts(db: AsyncSession, session_id: str) -> list[ExtractedFact]:
    """The session's fact memory, earliest reading per key.

    Earliest on purpose: the first number a candidate gives is the baseline
    every later answer is checked against, so the order of contradictions is
    stable no matter how many times they revise.
    """
    rows = (
        await db.execute(
            select(SessionFact)
            .where(SessionFact.session_id == session_id)
            .order_by(SessionFact.created_at)
        )
    ).scalars().all()

    out: dict[str, ExtractedFact] = {}
    for row in rows:
        out.setdefault(
            row.key,
            ExtractedFact(
                key=row.key,
                value_num=row.value_num,
                value_text=row.value_text,
                unit=row.unit,
                quote=row.quote,
            ),
        )
    return list(out.values())


async def build_claim_states(
    db: AsyncSession, session: ChatSession
) -> list[ClaimState]:
    """Everything the policy needs, in one pass over the session's answers."""
    claims = await _claims_of(db, session.candidate_id)
    weights = default_claim_weights(session.job_family)
    states = {
        c.id: ClaimState(
            claim=c,
            weight=float(weights.get(c.claim_type, 1.0)),
            claim_family=session.job_family,
        )
        for c in claims
    }

    for question, response in await _qa_rows(db, session.id):
        state = states.get(question.claim_id)
        if state is None:
            continue
        try:
            state.levels_used.add(ProbeLevel(question.probe_level))
        except ValueError:
            pass
        sig = evidence_engine.signals_of(response.signals_json)
        state.answer_signals.append(sig)
        state.answers += 1
        state.last_answer_signals = response.signals_found or 0

    # Also count questions asked but not yet answered, so the policy never
    # re-asks the level currently sitting unanswered in the candidate's chat.
    for question in await _questions_of(db, session.id):
        state = states.get(question.claim_id)
        if state is not None:
            try:
                state.levels_used.add(ProbeLevel(question.probe_level))
            except ValueError:
                pass

    scores = {
        s.claim_id: s
        for s in (
            await db.execute(
                select(ClaimScore).where(
                    ClaimScore.claim_id.in_([c.id for c in claims])
                )
            )
        ).scalars().all()
    } if claims else {}

    for state in states.values():
        stored = scores.get(state.claim.id)
        if stored is not None:
            state.score = stored.score
            state.dimensions = _load_dimensions(stored.dimensions_json)
        else:
            state.dimensions = {
                d: DimensionScore(dimension=d, score=0, basis="not probed", probed=False)
                for d in scoring.DIMENSION_ORDER
            }

    return sorted(states.values(), key=lambda s: (-s.weight, s.claim.order_index))


def _load_dimensions(payload: str | None) -> dict[Dimension, DimensionScore]:
    try:
        data = json.loads(payload or "{}")
    except (TypeError, ValueError):
        data = {}
    out: dict[Dimension, DimensionScore] = {}
    for dimension in scoring.DIMENSION_ORDER:
        entry = data.get(dimension.value)
        out[dimension] = (
            DimensionScore.model_validate(entry)
            if entry
            else DimensionScore(dimension=dimension, score=0, basis="not probed")
        )
    return out


def _dump_dimensions(dimensions: dict[Dimension, DimensionScore]) -> str:
    return json.dumps(
        {d.value: dimensions[d].model_dump(mode="json") for d in dimensions}
    )


# ---------------------------------------------------------------------------
# THE POLICY
# ---------------------------------------------------------------------------


def plan_next(states: list[ClaimState], index: int) -> Plan | None:
    """Decide (claim, probe level, target dimension) for question `index`.

    Pure function of the session's current evidence. No LLM, no randomness —
    the same session always asks the same questions in the same order.
    """
    if index >= settings.max_questions or not states:
        return None

    if not settings.adaptive_probing:
        # Strict sweep: level by level, claims in weight order.
        for level in signal_rubrics.PROBE_ORDER:
            for state in states:
                if level not in state.levels_used:
                    return Plan(state.claim, level, None, "fixed sweep")
        return None

    # Phase 1 — breadth. Every claim gets its VALIDATION probe first.
    untouched = [s for s in states if not s.levels_used]
    if untouched:
        state = untouched[0]                    # already sorted heaviest-first
        return Plan(
            state.claim,
            ProbeLevel.VALIDATION,
            None,
            f"opening probe on {claim_type_label(state.claim_family, state.claim.claim_type)}",
        )

    # Phase 2 — depth on the heaviest claim still worth probing.
    for state in states:
        if state.exhausted:
            continue
        remaining = state.levels_left
        gap = state.weakest_dimension()

        chosen: ProbeLevel | None = None
        if gap is not None:
            preferred = signal_rubrics.level_for_dimension(gap)
            if preferred in remaining:
                chosen = preferred
            else:
                # Any remaining level that touches the gap at all.
                chosen = next(
                    (
                        lv for lv in remaining
                        if gap in signal_rubrics.dimensions_for_level(lv)
                    ),
                    None,
                )

        if chosen is None:
            # No remaining level can cover the gap, so fall through to the next
            # unused level — and DROP the target dimension. Telling the model
            # "the answers are thin on AUTHENTICITY" while asking an
            # OPERATIONAL question produces a confused, hybrid question; the
            # hint must always describe the question actually being asked.
            chosen = remaining[0]
            covered = signal_rubrics.dimensions_for_level(chosen)
            gap = min(
                covered,
                key=lambda d: state.dimensions[d].score if d in state.dimensions else 0,
            ) if covered else None
            reason = f"next unused level on a {state.weight:g}-weight claim"
        else:
            reason = (
                f"weakest dimension {gap.value if gap else 'n/a'} on a "
                f"{state.weight:g}-weight claim"
            )

        return Plan(state.claim, chosen, gap, reason)

    return None      # every claim saturated, stalled or fully probed


# ---------------------------------------------------------------------------
# lifecycle
# ---------------------------------------------------------------------------


def _claim_out(claim: Claim, job_family: str, weight: float = 0.0) -> ClaimOut:
    return ClaimOut(
        id=claim.id,
        text=claim.text,
        claim_type=claim.claim_type,
        claim_type_label=claim_type_label(job_family, claim.claim_type),
        metric=claim.metric,
        weight=weight,
    )


async def create_session(
    db: AsyncSession,
    candidate: Candidate,
    resume: Resume,
    channel: Channel = Channel.whatsapp,
) -> tuple[ChatSession, list[Claim]]:
    """NEW -> CLAIMS_READY -> AWAITING_OPT_IN. Runs LLM call #1."""
    job_family, extracted = await extract_claims(
        resume.raw_text, candidate.job_family if candidate.job_family != "general" else None
    )
    candidate.job_family = job_family

    session = ChatSession(
        id=ids.session_id(),
        candidate_id=candidate.id,
        channel=channel.value,
        state=SessionState.NEW.value,
        job_family=job_family,
        opt_in_code=ids.join_code(),
    )
    db.add(session)

    claims: list[Claim] = []
    for order, item in enumerate(extracted):
        claim = Claim(
            id=ids.claim_id(),
            resume_id=resume.id,
            candidate_id=candidate.id,
            text=item.text.strip(),
            claim_type=item.claim_type or "delivery",
            metric=item.metric,
            order_index=order,
        )
        db.add(claim)
        claims.append(claim)

    # WhatsApp Business API: we cannot free-form message a candidate who has
    # not messaged us. The interview therefore waits for their opt-in.
    session.state = (
        SessionState.AWAITING_OPT_IN.value
        if channel is Channel.whatsapp
        else SessionState.CLAIMS_READY.value
    )
    await db.commit()
    log.info(
        "session %s ready: %s, %d claims", session.id, job_family, len(claims)
    )
    return session, claims


async def ask_next(db: AsyncSession, session: ChatSession) -> Question | None:
    """Generate, persist and return the next question. None => interview over.

    Idempotent: an already-open unanswered question is returned as-is, so a
    candidate double-tapping send on WhatsApp never burns a question.
    """
    if session.state in (SessionState.COMPLETE.value, SessionState.ABANDONED.value):
        return None

    existing = await _open_question(db, session.id)
    if existing is not None:
        return existing

    states = await build_claim_states(db, session)
    plan = plan_next(states, session.questions_asked)
    if plan is None:
        return None

    prior = [(q.text, r.answer_text) for q, r in await _qa_rows(db, session.id)]

    generated = await question_engine.generate_question(
        plan.claim.text,
        plan.probe_level,
        claim_type=plan.claim.claim_type,
        claim_metric=plan.claim.metric,
        job_family=session.job_family,
        prior_qa=prior,
        target_dimension=plan.target_dimension,
    )

    question = Question(
        id=ids.question_id(),
        claim_id=plan.claim.id,
        session_id=session.id,
        text=generated.question,
        probe_level=plan.probe_level.value,
        target_dimension=plan.target_dimension.value if plan.target_dimension else None,
        order_index=session.questions_asked,
    )
    db.add(question)

    session.questions_asked += 1
    session.current_claim_id = plan.claim.id
    session.current_probe_level = plan.probe_level.value
    session.state = SessionState.ASKING.value
    await db.commit()

    log.info(
        "session %s Q%d -> %s / %s (%s)",
        session.id, question.order_index + 1, plan.claim.claim_type,
        plan.probe_level.value, plan.reason,
    )
    return question


# ---------------------------------------------------------------------------
# scoring one answer
# ---------------------------------------------------------------------------


async def _persist_evidence(
    db: AsyncSession,
    session: ChatSession,
    claim: Claim,
    question: Question,
    response: Response,
) -> int:
    """Run B's engine over one answer and store everything it produced."""
    weights = default_claim_weights(session.job_family)
    voice = (
        VoiceSignals(
            duration_seconds=response.voice_duration_seconds or 0.0,
            word_count=response.voice_word_count or 0,
            effort_score=response.voice_effort or 0,
        )
        if response.answered_by == "voice"
        else None
    )

    result = await evidence_engine.score_response(
        ScoreRequest(
            claim=_claim_out(claim, session.job_family, weights.get(claim.claim_type, 0.0)),
            question_text=question.text,
            probe_level=ProbeLevel(question.probe_level),
            answer_text=response.answer_text,
            response_id=response.id,
            job_family=session.job_family,
            known_facts=await known_facts(db, session.id),
            voice=voice,
        )
    )

    for node in result.nodes:
        db.add(
            Evidence(
                id=ids.evidence_id(),
                response_id=response.id,
                claim_id=claim.id,
                dimension=node.dimension.value,
                score=node.score,
                basis=node.basis[:400],
                quotes_json=json.dumps(node.quotes),
                probe_level=node.probe_level.value,
            )
        )

    for fact in result.facts:
        db.add(
            SessionFact(
                id=ids.fact_id(),
                session_id=session.id,
                claim_id=claim.id,
                source_response_id=response.id,
                key=fact.key,
                value_num=fact.value_num,
                value_text=fact.value_text,
                unit=fact.unit,
                quote=fact.quote[:240],
            )
        )

    for clash in result.contradictions:
        earlier = (
            await db.execute(
                select(SessionFact)
                .where(
                    SessionFact.session_id == session.id,
                    SessionFact.key == clash.fact_key,
                )
                .order_by(SessionFact.created_at)
            )
        ).scalars().first()
        db.add(
            ContradictionRow(
                id=ids.contradiction_id(),
                session_id=session.id,
                fact_key=clash.fact_key,
                fact_label=clash.fact_label,
                earlier_value=clash.earlier_value,
                later_value=clash.later_value,
                earlier_response_id=earlier.source_response_id if earlier else None,
                later_response_id=response.id,
                severity=clash.severity.value,
                delta_pct=clash.delta_pct,
                note=clash.note[:400],
            )
        )

    # Store the validated signals so this claim can be rescored later without
    # paying the model again — the thing that makes live re-ranking possible.
    response.signals_json = result.signals.model_dump_json()
    response.answer_score = result.answer_score
    response.signals_found = result.signals_found
    await db.flush()
    return result.answer_score


async def recompute_claim(
    db: AsyncSession, session: ChatSession, claim: Claim
) -> ClaimScore:
    """Rescore one claim over the UNION of every answer about it."""
    rows = [
        (q, r) for q, r in await _qa_rows(db, session.id) if q.claim_id == claim.id
    ]
    answer_signals = [evidence_engine.signals_of(r.signals_json) for _, r in rows]
    levels = []
    for question, _ in rows:
        try:
            levels.append(ProbeLevel(question.probe_level))
        except ValueError:
            continue

    dimensions = signal_rubrics.score_claim(answer_signals, levels, session.job_family)

    voice_efforts = [r.voice_effort for _, r in rows if r.answered_by == "voice" and r.voice_effort is not None]
    voice_effort = int(sum(voice_efforts) / len(voice_efforts)) if voice_efforts else None

    score = scoring.claim_score(
        dimensions,
        session.job_family,
        voice_effort=voice_effort,
        voice_weight=settings.voice_weight,
    )

    stored = (
        await db.execute(select(ClaimScore).where(ClaimScore.claim_id == claim.id))
    ).scalar_one_or_none()
    if stored is None:
        stored = ClaimScore(id=ids.score_id(), claim_id=claim.id)
        db.add(stored)

    stored.score = score
    stored.dimensions_json = _dump_dimensions(dimensions)
    stored.probed_dimensions = scoring.probed_count(dimensions)
    stored.answers_count = len(rows)
    summaries = [s.summary for s in answer_signals if s.summary]
    stored.summary = (summaries[-1] if summaries else "")[:400]
    stored.computed_at = utcnow()

    await db.commit()
    return stored


async def submit_answer(
    db: AsyncSession,
    session: ChatSession,
    *,
    text: str | None = None,
    transcript: str | None = None,
    media_id: str | None = None,
    voice: VoiceSignals | None = None,
    channel: Channel | None = None,
) -> tuple[Response, Question | None, list]:
    """ASKING -> (score) -> ASKING | SCORING -> COMPLETE.

    Returns (stored response, next question or None, contradictions raised now).
    """
    if session.state in (SessionState.COMPLETE.value, SessionState.ABANDONED.value):
        raise SessionClosed("this session is already complete")

    question = await _open_question(db, session.id)
    if question is None:
        question = await ask_next(db, session)
        if question is None:
            raise SessionClosed("no open question and no question left to ask")

    response = Response(
        id=ids.response_id(),
        question_id=question.id,
        session_id=session.id,
        channel=(channel or Channel(session.channel)).value,
        raw_text=(text or "").strip(),
        transcript=(transcript or None),
        media_id=media_id,
        answered_by="voice" if voice else "text",
        voice_duration_seconds=voice.duration_seconds if voice else None,
        voice_word_count=voice.word_count if voice else None,
        voice_effort=voice.effort_score if voice else None,
    )
    db.add(response)
    question.answered = True
    session.last_inbound_at = utcnow()
    await db.commit()

    claim = await db.get(Claim, question.claim_id)
    contradictions: list = []

    if settings.score_inline and claim is not None:
        from api.engine import graph as graph_engine

        await _persist_evidence(db, session, claim, question, response)
        await db.commit()
        await recompute_claim(db, session, claim)
        contradictions = await graph_engine.session_contradictions(db, session.id)
        await graph_engine.recompute_profile(db, session.candidate_id)

    next_question = None
    if session.questions_asked < settings.max_questions:
        next_question = await ask_next(db, session)

    if next_question is None:
        await finalize(db, session)

    return response, next_question, contradictions


async def score_pending(db: AsyncSession, session_id: str) -> None:
    """Background-task entry point for SCORE_INLINE=false. Idempotent."""
    from api.engine import graph as graph_engine

    session = await db.get(ChatSession, session_id)
    if session is None:
        return

    touched: dict[str, Claim] = {}
    for question, response in await _qa_rows(db, session_id):
        if response.signals_found and response.answer_score is not None:
            continue
        already = (
            await db.execute(select(Evidence).where(Evidence.response_id == response.id))
        ).scalars().first()
        if already is not None:
            continue
        claim = await db.get(Claim, question.claim_id)
        if claim is None:
            continue
        await _persist_evidence(db, session, claim, question, response)
        await db.commit()
        touched[claim.id] = claim

    for claim in touched.values():
        await recompute_claim(db, session, claim)
    await graph_engine.recompute_profile(db, session.candidate_id)


async def finalize(db: AsyncSession, session: ChatSession) -> None:
    """SCORING -> COMPLETE. Arithmetic only, so this is instant."""
    from api.engine import graph as graph_engine

    session.state = SessionState.SCORING.value
    await db.commit()

    if not settings.score_inline:
        await score_pending(db, session.id)

    session.state = SessionState.COMPLETE.value
    session.completed_at = utcnow()
    await db.commit()

    await graph_engine.recompute_profile(db, session.candidate_id)
    log.info("session %s complete after %d questions", session.id, session.questions_asked)


# ---------------------------------------------------------------------------
# lookups
# ---------------------------------------------------------------------------


async def session_out(db: AsyncSession, session: ChatSession) -> SessionOut:
    open_question = await _open_question(db, session.id)
    return SessionOut(
        session_id=session.id,
        candidate_id=session.candidate_id,
        state=SessionState(session.state),
        channel=Channel(session.channel),
        job_family=session.job_family,
        questions_asked=session.questions_asked,
        max_questions=settings.max_questions,
        current_claim_id=session.current_claim_id,
        current_probe_level=(
            ProbeLevel(session.current_probe_level) if session.current_probe_level else None
        ),
        next_question=open_question.text if open_question else None,
        opt_in_code=session.opt_in_code,
    )


async def find_session_by_opt_in_code(
    db: AsyncSession, code: str
) -> ChatSession | None:
    return (
        await db.execute(
            select(ChatSession).where(ChatSession.opt_in_code == code.strip().upper())
        )
    ).scalars().first()


async def find_active_session_by_phone(
    db: AsyncSession, phone: str
) -> ChatSession | None:
    """Most recent live session for a phone number."""
    return (
        await db.execute(
            select(ChatSession)
            .join(Candidate, Candidate.id == ChatSession.candidate_id)
            .where(
                Candidate.phone == phone,
                ChatSession.state.notin_(
                    [SessionState.COMPLETE.value, SessionState.ABANDONED.value]
                ),
            )
            .order_by(ChatSession.started_at.desc())
        )
    ).scalars().first()
