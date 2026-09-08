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

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api import ids
from api.config import settings
from api.engine import anatomy as anatomy_engine
from api.engine import evidence as evidence_engine
from api.engine import question as question_engine
from api.engine import scoring
from api.engine import signals as signal_rubrics
from api.engine import v2_evidence_planner as evidence_planner
from api.engine.extract import extract_claims
from api.models import (
    Candidate,
    ChatSession,
    Claim,
    ClaimScore,
    ContradictionRow,
    Evidence,
    Profile,
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
from api.tenancy import TenantScope, scoped

log = logging.getLogger("proofscreen.orchestrator")


def _trace_value(value: object) -> str:
    """Render diagnostic values consistently without changing stored state."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, default=str, sort_keys=True)


def _question_turn_trace(
    *,
    session_id: str,
    claim_id: str | None = None,
    claim_text: str | None = None,
    target_evidence: object = None,
    known_evidence_before: object = None,
    question: str | None = None,
    candidate_answer: str | None = None,
    extracted_evidence: object = None,
    graph_updates: object = None,
    known_evidence_after: object = None,
    planner_reasoning: object = None,
    next_target_selected: object = None,
) -> None:
    """Emit a complete, grep-friendly snapshot at each turn pipeline boundary.

    These are deliberately logs only: the values are already-derived state and
    no trace data is persisted or fed back into extraction, graph, or planning.
    """
    log.info(
        "=== QUESTION TURN ===\n\n"
        "session_id=%s\n"
        "claim_id=%s\n\n"
        "claim_text=%s\n"
        "target_evidence=%s\n\n"
        "known_evidence_before=%s\n\n"
        "question=%s\n\n"
        "candidate_answer=%s\n\n"
        "extracted_evidence=%s\n\n"
        "graph_updates=%s\n\n"
        "known_evidence_after=%s\n\n"
        "planner_reasoning=%s\n\n"
        "next_target_selected=%s",
        session_id,
        claim_id or "",
        claim_text or "",
        _trace_value(target_evidence),
        _trace_value(known_evidence_before),
        question or "",
        candidate_answer or "",
        _trace_value(extracted_evidence),
        _trace_value(graph_updates),
        _trace_value(known_evidence_after),
        _trace_value(planner_reasoning),
        _trace_value(next_target_selected),
    )


def _known_evidence_trace(facts: list[ExtractedFact] | None = None, nodes: list | None = None) -> list[dict[str, object]]:
    res: list[dict[str, object]] = []
    if facts:
        res.extend(fact.model_dump(mode="json") for fact in facts)
    if nodes:
        for item in nodes:
            if hasattr(item, "model_dump"):
                res.append(item.model_dump(mode="json"))
            elif isinstance(item, dict):
                res.append(item)
    return res


def _plan_trace(plan: Plan | None, states: list[ClaimState]) -> dict[str, object]:
    """Explain the already-made planner decision; never participate in it."""
    if plan is None:
        return {"selected": None, "reason": "no viable claim or budget remaining"}
    state = next((item for item in states if item.claim.id == plan.claim.id), None)
    target = (
        plan.evidence_category.value if plan.evidence_category else
        plan.move.value if plan.move else
        plan.target_dimension.value if plan.target_dimension else
        plan.probe_level.value
    )
    return {
        "selected_claim": plan.claim.id,
        "candidate_claim_reason": {
            "planner_reason": plan.reason,
            "weight": state.weight if state else None,
            "score": state.score if state else None,
            "answers": state.answers if state else None,
            "levels_used": sorted(level.value for level in state.levels_used) if state else [],
            "stalled": state.stalled if state else None,
            "exhausted": state.exhausted if state else None,
        },
        "target_evidence_reason": {
            "selected": target,
            "probe_level": plan.probe_level.value,
            "target_dimension": plan.target_dimension.value if plan.target_dimension else None,
            "move": plan.move.value if plan.move else None,
            "evidence_category": plan.evidence_category.value if plan.evidence_category else None,
        },
    }


class SessionClosed(RuntimeError):
    """The candidate answered after the interview was already complete."""


@dataclass
class Plan:
    claim: Claim
    probe_level: ProbeLevel
    target_dimension: Dimension | None = None
    reason: str = ""
    # Set only for a TRANSFER probe. Chosen here, in the pure function, so the
    # whole decision is reproducible from stored evidence and `ask_next` has
    # nothing to do but forward it.
    transfer: question_engine.TransferSpec | None = None
    # --- forensic selection. All defaulted, so every probe-level construction
    # above stays valid and the two planners can coexist behind one flag.
    move: "question_engine.Move | None" = None
    alt_moves: tuple["question_engine.Move", ...] = ()
    anatomy: "anatomy_engine.ClaimAnatomy | None" = None
    ledger: tuple["question_engine.LedgerFact", ...] = ()
    # --- v2 evidence-category selection. Defaulted for the same reason: three
    # planners now coexist behind two flags, and only one of move/
    # evidence_category is ever set on a given Plan.
    evidence_category: "evidence_planner.EvidenceCategory | None" = None
    alt_categories: tuple["evidence_planner.EvidenceCategory", ...] = ()
    # --- hackathon demo: lightweight answer threading. Set only by
    # _thread_plan() below; when set, ask_next skips both generators entirely
    # and renders a canned per-entity question (question_engine.
    # thread_followup_question) -- no model call, same reasoning as REPAIR_PROMPTS.
    thread_entity: str | None = None


@dataclass
class ClaimState:
    claim: Claim
    weight: float
    claim_family: str = "general"
    # junior/mid/senior/None -- same value on every ClaimState in a session,
    # duplicated per-claim rather than threaded separately, matching
    # claim_family above. Read by question_engine.level_appropriate(); never
    # branched on anywhere else (CLAUDE.md rule 1 -- this is a planner-level
    # move filter, not a score).
    candidate_seniority: str | None = None
    levels_used: set[ProbeLevel] = field(default_factory=set)
    answer_signals: list[AnswerSignals] = field(default_factory=list)
    dimensions: dict[Dimension, DimensionScore] = field(default_factory=dict)
    score: int = 0
    answers: int = 0
    last_answer_signals: int = 0
    last_answer_was_non_answer: bool = False
    # --- forensic state, all derived in build_claim_states from rows that
    # already exist. `moves_used` needs the `questions.move` column; everything
    # else comes from `responses.signals_json`, which was already being parsed.
    moves_used: set[str] = field(default_factory=set)
    dear_by_answer: list[int] = field(default_factory=list)
    # --- v2 evidence-category state. `questions.move` holds EvidenceCategory
    # values instead of Move values when EVIDENCE_PLANNER_V2 is on — same
    # column, never mixed within one session. Ordered, parallel to
    # `answer_signals`, because `evidence_state` below has to replay
    # `update_coverage()` turn by turn (PARTIAL -> ESTABLISHED and the
    # EXHAUST_AFTER counter are both turn-order-dependent), unlike `moves_used`
    # above which only needs a flat set.
    targeted_sequence: list[str | None] = field(default_factory=list)

    @property
    def saturated(self) -> bool:
        return scoring.is_saturated(self.score)

    @property
    def stalled(self) -> bool:
        """The last answer added nothing — more of the same will not help."""
        return self.answers >= 2 and self.last_answer_signals == 0

    @property
    def levels_left(self) -> list[ProbeLevel]:
        """Unused rungs of the ladder. TRANSFER is not one: it is offered only
        by the stall branch, so it must not appear in the ordinary walk."""
        return [lv for lv in signal_rubrics.LADDER_ORDER if lv not in self.levels_used]

    @property
    def transfer_used(self) -> bool:
        """Derived from the levels actually asked rather than tracked
        separately — `build_claim_states` reads those back from the questions
        table, so this survives a process restart mid-interview and cannot
        drift out of step with what the candidate was really sent."""
        return ProbeLevel.TRANSFER in self.levels_used

    @property
    def transfer_available(self) -> bool:
        """Exactly one transfer probe, and only to a claim that has stalled.

        `stalled` already requires two answers, so an untouched claim can never
        qualify: TRANSFER never opens a claim. Saturated claims are excluded
        because there is nothing left to learn, not because they failed.
        """
        return (
            settings.transfer_probe
            and self.stalled
            and not self.transfer_used
            and not self.saturated
            and bool(self.levels_used)
        )

    @property
    def exhausted(self) -> bool:
        if self.saturated:
            return True
        if self.stalled:
            # A stall used to end the claim outright. Now it earns one transfer
            # probe first — the answers stopped adding evidence about what they
            # did, which is precisely when asking about what they did NOT do
            # separates a thin memory from a thin resume. With TRANSFER_PROBE
            # off, `transfer_available` is always False and this reduces to the
            # pre-phase behaviour exactly.
            return not self.transfer_available
        return not self.levels_left

    @property
    def anatomy(self) -> "anatomy_engine.ClaimAnatomy":
        """Derived, not stored — one sentence, parsed in Python, no model call."""
        return anatomy_engine.analyse(self.claim.text, self.claim.metric)

    @property
    def ledger(self) -> tuple["question_engine.LedgerFact", ...]:
        """This claim's established facts. `answer_signals` is already parsed
        from `responses.signals_json`; nothing new is read or stored."""
        return question_engine.build_ledger(self.answer_signals)

    @property
    def evidence_state(self) -> "evidence_planner.EvidenceState":
        """v2 planner coverage, replayed fresh from stored rows — same
        derive-don't-persist approach as `ledger` above, just turn-sequential
        because coverage state and the exhaustion counter both depend on order.

        `targeted_sequence` may hold Move-vocabulary strings for a claim asked
        under the OTHER planner (the column is shared) — `EvidenceCategory(mv)`
        raises on those, caught and treated as untargeted, same as the
        `ProbeLevel(question.probe_level)` guard already does in
        `build_claim_states` for the same kind of foreign value.
        """
        state = evidence_planner.new_state(self.claim.id)
        for mv, sig in zip(self.targeted_sequence, self.answer_signals):
            targeted = None
            if mv:
                try:
                    targeted = evidence_planner.EvidenceCategory(mv.split(",")[0])
                except ValueError:
                    targeted = None
            observed = evidence_planner.coverage_from_signals(sig.model_dump())
            state = evidence_planner.update_coverage(state, observed, targeted=targeted)
        return state

    @property
    def dear_total(self) -> int:
        return sum(self.dear_by_answer)

    @property
    def dear_stalled(self) -> bool:
        """Two answers running that produced nothing expensive to invent.

        This replaces the old signal-count stall. A candidate can produce plenty
        of cheap signal — a headcount, a tool name — while establishing nothing
        only its author could know, and that claim should release its remaining
        budget to a claim that is converting.
        """
        return len(self.dear_by_answer) >= 2 and sum(self.dear_by_answer[-2:]) == 0

    def forensic_moves_left(self) -> list["question_engine.Move"]:
        """Unspent moves from this claim's ladder whose precondition holds now.

        Preconditions are re-evaluated every turn because the ledger grows:
        COHERENCE is unavailable on an untouched claim and becomes available the
        moment two crossable facts exist.
        """
        anatomy = self.anatomy
        ledger = self.ledger
        return [
            mv for mv in question_engine.ARCHETYPE_LADDER[anatomy.archetype]
            if mv.value not in self.moves_used
            and question_engine.move_available(mv, anatomy, ledger)
            # Hackathon demo: EXCLUSION and AUTHORITY gated by candidate
            # seniority (settings.demo_mode). AUTHORITY measured as the single
            # highest-variance move in real logs this session -- richest
            # answer AND emptiest answer of any move, and the most
            # junior-unfriendly (an honest "not much was mine to decide" reads
            # identically to evasion) -- which is exactly why it unlocks at
            # mid/senior rather than staying off outright. Removing it for
            # juniors also keeps two findings from the same audit fixed as a
            # side effect: PROCESS-archetype claims that lose OPERATING_CONTEXT
            # to a session-fresh rotation collision fall through to FAILURE
            # instead of AUTHORITY, and VOLUME does not open cold on a
            # zero-grounding authority question. Unknown seniority
            # (candidate_seniority is None) is blocked by
            # question_engine.level_appropriate() itself -- same as the old
            # unconditional exclusion.
            # PERTURB is excluded from this list already -- it is offered only
            # by plan_next_forensic's separate stall branch -- and disabled
            # for the demo via settings.transfer_probe (or, for a senior
            # candidate, the level gate) which already gates that whole
            # branch; no new flag needed for PERTURB here.
            and not (
                settings.demo_mode
                and mv in (question_engine.Move.EXCLUSION, question_engine.Move.AUTHORITY)
                and not question_engine.level_appropriate(mv, self.candidate_seniority)
            )
        ]

    @property
    def demo_capped(self) -> bool:
        """Hackathon demo: hard stop at N questions per claim, independent of
        the ladder. `answers` already excludes repairs (see build_claim_states),
        so this counts only budgeted questions, matching demo_max_questions_per_claim."""
        return settings.demo_mode and self.answers >= settings.demo_max_questions_per_claim

    @property
    def forensic_closed(self) -> bool:
        if self.saturated:
            return True
        if self.dear_stalled:
            return True
        if self.demo_capped:
            return True
        return not self.forensic_moves_left()

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


async def _question_count(db: AsyncSession, session_id: str) -> int:
    """Transcript length, repairs included. See `order_index` in `ask_next`."""
    return int(
        (
            await db.execute(
                select(func.count())
                .select_from(Question)
                .where(Question.session_id == session_id)
            )
        ).scalar_one()
    )


async def _repair_already_used(db: AsyncSession, question: Question) -> bool:
    """One repair per parent question, hard -- one repair per CLAIM when
    settings.demo_mode (hackathon demo req #3).

    Without the cap a disengaged candidate loops inside a single probe forever
    and the interview never terminates — the same class of bug as unbounded
    regeneration, and the reason that cap is structural too.
    """
    if question.is_repair:
        return True          # a repair is never itself repaired
    if settings.demo_mode:
        # One repair per CLAIM, full stop (hackathon demo req #3) -- ANY
        # repair anywhere in this claim's transcript counts, not just one
        # created after this specific question. BUG FIXED HERE: the legacy
        # query below requires `order_index > question.order_index`, which
        # only ever matches a repair for THIS exact question (a repair is
        # always created immediately after its parent). A claim's SECOND
        # real question needs to see its FIRST question's already-spent
        # repair, which sits at a LOWER order_index -- the `>` comparison
        # can never find it, so a second repair slipped through. Measured
        # live: a real 2-claim interview logged `repairs=3`, one more than
        # the 2-claim ceiling, before this fix.
        existing = (
            await db.execute(
                select(Question).where(
                    Question.session_id == question.session_id,
                    Question.claim_id == question.claim_id,
                    Question.is_repair.is_(True),
                )
            )
        ).scalars().first()
        return existing is not None
    later = (
        await db.execute(
            select(Question).where(
                Question.session_id == question.session_id,
                Question.claim_id == question.claim_id,
                Question.probe_level == question.probe_level,
                Question.is_repair.is_(True),
                Question.order_index > question.order_index,
            )
        )
    ).scalars().first()
    return later is not None


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
                # D8 — `id` is the tiebreaker, not decoration. order_index is
                # unique in practice (it is a COUNT of the session's questions),
                # but "in practice" is not determinism: an unordered tie would
                # let replay merge a claim's answers in a different order from
                # the live run, and a replay that can disagree with itself
                # proves nothing. Costs one column in an already-indexed sort.
                .order_by(Question.order_index, Question.id)
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
    # One cheap extra read, no new LLM call: seniority was already captured at
    # extraction time (extract.classify_role) and just needs to reach the
    # planner. Same duplicate-per-claim shape as claim_family below.
    candidate = await db.get(Candidate, session.candidate_id)
    candidate_seniority = candidate.seniority if candidate is not None else None
    states = {
        c.id: ClaimState(
            claim=c,
            weight=float(weights.get(c.claim_type, 1.0)),
            claim_family=session.job_family,
            candidate_seniority=candidate_seniority,
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
        # The evidence counts however it arrived — a repair answer is a real
        # answer from the candidate and suppressing it would lose signal.
        sig = evidence_engine.signals_of(response.signals_json)
        state.answer_signals.append(sig)
        state.targeted_sequence.append(question.move)
        if question.move:
            state.moves_used.update(question.move.split(","))

        # P2-04 — but it does NOT count toward the stall signal. `stalled` is
        # "answers >= 2 and the last one produced nothing", and `stalled` is
        # what makes a claim transfer_available. Counting a repair here means a
        # candidate who says "ok" twice stalls a claim that was never properly
        # probed, and TRANSFER fires early on a claim with no evidence to
        # transfer. Measured against the seed, the invariant is 3 probes, all
        # Rohit, all signals_found = 0.
        if question.is_repair:
            continue
        state.answers += 1
        state.last_answer_signals = response.signals_found or 0
        state.last_answer_was_non_answer = evidence_engine.is_non_answer(response.answer_text)
        # How much of THIS answer was expensive to invent. The forensic stall
        # rule reads the last two entries.
        state.dear_by_answer.append(
            question_engine.dear_count(question_engine.build_ledger([sig]))
        )

    # Also count questions asked but not yet answered, so the policy never
    # re-asks the level currently sitting unanswered in the candidate's chat.
    for question in await _questions_of(db, session.id):
        state = states.get(question.claim_id)
        if state is not None:
            try:
                state.levels_used.add(ProbeLevel(question.probe_level))
            except ValueError:
                pass
            # An unanswered question has still been sent, so its moves are
            # spent — otherwise the policy re-asks what is sitting in the chat.
            if question.move:
                state.moves_used.update(question.move.split(","))

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

_SLOT_WS = re.compile(r"\s+")


# Function words that must not be the last thing in a slot value. A cut on a
# word boundary is not a cut on a clause boundary: "by rewriting the" is a
# dangling fragment that reads as a broken string to the candidate.
_DANGLING = frozenset(
    "a an the and or but by for from to of in on at with into over under as "
    "than that which while after before because so if when where".split()
)


def _phrase(text: str, limit: int = 70) -> str:
    """Trim a stored signal down to a slot value for a question.

    Deliberately not `question._short`: that one appends an ellipsis, which is
    fine when the claim is quoted at the front of a question and wrong here,
    because these values are read mid-sentence. Cuts on a word boundary and
    then keeps backing up while the last word is one that cannot end a clause.
    """
    clean = _SLOT_WS.sub(" ", text or "").strip().rstrip(".,;:")
    if len(clean) <= limit:
        return clean
    words = clean[:limit].split(" ")[:-1]          # drop the part-word
    while words and words[-1].strip(".,;:").lower() in _DANGLING:
        words.pop()
    return " ".join(words).rstrip(".,;:")


# The achievement shape a resume line almost always takes:
#   "<verb> <subject> from <A> to <B> by <method>"
# Everything from "from" or "by" onwards is the outcome they reached and the
# method they used to reach it — i.e. the answer. A transfer probe needs the
# SUBJECT, so it is cut away.
_OUTCOME_CLAUSE = re.compile(r"\s+(?:from|by)\s+", re.IGNORECASE)

# Leading past-tense achievement verbs. Regular ones end in "ed"; these are the
# irregulars that appear at the head of a resume line.
_IRREGULAR_VERBS = frozenset(
    "led built grew cut drove ran won kept held made took set sold "
    "rose spun brought".split()
)


def _problem_from(claim: Claim) -> str:
    """The subject of another claim, phrased as something to take on.

    A claim line is a RESULT — "Reduced AHT from 480 to 430 seconds by
    rewriting the call opening scripts". Substituting that whole sentence asks
    the candidate to take on an already-solved problem complete with its
    solution, which is incoherent and hands them the answer. Strip the outcome
    and method clauses and the leading achievement verb, and "AHT" is left:
    their subject, with nothing about how it went.

    Reads only the claim's own text, so no job family is needed to do it.
    """
    clean = _SLOT_WS.sub(" ", claim.text or "").strip()
    subject = _OUTCOME_CLAUSE.split(clean, maxsplit=1)[0]
    # A trailing appositive is more outcome: "Owned the payments service
    # reliability, holding error budget under 0.1%" is a subject plus the
    # result they got on it. Everything after the first comma goes.
    subject = subject.split(",", maxsplit=1)[0].strip().rstrip(".,;:")

    head, _, rest = subject.partition(" ")
    lowered = head.lower()
    if rest and (lowered.endswith("ed") or lowered in _IRREGULAR_VERBS):
        subject = rest.strip()

    # A pathological claim can trim to nothing useful; the full line is a worse
    # question than a short one, but it is better than an empty slot.
    return _phrase(subject if len(subject) >= 3 else clean)


# The method slot sits inside a fixed grammatical frame ("Using $their_method,
# where would you start?"), so `_method_phrase` has to GUARANTEE what it
# returns fits there. A clause with its own subject does not.
_METHOD_MAX_WORDS = 9
_SUBJECT_HEADS = frozenset("i we they it there he she you my our the".split())
_CLAUSE_JOINS = (", so ", ", and ", ", but ", " because ", " which ", " so we ")

# When they stated no usable method. Refers to the method instead of quoting
# it, which is the honest thing to do and reads correctly in the same frame.
NO_METHOD = "the approach you described"


def _method_phrase(text: str) -> str | None:
    """A stored signal, if and only if it already reads as a method phrase.

    Rejects rather than truncates. A method cut to fit — "Billing complaints
    were about 40% of our negative feedback, so we" — is worse than not
    quoting one at all, and truncation is what produced exactly that. The
    heuristic extractor that runs in fixture mode returns whole sentences here,
    so this is the common path offline, not an edge case.
    """
    clean = _SLOT_WS.sub(" ", text or "").strip().rstrip(".,;:")
    if not clean:
        return None
    lowered = clean.lower()
    if len(clean.split(" ")) > _METHOD_MAX_WORDS:
        return None
    if lowered.split(" ")[0] in _SUBJECT_HEADS:
        return None
    if any(join in lowered for join in _CLAUSE_JOINS):
        return None
    return clean


def _their_method(evidence: AnswerSignals) -> str:
    """The method the candidate described, in their own words.

    Preference order is evidential strength, not convenience: a complete
    cause -> action -> outcome chain is the strongest statement that they did
    the thing, a bare action next, then a process step, then the metric they
    said they watched. Within a tier, list order — so the same stored evidence
    always yields the same phrase.
    """
    candidates = (
        [link.action for link in evidence.causal_links if link.is_complete]
        + [link.action for link in evidence.causal_links]
        + [step.step for step in evidence.process_steps]
        + [
            f"the way you tracked {d.metric}"
            for d in evidence.metric_definitions
            if d.how_measured
        ]
    )
    for candidate in candidates:
        phrase = _method_phrase(candidate or "")
        if phrase is not None:
            return phrase
    # Reached when a claim stalled before stating any usable method, and
    # whenever the offline heuristics returned sentences rather than phrases.
    return NO_METHOD


def select_transfer(
    claim: Claim,
    evidence: AnswerSignals,
    other_claims: list[Claim],
) -> question_engine.TransferSpec:
    """Choose the perturbation for a TRANSFER probe. Pure, deterministic, no
    DB and no model call.

    NOTE THE SIGNATURE: there is no `job_family` parameter, so a family branch
    cannot be written in here without changing the contract — which a reviewer
    will see. Family may reach the *wording* call; it may never reach this one.
    Two candidates with identical evidence in unrelated industries must get the
    identical question, or the mechanism is a scenario library in disguise and
    every new cohort becomes an engineering ticket.

    T1 (substitute the problem) whenever a second claim exists, because both
    halves then come from the candidate's own resume — that is what makes it
    cheap and what makes it test whether two lines belong to one person.
    T3 (invert the outcome) otherwise, which is also the likely path for a thin
    resume: fabricators narrate success and cannot debug a failure.
    """
    method = _their_method(evidence)

    # Sort rather than trusting the caller's order: the target has to be a
    # function of the claims, not of how they were passed in.
    others = sorted(
        (c for c in other_claims if c.id != claim.id),
        key=lambda c: (c.order_index, c.id),
    )
    if others:
        target = others[0]
        log.info(
            "transfer selection: source_claim=%s(%s) target_claim=%s(%s) "
            "strategy=T1 selection_method='first other claim by resume order_index' "
            "semantic_similarity=not_computed (this architecture has no topical-"
            "relevance check between claims — any other claim on the resume is a "
            "valid T1 target by design, see select_transfer() docstring)",
            claim.id, claim.claim_type, target.id, target.claim_type,
        )
        return question_engine.TransferSpec(
            operator=question_engine.TransferOperator.T1,
            their_method=method,
            other_problem=_problem_from(target),
            target_claim_id=target.id,
            basis=(
                f"T1 substitute-the-problem: their method on {claim.id} applied "
                f"to the problem they claimed in {target.id}"
            ),
        )

    log.info(
        "transfer selection: source_claim=%s(%s) target_claim=none strategy=T3 "
        "selection_method='only claim on this resume, no T1 target available'",
        claim.id, claim.claim_type,
    )
    return question_engine.TransferSpec(
        operator=question_engine.TransferOperator.T3,
        their_method=method,
        other_problem="",
        target_claim_id=None,
        basis=(
            f"T3 invert-the-outcome: {claim.id} is the only claim, so there is "
            "no second problem of their own to substitute"
        ),
    )


MIN_STREAK = 2


def plan_next(states: list[ClaimState], index: int) -> Plan | None:
    """Decide (claim, probe level, target dimension) for question `index`.

    Pure function of the session's current evidence. No LLM, no randomness —
    the same session always asks the same questions in the same order.
    """
    if index >= settings.max_questions or not states:
        return None

    if not settings.adaptive_probing:
        # Strict sweep: level by level, claims in weight order. The ladder
        # only — a fixed sweep has no stall signal to react to, so there is
        # nothing for a transfer probe to be a response to.
        for level in signal_rubrics.LADDER_ORDER:
            for state in states:
                if level not in state.levels_used:
                    return Plan(state.claim, level, None, "fixed sweep")
        return None

    # Phase 1 — stalled claims get their transfer probe first
    for state in states:
        if not state.exhausted and state.transfer_available:
            covered = signal_rubrics.dimensions_for_level(ProbeLevel.TRANSFER)
            gap = min(
                covered,
                key=lambda d: state.dimensions[d].score if d in state.dimensions else 0,
            )
            return Plan(
                state.claim,
                ProbeLevel.TRANSFER,
                gap,
                f"stalled after {state.answers} answers — one transfer probe",
                transfer=select_transfer(
                    state.claim,
                    signal_rubrics.merge_signals(state.answer_signals),
                    [s.claim for s in states],
                ),
            )

    # Check for active claim momentum: maintain focus on active claim for MIN_STREAK turns
    active_streak = next(
        (s for s in states if 0 < s.answers < MIN_STREAK and not s.exhausted and not s.transfer_available),
        None,
    )
    if active_streak is not None:
        remaining = active_streak.levels_left
        if remaining:
            gap = active_streak.weakest_dimension()
            chosen: ProbeLevel | None = None
            if gap is not None:
                preferred = signal_rubrics.level_for_dimension(gap)
                if preferred in remaining:
                    chosen = preferred
                else:
                    chosen = next(
                        (
                            lv for lv in remaining
                            if gap in signal_rubrics.dimensions_for_level(lv)
                        ),
                        None,
                    )
            if chosen is None:
                chosen = remaining[0]
                covered = signal_rubrics.dimensions_for_level(chosen)
                gap = min(
                    covered,
                    key=lambda d: active_streak.dimensions[d].score if d in active_streak.dimensions else 0,
                ) if covered else None
                reason = f"continuation move (streak {active_streak.answers}/{MIN_STREAK}) on active claim"
            else:
                reason = (
                    f"weakest dimension {gap.value if gap else 'n/a'} on active claim streak "
                    f"({active_streak.answers}/{MIN_STREAK})"
                )
            return Plan(active_streak.claim, chosen, gap, reason)

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

        if state.transfer_available:
            # The claim stopped producing evidence. Spend one question on a
            # problem they have not solved before giving up on it. Ahead of the
            # gap logic on purpose: the reason to ask is the stall, not a
            # dimension gap, and TRANSFER is not on the ladder to be walked to.
            covered = signal_rubrics.dimensions_for_level(ProbeLevel.TRANSFER)
            gap = min(
                covered,
                key=lambda d: state.dimensions[d].score if d in state.dimensions else 0,
            )
            return Plan(
                state.claim,
                ProbeLevel.TRANSFER,
                gap,
                f"stalled after {state.answers} answers — one transfer probe",
                transfer=select_transfer(
                    state.claim,
                    signal_rubrics.merge_signals(state.answer_signals),
                    [s.claim for s in states],
                ),
            )

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

    return None      # every claim saturated, transferred or fully probed


# ---------------------------------------------------------------------------
# D9 — WHY THE QUERIES IN THIS FILE ARE NOT TENANT-SCOPED, AND WHY THAT IS SAFE
#
# The helpers above select by `session_id`, `claim_id` or `candidate_id` with
# no tenant predicate. That is deliberate: the SESSION is the aggregate root,
# and the tenant boundary is enforced when the root is resolved, not again at
# every inner read. Re-filtering here would be a second enforcement point that
# could drift from the first, which is the failure mode `api/tenancy.py` exists
# to avoid.
#
# The invariant that makes it hold: EVERY PUBLIC ENTRY POINT TAKES A RESOLVED
# ROW, NOT AN ID. `create_session(db, candidate, resume, ...)`,
# `ask_next(db, session)`, `submit_answer(db, session, ...)`,
# `finalize(db, session)` and `session_out(db, session)` all require an object
# the caller already fetched — and every router fetches it with
# `tenancy.get_owned()`. Possession of the row IS the authorisation. The two
# functions that DO take a bare lookup key, `find_session_by_opt_in_code` and
# `find_active_session_by_phone`, take a `TenantScope` instead and say so.
#
# `test_the_orchestrator_is_entered_with_resolved_rows_not_ids` pins this. Add
# a public function taking a bare `session_id` and it fails — which is the
# point, because that would be the hole.
#
# `score_pending(db, session_id)` is the one exception and is not reachable
# from any router: it is the background entry point for SCORE_INLINE=false,
# called only by `finalize()` with a session it already holds.
# ---------------------------------------------------------------------------

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
    job_family, extracted, seniority = await extract_claims(
        resume.raw_text, candidate.job_family if candidate.job_family != "general" else None
    )
    candidate.job_family = job_family
    candidate.seniority = seniority

    session = ChatSession(
        id=ids.session_id(),
        # D9 — every row this interview produces inherits the CANDIDATE's
        # tenant. That is the whole propagation rule: one lookup at the root,
        # never a re-resolution further down where it could differ.
        tenant_id=candidate.tenant_id,
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
            tenant_id=candidate.tenant_id,
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
    # D6 — the draft evaluation is opened WITH the interview, not after it.
    # An assessment that only exists once it succeeds cannot answer "what
    # happened to the one that did not", and the row costs nothing until
    # finalization fills it in.
    from api.engine import evaluation as evaluation_engine

    await evaluation_engine.open_evaluation(db, session, candidate)

    await db.commit()
    log.info(
        "session %s ready: %s, %d claims", session.id, job_family, len(claims)
    )
    return session, claims


def _moves_spent(plan: Plan, generated: "question_engine.QuestionAttempt") -> str | None:
    """Which ladder slots this question consumed. Comma-joined, planner-facing.

    `build_claim_states` splits this back into `moves_used`, so a move recorded
    here is never selected again for this claim. Same column, same
    both-planned-and-delivered convention, for whichever of `plan.move` /
    `plan.evidence_category` is set — never both.
    """
    primary = plan.move.value if plan.move is not None else (
        plan.evidence_category.value if plan.evidence_category is not None else None
    )
    if primary is None:
        return generated.move or None
    spent = [primary]
    if generated.move and generated.move != primary:
        spent.append(generated.move)
    return ",".join(spent)


def plan_next_evidence(states: list[ClaimState], index: int) -> Plan | None:
    """v2 planner selection: EvidenceCategory instead of Move.

    Per claim, heaviest-first (already the order `states` arrives in),
    `evidence_planner.plan_next()` picks the highest-priority category that
    isn't ESTABLISHED, exhausted, escalation-locked or just-touched. First
    claim with a target wins — a fresh claim's state starts all-MISSING, so
    this naturally opens every claim before deepening any one of them, the
    same breadth-then-depth shape `plan_next_forensic` gets from its explicit
    two-phase loop.

    `graph_edges` is always empty here: CROSS_CLAIM_LINK needs `claim_graph.txt`
    run as a real LLM call and its local ids reconciled against actual `Claim`
    rows, which is deferred. `evidence_planner.plan_next()` already treats an
    empty graph as "no edge to hang it on" and falls through to the next
    category, so CROSS_CLAIM_LINK is simply never offered — not a crash, not a
    stuck category.
    """
    # Prioritize active claim (already started) to maintain conversational depth per topic
    active_first = sorted(
        states,
        key=lambda s: (0 if s.evidence_state.turn > 0 and not evidence_planner.sufficiently_covered(s.evidence_state) else 1)
    )

    for state in active_first:
        anatomy = state.anatomy
        ev_state = state.evidence_state
        target = evidence_planner.plan_next(ev_state, has_metric=anatomy.has_metric)
        if target is None:
            continue
        # Escalation-gated the same way plan_next() itself gates the primary
        # choice — a retarget must not reach a harder category than the claim
        # has unlocked. `target.escalation_level` is plan_next()'s own unlocked
        # ceiling at selection time (never above it, by construction); using it
        # here rather than re-deriving `_unlocked_level` keeps this in sync
        # with that private function without depending on it directly.
        # CAUGHT LIVE: without this, a rejected PROCESS draft on a fresh claim
        # retargeted straight to INCIDENT (escalation level 3) — the backdoor
        # this filter closes.
        alt = tuple(
            c for c in evidence_planner.PRIORITY_ORDER
            if c is not target.target_evidence
            and c is not evidence_planner.EvidenceCategory.CROSS_CLAIM_LINK
            and evidence_planner.ESCALATION_LEVEL[c] <= target.escalation_level
            and ev_state.coverage.get(c) is not evidence_planner.CoverageState.ESTABLISHED
        )
        return Plan(
            claim=state.claim,
            probe_level=question_engine.EVIDENCE_PROBE_LEVEL[target.target_evidence],
            reason=target.reason,
            evidence_category=target.target_evidence,
            alt_categories=alt,
            anatomy=anatomy,
            ledger=state.ledger,
        )
    return None


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
    qa_rows = await _qa_rows(db, session.id)
    plan = (
        _thread_plan(states, session, qa_rows)
        if settings.demo_mode and settings.forensic_questions and not settings.evidence_planner_v2
        else None
    ) or (
        plan_next_evidence(states, session.questions_asked)
        if settings.evidence_planner_v2
        else plan_next_forensic(states, session.questions_asked)
        if settings.forensic_questions
        else plan_next(states, session.questions_asked)
    )

    log.info(
        "=== INTERVIEW SNAPSHOT === session=%s turn=%d remaining_budget=%d claims=%s "
        "chosen=%s",
        session.id, session.questions_asked + 1,
        settings.max_questions - session.questions_asked,
        [
            {
                "claim_id": s.claim.id,
                "claim_type": s.claim.claim_type,
                "weight": s.weight,
                "score": s.score,
                "answers": s.answers,
                "saturated": s.saturated,
                "stalled": s.stalled,
                "exhausted": s.exhausted,
                "dimensions": {
                    d.value: s.dimensions[d].score for d in s.dimensions
                } if s.dimensions else {},
            }
            for s in states
        ],
        (
            {
                "claim_id": plan.claim.id,
                "probe_level": plan.probe_level.value,
                "move": plan.move.value if plan.move else None,
                "evidence_category": plan.evidence_category.value if plan.evidence_category else None,
                "archetype": plan.anatomy.archetype.value if plan.anatomy else None,
                "dear_facts": sum(1 for f in plan.ledger if f.is_dear),
                "target_dimension": plan.target_dimension.value if plan.target_dimension else None,
                "reason": plan.reason,
            }
            if plan is not None
            else "none — every claim saturated, exhausted or budget spent"
        ),
    )
    if plan is None:
        return None

    prior = [(q.text, r.answer_text) for q, r in qa_rows]
    known_before = await known_facts(db, session.id)
    plan_trace = _plan_trace(plan, states)
    target_evidence = plan_trace["target_evidence_reason"]
    # Boundary 1: the exact state supplied to the generator. This happens
    # after selection and before any generator branch is entered.
    _question_turn_trace(
        session_id=session.id,
        claim_id=plan.claim.id,
        claim_text=plan.claim.text,
        target_evidence=target_evidence,
        known_evidence_before=_known_evidence_trace(known_before),
        planner_reasoning=plan_trace,
    )

    # P2-03 — the validator needs the claims it must NOT drift to, and on a
    # TRANSFER probe the one it MUST reference. Both are already in hand: the
    # planner chose them.
    target_claim = None
    if plan.transfer is not None and plan.transfer.target_claim_id:
        target = next(
            (s.claim for s in states if s.claim.id == plan.transfer.target_claim_id), None
        )
        target_claim = target.text if target else None

    if plan.thread_entity is not None:
        # Hackathon demo: answer threading. No model call -- same canned-line
        # reasoning as the repair path -- so nothing here can trip validate()
        # or need a fallback.
        generated = question_engine.QuestionAttempt(
            question_engine.thread_followup_question(plan.thread_entity),
            plan.probe_level, "thread", 1, (),
            "", plan.thread_entity, "answer-thread follow-up",
        )
        log.info(
            "thread question chosen claim=%s entity=%s", plan.claim.id, plan.thread_entity,
        )
    elif plan.evidence_category is not None:
        # v2 evidence-category path. Same anatomy/ledger inputs as the
        # forensic path below, rendered against v2_forensic_question.txt with
        # the EvidenceCategory vocabulary instead of Move.
        planned_state = next(s for s in states if s.claim.id == plan.claim.id)
        generated = await question_engine.generate_evidence_question(
            plan.claim.text,
            plan.evidence_category,
            anatomy=plan.anatomy,
            coverage=planned_state.evidence_state.coverage,
            ledger=plan.ledger,
            alt_categories=plan.alt_categories,
            claim_type=plan.claim.claim_type,
            claim_metric=plan.claim.metric,
            job_family=session.job_family,
            prior_questions=[q for q, _ in prior],
            prior_answers=[a for _, a in prior],
            other_claims=[s.claim.text for s in states if s.claim.id != plan.claim.id],
        )
        log.info(
            "evidence question chosen claim=%s category=%s source=%s target=%r",
            plan.claim.id, generated.move, generated.source, generated.target_signal,
        )
    elif plan.move is not None:
        # Forensic path. The generator receives the claim DECOMPOSED and the
        # ledger of what the candidate has already established — neither of
        # which the probe-level generator could see, though both already
        # existed one stack frame up.
        generated = await question_engine.generate_forensic_question(
            plan.claim.text,
            plan.move,
            anatomy=plan.anatomy,
            ledger=plan.ledger,
            alt_moves=plan.alt_moves,
            claim_type=plan.claim.claim_type,
            claim_metric=plan.claim.metric,
            job_family=session.job_family,
            prior_questions=[q for q, _ in prior],
            prior_answers=[a for _, a in prior],
            other_claims=[s.claim.text for s in states if s.claim.id != plan.claim.id],
        )
        log.info(
            "forensic question chosen claim=%s move=%s source=%s target=%r",
            plan.claim.id, generated.move, generated.source, generated.target_signal,
        )
    else:
        generated = await question_engine.generate_question(
            plan.claim.text,
            plan.probe_level,
            claim_type=plan.claim.claim_type,
            claim_metric=plan.claim.metric,
            job_family=session.job_family,
            prior_qa=prior,
            target_dimension=plan.target_dimension,
            transfer=plan.transfer,
            other_claims=[s.claim.text for s in states if s.claim.id != plan.claim.id],
            target_claim_text=target_claim,
        )

    # Boundary 2: wording returned by the actual selected generator.
    _question_turn_trace(
        session_id=session.id,
        claim_id=plan.claim.id,
        claim_text=plan.claim.text,
        target_evidence=target_evidence,
        known_evidence_before=_known_evidence_trace(known_before),
        question=generated.question,
        planner_reasoning=plan_trace,
    )

    question = Question(
        id=ids.question_id(),
        tenant_id=session.tenant_id,
        claim_id=plan.claim.id,
        session_id=session.id,
        text=generated.question,
        probe_level=generated.probe_level.value,
        # BOTH MOVES WHEN A RE-TARGET HAPPENED, comma-joined.
        #
        # Storing only the delivered move leaves the planned one unspent and the
        # planner re-selects it every turn — measured as COHERENCE chosen three
        # turns running. Storing only the planned one leaves the DELIVERED move
        # unspent, and it gets planned later and asks the same thing again —
        # also measured. Both were spent, so both are recorded.
        move=_moves_spent(plan, generated),
        target_dimension=plan.target_dimension.value if plan.target_dimension else None,
        # P2-04 — derived from a COUNT of this session's questions, not from
        # `questions_asked`. The two used to be the same number and therefore
        # the same concept; a repair turn does not consume budget, so
        # `questions_asked` stays the budget counter and this stays transcript
        # position. Dense and unique either way.
        order_index=await _question_count(db, session.id),
        # P2-03 provenance. M6d-M6g are computed from these four columns and
        # nothing else, so they are written here on the one path that creates a
        # question row.
        source=generated.source,
        attempts=generated.attempts,
        violations_json=json.dumps(list(generated.violations)) if generated.violations else None,
    )
    db.add(question)

    session.questions_asked += 1
    session.current_claim_id = plan.claim.id
    session.current_probe_level = plan.probe_level.value
    session.state = SessionState.ASKING.value
    await db.commit()

    log.info(
        "session %s Q%d -> %s / %s (%s)%s",
        session.id, question.order_index + 1, plan.claim.claim_type,
        plan.probe_level.value, plan.reason,
        f" [{plan.transfer.basis}]" if plan.transfer else "",
    )
    log.info(
        "session %s Q%d text (source=%s, attempts=%d%s): %s",
        session.id, question.order_index + 1, generated.source, generated.attempts,
        f", violations={list(generated.violations)}" if generated.violations else "",
        question.text,
    )

    if settings.live_question_quality_log:
        # Fire-and-forget. Scheduled AFTER commit, on the question already
        # decided and on its way out -- this can never gate, delay or change
        # what the candidate is asked (see question.log_question_quality).
        asyncio.create_task(
            question_engine.log_question_quality(
                session_id=session.id,
                question_id=question.id,
                claim_text=plan.claim.text,
                move=question.move or question.probe_level,
                question_text=question.text,
            )
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
    log.info(
        "session %s answer to Q%d (%s): %s",
        session.id, question.order_index + 1, response.answered_by, response.answer_text,
    )
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
    known_before = await known_facts(db, session.id)

    result = await evidence_engine.score_response(
        ScoreRequest(
            claim=_claim_out(claim, session.job_family, weights.get(claim.claim_type, 0.0)),
            question_text=question.text,
            probe_level=ProbeLevel(question.probe_level),
            answer_text=response.answer_text,
            response_id=response.id,
            job_family=session.job_family,
            known_facts=known_before,
            voice=voice,
        )
    )

    log.info(
        "answer scoring: response=%s claim=%s probe_level=%s answer_score=%d "
        "signals_found=%d quotes_dropped=%d contradictions=%d dimensions=%s",
        response.id, claim.id, question.probe_level, result.answer_score,
        result.signals_found, result.quotes_dropped, len(result.contradictions),
        [
            {
                "dimension": n.dimension.value,
                "score": n.score,
                "basis": n.basis,
                "quotes": n.quotes,
            }
            for n in result.nodes
        ],
    )

    for node in result.nodes:
        db.add(
            Evidence(
                id=ids.evidence_id(),
                tenant_id=session.tenant_id,
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
                tenant_id=session.tenant_id,
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
                tenant_id=session.tenant_id,
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

    categories = {
        name: len(items)
        for name, items in result.signals.model_dump(mode="json").items()
        if isinstance(items, list) and items
    }
    # Boundary 3: extraction is complete and the validated output is now the
    # exact payload being persisted.  The raw model response is intentionally
    # not available beyond evidence.score_response(); this is its post-
    # verbatim-enforcement output, which is what can affect the graph.
    _question_turn_trace(
        session_id=session.id,
        claim_id=claim.id,
        claim_text=claim.text,
        target_evidence={
            "probe_level": question.probe_level,
            "move": question.move,
            "target_dimension": question.target_dimension,
        },
        known_evidence_before=_known_evidence_trace(known_before),
        question=question.text,
        candidate_answer=response.answer_text,
        extracted_evidence={
            "raw_extraction_output": result.signals.model_dump(mode="json"),
            "evidence_categories_discovered": categories,
            "evidence_entities_discovered": [
                entity.model_dump(mode="json") for entity in result.signals.entities
            ],
            "evidence_nodes": [node.model_dump(mode="json") for node in result.nodes],
            "facts": [fact.model_dump(mode="json") for fact in result.facts],
            "signals_found": result.signals_found,
            "quotes_dropped": result.quotes_dropped,
        },
        known_evidence_after=_known_evidence_trace(await known_facts(db, session.id), nodes=result.nodes),
    )
    return result.answer_score


async def recompute_claim(
    db: AsyncSession, session: ChatSession, claim: Claim
) -> ClaimScore:
    """Rescore one claim over the UNION of every answer about it."""
    rows = [
        (q, r) for q, r in await _qa_rows(db, session.id) if q.claim_id == claim.id
    ]
    answer_signals = [evidence_engine.signals_of(r.signals_json) for _, r in rows]
    levels: list[ProbeLevel] = []
    moves: list[str | None] = []
    for question, _ in rows:
        try:
            levels.append(ProbeLevel(question.probe_level))
        except ValueError:
            continue
        moves.append(question.move)

    dimensions = signal_rubrics.score_claim(
        answer_signals, levels, session.job_family, moves_used=moves
    )

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
        stored = ClaimScore(
            id=ids.score_id(), tenant_id=session.tenant_id, claim_id=claim.id
        )
        db.add(stored)
        before_score: int | None = None
        before_dims: dict[Dimension, DimensionScore] = {}
    else:
        before_score = stored.score
        before_dims = _load_dimensions(stored.dimensions_json)

    stored.score = score
    stored.dimensions_json = _dump_dimensions(dimensions)
    stored.probed_dimensions = scoring.probed_count(dimensions)
    stored.answers_count = len(rows)
    summaries = [s.summary for s in answer_signals if s.summary]
    stored.summary = (summaries[-1] if summaries else "")[:400]
    stored.computed_at = utcnow()

    log.info(
        "claim recompute: claim=%s score_before=%s score_after=%d answers_count=%d "
        "dimension_deltas=%s",
        claim.id, before_score, score, len(rows),
        {
            d.value: f"{before_dims.get(d).score if d in before_dims else 0}->{dimensions[d].score}"
            for d in dimensions
            if (before_dims.get(d).score if d in before_dims else 0) != dimensions[d].score
        },
    )

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
        tenant_id=session.tenant_id,
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

        scope = TenantScope.of(session.tenant_id)
        prior_claim_score = (
            await db.execute(select(ClaimScore).where(ClaimScore.claim_id == claim.id))
        ).scalar_one_or_none()
        prior_dimensions = _load_dimensions(
            prior_claim_score.dimensions_json if prior_claim_score else None
        )
        prior_profile = (
            await db.execute(select(Profile).where(Profile.candidate_id == session.candidate_id))
        ).scalar_one_or_none()
        prior_competence = prior_profile.competence_score if prior_profile else 0
        prior_known_fact_keys = {fact.key for fact in await known_facts(db, session.id)}
        await _persist_evidence(db, session, claim, question, response)
        await db.commit()
        updated_claim_score = await recompute_claim(db, session, claim)
        contradictions = await graph_engine.session_contradictions(db, session.id, scope)
        updated_profile = await graph_engine.recompute_profile(db, session.candidate_id, scope)
        turn_evidence = (
            await db.execute(select(Evidence).where(Evidence.response_id == response.id))
        ).scalars().all()
        updated_dimensions = _load_dimensions(updated_claim_score.dimensions_json)
        dimension_deltas = {
            dimension.value: {
                "before": prior_dimensions[dimension].score if dimension in prior_dimensions else 0,
                "after": updated_dimensions[dimension].score if dimension in updated_dimensions else 0,
            }
            for dimension in scoring.DIMENSION_ORDER
            if (prior_dimensions[dimension].score if dimension in prior_dimensions else 0)
            != (updated_dimensions[dimension].score if dimension in updated_dimensions else 0)
        }
        # Boundary 4: both the claim aggregate and candidate graph have been
        # recomputed and committed. Nothing in this block feeds the planner.
        _question_turn_trace(
            session_id=session.id,
            claim_id=claim.id,
            claim_text=claim.text,
            target_evidence={
                "probe_level": question.probe_level,
                "move": question.move,
                "target_dimension": question.target_dimension,
            },
            question=question.text,
            candidate_answer=response.answer_text,
            graph_updates={
                "claim_score": {
                    "before": prior_claim_score.score if prior_claim_score else 0,
                    "after": updated_claim_score.score,
                },
                "dimension_deltas": dimension_deltas,
                "competence_score": {
                    "before": prior_competence,
                    "after": updated_profile.competence_score if updated_profile else None,
                },
                "newly_established_evidence": [
                    {
                        "dimension": item.dimension,
                        "score": item.score,
                        "basis": item.basis,
                        "quotes": json.loads(item.quotes_json or "[]"),
                    }
                    for item in turn_evidence
                ],
                "newly_established_facts": [
                    fact.model_dump(mode="json") for fact in await known_facts(db, session.id)
                    if fact.key not in prior_known_fact_keys
                ],
                "contradictions_added": [item.model_dump(mode="json") for item in contradictions],
            },
            known_evidence_after=_known_evidence_trace(
                await known_facts(db, session.id), nodes=turn_evidence
            ),
        )

    # P2-04 — a non-answer earns one more go at the SAME probe, off-budget.
    #
    # Spending a budgeted question on "ok" is how a 12-question interview
    # becomes an 8-question one, and the claim it was about scores zero for
    # reasons that have nothing to do with the candidate's competence.
    repair = await _maybe_repair(db, session, question, response)
    if repair is not None:
        return response, repair, contradictions

    next_question = None
    if session.questions_asked < settings.max_questions:
        next_question = await ask_next(db, session)

    if next_question is None:
        await finalize(db, session)

    return response, next_question, contradictions


async def _maybe_repair(
    db: AsyncSession,
    session: ChatSession,
    question: Question,
    response: Response,
) -> Question | None:
    """One repair question, or None. Deterministic, and makes no model call.

    Deliberately narrow. It does NOT re-plan, does not change the probe level,
    and does not touch `questions_asked` — the whole point is that this turn is
    free. The answer that follows is stored and scored like any other, because
    it is a real answer; only the BUDGET and the STALL COUNT treat it
    differently.
    """
    if not settings.repair_turn:
        return None
    if not evidence_engine.is_non_answer(response.answer_text):
        return None
    if await _repair_already_used(db, question):
        # Second non-answer in a row: accept it, score it, move on. Without
        # this the interview never terminates for a disengaged candidate.
        log.info("repair already spent on %s, accepting the non-answer", question.id)
        return None

    claim = await db.get(Claim, question.claim_id)
    repair = Question(
        id=ids.question_id(),
        tenant_id=session.tenant_id,
        claim_id=question.claim_id,
        session_id=session.id,
        text=question_engine.repair_question(
            ProbeLevel(question.probe_level), claim.text if claim else None, job_family=session.job_family
        ),
        probe_level=question.probe_level,
        target_dimension=question.target_dimension,
        order_index=await _question_count(db, session.id),
        source="repair",
        attempts=1,
        is_repair=True,
    )
    db.add(repair)
    # `questions_asked` is NOT incremented. That is the task.
    await db.commit()
    log.info("repair turn on %s (%s)", question.id, question.probe_level)
    return repair


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
    await graph_engine.recompute_profile(
        db, session.candidate_id, TenantScope.of(session.tenant_id)
    )


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

    scope = TenantScope.of(session.tenant_id)
    await graph_engine.recompute_profile(db, session.candidate_id, scope)

    # D6 — the profile is recomputed FIRST, deliberately. The evaluation reads
    # the same graph the profile just cached and then points the profile at
    # itself, so the mutable cache and the immutable record can never disagree
    # about what this interview concluded.
    from api.engine import evaluation as evaluation_engine

    evaluation = await evaluation_engine.finalize_evaluation(db, session, scope)

    log.info("session %s complete after %d questions", session.id, session.questions_asked)

    all_questions = await _questions_of(db, session.id)
    all_claims = await _claims_of(db, session.candidate_id)
    qa_rows = await _qa_rows(db, session.id)
    claim_by_id = {claim.id: claim for claim in all_claims}
    claim_scores = {
        score.claim_id: score
        for score in (
            await db.execute(
                select(ClaimScore).where(ClaimScore.claim_id.in_([claim.id for claim in all_claims]))
            )
        ).scalars().all()
    } if all_claims else {}
    facts_by_response: dict[str, list[dict[str, object]]] = {}
    for fact in (
        await db.execute(select(SessionFact).where(SessionFact.session_id == session.id))
    ).scalars().all():
        facts_by_response.setdefault(fact.source_response_id, []).append(
            {
                "key": fact.key,
                "value_num": fact.value_num,
                "value_text": fact.value_text,
                "unit": fact.unit,
                "quote": fact.quote,
            }
        )
    evidence_count = int((
        await db.execute(
            select(func.count()).select_from(Evidence).join(Response).where(Response.session_id == session.id)
        )
    ).scalar_one())
    fact_count = sum(len(items) for items in facts_by_response.values())
    # The graph is materialized as nested claim -> Q&A -> evidence/fact data,
    # not a separate nodes/edges table. These counts make that representation
    # explicit for the trace without altering its public contract.
    graph_nodes = len(all_claims) + len(all_questions) + len(qa_rows) + evidence_count + fact_count
    graph_edges = len(all_questions) + len(qa_rows) + evidence_count + fact_count
    dimensions_verified = sum(
        1
        for score in claim_scores.values()
        for dimension in _load_dimensions(score.dimensions_json).values()
        if dimension.probed
    )
    claims_verified = sum(1 for score in claim_scores.values() if score.score > 0)
    summary_lines = ["=== INTERVIEW TRACE SUMMARY ===", ""]
    for position, (question, response) in enumerate(qa_rows, start=1):
        claim = claim_by_id.get(question.claim_id)
        summary_lines.extend((
            f"Q{position}",
            f"claim={claim.id if claim else question.claim_id}",
            f"target={question.move or question.target_dimension or question.probe_level}",
            f"question={question.text}",
            f"answer={response.answer_text}",
            f"new_evidence={_trace_value(facts_by_response.get(response.id, []))}",
            "",
        ))
    summary_lines.extend((
        "FINAL",
        f"claims_verified={claims_verified}",
        f"dimensions_verified={dimensions_verified}",
        f"graph_nodes={graph_nodes}",
        f"graph_edges={graph_edges}",
        f"competence_score={evaluation.competence_score if evaluation is not None else ''}",
    ))
    log.info("\n".join(summary_lines))
    if evaluation is not None:
        log.info(
            "=== INTERVIEW SUMMARY === session=%s candidate=%s job_family=%s "
            "claims_extracted=%d questions_asked=%d repairs=%d fallback_questions=%d "
            "regenerated_questions=%d transfer_questions=%d resume_score=%d "
            "weighted_evidence_score=%d competence_score=%d consistency_score=%d "
            "contradiction_count=%d role_coverage=%d badge=%s",
            session.id, session.candidate_id, session.job_family,
            len(all_claims), session.questions_asked,
            sum(1 for q in all_questions if q.is_repair),
            sum(1 for q in all_questions if q.source == "fallback"),
            sum(1 for q in all_questions if q.source == "regenerated"),
            sum(1 for q in all_questions if q.probe_level == ProbeLevel.TRANSFER.value),
            evaluation.resume_score, evaluation.weighted_evidence_score,
            evaluation.competence_score, evaluation.consistency_score,
            evaluation.contradiction_count, evaluation.role_coverage, evaluation.badge,
        )


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
    db: AsyncSession, code: str, scope: TenantScope
) -> ChatSession | None:
    """Opt-in code -> session. Takes a scope so the bypass is stated, not assumed.

    The webhook passes `TenantScope.system(...)` because one WhatsApp business
    number serves every tenant and an inbound message carries no tenant until
    this lookup resolves one. Any other caller passes a real scope and gets a
    filtered query, because `scoped()` is what applies the predicate.
    """
    return (
        await db.execute(
            scoped(
                select(ChatSession)
                .where(ChatSession.opt_in_code == code.strip().upper())
                .order_by(ChatSession.started_at.desc(), ChatSession.id),
                ChatSession,
                scope,
            )
        )
    ).scalars().first()


async def find_active_session_by_phone(
    db: AsyncSession, phone: str, scope: TenantScope
) -> ChatSession | None:
    """Most recent live session for a phone number. See the note above on scope."""
    return (
        await db.execute(
            scoped(
                select(ChatSession)
                .join(Candidate, Candidate.id == ChatSession.candidate_id)
                .where(
                    Candidate.phone == phone,
                    ChatSession.state.notin_(
                        [SessionState.COMPLETE.value, SessionState.ABANDONED.value]
                    ),
                )
                .order_by(ChatSession.started_at.desc(), ChatSession.id),
                ChatSession,
                scope,
            )
        )
    ).scalars().first()


# ---------------------------------------------------------------------------
# FORENSIC PLANNING
#
# The objective is authorship verification, so the planner no longer routes by
# rubric dimension gap. It routes by CLAIM SHAPE (which moves are possible) and
# by LEDGER COST (whether the claim is still producing anything expensive to
# invent).
#
# Pure function, no model call, no randomness — the same session always produces
# the same interview, which is what makes an evaluation replayable.
# ---------------------------------------------------------------------------


def _rotate_session_fresh(
    moves: list["question_engine.Move"], session_used: set[str]
) -> list["question_engine.Move"]:
    """LIVE_INTERVIEW_QUALITY_AUDIT F2/P3 — prefer a move not already spent on
    ANY claim this session, not just this one.

    Two same-archetype claims (e.g. two "built X" claims, both `BUILD`) open on
    the identical ladder entry, `OPERATING_CONTEXT`, and its wording is
    formulaic enough that the second draft trips `duplicate_content` against
    the first. The retarget that follows then picks the next ladder entry —
    `DEPENDENCY` for `BUILD` — independently for every claim that lands here,
    so a third same-archetype claim repeats the exact same collision. Filtering
    by what the SESSION has already spent, not just this claim, breaks that:
    once one claim has used a move, a sibling claim's turn skips straight past
    it to whatever is next on its own ladder.

    Falls back to the unfiltered list when every remaining move has already
    been used elsewhere this session — a repeated move is still better than
    skipping this claim's turn entirely.
    """
    fresh = [m for m in moves if m.value not in session_used]
    return fresh or moves


def _thread_plan(
    states: list[ClaimState], session: ChatSession, prior_qa: list[tuple[Question, Response]]
) -> Plan | None:
    """Hackathon demo: planner priority 1 (answer threading), ahead of
    everything plan_next_forensic does. Reuses existing state only --
    `session.current_claim_id` (already set every turn), `state.answers`
    (already excludes repairs), and the raw answer text already fetched by
    the caller. No new table, no new column, no model call.

    Fires only right after a claim's FIRST budgeted answer: with
    demo_max_questions_per_claim=2 that is the only point a thread can open
    and still leave room for its own follow-up, which is also why a claim
    can never need more than the one threaded question `detect_thread_entity`
    finds -- the per-claim cap (ClaimState.demo_capped) closes the claim right
    after.
    """
    if not settings.demo_mode or not session.current_claim_id:
        return None
    if session.questions_asked >= settings.max_questions:
        return None
    state = next((s for s in states if s.claim.id == session.current_claim_id), None)
    if state is None or state.answers != 1 or state.demo_capped:
        return None
    last = next(
        (
            (q, r) for q, r in reversed(prior_qa)
            if q.claim_id == session.current_claim_id and not q.is_repair
        ),
        None,
    )
    if last is None:
        return None
    question, response = last
    entity = question_engine.detect_thread_entity(response.answer_text)
    if entity is None:
        return None
    try:
        probe_level = ProbeLevel(question.probe_level)
    except ValueError:
        probe_level = ProbeLevel.OPERATIONAL
    return Plan(
        claim=state.claim,
        probe_level=probe_level,
        reason=f"answer-thread follow-up: {entity}",
        anatomy=state.anatomy,
        ledger=state.ledger,
        thread_entity=entity,
    )


def _level_filtered_moves(state: ClaimState) -> list["question_engine.Move"]:
    """Moves that would otherwise be precondition-eligible right now but are
    blocked by the candidate-level gate -- for the `filtered_moves=` log line
    only. Covers all three gated moves uniformly (EXCLUSION/AUTHORITY reached
    via `forensic_moves_left`, PERTURB via the stall branch), since
    `question_engine.LEVEL_RESTRICTED` is the single source of truth for which
    moves are level-gated at all."""
    anatomy = state.anatomy
    ledger = state.ledger
    return [
        mv for mv in question_engine.LEVEL_RESTRICTED
        if mv.value not in state.moves_used
        and question_engine.move_available(mv, anatomy, ledger)
        and not question_engine.level_appropriate(mv, state.candidate_seniority)
    ]


PIVOT_PREFERENCE = (
    question_engine.Move.OWNERSHIP_BOUNDARY,
    question_engine.Move.EXCLUSION,
    question_engine.Move.AUTHORITY,
    question_engine.Move.OPERATING_CONTEXT,
    question_engine.Move.METRIC_DEFINITION,
)


def _apply_evidence_gap_pivot(
    state: ClaimState, moves: list["question_engine.Move"]
) -> tuple[list["question_engine.Move"], str | None]:
    if state.answers > 0 and not state.last_answer_was_non_answer and (
        state.last_answer_signals == 0
        or (state.dear_by_answer and state.dear_by_answer[-1] == 0)
    ):
        pivots = [m for m in moves if m in PIVOT_PREFERENCE]
        if pivots:
            reordered = pivots + [m for m in moves if m not in pivots]
            reason = f"evidence gap pivot (weak answer on turn {state.answers}) on active claim"
            return reordered, reason
    return moves, None



def plan_next_forensic(states: list[ClaimState], index: int) -> Plan | None:
    """Choose (claim, move) for question `index`.

    Order of preference, first match wins:

      1. BREADTH   — every claim gets its opening move before any gets a second
      2. SEAM      — a claim with two crossable facts earns a coherence test
                     ahead of a third independent fact: putting two established
                     things against each other is worth more than adding a third
      3. DEPTH     — heaviest still-open claim, next move on its ladder
      4. TRANSFER  — a claim that has stopped producing expensive detail gets
                     one perturbation before it closes
    """
    if index >= settings.max_questions or not states:
        return None

    # F2/P3 — moves already spent anywhere this session, across every claim.
    # Read fresh each call from `moves_used`, which `build_claim_states` already
    # populates from the persisted `questions.move` column — no new storage.
    session_used: set[str] = set().union(*(s.moves_used for s in states))

    def brief(state: ClaimState, move: "question_engine.Move", reason: str) -> Plan:
        left = [m for m in state.forensic_moves_left() if m is not move]
        rotated = _rotate_session_fresh(left, session_used)
        level = state.candidate_seniority or "unknown"
        log.info(
            "planner level=%s candidate seniority=%s allowed_moves=%s filtered_moves=%s",
            level,
            level,
            [m.value for m in state.forensic_moves_left()],
            [m.value for m in _level_filtered_moves(state)],
        )
        return Plan(
            claim=state.claim,
            probe_level=question_engine.MOVE_PROBE_LEVEL[move],
            target_dimension=None,
            reason=reason,
            move=move,
            # Attempt two re-targets to one of these rather than re-wording the
            # rejected draft. TRANSFER is excluded: it is earned by a stall, not
            # reached by falling through a rejection. Session-fresh first, so
            # the retarget does not repeat a move a sibling claim already spent.
            alt_moves=tuple(m for m in rotated if m is not question_engine.Move.PERTURB),
            anatomy=state.anatomy,
            ledger=state.ledger,
        )

    # 0 — momentum. Maintain focus on active claim for MIN_STREAK turns before switching
    for state in states:
        moves_count = len(state.moves_used)
        if (
            0 < moves_count < MIN_STREAK
            and not state.forensic_closed
            and not (state.dear_stalled and state.answers >= 2)
        ):
            moves = [
                m for m in _rotate_session_fresh(state.forensic_moves_left(), session_used)
                if m is not question_engine.Move.PERTURB
            ]
            if moves:
                moves, pivot_reason = _apply_evidence_gap_pivot(state, moves)
                reason = pivot_reason or f"claim momentum streak ({moves_count}/{MIN_STREAK}) on active claim"
                return brief(
                    state,
                    moves[0],
                    reason,
                )

    # 1 — breadth. Heaviest-first ordering is already applied by the caller.
    for state in states:
        if not state.moves_used:
            moves = _rotate_session_fresh(state.forensic_moves_left(), session_used)
            if moves:
                return brief(
                    state, moves[0],
                    f"opening move on a {state.anatomy.archetype.value} claim",
                )

    # 2 — seam, preferred over further depth once it becomes possible.
    for state in states:
        if state.forensic_closed:
            continue
        if question_engine.Move.COHERENCE.value in state.moves_used:
            continue
        if question_engine.Move.COHERENCE in state.forensic_moves_left():
            return brief(
                state, question_engine.Move.COHERENCE,
                f"crossing two established facts ({state.dear_total} hard-to-invent so far)",
            )

    # 3 — depth on the heaviest claim still producing.
    for state in states:
        if state.forensic_closed:
            continue
        moves = [m for m in _rotate_session_fresh(state.forensic_moves_left(), session_used)
                 if m is not question_engine.Move.PERTURB]
        if moves:
            moves, pivot_reason = _apply_evidence_gap_pivot(state, moves)
            reason = pivot_reason or f"next move on a {state.weight:g}-weight claim"
            return brief(
                state, moves[0],
                reason,
            )

    # 4 — one perturbation for a claim that has stopped paying. Off by default
    # in demo mode (settings.transfer_probe=False); the level gate is a
    # narrower override of that same default, not a second independent flag —
    # a senior candidate earns PERTURB back, an unknown/junior/mid one sees
    # exactly today's behaviour (settings.transfer_probe alone decides).
    for state in states:
        if not (
            settings.transfer_probe
            or (
                settings.demo_mode
                and question_engine.level_appropriate(
                    question_engine.Move.PERTURB, state.candidate_seniority
                )
            )
        ):
            continue
        if state.saturated or not state.moves_used:
            continue
        if question_engine.Move.PERTURB.value in state.moves_used:
            continue
        if not state.dear_stalled:
            continue
        if question_engine.move_available(
            question_engine.Move.PERTURB, state.anatomy, state.ledger
        ):
            return brief(
                state, question_engine.Move.PERTURB,
                f"stalled after {state.answers} answers — one perturbation",
            )

    return None
