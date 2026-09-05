"""
Replay a finalized evaluation from the command line. D8's support surface.

    python scripts/replay.py ev_9f3a21c4d0
    python scripts/replay.py --candidate c_80d850        # every evaluation
    python scripts/replay.py --all --tenant t_dev

Prints MATCH or MISMATCH per evaluation, the fields that moved, and any
provenance input that changed since finalization. Exit status is 0 when
everything matched and 1 when anything did not, so it works in a cron.

MAKES NO MODEL CALL. The key is cleared at import, exactly as `seed.py` and
`scripts/dump_fixture.py` do — support tooling must be free, instant and
offline, and a replay that could reach a provider would not be a replay.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.config import settings  # noqa: E402

settings.openai_api_key = None

from sqlalchemy import select  # noqa: E402

from api.db import SessionLocal  # noqa: E402
from api.engine.replay import ReplayUnavailable, replay_evaluation  # noqa: E402
from api.models import DEVELOPMENT_TENANT_ID, Evaluation  # noqa: E402
from api.schemas import ReplayStatus  # noqa: E402
from api.tenancy import TenantScope, scoped  # noqa: E402


async def _targets(db, args, scope) -> list[Evaluation]:
    stmt = select(Evaluation).where(Evaluation.status == "finalized")
    if args.evaluation_id:
        stmt = stmt.where(Evaluation.id == args.evaluation_id)
    if args.candidate:
        stmt = stmt.where(Evaluation.candidate_id == args.candidate)
    stmt = stmt.order_by(Evaluation.finalized_at, Evaluation.id)
    return list((await db.execute(scoped(stmt, Evaluation, scope))).scalars().all())


async def main(args) -> int:
    scope = TenantScope.of(args.tenant)
    failures = 0
    async with SessionLocal() as db:
        rows = await _targets(db, args, scope)
        if not rows:
            print("no finalized evaluations matched")
            return 1

        for evaluation in rows:
            try:
                result = await replay_evaluation(db, evaluation, scope)
            except ReplayUnavailable as exc:
                failures += 1
                print(f"  {evaluation.id}  UNAVAILABLE  {exc}")
                continue

            mark = "MATCH   " if result.status is ReplayStatus.MATCH else "MISMATCH"
            print(
                f"  {evaluation.id}  {mark}  competence "
                f"{evaluation.competence_score:>3}  "
                f"{result.claims_replayed} claim(s), "
                f"{result.answers_replayed} answer(s), "
                f"{result.llm_calls} model call(s)"
            )
            for difference in result.differences:
                failures += 1
                print(
                    f"      {difference.field}: stored {difference.stored} "
                    f"-> replayed {difference.replayed}"
                )
            for moved in result.provenance_drift:
                print(
                    f"      drift  {moved.field}: {moved.stored} -> {moved.replayed}"
                )
    return 1 if failures else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Replay finalized evaluations.")
    parser.add_argument("evaluation_id", nargs="?", help="one evaluation (ev_...)")
    parser.add_argument("--candidate", help="every evaluation for one candidate")
    parser.add_argument("--all", action="store_true", help="every finalized evaluation")
    parser.add_argument(
        "--tenant", default=DEVELOPMENT_TENANT_ID, help="tenant id (default t_dev)"
    )
    parsed = parser.parse_args()
    if not (parsed.evaluation_id or parsed.candidate or parsed.all):
        parser.error("give an evaluation id, --candidate, or --all")
    raise SystemExit(asyncio.run(main(parsed)))
