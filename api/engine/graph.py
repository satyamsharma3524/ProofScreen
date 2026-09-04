"""
ARTIFACT 5 — graph assembly and the recruiter ranking engine.

Two jobs:

  build_candidate_graph()   the claim -> Q&A -> dimension tree the dashboard renders
  rank_candidates()         the ranked list, FOR A GIVEN ROLE

The second one is the demo moment. Every dimension score is already stored, so
re-ranking for a different recruiter is arithmetic over rows we have — no model
call, no re-interview. Two requests with two role_ids return two different
orders over identical evidence, in milliseconds.
"""

from __future__ import annotations

import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api import ids
from api.config import settings
from api.engine import consistency, scoring
from api.models import (
    Candidate,
    ChatSession,
    Claim,
    ClaimScore,
    ContradictionRow,
    Evidence,
    JobRole,
    Profile,
    Question,
    Response,
    Resume,
    utcnow,
)
from api.schemas import (
    AnswerMode,
    Badge,
    CandidateGraph,
    CandidateRef,
    CandidateSummary,
    ClaimGraph,
    ConsistencyReport,
    Contradiction,
    DimensionScore,
    ExtractedFact,
    ProbeLevel,
    QATurn,
    RoleOut,
    RoleRef,
    Severity,
    SessionState,
    VoiceSignals,
)
from api.taxonomy import (
    claim_type_label,
    match_family,
    default_claim_weights,
    dimension_weights,
    family_label,
    resolve_family,
)

log = logging.getLogger("proofscreen.graph")


def _load_dimensions(payload: str | None) -> dict[str, DimensionScore]:
    try:
        data = json.loads(payload or "{}")
    except (TypeError, ValueError):
        return {}
    out: dict[str, DimensionScore] = {}
    for key, entry in data.items():
        try:
            out[key] = DimensionScore.model_validate(entry)
        except Exception:  # noqa: BLE001
            continue
    return out


# ---------------------------------------------------------------------------
# role weight profiles
# ---------------------------------------------------------------------------


def role_to_out(role: JobRole) -> RoleOut:
    return RoleOut(
        id=role.id,
        title=role.title,
        job_family=role.job_family,
        job_family_label=family_label(role.job_family),
        claim_weights=json.loads(role.claim_weights_json or "{}"),
        dimension_weights=json.loads(role.dimension_weights_json or "{}"),
        is_default=role.is_default,
    )


async def create_role(
    db: AsyncSession,
    title: str,
    job_family: str,
    claim_weights: dict[str, float] | None = None,
    dimension_weights_override: dict[str, float] | None = None,
    is_default: bool = False,
) -> JobRole:
    """A recruiter's weight profile. Unspecified weights fall back to the
    family defaults, and everything is rescaled to sum to 100 — a recruiter who
    types 40/30/20/20 gets what they meant rather than a validation error."""
    family = resolve_family(job_family)
    weights = scoring.normalise_weights(claim_weights or default_claim_weights(family))
    role = JobRole(
        id=ids.role_id(),
        title=title,
        job_family=family,
        claim_weights_json=json.dumps(weights),
        dimension_weights_json=json.dumps(dimension_weights_override or {}),
        is_default=is_default,
    )
    db.add(role)
    await db.commit()
    return role


async def resolve_weights(
    db: AsyncSession, job_family: str, role_id: str | None
) -> tuple[dict[str, float], dict[str, float], RoleRef | None]:
    """(claim weights, dimension weight OVERRIDE, which role produced them).

    The second element is the role's EXPLICIT dimension weights, or {} when the
    role did not set any. Empty means "use the family defaults that were already
    applied when the claim was scored" — so an empty dict lets the caller keep
    the stored claim score untouched instead of recomputing it to the same
    number. See `_claim_score_under()`.
    """
    family = resolve_family(job_family)
    if role_id:
        role = await db.get(JobRole, role_id)
        if role is not None:
            claim_w = json.loads(role.claim_weights_json or "{}") or default_claim_weights(family)
            dim_w = json.loads(role.dimension_weights_json or "{}")
            return (
                claim_w,
                dim_w,
                RoleRef(id=role.id, title=role.title, job_family=role.job_family),
            )
    return default_claim_weights(family), {}, None


def _claim_score_under(
    stored: ClaimScore | None, job_family: str, dim_weights: dict[str, float]
) -> int:
    """Re-score one stored claim through a role's dimension lens.

    THE LATE-LENS RULE. Dimension scores are stored per claim, so a recruiter
    who weights CAUSAL_REASONING above TOOL_FAMILIARITY gets a different claim
    score over the SAME evidence — no re-interviewing, no model call, pure
    arithmetic over rows we already have.

    With no override this returns the stored score unchanged, so the default
    path is byte-identical to before (and keeps the voice blend that was applied
    when the claim was first scored).
    """
    if stored is None:
        return 0
    if not dim_weights:
        return stored.score

    by_dimension = _load_dimensions(stored.dimensions_json)
    ordered = {
        d: by_dimension[d.value] for d in scoring.DIMENSION_ORDER if d.value in by_dimension
    }
    if not ordered:
        return stored.score
    return scoring.claim_score(ordered, job_family, weights=dim_weights)


# ---------------------------------------------------------------------------
# consistency
# ---------------------------------------------------------------------------


async def session_contradictions(
    db: AsyncSession, session_id: str
) -> list[Contradiction]:
    rows = (
        await db.execute(
            select(ContradictionRow)
            .where(ContradictionRow.session_id == session_id)
            .order_by(ContradictionRow.created_at)
        )
    ).scalars().all()
    return [
        Contradiction(
            fact_key=r.fact_key,
            fact_label=r.fact_label,
            earlier_value=r.earlier_value,
            later_value=r.later_value,
            earlier_response_id=r.earlier_response_id,
            later_response_id=r.later_response_id,
            severity=Severity(r.severity),
            delta_pct=r.delta_pct,
            note=r.note,
        )
        for r in rows
    ]


async def build_consistency_report(
    db: AsyncSession, session_id: str
) -> ConsistencyReport:
    from api.models import SessionFact

    clashes = await session_contradictions(db, session_id)
    facts_tracked = len(
        (
            await db.execute(
                select(SessionFact).where(SessionFact.session_id == session_id)
            )
        ).scalars().all()
    )
    score = consistency.consistency_score(clashes)
    return ConsistencyReport(
        score=score,
        multiplier=consistency.multiplier(score),
        facts_tracked=facts_tracked,
        contradictions=clashes,
        note=consistency.summarise(clashes),
    )


# ---------------------------------------------------------------------------
# the graph
# ---------------------------------------------------------------------------


async def build_candidate_graph(
    db: AsyncSession, candidate_id: str, role_id: str | None = None
) -> CandidateGraph | None:
    candidate = await db.get(Candidate, candidate_id)
    if candidate is None:
        return None

    family = resolve_family(candidate.job_family)
    claim_weights, dim_weights, role_ref = await resolve_weights(
        db, family, role_id or candidate.role_id
    )

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

    qa_by_claim: dict[str, list[QATurn]] = {}
    facts_by_claim: dict[str, list[ExtractedFact]] = {}
    for question, response in qa_rows:
        voice = (
            VoiceSignals(
                duration_seconds=response.voice_duration_seconds or 0.0,
                word_count=response.voice_word_count or 0,
                effort_score=response.voice_effort or 0,
            )
            if response.answered_by == "voice"
            else None
        )
        qa_by_claim.setdefault(question.claim_id, []).append(
            QATurn(
                question=question.text,
                probe_level=ProbeLevel(question.probe_level),
                answer=response.answer_text,
                answered_by=AnswerMode(response.answered_by),
                voice=voice,
                question_id=question.id,
                response_id=response.id,
                answer_score=response.answer_score,
            )
        )
        try:
            from api.engine.evidence import signals_of

            for fact in signals_of(response.signals_json).facts:
                facts_by_claim.setdefault(question.claim_id, []).append(fact)
        except Exception:  # noqa: BLE001
            pass

    session = (
        await db.execute(
            select(ChatSession)
            .where(ChatSession.candidate_id == candidate_id)
            .order_by(ChatSession.started_at.desc())
        )
    ).scalars().first()

    consistency_report = (
        await build_consistency_report(db, session.id) if session else ConsistencyReport()
    )

    claim_graphs: list[ClaimGraph] = []
    scored_pairs: list[tuple[str, int]] = []
    profile_input: list[tuple[float, dict]] = []

    for claim in claims:
        stored = scores.get(claim.id)
        dimensions_map = _load_dimensions(stored.dimensions_json if stored else None)
        ordered = [
            dimensions_map.get(
                d.value,
                DimensionScore(dimension=d, score=0, basis="not probed", probed=False),
            )
            for d in scoring.DIMENSION_ORDER
        ]
        weight = float(claim_weights.get(claim.claim_type, 0.0))
        claim_score = _claim_score_under(stored, family, dim_weights)

        claim_graphs.append(
            ClaimGraph(
                id=claim.id,
                text=claim.text,
                claim_type=claim.claim_type,
                claim_type_label=claim_type_label(family, claim.claim_type),
                metric=claim.metric,
                weight=weight,
                claim_score=claim_score if stored else None,
                dimensions=ordered,
                probed_dimensions=stored.probed_dimensions if stored else 0,
                qa=qa_by_claim.get(claim.id, []),
                summary=stored.summary if stored else None,
                facts=facts_by_claim.get(claim.id, []),
            )
        )
        scored_pairs.append((claim.claim_type, claim_score))
        profile_input.append(
            (weight, {d: dimensions_map.get(d.value) for d in scoring.DIMENSION_ORDER
                      if dimensions_map.get(d.value)})
        )

    weighted, coverage = scoring.weighted_evidence_score(scored_pairs, claim_weights)
    competence = scoring.competence_score(weighted, consistency_report.multiplier)

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
        else 0
    )

    # P1-08b — how close the routing call was.
    #
    # THIS IS A MARGIN, NOT A PROBABILITY: (top1 - top2) / top1 over the
    # per-family scores. It answers "was this close?", which is the question a
    # recruiter looking at a mis-routed candidate actually has. It makes no
    # claim about being right — a confidently wrong router would report 1.00.
    #
    # 0.0 has two causes, and `job_family` is what tells them apart: either no
    # family cleared the two-term floor (family reads `general`), or two
    # families tied exactly (family reads the winner). `CandidateGraph` has one
    # float and `schemas.py` is frozen, so the disambiguation lives in the pair
    # of fields rather than in a second one. `GET /api/dev/detect` renders the
    # full explanation.
    #
    # Reuses the resume already loaded above for `resume_score`, so this costs
    # no query and no model call — `match_family` is a pure function of the
    # text and the taxonomy file.
    confidence = match_family(resume.raw_text).confidence if resume else None

    return CandidateGraph(
        candidate=CandidateRef(
            id=candidate.id, name=candidate.name, role=candidate.role, phone=candidate.phone
        ),
        job_family=family,
        job_family_label=family_label(family),
        scored_for=role_ref,
        state=SessionState(session.state) if session else SessionState.NEW,
        questions_asked=session.questions_asked if session else 0,
        resume_score=r_score,
        routing_confidence=confidence,
        weighted_evidence_score=weighted,
        competence_score=competence,
        badge=scoring.badge_for(competence),
        role_coverage=coverage,
        consistency=consistency_report,
        dimension_profile=scoring.candidate_dimension_profile(profile_input),
        claims=claim_graphs,
        computed_at=utcnow(),
    )


# ---------------------------------------------------------------------------
# profile (default-role snapshot, for the fast list view)
# ---------------------------------------------------------------------------


async def recompute_profile(db: AsyncSession, candidate_id: str) -> Profile | None:
    graph = await build_candidate_graph(db, candidate_id)
    if graph is None:
        return None

    profile = (
        await db.execute(select(Profile).where(Profile.candidate_id == candidate_id))
    ).scalar_one_or_none()
    if profile is None:
        profile = Profile(id=ids.profile_id(), candidate_id=candidate_id)
        db.add(profile)

    profile.resume_score = graph.resume_score
    profile.weighted_evidence_score = graph.weighted_evidence_score
    profile.competence_score = graph.competence_score
    profile.consistency_score = graph.consistency.score
    profile.contradiction_count = len(graph.consistency.contradictions)
    profile.role_coverage = graph.role_coverage
    profile.badge = graph.badge.value
    profile.status = graph.state.value
    profile.scored_role_id = graph.scored_for.id if graph.scored_for else None
    profile.dimension_profile_json = json.dumps(
        [d.model_dump(mode="json") for d in graph.dimension_profile]
    )
    profile.computed_at = utcnow()

    await db.commit()
    return profile


# ---------------------------------------------------------------------------
# ranking — same evidence, different recruiter, different order
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# P1-13 — why_ranked
#
# The ranked list is the first screen a recruiter opens, and until now it
# answered `that` a candidate ranks where they do and never `why`. The
# drill-down answers it in full, but nobody opens twenty drill-downs.
#
# Two rules this sentence obeys:
#   1. It CITES EVIDENCE, never restates the score. "competence 56" in prose is
#      a row of text with no information in it.
#   2. It COSTS NOTHING EXTRA. Every input is already loaded by
#      rank_candidates(); counting quantities from responses.signals_json would
#      mean ~12 JSON parses per candidate on the busiest endpoint.
# ---------------------------------------------------------------------------

# Each rubric counts a disjoint bucket of signals — specificity counts
# quantities and named entities, process counts steps, causal counts chains,
# authenticity counts incidents, tool counts tools, metric counts definitions —
# so summing signal_count across the six is a true total, not double counting.
_DIMENSION_PHRASE = {
    "SPECIFICITY": "concrete figures",
    "PROCESS": "process detail",
    "METRIC_OWNERSHIP": "metric ownership",
    "CAUSAL_REASONING": "causal reasoning",
    "AUTHENTICITY": "recalled incidents",
    "TOOL_FAMILIARITY": "tool usage",
}


def _dimension_totals(
    claims: "list[Claim]", claim_scores: "dict[str, ClaimScore]"
) -> dict:
    """Structured counts from `dimensions_json`. No string parsing.

    The `basis` strings are for display ("3 quantities, 2 named entities") and
    parsing them back would couple this sentence to their wording. The numbers
    beside them are the real data.
    """
    signals = 0
    probed: set[str] = set()
    best: tuple[int, str] | None = None
    specificity_signals = 0
    scored_claims = 0
    stalled: list[str] = []

    for claim in claims:
        stored = claim_scores.get(claim.id)
        if stored is None:
            continue
        scored_claims += 1
        for key, entry in _load_dimensions(stored.dimensions_json).items():
            signals += entry.signal_count
            if entry.probed:
                probed.add(key)
            if key == "SPECIFICITY":
                specificity_signals += entry.signal_count
            if entry.score > 0 and (best is None or entry.score > best[0]):
                best = (entry.score, key)
        # Probed at least twice and still nothing: the adaptive stop gave up on
        # this claim. That is a finding about the candidate, not a gap in ours.
        if (stored.answers_count or 0) >= 2 and stored.score == 0:
            stalled.append(claim.claim_type)

    return {
        "signals": signals,
        "probed": len(probed),
        "best": best,
        "specificity_signals": specificity_signals,
        "scored_claims": scored_claims,
        "stalled": stalled,
    }


def _why_ranked(
    claims: "list[Claim]",
    claim_scores: "dict[str, ClaimScore]",
    contradiction_count: int,
    questions_asked: int,
    family: str,
    claim_weights: "dict[str, float]",
) -> str:
    """One sentence, from stored rows, no model call.

    Three clauses: what evidence exists, what undermines it, and what this
    lens cared about. The third is why the sentence changes with `role_id` —
    the same evidence read through a different lens is a different explanation,
    and a list view whose reasoning ignored the lens would contradict the
    ranking it sits next to.
    """
    if not claims:
        return "No claims extracted from this resume yet."
    if questions_asked == 0:
        return f"{len(claims)} claims extracted, not yet interviewed."

    totals = _dimension_totals(claims, claim_scores)
    if totals["scored_claims"] == 0:
        return f"{len(claims)} claims extracted, no answers scored yet."

    parts: list[str] = [
        f"{totals['signals']} evidence signal"
        f"{'' if totals['signals'] == 1 else 's'} across "
        f"{totals['scored_claims']} claim"
        f"{'' if totals['scored_claims'] == 1 else 's'}, "
        f"{totals['probed']} of 6 dimensions probed"
    ]

    if totals["best"]:
        score, key = totals["best"]
        parts.append(f"strongest on {_DIMENSION_PHRASE.get(key, key.lower())} ({score})")
    if totals["specificity_signals"] == 0:
        # The single most diagnostic absence: no number anywhere in any answer.
        parts.append("no concrete figures in any answer")
    if totals["stalled"]:
        labels = ", ".join(
            claim_type_label(family, t) for t in sorted(set(totals["stalled"]))
        )
        parts.append(
            f"{len(totals['stalled'])} claim"
            f"{'' if len(totals['stalled']) == 1 else 's'} stalled ({labels})"
        )
    parts.append(
        "no contradictions"
        if not contradiction_count
        else f"{contradiction_count} contradiction"
        f"{'' if contradiction_count == 1 else 's'}"
    )

    # The lens clause. Names the claim type these weights care about most and
    # how the candidate actually did on it, so the explanation moves when the
    # ranking moves.
    present = {c.claim_type for c in claims}
    weighted = [(claim_weights.get(t, 0.0), t) for t in present]
    if weighted:
        weight, heaviest = max(weighted, key=lambda pair: (pair[0], pair[1]))
        if weight > 0:
            claim = next(c for c in claims if c.claim_type == heaviest)
            stored = claim_scores.get(claim.id)
            scored = f" scored {stored.score}" if stored else " not yet scored"
            parts.append(
                f"this lens weights {claim_type_label(family, heaviest)} most "
                f"({weight:g}%),{scored}"
            )

    return "; ".join(parts) + "."


async def rank_candidates(
    db: AsyncSession, role_id: str | None = None
) -> tuple[RoleRef | None, list[CandidateSummary]]:
    """Ranked list. With a role_id, every score is recomputed from stored
    dimension scores under that role's weights — no model calls, no
    re-interviewing, and the order genuinely changes."""
    candidates = (
        await db.execute(select(Candidate).order_by(Candidate.created_at.desc()))
    ).scalars().all()
    if not candidates:
        return None, []

    ids_list = [c.id for c in candidates]

    role: JobRole | None = await db.get(JobRole, role_id) if role_id else None
    role_ref = (
        RoleRef(id=role.id, title=role.title, job_family=role.job_family) if role else None
    )
    role_claim_weights = (
        json.loads(role.claim_weights_json or "{}") if role else None
    )
    # The same late lens the detail view applies, so the ranked list and the
    # candidate graph can never disagree about a claim's score.
    role_dim_weights = json.loads(role.dimension_weights_json or "{}") if role else {}

    profiles = {
        p.candidate_id: p
        for p in (
            await db.execute(select(Profile).where(Profile.candidate_id.in_(ids_list)))
        ).scalars().all()
    }

    claims_by_candidate: dict[str, list[Claim]] = {}
    for claim in (
        await db.execute(select(Claim).where(Claim.candidate_id.in_(ids_list)))
    ).scalars().all():
        claims_by_candidate.setdefault(claim.candidate_id, []).append(claim)

    all_claim_ids = [c.id for group in claims_by_candidate.values() for c in group]
    claim_scores = {
        s.claim_id: s
        for s in (
            (
                await db.execute(
                    select(ClaimScore).where(ClaimScore.claim_id.in_(all_claim_ids))
                )
            ).scalars().all()
            if all_claim_ids
            else []
        )
    }

    sessions: dict[str, ChatSession] = {}
    for session in (
        await db.execute(
            select(ChatSession)
            .where(ChatSession.candidate_id.in_(ids_list))
            .order_by(ChatSession.started_at)
        )
    ).scalars().all():
        sessions[session.candidate_id] = session

    out: list[CandidateSummary] = []
    for candidate in candidates:
        profile = profiles.get(candidate.id)
        session = sessions.get(candidate.id)
        family = resolve_family(candidate.job_family)
        claims = claims_by_candidate.get(candidate.id, [])

        if role_claim_weights is not None and claims:
            # Re-rank: same stored evidence, this recruiter's weights.
            pairs = [
                (
                    c.claim_type,
                    _claim_score_under(claim_scores.get(c.id), family, role_dim_weights),
                )
                for c in claims
            ]
            weighted, coverage = scoring.weighted_evidence_score(pairs, role_claim_weights)
            consistency_score = profile.consistency_score if profile else 100
            competence = scoring.competence_score(
                weighted, consistency.multiplier(consistency_score)
            )
            badge = scoring.badge_for(competence)
        else:
            weighted = profile.weighted_evidence_score if profile else 0
            competence = profile.competence_score if profile else 0
            coverage = profile.role_coverage if profile else 0
            consistency_score = profile.consistency_score if profile else 100
            badge = Badge(profile.badge) if profile else Badge.unverified

        effective_weights = (
            role_claim_weights
            if role_claim_weights is not None
            else default_claim_weights(family)
        )

        out.append(
            CandidateSummary(
                id=candidate.id,
                name=candidate.name,
                role=candidate.role,
                why_ranked=_why_ranked(
                    claims,
                    claim_scores,
                    profile.contradiction_count if profile else 0,
                    session.questions_asked if session else 0,
                    family,
                    effective_weights,
                ),
                job_family=family,
                job_family_label=family_label(family),
                resume_score=profile.resume_score if profile else 0,
                weighted_evidence_score=weighted,
                competence_score=competence,
                badge=badge,
                role_coverage=coverage,
                consistency_score=consistency_score,
                contradiction_count=profile.contradiction_count if profile else 0,
                state=SessionState(session.state) if session else None,
                claims_count=len(claims),
                questions_asked=session.questions_asked if session else 0,
                computed_at=profile.computed_at if profile else None,
            )
        )

    out.sort(key=lambda c: (-c.competence_score, -c.weighted_evidence_score, c.name))
    return role_ref, out
