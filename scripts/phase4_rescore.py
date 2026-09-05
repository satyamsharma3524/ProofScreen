"""
Phase 4A — re-run the CURRENT validator over the Phase 3 study, and score it
against the labels a human already gave.

    python scripts/phase4_rescore.py

WHY THIS NUMBER IS NOT THE ANSWER
---------------------------------
It is IN-SAMPLE. Both Phase 4A validator changes were derived from these exact
disagreements, so an improvement here is optimistically biased by construction —
the changes were fitted to this data by a human reading it, which is the slow
version of overfitting. Reported for DIRECTION ONLY.

The honest number needs new questions and new labels. That is what the second
out-of-distribution run is for, and until it has labels, Phase 4A's success
criteria "precision > 54%" and "recall > 50.7%" are not settled by this file.

THE ESTIMATOR
-------------
The 100 reviewed items were stratified on the OLD verdicts: 50 of 362 accepts
and 50 of 124 rejects. Under the new validator some of those move. So the sample
is NOT a random sample of the new strata, and the Phase 3 estimator does not
apply unchanged.

What still holds is each item's inclusion probability, which is a property of the
OLD stratum and is known exactly. So every sampled item carries a design weight

    w = N_old_stratum / n_sampled_from_it      (362/50 = 7.24, or 124/50 = 2.48)

and the population cells are Horvitz-Thompson sums of those weights under the
NEW verdict. Same data, correct arithmetic, no re-labelling.
"""

from __future__ import annotations

import csv
import json
import os
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "studies" / "phase3"
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{OUT / 'study.sqlite3'}")

from api.engine.question import validate  # noqa: E402
from api.schemas import ProbeLevel  # noqa: E402


def _id(row) -> tuple[str, str, str]:
    """A dataset row's unique address. `attempt_index` alone is NOT unique — it
    restarts at 1 for every planner slot, so it collided on 136 of 519 rows."""
    return (row["interview_id"], row["order_index"], row["attempt_index"])


def load():
    rows = list(csv.DictReader((OUT / "real_question_dataset.csv").open(encoding="utf-8")))
    key = {r["row_id"]: r for r in csv.DictReader((OUT / ".sample_key.csv").open(encoding="utf-8"))}
    rev = {r["row_id"]: r for r in
           csv.DictReader((OUT / "human_review_sample_completed.csv").open(encoding="utf-8"))}
    return rows, key, rev


def build_context(rows):
    """Reconstruct each row's validate() inputs from the dataset and the study DB.

    Priors come from the dataset (the questions actually ASKED, `is_final`, with a
    lower `order_index` in the same interview). Answers and the session's other
    claims come from the DB, which the dataset does not carry.

    Rule 2's redesign needs no extra input: it discounts the claim's own words,
    and `claim_text` is already here.

    ONE KNOWN GAP, stated rather than papered over: `target_claim_text` is not
    persisted anywhere, so TRANSFER rows are re-validated with None — the same
    path the planner takes when it cannot build a spec. 14 of 519 rows are
    TRANSFER. The fidelity check below is what keeps this honest: any verdict
    that changes and is NOT attributable to one of the two Phase 4A edits is
    printed, so a reconstruction error cannot hide inside the result.
    """
    db = sqlite3.connect(OUT / "study.sqlite3")
    answers = defaultdict(dict)
    for sid, oidx, text in db.execute(
        "select q.session_id, q.order_index, coalesce(r.transcript, r.raw_text) from questions q "
        "join responses r on r.question_id = q.id"
    ):
        answers[sid][oidx] = text
    claims = defaultdict(dict)
    for sid, cid, text in db.execute(
        "select distinct s.id, c.id, c.text from sessions s "
        "join claims c on c.candidate_id = s.candidate_id"
    ):
        claims[sid][cid] = text

    by_interview = defaultdict(list)
    for r in rows:
        by_interview[r["interview_id"]].append(r)

    out = []
    for r in rows:
        sid, order = r["interview_id"], int(r["order_index"])
        asked = sorted(
            (x for x in by_interview[sid]
             if x["is_final"] == "True" and int(x["order_index"]) < order),
            key=lambda x: int(x["order_index"]),
        )
        out.append((r, dict(
            claim_text=r["claim"],
            probe_level=ProbeLevel(r["probe_level"]),
            claim_type=r["claim_type"] or None,
            claim_metric=r["claim_metric"] or None,
            job_family=r["family"],
            prior_questions=[x["generated_question"] for x in asked],
            prior_answers=[answers[sid].get(int(x["order_index"]), "") for x in asked],
            other_claims=[t for cid, t in claims[sid].items() if cid != r["claim_id"]],
            target_claim_text=None,
        )))
    return out


def main() -> int:
    rows, key, rev = load()
    contexts = build_context(rows)

    changed, new_verdict = [], {}
    for r, ctx in contexts:
        if r["validator_ran"] != "True":
            continue
        result = validate(r["generated_question"], **ctx)
        was = r["validation_result"]
        now = "accept" if result.accepted else "reject"
        new_verdict[_id(r)] = (now, result.violations)
        if was != now:
            changed.append((r, was, now, r["violations"], "|".join(result.violations)))

    print(f"=== re-validated {len(new_verdict)} rows; {len(changed)} verdicts moved ===")
    unexplained = []
    for r, was, now, old_v, new_v in changed:
        old_rules, new_rules = set(old_v.split("|")) - {""}, set(new_v.split("|")) - {""}
        dropped = old_rules - new_rules
        # Attributable iff the ONLY rules that stopped firing are the two this
        # phase touched. Anything else is a reconstruction error, not a fix.
        if not dropped <= {"answer_leakage", "duplicate_content"} or (new_rules - old_rules):
            unexplained.append((r["interview_id"], r["attempt_index"], old_v, new_v))
    print(f"  attributable to the two Phase 4A edits : {len(changed) - len(unexplained)}")
    print(f"  NOT attributable (reconstruction risk) : {len(unexplained)}")
    for u in unexplained[:10]:
        print(f"    {u}")

    old_pop = Counter(r["validation_result"] for r, _ in contexts if r["validator_ran"] == "True")
    new_pop = Counter(v for v, _ in new_verdict.values())
    print(f"\n  population verdicts  before: {dict(old_pop)}")
    print(f"                        after: {dict(new_pop)}")
    print(f"  M7h reject rate      before: {100*old_pop['reject']/sum(old_pop.values()):.1f}%"
          f"   after: {100*new_pop['reject']/sum(new_pop.values()):.1f}%")

    rule_fires = Counter()
    for _, viol in new_verdict.values():
        for v in viol:
            rule_fires[v] += 1
    print(f"  per-rule fires after: {dict(rule_fires.most_common())}")

    # --- Horvitz-Thompson over the OLD strata ------------------------------
    n_a, n_r = old_pop["accept"], old_pop["reject"]
    sampled = Counter(k["stratum"] for k in key.values())
    weight = {"accept": n_a / sampled["accept"], "reject": n_r / sampled["reject"]}
    cells = defaultdict(float)
    per_rule = defaultdict(lambda: [0.0, 0.0])
    for rid, k in key.items():
        human = rev[rid]["human_verdict"]
        nv, viol = new_verdict[(k["interview_id"], k["order_index"], k["attempt_index"])]
        w = weight[k["stratum"]]
        cells[(nv, human)] += w
        if nv == "reject":
            rule = viol[0] if viol else "?"
            per_rule[rule][1] += w
            if human == "reject":
                per_rule[rule][0] += w
    TP, FP = cells[("reject", "reject")], cells[("reject", "accept")]
    FN, TN = cells[("accept", "reject")], cells[("accept", "accept")]
    prec = TP / (TP + FP) if TP + FP else 0.0
    rec = TP / (TP + FN) if TP + FN else 0.0
    acc = (TP + TN) / (TP + FP + FN + TN)
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0

    print(f"\n=== IN-SAMPLE, weighted (direction only — see the module docstring) ===")
    print(f"  weights: accept {weight['accept']:.2f}  reject {weight['reject']:.2f}")
    print(f"  TP {TP:.0f}  FP {FP:.0f}  FN {FN:.0f}  TN {TN:.0f}")
    print(f"  precision {100*prec:.1f}%  (Phase 3: 54.0%)")
    print(f"  recall    {100*rec:.1f}%  (Phase 3: 50.7%)")
    print(f"  accuracy  {100*acc:.1f}%  (Phase 3: 74.9%)")
    print(f"  F1        {100*f1:.1f}%  (Phase 3: 52.3%)")
    print("\n  per-rule precision (weighted):")
    for rule, (agree, total) in sorted(per_rule.items(), key=lambda kv: -kv[1][1]):
        print(f"    {rule:<24} {100*agree/total:5.1f}%   (weighted n={total:.0f})")

    (OUT / "phase4_insample_rescore.json").write_text(json.dumps({
        "precision": round(100 * prec, 1), "recall": round(100 * rec, 1),
        "accuracy": round(100 * acc, 1), "f1": round(100 * f1, 1),
        "reject_rate_before": round(100*old_pop['reject']/sum(old_pop.values()), 1),
        "reject_rate_after": round(100*new_pop['reject']/sum(new_pop.values()), 1),
        "verdicts_moved": len(changed), "unexplained": len(unexplained),
        "per_rule_precision": {k: round(100*v[0]/v[1], 1) for k, v in per_rule.items()},
        "rule_fires_after": dict(rule_fires),
        "caveat": "IN-SAMPLE. Changes were derived from these disagreements. Direction only.",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
