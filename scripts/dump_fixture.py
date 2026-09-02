"""Regenerate fixtures/sample_graph.json from the seeded database.

    python seed.py --reset && python scripts/dump_fixture.py

The fixture is GENERATED, never hand-written. A hand-written fixture drifts
away from the rubrics the moment anyone tunes a target, and then the dashboard
Dev B built against it disagrees with the live API — the exact failure the
frozen-contract rule exists to prevent.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.config import settings  # noqa: E402

settings.openai_api_key = None

from sqlalchemy import select  # noqa: E402

from api.db import SessionLocal  # noqa: E402
from api.engine.graph import build_candidate_graph  # noqa: E402
from api.models import Candidate  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "fixtures" / "sample_graph.json"

NOTE = (
    "Reference evidence graph — the exact shape of "
    "GET /api/recruiter/candidates/{id}. GENERATED from the real engine by "
    "`python seed.py` and then `scripts/dump_fixture.py`, never hand-written, so "
    "the fixture and the rubrics can never drift apart. tests/test_pipeline.py "
    "asserts every claim_score here is what engine/signals.py + engine/scoring.py "
    "recompute from the stored dimension scores. Served live at GET /api/dev/fixture."
)


async def main(name_like: str = "Priya%") -> None:
    async with SessionLocal() as db:
        candidate = (
            await db.execute(select(Candidate).where(Candidate.name.like(name_like)))
        ).scalars().first()
        if candidate is None:
            raise SystemExit(f"no candidate matching {name_like!r} — run seed.py first")

        graph = await build_candidate_graph(db, candidate.id)
        payload = {"_note": NOTE, **json.loads(graph.model_dump_json())}
        OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        print(f"wrote {OUT.relative_to(Path.cwd())} from {candidate.name}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "Priya%"))
