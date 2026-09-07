"""
Question Evaluation Harness — offline only.

    python scripts/question_eval_harness.py                  # everything
    python scripts/question_eval_harness.py --limit 50        # costed pilot
    python scripts/question_eval_harness.py --move AUTHORITY  # one move only

Reads QUESTIONS FROM COMPLETED SESSIONS ONLY (`ChatSession.completed_at IS NOT
NULL`) — an in-progress interview's questions haven't finished proving
anything about the candidate yet, and mixing them in would let a question
that's still mid-repair-and-retry look identical to one that ran its full
course. Joins each question to its claim, its session's candidate, and asks
an LLM judge to score it on 7 axes. Writes a CSV (one row per question) plus
a markdown report (by-move, by-seniority, worst 20, best 20).

THIS SCRIPT DOES NOT TOUCH `api/`. No production file is imported for its
side effects, no runtime setting is flipped, no new LLM call is added to the
interview flow — this reads rows that already exist, after the fact.
`api/engine/question.py::log_question_quality` is a SEPARATE, live,
background-task version of a near-identical rubric wired into
`orchestrator.ask_next()` behind `settings.live_question_quality_log`
(default off) — that one exists to be read from the log stream in real time;
this one exists to be aggregated across many interviews at once, batched,
with a written CSV to sort and filter. Same axes, deliberately, so the two
are comparable; two different code paths on purpose, since one lives in
`api/` and must never add interview-flow latency or cost, and the other is
disposable analysis tooling that is fine to run whenever you choose to spend
on it.

The judge prompt is inline, not `api/prompts/*.txt` — that directory is
glob-discovered into `provenance.prompt_versions()`, and a prompt with zero
influence on any evaluation should not silently become one of its inputs
(what `test_every_versioned_input_has_a_value` pins against).
"""
from __future__ import annotations

import argparse
import asyncio
import csv
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

OUT_DIR = ROOT / "studies" / "question_eval"
OUT_DIR.mkdir(parents=True, exist_ok=True)
SCORES_CSV = OUT_DIR / "scores.csv"
REPORT_MD = OUT_DIR / "report.md"

AXES = [
    "clarity", "specificity", "naturalness", "single_focus",
    "answerability", "evidence_yield", "relevance_to_claim",
]

CSV_FIELDS = [
    "question_id", "move", "claim_type", "seniority",
    *AXES, "average_score",
]


# Local to this script, not api/schemas.py — mirrors the "new, local Pydantic
# model" pattern extract.py's RoleClassification already uses, for the same
# reason: this is a study instrument's output shape, not a production contract.
class QuestionEvalScore(BaseModel):
    clarity: int
    specificity: int
    naturalness: int
    single_focus: int
    answerability: int
    evidence_yield: int
    relevance_to_claim: int


_EVAL_PROMPT = """You are auditing the QUALITY of a question an automated \
recruiting system asked, NOT judging the candidate. Score the QUESTION only.

CANDIDATE SENIORITY (may be "unknown")
$seniority

CLAIM TYPE
$claim_type

THE CLAIM THIS QUESTION IS PROBING
$claim

THE MOVE IT WAS TARGETING
$move

THE GENERATED QUESTION
$question

Score each axis 1 (worst) to 5 (best):

- clarity: can a candidate understand the question immediately?
- specificity: does it ask for something concrete, not a vague generality?
- naturalness: does it sound like a human interviewer, not a form?
- single_focus: does it ask one thing only, not several bundled together?
- answerability: can a realistic candidate who did this work actually answer it?
- evidence_yield: will a strong answer reveal real competence evidence,
  verifiable and hard to invent?
- relevance_to_claim: is this the best next question for verifying THIS
  claim specifically, not a generic question that could apply to any claim?

Return JSON:
{"clarity": 1-5, "specificity": 1-5, "naturalness": 1-5, "single_focus": 1-5, \
"answerability": 1-5, "evidence_yield": 1-5, "relevance_to_claim": 1-5}"""


@dataclass
class Row:
    question_id: str
    claim_text: str
    claim_type: str
    seniority: str
    move: str
    question_text: str


async def _fetch_rows(limit: int | None, move: str | None) -> list[Row]:
    async with SessionLocal() as db:
        stmt = (
            select(Question, Claim, Candidate)
            .join(Claim, Claim.id == Question.claim_id)
            .join(ChatSession, ChatSession.id == Question.session_id)
            .join(Candidate, Candidate.id == ChatSession.candidate_id)
            .where(ChatSession.completed_at.isnot(None))
            # A repair is a canned, un-generated line (CLAUDE.md / P2-04) —
            # there is nothing for a generation-quality judge to say about it.
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
            claim_text=c.text,
            claim_type=c.claim_type,
            seniority=cand.seniority or "unknown",
            move=q.move or q.probe_level,
            question_text=q.text,
        )
        for q, c, cand in result
    ]


def _fallback_score() -> QuestionEvalScore:
    return QuestionEvalScore(**{axis: 0 for axis in AXES})


async def _judge(row: Row) -> tuple[QuestionEvalScore, bool]:
    prompt = Template(_EVAL_PROMPT).safe_substitute(
        seniority=row.seniority,
        claim_type=row.claim_type,
        claim=row.claim_text,
        move=row.move,
        question=row.question_text,
    )
    used_fallback = not settings.llm_enabled
    score = await complete_json(
        prompt,
        QuestionEvalScore,
        temperature=0.0,
        fallback=_fallback_score,  # CLAUDE.md rule 5 — every LLM call has one
        cache=False,
    )
    return score, used_fallback


def _average(score: QuestionEvalScore) -> float:
    return sum(getattr(score, axis) for axis in AXES) / len(AXES)


async def run(limit: int | None, move: str | None) -> int:
    if not settings.llm_enabled:
        print(
            "\n  !! FIXTURE MODE — no OPENAI_API_KEY. Every row will be judged\n"
            "     0/5 across all axes and excluded from every breakdown below.\n"
            "     This is a plumbing smoke test, not a measurement.\n"
        )

    rows = await _fetch_rows(limit, move)
    if not rows:
        print("no matching Question rows found (completed sessions, non-repair)")
        return 1

    print(f"judging {len(rows)} questions from completed sessions "
          f"with {settings.openai_model}...")
    records: list[dict] = []
    fallback_count = 0
    for index, row in enumerate(rows, start=1):
        score, used_fallback = await _judge(row)
        fallback_count += used_fallback
        records.append({
            "question_id": row.question_id,
            "move": row.move,
            "claim_type": row.claim_type,
            "seniority": row.seniority,
            **{axis: getattr(score, axis) for axis in AXES},
            "average_score": round(_average(score), 2),
            # Not a CSV column (extrasaction="ignore" drops these two on
            # write) — kept only so the worst/best-20 report can quote the
            # actual question instead of an id a human has to look up.
            "_judge_source": "fixture_fallback" if used_fallback else "model",
            "_question_text": row.question_text,
        })
        if index % 20 == 0 or index == len(rows):
            print(f"  [{index}/{len(rows)}]")

    with SCORES_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    print(f"\nwrote {len(records)} scored rows -> {SCORES_CSV}")
    if fallback_count:
        print(f"  {fallback_count} of {len(records)} rows are fixture fallbacks "
              f"— excluded from the report below")

    _write_report(records)
    return 0


def _write_report(records: list[dict]) -> None:
    judged = [r for r in records if r["_judge_source"] == "model"]
    if not judged:
        print("\n  no model-judged rows — report skipped")
        return

    lines = [
        "# Question Evaluation Harness — Report",
        "",
        f"{len(judged)} questions judged by {settings.openai_model} from completed "
        f"sessions ({len(records) - len(judged)} fixture-fallback rows excluded).",
        "",
        "## Average score by move",
        "",
        "| Move | n | avg score |",
        "|---|---|---|",
    ]
    by_move: dict[str, list[float]] = defaultdict(list)
    for r in judged:
        by_move[r["move"]].append(r["average_score"])
    for mv, scores in sorted(by_move.items(), key=lambda kv: -statistics.mean(kv[1])):
        lines.append(f"| `{mv}` | {len(scores)} | {statistics.mean(scores):.2f} |")

    lines += ["", "## Average score by seniority", "",
              "| Seniority | n | avg score |", "|---|---|---|"]
    by_seniority: dict[str, list[float]] = defaultdict(list)
    for r in judged:
        by_seniority[r["seniority"]].append(r["average_score"])
    for sen, scores in sorted(by_seniority.items()):
        lines.append(f"| `{sen}` | {len(scores)} | {statistics.mean(scores):.2f} |")

    lines += ["", "## Worst 20 questions", ""]
    for r in sorted(judged, key=lambda r: r["average_score"])[:20]:
        lines.append(
            f"- **{r['average_score']:.2f}** `{r['move']}` / {r['claim_type']} "
            f"/ seniority={r['seniority']} / {r['question_id']} — {r['_question_text']!r}"
        )

    lines += ["", "## Best 20 questions", ""]
    for r in sorted(judged, key=lambda r: -r["average_score"])[:20]:
        lines.append(
            f"- **{r['average_score']:.2f}** `{r['move']}` / {r['claim_type']} "
            f"/ seniority={r['seniority']} / {r['question_id']} — {r['_question_text']!r}"
        )

    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote report -> {REPORT_MD}")


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").strip().split("\n")[0])
    parser.add_argument("--limit", type=int, default=None, help="cap rows judged (costed pilot)")
    parser.add_argument("--move", default=None, help="filter to one Move value")
    args = parser.parse_args()
    return asyncio.run(run(args.limit, args.move))


if __name__ == "__main__":
    raise SystemExit(main())
