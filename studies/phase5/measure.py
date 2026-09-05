"""
Phase 5 measurement. READ-ONLY against the validator; NOTHING IS MODIFIED.

Three questions, three sections:

  1. OVERLAP        how many examples does the CURRENT validator already
                    reject, and for what reason? A premise rule that fires on
                    a question `answer_leakage` already catches buys nothing
                    and double-counts a defect.
  2. DETERMINISM    how far do the written rules reduce to surface features?
                    Measured as agreement between the hand labels and the
                    miner's mechanical guess on the MINED items only.
  3. CEILINGS       precision and recall bounds, computed ONLY on the 100
                    observed items — the sole set with an independent human
                    verdict. Constructed examples contribute nothing here.

`validate()` is imported and called. It is not changed, and no threshold is
touched: `git diff api/` for this phase is empty.
"""

from __future__ import annotations

import csv
import os
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("OPENAI_API_KEY", "")

from api.engine.question import validate            # noqa: E402
from api.schemas import ProbeLevel                  # noqa: E402

EXAMPLES = HERE / "taxonomy_examples.csv"
CANDIDATES = HERE / "premise_candidates.csv"
OBSERVED = ROOT / "studies/phase4/unsupported_premise_dataset.csv"

# The probe level a sub-type's questions are typically generated at. The
# validator needs one, and it changes which rules apply (rule 3 is not
# evaluated on TRANSFER). Chosen from where the MINED examples of each
# sub-type actually occur, not to produce a convenient answer.
DEFAULT_LEVEL = {
    "invented_tool": ProbeLevel.OPERATIONAL,
    "invented_outcome": ProbeLevel.OUTCOME,
    "invented_metric": ProbeLevel.OUTCOME,
    "invented_event": ProbeLevel.INCIDENT,
    "invented_artefact": ProbeLevel.DECISION,
    "invented_condition": ProbeLevel.INCIDENT,
}


def section(title: str) -> None:
    print(f"\n{'=' * 74}\n{title}\n{'=' * 74}")


def overlap() -> None:
    section("1. OVERLAP WITH THE EXISTING VALIDATOR  (all 364 examples)")
    rows = list(csv.DictReader(EXAMPLES.open()))
    per_type: dict[str, Counter] = {}
    already = Counter()
    for row in rows:
        key = row["sub_type"] + (f"/{row['tool_level']}" if row["tool_level"] else "")
        result = validate(
            row["question"],
            claim_text=row["claim"],
            probe_level=DEFAULT_LEVEL.get(row["sub_type"], ProbeLevel.OPERATIONAL),
        )
        bucket = per_type.setdefault(key, Counter())
        bucket["n"] += 1
        if result.violations:
            bucket["already_rejected"] += 1
            for rule in result.violations:
                already[rule] += 1
        else:
            bucket["would_be_new"] += 1

    # Split by provenance. CONSTRUCTED questions are short and written to
    # isolate one premise, so they anchor to the claim far less than real
    # generated text does — which inflates `no_claim_anchor`. The MINED column
    # is the honest one, and the report quotes it.
    by_prov: dict[str, Counter] = {}
    for row in rows:
        result = validate(
            row["question"], claim_text=row["claim"],
            probe_level=DEFAULT_LEVEL.get(row["sub_type"], ProbeLevel.OPERATIONAL),
        )
        bucket = by_prov.setdefault(row["provenance"], Counter())
        bucket["n"] += 1
        bucket["already" if result.violations else "new"] += 1
    print("  by provenance — the mined column is the one that generalises:")
    for prov in ("observed", "mined", "constructed"):
        c = by_prov.get(prov)
        if not c:
            continue
        print(f"    {prov:<14}n={c['n']:<5} already rejected {c['already']:<5}"
              f" NEW {c['new']:<5} ({c['new'] / c['n'] * 100:.0f}% new)")
    print()

    print(f"{'sub-type':<42}{'n':>5}{'already':>9}{'NEW':>6}{'new %':>8}")
    total_n = total_new = 0
    for key in sorted(per_type):
        c = per_type[key]
        total_n += c["n"]
        total_new += c["would_be_new"]
        print(f"{key:<42}{c['n']:>5}{c['already_rejected']:>9}"
              f"{c['would_be_new']:>6}{c['would_be_new'] / c['n'] * 100:>7.0f}%")
    print(f"{'TOTAL':<42}{total_n:>5}{total_n - total_new:>9}{total_new:>6}"
          f"{total_new / total_n * 100:>7.0f}%")
    print("\n  which existing rule already catches them:")
    for rule, count in already.most_common():
        print(f"    {rule:<24}{count:>5}")


def determinism() -> None:
    section("2. DETERMINISM  (hand label vs the mechanical guess, MINED only)")
    hand = {}
    for row in csv.DictReader(EXAMPLES.open()):
        if row["provenance"] == "constructed":
            continue
        hand[row["question"]] = (row["sub_type"], row["tool_level"])

    seen: set[tuple[str, str]] = set()
    agree = disagree = 0
    confusion: Counter = Counter()
    for row in csv.DictReader(CANDIDATES.open()):
        key = (row["matched_term"], row["question"])
        if key in seen:
            continue
        seen.add(key)
        if row["question"] not in hand:
            continue
        want_type, want_level = hand[row["question"]]
        got_type = row["sub_type_guess"]
        if want_type == "invented_tool" and got_type == "invented_tool":
            ok = row["tool_level_guess"] == want_level
            confusion[(want_level or "?", row["tool_level_guess"] or "?")] += 1
        else:
            ok = got_type == want_type
        agree += ok
        disagree += not ok
    total = agree + disagree
    print(f"  items compared      {total}")
    print(f"  machine agrees      {agree}  ({agree / total * 100:.1f}%)")
    print(f"  machine disagrees   {disagree}")
    print("\n  invented_tool second level — hand (rows) vs machine (cols):")
    levels = sorted({k[0] for k in confusion} | {k[1] for k in confusion})
    print("    " + "".join(f"{c[:12]:>15}" for c in [""] + levels))
    for want in levels:
        cells = "".join(f"{confusion.get((want, got), 0):>15}" for got in levels)
        print(f"    {want[:12]:>15}{cells}")


def ceilings() -> None:
    """3. Precision and recall bounds, POPULATION-WEIGHTED.

    The 100-item review is stratified 50 validator-accepts / 50
    validator-rejects. Counting it raw reports recall of 75%, which is an
    artefact of over-sampling the rejects — the population figure is 50.7%,
    and that is the number Phase 3 published. Every cell below is weighted by
    its stratum's share of the 486 judged questions before any ratio is taken.
    """
    section("3. CEILINGS  (100 OBSERVED items, weighted to the population)")
    rows = list(csv.DictReader(OBSERVED.open()))
    accepts = [r for r in rows if r["validator_verdict"] == "accept"]
    rejects = [r for r in rows if r["validator_verdict"] == "reject"]
    w_accept = (486 - 124) / 486 / len(accepts)
    w_reject = 124 / 486 / len(rejects)

    tp = sum(w_reject for r in rejects if r["human_verdict"] == "reject")
    fp = sum(w_reject for r in rejects if r["human_verdict"] == "accept")
    fn = sum(w_accept for r in accepts if r["human_verdict"] == "reject")
    tn = sum(w_accept for r in accepts if r["human_verdict"] == "accept")
    print(f"  weighted confusion: TP {tp:.4f}  FP {fp:.4f}  FN {fn:.4f}  TN {tn:.4f}")
    print(f"  validator precision {tp / (tp + fp) * 100:.1f}%   "
          f"recall {tp / (tp + fn) * 100:.1f}%")

    verbs = ("assum", "invent", "introduc")

    def premise(r):
        return (r["human_verdict"] == "reject"
                and any(v in r["human_note"].lower() for v in verbs))

    missed = [r for r in accepts if premise(r)]
    all_fn = [r for r in accepts if r["human_verdict"] == "reject"]
    print(f"\n  the miss mass: {len(all_fn)} false negatives in the accept stratum,")
    print(f"  of which {len(missed)} are premise rejections "
          f"({len(missed) / len(all_fn) * 100:.0f}%).")
    print("  THIS IS THE BUSINESS CASE: the validator's recall problem is not")
    print("  spread across seven rules that each miss a little. It is one absent rule.")

    def bound(caught: int, label: str) -> None:
        tp2 = tp + caught * w_accept
        print(f"    {label:<46}precision {tp2 / (tp2 + fp) * 100:>5.1f}%   "
              f"recall {tp2 / (tp + fn) * 100:>5.1f}%")

    print(f"\n  CEILINGS — a rule with NO false positives (no rule here achieves this;")
    print(f"  the best, answer_leakage, runs at 86.4%):")
    bound(0, "today")
    bound(len(missed), f"a perfect rule catching all {len(missed)}")

    print("\n  SCOPED CEILINGS, by sub-type of the miss mass (hand-typed from the")
    print("  reviewer's own notes; the nine items are listed in the report):")
    # Typed to match 2.2 of the report. r0012 sits in `invented_metric`, not
    # `invented_outcome`: the reviewer's own note is "invents team-performance
    # METRICS as the outcome", and the metrics are the object presupposed.
    # r0037 is absent because the validator already rejects it, so it is not a
    # miss and cannot be part of a recall gain.
    typed = {
        "invented_tool/specifically_unentailed": ["r0036", "r0093"],
        "invented_tool/contested": ["r0003", "r0052"],
        "invented_event": ["r0018", "r0025"],
        "invented_metric": ["r0012"],
        "invented_outcome": ["r0041"],
        "invented_artefact": ["r0032"],
        "invented_outcome + invented_metric together": ["r0041", "r0012"],
    }
    by_id = {r["row_id"]: r for r in rows}
    for name, ids in typed.items():
        hits = [i for i in ids if by_id[i]["validator_verdict"] == "accept"]
        bound(len(hits), f"{name} only ({len(hits)} of {len(missed)})")

    print("\n  the naive predicate, recomputed mechanically")
    print("  ('the/your <noun phrase>' whose head is absent from the claim):")
    sys.path.insert(0, str(HERE))
    from mine_premises import DEFINITE, _stems, classify

    fires, true_premise, other_reject, accepted = 0, 0, 0, 0
    for row in rows:
        claim_terms = _stems(row["claim"])
        hit = False
        for match in DEFINITE.finditer(row["question"]):
            sub_type, term = classify(match.group(1))
            if sub_type and not (_stems(term) & claim_terms):
                hit = True
                break
        if not hit:
            continue
        fires += 1
        note = row["human_note"].lower()
        if row["human_verdict"] == "reject":
            if any(v in note for v in verbs):
                true_premise += 1
            else:
                other_reject += 1
        else:
            accepted += 1
    print(f"    fires on {fires} of {len(rows)} sample items")
    print(f"    true premise rejects {true_premise} | other reason {other_reject} "
          f"| human ACCEPTED {accepted}")
    print(f"    naive precision {true_premise / fires * 100:.1f}%")


def impact() -> None:
    """4. Reject-rate and regeneration-rate impact, population-weighted.

    The 100-item review is STRATIFIED — 50 validator-accepts and 50
    validator-rejects — so counting it directly would report a 50% reject rate
    for a population whose real rate is 25.5%. Every figure below is weighted
    back to the population before it is quoted.
    """
    section("4. REJECT-RATE AND REGENERATION IMPACT  (population-weighted)")
    rows = list(csv.DictReader(OBSERVED.open()))
    accepts = [r for r in rows if r["validator_verdict"] == "accept"]
    rejects = [r for r in rows if r["validator_verdict"] == "reject"]

    # Phase 3, judged questions: 486, of which 124 rejected.
    pop_reject = 124 / 486
    pop_accept = 1 - pop_reject
    print(f"  population: 486 judged questions, reject rate {pop_reject * 100:.1f}%")
    print(f"  sample strata: {len(accepts)} accepts, {len(rejects)} rejects\n")

    verbs = ("assum", "invent", "introduc")

    def premise(r):
        return (r["human_verdict"] == "reject"
                and any(v in r["human_note"].lower() for v in verbs))

    missed = [r for r in accepts if premise(r)]
    share_of_accepts = len(missed) / len(accepts)
    added = pop_accept * share_of_accepts
    print(f"  A PERFECT rule (catches every premise miss, fires on nothing else)")
    print(f"    {len(missed)}/{len(accepts)} of the accept stratum are premise misses"
          f"  ({share_of_accepts * 100:.0f}%)")
    print(f"    new rejections            +{added * 100:.1f} points of the population")
    print(f"    reject rate {pop_reject * 100:.1f}% -> {(pop_reject + added) * 100:.1f}%"
          f"   (relative +{added / pop_reject * 100:.0f}%)")

    # The mechanical predicate, fired in each stratum and weighted.
    sys.path.insert(0, str(HERE))
    from mine_premises import DEFINITE, _stems, classify

    def fires(r):
        claim_terms = _stems(r["claim"])
        for match in DEFINITE.finditer(r["question"]):
            sub_type, term = classify(match.group(1))
            if sub_type and not (_stems(term) & claim_terms):
                return True
        return False

    fa = sum(fires(r) for r in accepts) / len(accepts)
    fr = sum(fires(r) for r in rejects) / len(rejects)
    new_fires = pop_accept * fa          # firing on an already-rejected question adds nothing
    good = sum(1 for r in accepts if fires(r) and premise(r)) / len(accepts)
    print(f"\n  THE MECHANICAL PREDICATE (definite noun phrase absent from the claim)")
    print(f"    fires on {fa * 100:.0f}% of the accept stratum, "
          f"{fr * 100:.0f}% of the reject stratum")
    print(f"    new rejections            +{new_fires * 100:.1f} points")
    print(f"    of which correct          +{pop_accept * good * 100:.1f} points "
          f"({good / fa * 100:.0f}% precision on NEW rejections)")
    print(f"    reject rate {pop_reject * 100:.1f}% -> "
          f"{(pop_reject + new_fires) * 100:.1f}%"
          f"   (relative +{new_fires / pop_reject * 100:.0f}%)")

    print(f"\n  REGENERATION AND FALLBACK")
    print(f"    Every rejection buys one regeneration; the cap is one, so a")
    print(f"    question failing twice lands on the FALLBACK, which is never")
    print(f"    validated and is thin by design.")
    for name, add in (("perfect rule", added), ("mechanical predicate", new_fires)):
        rate = pop_reject + add
        # Second attempts fail at roughly the first-attempt rate, which is the
        # only estimate the data supports.
        fallback_now = pop_reject * pop_reject
        fallback_then = rate * rate
        print(f"    {name:<22} regenerations {pop_reject * 100:.1f}% -> {rate * 100:.1f}%"
              f"   fallback share {fallback_now * 100:.1f}% -> {fallback_then * 100:.1f}%")


if __name__ == "__main__":
    overlap()
    determinism()
    ceilings()
    impact()
