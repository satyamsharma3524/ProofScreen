"""
Re-run the CURRENT validator over any study dataset and report label-free rates.

    python scripts/revalidate_dataset.py studies/phase4 phase4_question_dataset.csv

WHY IT EXISTS
-------------
Comparing Phase 3's reject rate to Phase 4A's compares two things at once: a
changed validator AND a different population of questions (different seed,
44 interviews against 68, 8 families against 9). A rate that moves tells you
nothing about which one moved it.

So the comparison is run as a 2x2 — each validator over each dataset — and this
is the tool that fills the off-diagonal. Needs no human labels, because a fire
rate is a property of the validator and the data alone.
"""

from __future__ import annotations

import collections
import csv
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DATA = Path(sys.argv[1] if len(sys.argv) > 1 else "studies/phase3")
NAME = sys.argv[2] if len(sys.argv) > 2 else "real_question_dataset.csv"
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{DATA / 'study.sqlite3'}")

from api.engine.question import validate  # noqa: E402
from api.schemas import ProbeLevel  # noqa: E402

rows = list(csv.DictReader((DATA / NAME).open(encoding="utf-8")))
db = sqlite3.connect(DATA / "study.sqlite3")
answers: dict = collections.defaultdict(dict)
for sid, oidx, text in db.execute(
    "select q.session_id, q.order_index, coalesce(r.transcript, r.raw_text) "
    "from questions q join responses r on r.question_id = q.id"
):
    answers[sid][oidx] = text
claims: dict = collections.defaultdict(dict)
for sid, cid, text in db.execute(
    "select distinct s.id, c.id, c.text from sessions s "
    "join claims c on c.candidate_id = s.candidate_id"
):
    claims[sid][cid] = text

by_interview: dict = collections.defaultdict(list)
for r in rows:
    by_interview[r["interview_id"]].append(r)

judged = rejects = 0
fires: collections.Counter = collections.Counter()
for r in rows:
    if r["validator_ran"] != "True":
        continue
    sid, order = r["interview_id"], int(r["order_index"])
    asked = sorted((x for x in by_interview[sid]
                    if x["is_final"] == "True" and int(x["order_index"]) < order),
                   key=lambda x: int(x["order_index"]))
    result = validate(
        r["generated_question"],
        claim_text=r["claim"], probe_level=ProbeLevel(r["probe_level"]),
        claim_type=r["claim_type"] or None, claim_metric=r["claim_metric"] or None,
        job_family=r["family"],
        prior_questions=[x["generated_question"] for x in asked],
        prior_answers=[answers[sid].get(int(x["order_index"]), "") for x in asked],
        other_claims=[t for cid, t in claims[sid].items() if cid != r["claim_id"]],
        # Not persisted anywhere; 14 of 519 rows are TRANSFER. Same gap as
        # phase4_rescore.py, and stated in both places rather than one.
        target_claim_text=None,
    )
    judged += 1
    if not result.accepted:
        rejects += 1
    for v in result.violations:
        fires[v] += 1

print(f"{DATA / NAME}")
print(f"  judged {judged}   rejects {rejects}   reject rate {100*rejects/judged:.1f}%")
for rule in ("answer_leakage", "duplicate_content", "no_claim_anchor",
             "multiple_fact_targets", "scope_drift", "unsupported_metric",
             "hypothetical_misuse"):
    print(f"    {rule:<24}{fires[rule]:>4}   {100*fires[rule]/judged:5.2f}%")
