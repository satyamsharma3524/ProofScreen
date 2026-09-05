"""
Reviewer M — a model applying the written rules, one item at a time.

WHAT THIS IS AND IS NOT

It is **not** the human κ that Phase 4B's D13 still needs, and it is not a
substitute for one. `PHASE_2_EXECUTION_PLAN.md` §Deferred rejected LLM-as-judge
for question quality outright, and that rejection stands: no product metric in
this repository is a model's opinion.

What this measures is narrower and is a legitimate research question:

> **Is `decision_rules.md` self-sufficient?** Given the rules and nothing else —
> no author's intent, no memory of the labels, no discussion — does a competent
> reader reach the same verdicts?

A rule set that a careful reader cannot apply is not deterministic enough to
encode, whoever the reader is. Disagreement here is therefore informative in
one direction only: it can show the rules are UNDER-SPECIFIED. It cannot show
they are correct.

Independent by construction: one call per item, temperature 0, no item sees
another, and the model is never told the sub-type distribution or that the
sample is balanced.

    python studies/phase5/reviewer_model.py            # dry run, prints cost
    python studies/phase5/reviewer_model.py --run
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

RULES = (HERE / "decision_rules.md").read_text(encoding="utf-8")
SAMPLE = HERE / "reviewer_sample.csv"
OUT = HERE / "reviewer_model_labels.csv"

MODEL = "gpt-4o"
# Published rates, USD per 1M tokens, for the cost line in the report.
RATE_IN, RATE_OUT = 2.50, 10.00

SYSTEM = (
    "You are labelling interview questions against a written specification. "
    "Apply the specification exactly as written. Where it does not decide an "
    "item, say so in the note rather than guessing a rule that is not there. "
    "Return only JSON."
)

TEMPLATE = """{rules}

---

Apply the procedure above to ONE item.

CLAIM:    {claim}
QUESTION: {question}

Return JSON with exactly these keys:
  "sub_type":   one of invented_tool, invented_outcome, invented_metric,
                invented_event, invented_artefact, invented_condition, none
  "tool_level": generally_entailed or specifically_unentailed when sub_type is
                invented_tool or when you considered an instrument; else ""
  "note":       one short line. If the specification did not decide this item,
                begin the note with UNDECIDED.
"""


async def label_one(client, row: dict) -> dict:
    prompt = TEMPLATE.format(
        rules=RULES, claim=row["claim"], question=row["question"]
    )
    response = await client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    usage = response.usage
    try:
        data = json.loads(response.choices[0].message.content or "{}")
    except json.JSONDecodeError:
        data = {}
    return {
        "item_id": row["item_id"],
        "sub_type": str(data.get("sub_type", "") or "").strip(),
        "tool_level": str(data.get("tool_level", "") or "").strip(),
        "note": str(data.get("note", "") or "").strip()[:200],
        "in_tokens": usage.prompt_tokens,
        "out_tokens": usage.completion_tokens,
    }


async def run(rows: list[dict]) -> None:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=60)
    results: list[dict] = []
    semaphore = asyncio.Semaphore(6)

    async def worker(row):
        async with semaphore:
            for attempt in (1, 2):
                try:
                    return await label_one(client, row)
                except Exception as exc:                  # noqa: BLE001
                    if attempt == 2:
                        print(f"  {row['item_id']} failed: {exc}")
                        return {"item_id": row["item_id"], "sub_type": "ERROR",
                                "tool_level": "", "note": str(exc)[:120],
                                "in_tokens": 0, "out_tokens": 0}
                    await asyncio.sleep(2)

    for index in range(0, len(rows), 24):
        chunk = rows[index : index + 24]
        results.extend(await asyncio.gather(*(worker(r) for r in chunk)))
        print(f"  {len(results)}/{len(rows)}")

    results.sort(key=lambda r: r["item_id"])
    with OUT.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(results[0]))
        writer.writeheader()
        writer.writerows(results)

    tin = sum(r["in_tokens"] for r in results)
    tout = sum(r["out_tokens"] for r in results)
    cost = tin / 1e6 * RATE_IN + tout / 1e6 * RATE_OUT
    print(f"\n{len(results)} labelled -> {OUT.name}")
    print(f"tokens in {tin:,}  out {tout:,}   cost ${cost:.2f}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true", help="actually call the model")
    args = parser.parse_args()

    rows = list(csv.DictReader(SAMPLE.open()))
    rules_tokens = len(RULES) // 4
    est_in = len(rows) * (rules_tokens + 120)
    est = est_in / 1e6 * RATE_IN + len(rows) * 50 / 1e6 * RATE_OUT
    print(f"{len(rows)} items, ~{rules_tokens} tokens of rules each")
    print(f"estimated cost ${est:.2f} (before prompt caching)")
    if not args.run:
        print("dry run — pass --run to call the model")
        raise SystemExit(0)
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is not set")
    asyncio.run(run(rows))
