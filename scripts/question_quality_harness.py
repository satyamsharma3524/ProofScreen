"""
Question Evaluation Harness — Phase 2 of the Candidate-Level work.

Design: docs/QUESTION_EVAL_HARNESS_AND_LEVEL_MODEL.md Part A. Reads
already-persisted `Question` rows (joined to their `Claim`, `ChatSession`
and `Candidate`) and asks an LLM judge to rate each one on an 8-axis
rubric. Entirely offline: no `api/` change, no live gate, nothing here is
read by the interview pipeline or by scoring.

    python scripts/question_quality_harness.py                 # judge everything
    python scripts/question_quality_harness.py --limit 50       # costed pilot
    python scripts/question_quality_harness.py --move AUTHORITY # one move only

CLAUDE.md rule 1 ("the model never produces a score") governs the LIVE
interview's judgment of a CANDIDATE — `api/engine/scoring.py` and
`AnswerSignals`, both enforced by tests that import nothing in this file.
This script's model call judges the GENERATOR's output quality, offline,
after the fact, never read by anything that scores a candidate. That is
the same distinction Phase 3 (`scripts/interview_study.py`) drew for its
own model call, on the other side of the line: there the model played the
CANDIDATE and a blind human judged `validate()`; here there is no
candidate in the loop at all, and the model judges the SYSTEM's output,
not a person. If this script's output were ever wired into `api/` or into
`scoring.py`, that distinction would stop holding — it is not, and isn't
meant to be: see docs/QUESTION_EVAL_HARNESS_AND_LEVEL_MODEL.md §A2.

The judge prompt lives inline in this file, not under `api/prompts/`, for
the same two reasons `interview_study.py`'s `_SIMULATOR_PROMPT` does: this
is a study instrument, not production, and `api/prompts/` is
glob-discovered into `prompt_versions()` — dropping a file there would
silently join the exact-five-prompt set `test_every_versioned_input_has_a_value`
pins.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from string import Template

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pydantic import BaseModel  # noqa: E402
from sqlalchemy import select  # noqa: E402

from api.config import settings  # noqa: E402
from api.db import SessionLocal  # noqa: E402
from api.llm import complete_json  # noqa: E402
from api.models import Candidate, ChatSession, Claim, Question  # noqa: E402

OUT_DIR = ROOT / "studies" / "question_quality"
OUT_DIR.mkdir(parents=True, exist_ok=True)

AXES = [
    "clarity", "specificity", "naturalness", "single_focus",
    "answerability", "evidence_yield", "relevance_to_claim", "level_fit",
]


# Local to this script, not api/schemas.py — same "new, local Pydantic model"
# pattern extract.py's RoleClassification already uses for exactly this reason.
class QuestionQualityScore(BaseModel):
    clarity: int
    specificity: int
    naturalness: int
    single_focus: int
    answerability: int
    evidence_yield: int
    relevance_to_claim: int
    level_fit: int
    reasoning: str


_JUDGE_PROMPT = """You are auditing the QUALITY of a question an automated \
recruiting system generated, NOT judging the candidate. Score the QUESTION only.

CANDIDATE SENIORITY (may be "unknown")
$seniority

THE CLAIM THIS QUESTION IS PROBING
$claim

THE MOVE IT WAS TARGETING
$move

THE GENERATED QUESTION
$question

Score each axis 1 (worst) to 5 (best):

- clarity: unambiguous and easy to parse on first read?
- specificity: targets something concrete, not a vague generality?
- naturalness: would a real interviewer actually phrase it this way out loud?
- single_focus: asks exactly one thing, not several bundled together?
- answerability: could a real candidate who did this work actually answer it?
- evidence_yield: is a strong answer likely to produce verifiable,
  hard-to-invent detail?
- relevance_to_claim: clearly follows from the claim above, not a generic
  question that could apply to any claim?
- level_fit: given the candidate's seniority, is this appropriate to ask them
  right now — not assuming authority or scope they may not have (score low if
  a junior is asked something that presumes decision-making authority or an
  intentional tradeoff), and not so basic it wastes a senior candidate's time
  (score low if a senior is asked something trivial). If seniority is
  "unknown", score 3 unless the question is obviously mismatched either way.

Return JSON:
{"clarity": 1-5, "specificity": 1-5, "naturalness": 1-5, "single_focus": 1-5, \
"answerability": 1-5, "evidence_yield": 1-5, "relevance_to_claim": 1-5, \
"level_fit": 1-5, "reasoning": "one sentence naming what drove the lowest score"}"""


@dataclass
class Row:
    question_id: str
    session_id: str
    claim_text: str
    claim_type: str
    move: str
    probe_level: str
    question_text: str
    source: str
    seniority: str


async def _fetch_rows(limit: int | None, move: str | None) -> list[Row]:
    async with SessionLocal() as db:
        stmt = (
            select(Question, Claim, Candidate)
            .join(Claim, Claim.id == Question.claim_id)
            .join(ChatSession, ChatSession.id == Question.session_id)
            .join(Candidate, Candidate.id == ChatSession.candidate_id)
            # A repair is a canned, un-generated line (CLAUDE.md/P2-04) — there
            # is nothing for a generation-quality judge to say about it.
            .where(Question.is_repair.is_(False))
            .order_by(Question.asked_at)
        )
        if move:
            stmt = stmt.where(Question.move == move)
        if limit:
            stmt = stmt.limit(limit)
        result = (await db.execute(stmt)).all()
    return [
        Row(
            question_id=q.id,
            session_id=q.session_id,
            claim_text=c.text,
            claim_type=c.claim_type,
            move=q.move or "",
            probe_level=q.probe_level,
            question_text=q.text,
            source=q.source,
            seniority=cand.seniority or "unknown",
        )
        for q, c, cand in result
    ]


def _fixture_score() -> QuestionQualityScore:
    return QuestionQualityScore(
        **{axis: 0 for axis in AXES}, reasoning="FIXTURE_MODE_NO_JUDGE",
    )


async def _judge(row: Row) -> tuple[QuestionQualityScore, bool]:
    prompt = Template(_JUDGE_PROMPT).safe_substitute(
        seniority=row.seniority,
        claim=row.claim_text,
        move=row.move or row.probe_level,
        question=row.question_text,
    )
    used_fallback = not settings.llm_enabled
    result = await complete_json(
        prompt,
        QuestionQualityScore,
        temperature=0.0,
        fallback=_fixture_score,  # CLAUDE.md rule 5 — every LLM call has one
        cache=False,
    )
    return result, used_fallback


def _overall(score: QuestionQualityScore) -> float:
    return sum(getattr(score, axis) for axis in AXES) / len(AXES)


async def run(limit: int | None, move: str | None) -> int:
    if not settings.llm_enabled:
        print(
            "\n  !! FIXTURE MODE — no OPENAI_API_KEY. Every row will be judged\n"
            "     0/5 with reasoning=FIXTURE_MODE_NO_JUDGE and excluded from the\n"
            "     leaderboard. This is a plumbing smoke test, not a measurement.\n"
        )

    rows = await _fetch_rows(limit, move)
    if not rows:
        print("no matching Question rows found")
        return 1

    print(f"judging {len(rows)} questions with {settings.openai_model}...")
    records: list[dict] = []
    fallback_count = 0
    for index, row in enumerate(rows, start=1):
        score, used_fallback = await _judge(row)
        fallback_count += used_fallback
        records.append({
            "question_id": row.question_id,
            "session_id": row.session_id,
            "claim_type": row.claim_type,
            "move": row.move,
            "probe_level": row.probe_level,
            "source": row.source,
            "seniority": row.seniority,
            "question": row.question_text,
            "judge_source": "fixture_fallback" if used_fallback else "model",
            **{axis: getattr(score, axis) for axis in AXES},
            "overall": round(_overall(score), 2),
            "reasoning": score.reasoning,
        })
        if index % 20 == 0 or index == len(rows):
            print(f"  [{index}/{len(rows)}]")

    out_path = OUT_DIR / "scores.json"
    out_path.write_text(json.dumps(records, indent=2), encoding="utf-8")
    print(f"\nwrote {len(records)} scored rows -> {out_path}")
    if fallback_count:
        print(f"  {fallback_count} of {len(records)} rows are fixture fallbacks "
              f"(judge_source=fixture_fallback) — excluded from the leaderboard below")

    _write_leaderboard(records)
    return 0


def _write_leaderboard(records: list[dict]) -> None:
    judged = [r for r in records if r["judge_source"] == "model"]
    if not judged:
        print("\n  no model-judged rows — leaderboard skipped")
        return

    by_move: dict[str, list[float]] = defaultdict(list)
    for r in judged:
        by_move[r["move"] or r["probe_level"]].append(r["overall"])

    lines = [
        "# Question Quality Leaderboard",
        "",
        f"{len(judged)} questions judged by {settings.openai_model} "
        f"({len(records) - len(judged)} fixture-fallback rows excluded).",
        "",
        "## By move (overall, mean of 8 axes)",
        "",
        "| Move | n | avg overall |",
        "|---|---|---|",
    ]
    for mv, scores in sorted(by_move.items(), key=lambda kv: -statistics.mean(kv[1])):
        lines.append(f"| `{mv}` | {len(scores)} | {statistics.mean(scores):.2f} |")

    lines += ["", "## By axis, overall population", "", "| Axis | mean |", "|---|---|"]
    for axis in AXES:
        lines.append(f"| `{axis}` | {statistics.mean(r[axis] for r in judged):.2f} |")

    by_seniority: dict[str, list[float]] = defaultdict(list)
    for r in judged:
        by_seniority[r["seniority"]].append(r["level_fit"])
    lines += ["", "## `level_fit` by candidate seniority", "",
              "| Seniority | n | avg level_fit |", "|---|---|---|"]
    for sen, scores in sorted(by_seniority.items()):
        lines.append(f"| `{sen}` | {len(scores)} | {statistics.mean(scores):.2f} |")

    lines += ["", "## 10 worst-scoring questions", ""]
    for r in sorted(judged, key=lambda r: r["overall"])[:10]:
        lines.append(
            f"- **{r['overall']:.2f}** (`{r['move'] or r['probe_level']}`, "
            f"seniority={r['seniority']}): {r['question']!r} — {r['reasoning']}"
        )

    path = OUT_DIR / "leaderboard.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote leaderboard -> {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").strip().split("\n")[0])
    parser.add_argument("--limit", type=int, default=None, help="cap rows judged (costed pilot)")
    parser.add_argument("--move", default=None, help="filter to one Move value")
    args = parser.parse_args()
    return asyncio.run(run(args.limit, args.move))


if __name__ == "__main__":
    raise SystemExit(main())
