"""
Agreement between Reviewer 1 (me, sealed key) and Reviewer M (the model).

Three numbers, and they answer different questions:

  binary κ      defect vs none. "Is there an unsupported premise here at all?"
  six-way κ     which sub-type. "Is the taxonomy usable?"
  tool-level κ  generally_entailed vs specifically_unentailed, on the items
                where either reviewer saw an instrument. This is D12's
                entailment hypothesis, tested for the first time.

Cohen's κ, same implementation as `scripts/interview_study.py` uses, so the
number is comparable with Phase 3's.
"""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
SUBTYPES = ["invented_tool", "invented_outcome", "invented_metric",
            "invented_event", "invented_artefact", "invented_condition", "none"]


def kappa(a: list[str], b: list[str]) -> float:
    n = len(a)
    if not n:
        return float("nan")
    observed = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    expected = sum(ca[k] / n * cb[k] / n for k in set(ca) | set(cb))
    return (observed - expected) / (1 - expected) if expected < 1 else 1.0


def load() -> list[dict]:
    key = {r["item_id"]: r for r in csv.DictReader((HERE / ".reviewer1_key.csv").open())}
    model = {r["item_id"]: r
             for r in csv.DictReader((HERE / "reviewer_model_labels.csv").open())}
    rows = []
    for item_id, k in sorted(key.items()):
        m = model.get(item_id)
        if not m or m["sub_type"] == "ERROR":
            continue
        got = m["sub_type"] if m["sub_type"] in SUBTYPES else "none"
        rows.append({
            "item_id": item_id,
            "r1": k["sub_type"], "r1_level": k["tool_level"],
            "rm": got, "rm_level": m["tool_level"],
            "provenance": k["provenance"], "contested": k["contested"],
            "note": m["note"],
        })
    return rows


def main() -> None:
    rows = load()
    n = len(rows)
    print(f"items scored: {n}\n")

    # --- binary -------------------------------------------------------------
    b1 = ["defect" if r["r1"] != "none" else "none" for r in rows]
    bm = ["defect" if r["rm"] != "none" else "none" for r in rows]
    agree = sum(x == y for x, y in zip(b1, bm))
    print("1. IS THERE AN UNSUPPORTED PREMISE AT ALL?")
    print(f"   raw agreement {agree}/{n} = {agree / n * 100:.1f}%")
    print(f"   Cohen's kappa {kappa(b1, bm):.3f}")
    tp = sum(1 for x, y in zip(b1, bm) if x == y == "defect")
    fn = sum(1 for x, y in zip(b1, bm) if x == "defect" and y == "none")
    fp = sum(1 for x, y in zip(b1, bm) if x == "none" and y == "defect")
    tn = sum(1 for x, y in zip(b1, bm) if x == y == "none")
    print(f"   both defect {tp} | both none {tn} | R1 only {fn} | RM only {fp}")

    # --- six-way ------------------------------------------------------------
    s1 = [r["r1"] for r in rows]
    sm = [r["rm"] for r in rows]
    agree6 = sum(x == y for x, y in zip(s1, sm))
    print("\n2. WHICH SUB-TYPE?")
    print(f"   raw agreement {agree6}/{n} = {agree6 / n * 100:.1f}%")
    print(f"   Cohen's kappa {kappa(s1, sm):.3f}")

    # per sub-type recall, from Reviewer 1's perspective
    print("\n   per sub-type — of R1's items, how many did RM place identically:")
    for st in SUBTYPES:
        mine = [r for r in rows if r["r1"] == st]
        if not mine:
            continue
        same = sum(1 for r in mine if r["rm"] == st)
        conf = Counter(r["rm"] for r in mine if r["rm"] != st)
        drift = ", ".join(f"{k}:{v}" for k, v in conf.most_common(3))
        print(f"     {st:<22}{same:>3}/{len(mine):<4}"
              f"{same / len(mine) * 100:>6.0f}%   {drift}")

    # --- tool second level ---------------------------------------------------
    tool = [r for r in rows
            if r["r1"] == "invented_tool" or r["r1_level"]
            or r["rm"] == "invented_tool"]
    def level(r, who):
        raw = r[f"{who}_level"]
        if raw in ("generally_entailed", "specifically_unentailed"):
            return raw
        # A reviewer who labelled the item `none` and named no level saw an
        # entailed instrument, which IS the generally_entailed verdict.
        return "generally_entailed" if r[who] == "none" else "specifically_unentailed"
    l1 = [level(r, "r1") for r in tool]
    lm = [level(r, "rm") for r in tool]
    agree_t = sum(x == y for x, y in zip(l1, lm))
    print("\n3. THE ENTAILMENT SPLIT  (invented_tool second level)")
    print(f"   items {len(tool)}   raw agreement {agree_t}/{len(tool)} = "
          f"{agree_t / len(tool) * 100:.1f}%")
    print(f"   Cohen's kappa {kappa(l1, lm):.3f}")
    print("   R1 (rows) vs RM (cols):")
    cells = Counter(zip(l1, lm))
    labels = ["generally_entailed", "specifically_unentailed"]
    print("      " + "".join(f"{c[:22]:>25}" for c in [""] + labels))
    for a in labels:
        print(f"      {a[:22]:>22}" + "".join(f"{cells.get((a, b), 0):>25}" for b in labels))

    # --- where the rules failed ---------------------------------------------
    undecided = [r for r in rows if r["note"].upper().startswith("UNDECIDED")]
    print(f"\n4. ITEMS THE RULES DID NOT DECIDE (reviewer M said so): {len(undecided)}")
    for r in undecided[:12]:
        print(f"   {r['item_id']} R1={r['r1']:<20} RM={r['rm']:<20} {r['note'][:80]}")

    # --- by provenance --------------------------------------------------------
    print("\n5. AGREEMENT BY PROVENANCE  (does real text behave like written text?)")
    for prov in ("observed", "mined", "mined_negative", "constructed"):
        sub = [r for r in rows if r["provenance"] == prov]
        if not sub:
            continue
        a6 = sum(1 for r in sub if r["r1"] == r["rm"])
        ab = sum(1 for r in sub
                 if (r["r1"] != "none") == (r["rm"] != "none"))
        print(f"   {prov:<16}n={len(sub):<4} binary {ab / len(sub) * 100:>5.1f}%"
              f"   six-way {a6 / len(sub) * 100:>5.1f}%")

    # --- contested items -------------------------------------------------------
    cont = [r for r in rows if r["contested"] == "1"]
    if cont:
        same = sum(1 for r in cont if r["r1"] == r["rm"])
        print(f"\n6. THE ITEMS I MARKED CONTESTED: {len(cont)}, "
              f"reviewer M agreed on {same}")


if __name__ == "__main__":
    main()
