"""
D8 — deterministic replay.  NO MODEL CALL, NO NETWORK, EVER.

THE CONTRACT, AND IT IS DELIBERATELY NARROWER THAN "REPLAY"

    Extraction is recorded. Everything downstream of extraction is replayable.

Full replay is impossible and promising it is a mistake: LLM extraction is
non-deterministic even at temperature 0, and models are deprecated on the
provider's schedule rather than ours. Any commitment to "re-run the March
evaluation and get March's output" gets broken by somebody else's release.

But that is not what disputes are about. Nobody argues about whether the model
saw three quantities — the quotes are right there, verbatim, stored. People
argue about **why three quantities produced 62**, and that part is fully
deterministic.

WHAT IS REPLAYED

    responses.signals_json          (stored, verbatim-enforced)
        -> signals.score_claim      the published rubrics
        -> scoring.claim_score      dimension weights, voice blend
        -> weighted_evidence_score  the RECORDED role weights
        -> consistency.multiplier   from stored contradiction rows
        -> competence_score, badge

WHAT IS NOT

Question generation, claim extraction and the candidate's answers are
historical artifacts. They are read, never re-created. `resume_score` is
excluded from the comparison too, and that one is worth saying out loud: it is
keyword overlap against `settings.default_job_description` whenever a resume
carries no JD of its own, which makes it a function of LIVE CONFIGURATION
rather than of stored evidence. Comparing it would report drift in the
environment as drift in the evaluation.

REPLAY OWNS NO FORMULA. Every number below comes from the same function the
live path calls. If replay ever needed its own copy of any arithmetic, the
design would be wrong — two implementations of "the same" number disagree
eventually, and then nobody can say which one the recruiter saw.

MISSING STATE FAILS LOUDLY. An answer with no stored signals is not zero
evidence, it is an unanswerable question, and returning a confident lower score
would be the single most damaging thing this module could do.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.engine import consistency as consistency_engine
from api.engine import provenance as provenance_engine
from api.engine import scoring
from api.engine import signals as signal_rubrics
from api.models import (
    ChatSession,
    Claim,
    ClaimScore,
    ContradictionRow,
    Evaluation,
    Question,
    Response,
    utcnow,
)
from api.schemas import (
    AnswerSignals,
    Badge,
    Contradiction,
    Dimension,
    DimensionScore,
    ProbeLevel,
    ReplayDifference,
    ReplayResultOut,
    ReplayStatus,
    Severity,
)
from api.tenancy import TenantScope, scoped

log = logging.getLogger("proofscreen.replay")

__all__ = ["ReplayUnavailable", "replay_evaluation", "required_state"]


class ReplayUnavailable(RuntimeError):
    """The historical state needed to replay this evaluation is not there.

    Raised rather than returning MISMATCH, and rather than scoring what IS
    there. A partial replay that produces a number looks like a finding and is
    an artifact of missing data.
    """


@dataclass
class _Recomputed:
    weighted_evidence_score: int = 0
    competence_score: int = 0
    badge: Badge = Badge.unverified
    consistency_score: int = 100
    role_coverage: int = 0
    claim_scores: dict[str, int] = field(default_factory=dict)
    answers: int = 0


def _signals_of(payload: str | None) -> AnswerSignals:
    """Local, so this module imports nothing that imports the LLM wrapper.

    `evidence.signals_of` does the same thing, but `engine/evidence.py` calls
    the model, and a replay module that imports it would make
    `test_replay_never_imports_the_llm` an argument rather than a check. Four
    lines of duplication buys a structural guarantee.
    """
    try:
        return AnswerSignals.model_validate_json(payload or "{}")
    except Exception:  # noqa: BLE001
        return AnswerSignals()


def _weights(payload: str | None) -> dict[str, float]:
    try:
        data = json.loads(payload or "{}")
    except (TypeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, float] = {}
    for key, value in data.items():
        try:
            out[str(key)] = float(value)
        except (TypeError, ValueError):
            continue
    return out


def _recorded_voice_weight(evaluation: Evaluation) -> float:
    """The voice weight IN FORCE AT FINALIZATION, from the stored flags.

    Not `settings.voice_weight`. That is the hidden configuration dependency
    D8 asks about: `recompute_claim` reads the live setting, so replaying with
    today's value against yesterday's evaluation would report a mismatch caused
    by an env var rather than by anything about the assessment.

    Absent or unparseable is a hard failure. A default here would silently
    substitute today's behaviour for the recorded one.
    """
    flags = json.loads(evaluation.feature_flags_json or "{}")
    raw = flags.get("VOICE_WEIGHT") if isinstance(flags, dict) else None
    if raw in (None, ""):
        raise ReplayUnavailable(
            f"evaluation {evaluation.id} recorded no VOICE_WEIGHT, so the voice "
            f"blend that produced its claim scores cannot be reproduced"
        )
    try:
        return float(raw)
    except (TypeError, ValueError) as exc:
        raise ReplayUnavailable(
            f"evaluation {evaluation.id} recorded VOICE_WEIGHT={raw!r}, which is "
            f"not a number"
        ) from exc


def required_state() -> tuple[str, ...]:
    """The minimum persisted state, named. Read by the docs and the tests."""
    return (
        "evaluations.status == finalized",
        "evaluations.claim_weights_json",
        "evaluations.feature_flags_json[VOICE_WEIGHT]",
        "sessions row",
        "claims rows",
        "questions.probe_level and questions.order_index",
        "responses.signals_json for every answered question",
        "contradictions rows",
    )


async def replay_evaluation(
    db: AsyncSession, evaluation: Evaluation, scope: TenantScope
) -> ReplayResultOut:
    """Recompute the deterministic tail and diff it against what was finalized.

    READ ONLY. Nothing here writes, and the session is checked for pending
    changes before returning — a replay that mutated the record it is auditing
    would be worse than no replay.
    """
    from api import llm

    if evaluation.status != "finalized":
        raise ReplayUnavailable(
            f"evaluation {evaluation.id} is a {evaluation.status}; only a "
            f"finalized evaluation has a result to replay against"
        )

    claim_weights = _weights(evaluation.claim_weights_json)
    if not claim_weights:
        raise ReplayUnavailable(
            f"evaluation {evaluation.id} recorded no claim weights, so the "
            f"role-weighted mean that produced its evidence score cannot be "
            f"reproduced"
        )
    dimension_weights = _weights(evaluation.dimension_weights_json)
    voice_weight = _recorded_voice_weight(evaluation)

    session = await db.get(ChatSession, evaluation.session_id)
    if session is None or session.tenant_id != evaluation.tenant_id:
        raise ReplayUnavailable(
            f"evaluation {evaluation.id} points at session "
            f"{evaluation.session_id}, which is gone"
        )

    calls_before = llm.cache_stats()["calls"]

    claims = list(
        (
            await db.execute(
                scoped(
                    select(Claim)
                    .where(Claim.candidate_id == evaluation.candidate_id)
                    .order_by(Claim.order_index, Claim.id),
                    Claim,
                    scope,
                )
            )
        ).scalars().all()
    )
    if not claims:
        raise ReplayUnavailable(
            f"evaluation {evaluation.id} has no claims; there is nothing to score"
        )

    qa_rows = list(
        (
            await db.execute(
                scoped(
                    select(Question, Response)
                    .join(Response, Response.question_id == Question.id)
                    .where(Question.session_id == session.id)
                    # The same ordering the live path uses, `id` tiebreaker
                    # included. Replay that sorted differently could disagree
                    # with a live run for reasons that are not about evidence.
                    .order_by(Question.order_index, Question.id),
                    Question,
                    scope,
                )
            )
        ).all()
    )

    unscored = [
        response.id for _question, response in qa_rows if response.signals_json is None
    ]
    if unscored:
        raise ReplayUnavailable(
            f"evaluation {evaluation.id} cannot be replayed: "
            f"{len(unscored)} answer(s) have no stored signals "
            f"({', '.join(unscored[:5])}). Scoring what is there would report a "
            f"confident lower number produced by missing data."
        )

    stored_claim_scores = {
        row.claim_id: row
        for row in (
            await db.execute(
                scoped(
                    select(ClaimScore).where(
                        ClaimScore.claim_id.in_([c.id for c in claims])
                    ),
                    ClaimScore,
                    scope,
                )
            )
        ).scalars().all()
    }

    # --- the deterministic tail --------------------------------------------

    by_claim: dict[str, list[tuple[Question, Response]]] = {}
    for question, response in qa_rows:
        by_claim.setdefault(question.claim_id, []).append((question, response))

    result = _Recomputed(answers=len(qa_rows))
    pairs: list[tuple[str, int]] = []

    for claim in claims:
        rows = by_claim.get(claim.id, [])
        if not rows:
            pairs.append((claim.claim_type, 0))
            result.claim_scores[claim.id] = 0
            continue

        answer_signals = [_signals_of(response.signals_json) for _q, response in rows]
        levels: list[ProbeLevel] = []
        moves: list[str | None] = []
        for question, _response in rows:
            try:
                levels.append(ProbeLevel(question.probe_level))
            except ValueError:
                continue
            moves.append(question.move)

        # `session.job_family`, not the evaluation's, and the difference is not
        # cosmetic: `recompute_claim` scored the stored claims under the
        # SESSION's family, so that is what a faithful replay must use. The
        # evaluation's family comes from the candidate row and drives the
        # weights, one step later.
        dimensions = signal_rubrics.score_claim(
            answer_signals, levels, session.job_family, moves_used=moves
        )

        efforts = [
            response.voice_effort
            for _q, response in rows
            if response.answered_by == "voice" and response.voice_effort is not None
        ]
        voice_effort = int(sum(efforts) / len(efforts)) if efforts else None

        if dimension_weights:
            # Mirrors graph._claim_score_under: a role that overrides dimension
            # weights re-scores the claim through that lens and, as the live
            # path does, drops the voice blend. Replaying it any other way
            # would diff against a number the recruiter was never shown.
            ordered: dict[Dimension, DimensionScore] = {
                d: dimensions[d] for d in scoring.DIMENSION_ORDER if d in dimensions
            }
            score = scoring.claim_score(
                ordered, session.job_family, weights=dimension_weights, signals=answer_signals
            )
        else:
            score = scoring.claim_score(
                dimensions,
                session.job_family,
                voice_effort=voice_effort,
                voice_weight=voice_weight,
                signals=answer_signals,
            )

        result.claim_scores[claim.id] = score
        pairs.append((claim.claim_type, score))

    weighted, coverage = scoring.weighted_evidence_score(pairs, claim_weights)

    clashes = [
        Contradiction(
            fact_key=row.fact_key,
            fact_label=row.fact_label,
            earlier_value=row.earlier_value,
            later_value=row.later_value,
            earlier_response_id=row.earlier_response_id,
            later_response_id=row.later_response_id,
            severity=Severity(row.severity),
            delta_pct=row.delta_pct,
        )
        for row in (
            await db.execute(
                scoped(
                    select(ContradictionRow)
                    .where(ContradictionRow.session_id == session.id)
                    .order_by(ContradictionRow.created_at, ContradictionRow.id),
                    ContradictionRow,
                    scope,
                )
            )
        ).scalars().all()
    ]
    consistency_score = consistency_engine.consistency_score(clashes)

    result.weighted_evidence_score = weighted
    result.role_coverage = coverage
    result.consistency_score = consistency_score
    result.competence_score = scoring.competence_score(
        weighted, consistency_engine.multiplier(consistency_score)
    )
    result.badge = scoring.badge_for(result.competence_score)

    # --- the diff ----------------------------------------------------------

    differences: list[ReplayDifference] = []

    def compare(name: str, stored, replayed) -> None:
        if stored != replayed:
            differences.append(
                ReplayDifference(field=name, stored=str(stored), replayed=str(replayed))
            )

    compare(
        "weighted_evidence_score",
        evaluation.weighted_evidence_score,
        result.weighted_evidence_score,
    )
    compare("competence_score", evaluation.competence_score, result.competence_score)
    compare("badge", evaluation.badge, result.badge.value)
    compare("consistency_score", evaluation.consistency_score, result.consistency_score)
    compare("role_coverage", evaluation.role_coverage, result.role_coverage)
    compare("contradiction_count", evaluation.contradiction_count, len(clashes))
    for claim in claims:
        stored = stored_claim_scores.get(claim.id)
        if stored is not None:
            compare(
                f"claim.{claim.id}.score", stored.score, result.claim_scores[claim.id]
            )

    drift = [
        ReplayDifference(field=name, stored=then, replayed=now)
        for name, then, now in provenance_engine.drift(
            provenance_engine.from_row(evaluation), provenance_engine.current()
        )
    ]

    llm_calls = llm.cache_stats()["calls"] - calls_before
    if llm_calls:                                            # pragma: no cover
        raise ReplayUnavailable(
            f"replay made {llm_calls} model call(s); it is not a replay"
        )
    if db.new or db.dirty or db.deleted:                     # pragma: no cover
        raise ReplayUnavailable(
            "replay left pending changes on the session; it must be read-only"
        )

    status = ReplayStatus.MATCH if not differences else ReplayStatus.MISMATCH
    note = (
        "Recomputed from stored signals with zero model calls. "
        "Extraction is recorded; everything downstream of it is replayable. "
        "resume_score is excluded — it depends on live configuration, not on "
        "stored evidence."
    )
    if differences and drift:
        note += (
            f" {len(drift)} provenance input(s) moved since finalization, which "
            f"is the first place to look."
        )
    elif differences:
        note += (
            " No provenance input moved, so the difference is NOT explained by a "
            "version change — investigate the stored rows."
        )

    log.info(
        "replay %s -> %s (%d difference(s), %d drift, %d model calls)",
        evaluation.id, status.value, len(differences), len(drift), llm_calls,
    )
    return ReplayResultOut(
        evaluation_id=evaluation.id,
        status=status,
        replayed_at=utcnow(),
        llm_calls=llm_calls,
        claims_replayed=len(claims),
        answers_replayed=result.answers,
        differences=differences,
        provenance_drift=drift,
        note=note,
    )
