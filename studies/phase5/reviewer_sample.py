"""
Builds the blind sample two reviewers label independently.

BALANCED ON PURPOSE. Half the items are things the rules say `none` about —
nominalisations, indefinite solicitations, the claim's own movement in other
words, entailed instruments. Without them a reviewer who labelled *everything*
as a premise defect would score high agreement, and the number would mean
nothing. `disagreement over what is NOT a defect` is most of what went wrong in
Phase 3.

Writes:
  reviewer_sample.csv    the blind items — no sub-type, no verdict
  .reviewer1_key.csv     SEALED. My labels. Do not open before labelling.
"""

from __future__ import annotations

import csv
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXAMPLES = HERE / "taxonomy_examples.csv"
CANDIDATES = HERE / "premise_candidates.csv"
SAMPLE = HERE / "reviewer_sample.csv"
KEY = HERE / ".reviewer1_key.csv"

SEED = 20260905          # fixed, so the sample is reproducible


def main() -> None:
    rng = random.Random(SEED)
    examples = list(csv.DictReader(EXAMPLES.open()))
    positives = {r["question"]: r for r in examples}

    # Negatives: mined candidates the rules label `none`. They are real
    # generated text and they are the hard half.
    seen: set[tuple[str, str]] = set()
    negatives: list[dict] = []
    for row in csv.DictReader(CANDIDATES.open()):
        key = (row["matched_term"], row["question"])
        if key in seen or row["question"] in positives:
            continue
        seen.add(key)
        negatives.append(row)

    real_pos = [r for r in examples if r["provenance"] in ("mined", "observed")]
    made_pos = [r for r in examples if r["provenance"] == "constructed"]

    # Stratify the constructed half across sub-types so no sub-type is unseen.
    by_type: dict[str, list[dict]] = {}
    for row in made_pos:
        by_type.setdefault(row["sub_type"] + "/" + row["tool_level"], []).append(row)
    made_pick: list[dict] = []
    for key in sorted(by_type):
        pool = by_type[key][:]
        rng.shuffle(pool)
        made_pick.extend(pool[:12])

    real_pick = real_pos[:]
    rng.shuffle(real_pick)
    real_pick = real_pick[:60]

    neg_pick = negatives[:]
    rng.shuffle(neg_pick)
    neg_pick = neg_pick[:70]

    items = []
    for row in real_pick + made_pick:
        items.append({
            "claim": row["claim"], "question": row["question"],
            "_truth_sub_type": row["sub_type"],
            "_truth_tool_level": row["tool_level"],
            "_provenance": row["provenance"],
            "_contested": row["contested"],
        })
    for row in neg_pick:
        items.append({
            "claim": row["claim"], "question": row["question"],
            "_truth_sub_type": "none", "_truth_tool_level": "",
            "_provenance": "mined_negative", "_contested": "0",
        })

    rng.shuffle(items)
    for index, item in enumerate(items, 1):
        item["item_id"] = f"i{index:03d}"

    with SAMPLE.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["item_id", "claim", "question", "sub_type", "tool_level", "note"],
        )
        writer.writeheader()
        for item in items:
            writer.writerow({
                "item_id": item["item_id"], "claim": item["claim"],
                "question": item["question"], "sub_type": "", "tool_level": "",
                "note": "",
            })

    with KEY.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["item_id", "sub_type", "tool_level", "provenance", "contested"],
        )
        writer.writeheader()
        for item in items:
            writer.writerow({
                "item_id": item["item_id"],
                "sub_type": item["_truth_sub_type"],
                "tool_level": item["_truth_tool_level"],
                "provenance": item["_provenance"],
                "contested": item["_contested"],
            })

    from collections import Counter

    print(f"{len(items)} blind items -> {SAMPLE.name}")
    print("  reviewer 1 key sealed in", KEY.name)
    print("  composition:", dict(Counter(i["_provenance"] for i in items)))
    print("  positives vs none:",
          dict(Counter("none" if i["_truth_sub_type"] == "none" else "defect"
                       for i in items)))


if __name__ == "__main__":
    main()
