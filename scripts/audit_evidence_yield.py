"""
Evidence Yield Audit Script — Measures Evidence Delta (Delta E = Evidence_after - Evidence_before)
per interview turn and evaluates yield across question moves/categories.

Usage:
    python scripts/audit_evidence_yield.py
"""

from __future__ import annotations

import asyncio
import json
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from api.db import SessionLocal  # noqa: E402
from api.engine import evidence, scoring, signals  # noqa: E402
from api.models import Candidate, ChatSession, Claim, Question, Response  # noqa: E402
from api.schemas import AnswerSignals  # noqa: E402

OUT_DIR = ROOT / "studies" / "evidence_yield"
OUT_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class TurnYield:
    session_id: str
    candidate_name: str
    job_family: str
    turn_index: int
    question_id: str
    claim_id: str
    move: str
    probe_level: str
    question_text: str
    answer_text: str
    e_before: int
    e_after: int
    delta_e: int
    dimension_growth: dict[str, int]


async def fetch_session_yields() -> list[TurnYield]:
    yields: list[TurnYield] = []
    async with SessionLocal() as db:
        sessions = (await db.execute(select(ChatSession))).scalars().all()
        for session in sessions:
            candidate = await db.get(Candidate, session.candidate_id)
            cand_name = candidate.name if candidate else "Unknown"

            # Query Q&A rows in transcript order
            qa_rows = (
                await db.execute(
                    select(Question, Response)
                    .join(Response, Response.question_id == Question.id)
                    .where(Question.session_id == session.id)
                    .order_by(Question.order_index)
                )
            ).all()

            if not qa_rows:
                continue

            # Group by claim_id to compute per-claim evidence accumulation
            claim_qa: dict[str, list[tuple[Question, Response]]] = defaultdict(list)
            for q, r in qa_rows:
                claim_qa[q.claim_id].append((q, r))

            for claim_id, pairs in claim_qa.items():
                parsed_signals: list[AnswerSignals] = [
                    evidence.signals_of(r.signals_json) for _, r in pairs
                ]
                levels_used = [q.probe_level for q, _ in pairs]
                moves_used = [q.move for q, _ in pairs]

                for t in range(len(pairs)):
                    q, r = pairs[t]

                    sig_before = (
                        signals.merge_signals(parsed_signals[:t])
                        if t > 0
                        else AnswerSignals()
                    )
                    sig_after = signals.merge_signals(parsed_signals[: t + 1])

                    e_before = signals.total_signals(sig_before) if t > 0 else 0
                    e_after = signals.total_signals(sig_after)
                    delta_e = e_after - e_before

                    scores_before = (
                        signals.score_claim(
                            parsed_signals[:t],
                            levels_used[:t],
                            session.job_family,
                            moves_used[:t],
                        )
                        if t > 0
                        else {d: 0 for d in scoring.DIMENSION_ORDER}
                    )
                    scores_after = signals.score_claim(
                        parsed_signals[: t + 1],
                        levels_used[: t + 1],
                        session.job_family,
                        moves_used[: t + 1],
                    )

                    dim_growth: dict[str, int] = {}
                    for dim in scoring.DIMENSION_ORDER:
                        score_b = (
                            scores_before[dim].score
                            if hasattr(scores_before[dim], "score")
                            else 0
                        )
                        score_a = scores_after[dim].score
                        if score_a > score_b:
                            dim_growth[dim.value] = score_a - score_b

                    yields.append(
                        TurnYield(
                            session_id=session.id,
                            candidate_name=cand_name,
                            job_family=session.job_family,
                            turn_index=q.order_index,
                            question_id=q.id,
                            claim_id=q.claim_id,
                            move=q.move or q.probe_level,
                            probe_level=q.probe_level,
                            question_text=q.text,
                            answer_text=r.answer_text,
                            e_before=e_before,
                            e_after=e_after,
                            delta_e=delta_e,
                            dimension_growth=dim_growth,
                        )
                    )
    return yields


def generate_report(yields: list[TurnYield]) -> str:
    lines: list[str] = [
        "# Evidence Yield Audit Report (\u0394E = Evidence_after - Evidence_before)",
        "",
        f"Total session turns analyzed: **{len(yields)}**",
        "",
        "## Summary by Question Move / Category",
        "",
        "| Move / Target | n | Avg \u0394E (Evidence Yield) | Max \u0394E | Yield Quality |",
        "|---|---|---|---|---|",
    ]

    by_move: dict[str, list[int]] = defaultdict(list)
    for y in yields:
        by_move[y.move].append(y.delta_e)

    for move, deltas in sorted(
        by_move.items(), key=lambda kv: -statistics.mean(kv[1])
    ):
        avg_yield = statistics.mean(deltas)
        max_yield = max(deltas)
        if avg_yield >= 3.0:
            quality = "HIGH (\u2265 3.0)"
        elif avg_yield >= 1.5:
            quality = "MODERATE (1.5 - 2.9)"
        else:
            quality = "LOW (< 1.5)"
        lines.append(
            f"| `{move}` | {len(deltas)} | **{avg_yield:.2f}** | {max_yield} | {quality} |"
        )

    lines += [
        "",
        "## Turn-by-Turn Evidence Breakdown",
        "",
        "| Candidate | Turn | Move | Question | E_before | E_after | \u0394E | Dimension Growth |",
        "|---|---|---|---|---|---|---|---|",
    ]

    for y in sorted(yields, key=lambda y: (y.candidate_name, y.turn_index)):
        growth_str = (
            ", ".join(f"{k}:+{v}" for k, v in y.dimension_growth.items())
            if y.dimension_growth
            else "none"
        )
        q_short = (
            y.question_text[:50] + "..."
            if len(y.question_text) > 50
            else y.question_text
        )
        lines.append(
            f"| {y.candidate_name} | Q{y.turn_index+1} | `{y.move}` | {q_short!r} | {y.e_before} | {y.e_after} | **+{y.delta_e}** | {growth_str} |"
        )

    return "\n".join(lines) + "\n"


async def main() -> int:
    yields = await fetch_session_yields()
    if not yields:
        print("No sessions found in database. Running seed first...")
        import seed

        seed.main()
        yields = await fetch_session_yields()

    report_text = generate_report(yields)
    out_file = OUT_DIR / "evidence_yield_report.md"
    out_file.write_text(report_text, encoding="utf-8")

    json_file = OUT_DIR / "evidence_yield_data.json"
    json_file.write_text(
        json.dumps([y.__dict__ for y in yields], indent=2), encoding="utf-8"
    )

    print(f"\nReport written to {out_file.relative_to(ROOT)}")
    print(report_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
