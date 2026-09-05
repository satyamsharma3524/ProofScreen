"""
Phase 5 curation. NOT VALIDATOR CODE, and nothing here is imported by `api/`.

Turns `premise_candidates.csv` (surface matches) into `taxonomy_examples.csv`
(labelled examples), by applying the hand labels recorded below and then adding
constructed examples for the sub-types real data does not supply enough of.

THREE PROVENANCE CLASSES, AND THE DISTINCTION IS LOAD-BEARING:

  observed     the pair AND a human verdict exist (the Phase 3 100-item review)
  mined        the pair is real generated text; the label is mine, unverified
  constructed  the CLAIM is real, the QUESTION is written by me to instantiate
               a sub-type

Only `observed` may be used to compute precision or recall. `mined` supports
frequency claims. `constructed` supports NOTHING quantitative — it exists so
the written rules have edges to be tested against, and a κ measured over
constructed items measures the clarity of the rules, not the prevalence of the
defect. Every table in the report states which class it rests on.

Constructed questions are written over REAL claims on purpose. A fully invented
pair lets me choose both sides of the test, which is how a taxonomy ends up
describing its author's imagination.
"""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
CANDIDATES = HERE / "premise_candidates.csv"
OUT = HERE / "taxonomy_examples.csv"

FALLBACK_MARK = "Walk me through the steps and the systems you used"

# ---------------------------------------------------------------------------
# Hand labels for the 79 distinct `invented_tool` candidates.
#
# Keyed by the first 52 characters of the question plus the matched term, so a
# label cannot silently attach to a different item if the miner changes.
#
# Codes:
#   G   generally_entailed        the claimed work at its stated scale cannot
#                                 be done without an instrument of this KIND
#   S   specifically_unentailed   a vendor, a mechanism inside a category, an
#                                 instrument bolted to an OUTCOME, or a
#                                 category the work does not require
#   C   contested                 the rule does not decide it, or the rule and
#                                 the human reviewer disagreed. Kept and
#                                 counted; excluded from the clean sets
#   X   not a premise             solicited ("which systems did you use"), or
#                                 the instrument is in the claim
#   A   mis-typed by the miner    belongs to another sub-type
# ---------------------------------------------------------------------------

TOOL_LABELS: dict[str, str] = {
    # --- solicitation: the FALLBACK question template asks WHICH systems -----
    # `On "<claim>" — How did this work day to day? Walk me through the steps
    # and the systems you used.` This asserts no instrument at all; it asks the
    # candidate to name one. It is also never validated (CLAUDE.md), so it
    # could not be rejected even if it were wrong.
    "fallback": "X",
    # --- attendance / roster / workforce, at a stated headcount --------------
    "the system to track daily attendance|system": "G",
    "the system for daily attendance tracking|system": "G",
    "the system to adjust rosters for unexpected absences|system": "G",
    "the system to adjust rosters during unexpected absences|system": "G",
    "daily in the workforce planning system|system": "G",
    "the workforce planning system each morning|system": "G",
    "your system each morning to monitor shrinkage|system": "G",
    "the system to manage the nesting batches|system": "G",
    "the system during calibration sessions|system": "G",
    "in the system to maintain occupancy above 85|system": "G",
    "the call handling system daily to maintain occupancy|system": "G",
    # --- ticketing / support -------------------------------------------------
    "the ticketing system to reduce response time|ticketing system": "G",
    "the ticketing system to test and tweak macros|ticketing system": "G",
    "the system to prioritize P1 issues|system": "G",
    "the chat support system|system": "G",
    "to manage ticket handling in your system|system": "G",
    "the support dashboard to track resolution times|dashboard": "G",
    "the system to track resolution times|system": "G",
    "your tracking system|system": "G",
    # --- CRM, on quota / pipeline / deal claims ------------------------------
    "your CRM each day to manage your pipeline|crm": "G",
    "your CRM system daily to manage your|crm": "G",
    "the CRM system to track interactions daily|crm": "G",
    "the CRM to track interactions and schedule follow-ups|crm": "G",
    "the CRM to manage your leads|crm": "G",
    "the CRM to manage the sales funnel|crm": "G",
    "the CRM each day to manage your pipeline|crm": "G",
    "your CRM daily to manage your pipeline|crm": "G",
    "the CRM system to track and manage your deals daily|crm": "G",
    "the CRM system daily to track and convert leads|crm": "G",
    "the CRM to track sales progress|crm": "G",
    "the pricing approval system daily|system": "G",
    "the system for revenue forecast reviews|system": "G",
    # --- back office / regulated ---------------------------------------------
    "the systems for processing claims|systems": "G",
    "the system during a KYC audit|system": "G",
    "the system when processing a mutual fund transaction|system": "G",
    "the system when preparing for the risk committee|system": "G",
    # --- HR ------------------------------------------------------------------
    "the payroll system each month|system": "G",
    "the payroll system each day|system": "G",
    "the interview system to streamline the process|system": "G",
    "the recruitment software daily|software": "G",
    # --- delivery / product ---------------------------------------------------
    "the system to track deliverables|system": "G",
    "the system to prepare for each quarterly review|system": "G",
    "the analytics tool during the A/B tests|analytics tool": "G",
    "the project management tool to deprioritize the epics|project management tool": "G",
    "the data analytics tool|analytics tool": "G",
    "the project management tools during the transition|project management tools": "G",
    "the system to prepare the CX report|system": "G",
    "the reporting system to prepare the CX metrics|system": "G",
    "the system to monitor the model|system": "G",
    "the system to monitor the model's performance|system": "G",

    # --- specifically unentailed ---------------------------------------------
    # (a) a mechanism INSIDE a category, not the category
    "each day to monitor and adjust the macros|macros": "S",
    "each morning to review and adjust the macros|macros": "S",
    "after implementing the macros|macros": "S",
    # (b) a category the work does not require
    "the transcription tool during the interviews|transcription tool": "S",
    "the performance tracking software daily|software": "S",
    "the performance tracking software to adjust daily rosters|software": "S",
    # (c) an instrument bolted to an OUTCOME noun rather than an activity
    "the system to manage attrition|system": "S",
    "the system to analyze the top ten issues|system": "S",
    "the CRM to provide feedback on each rep's progress|crm": "S",

    # --- contested: the rule and the human disagree, or the rule is silent ---
    "the analytics dashboard each Monday|dashboard": "C",
    "the product analytics dashboard each week|dashboard": "C",
    "the product analytics dashboard each Monday|dashboard": "C",
    "the analytics tool each morning|analytics tool": "C",
    "the analytics tool during the onboarding rebuild|analytics tool": "C",
    "the sourcing system to reduce attrition|system": "C",
    "in the system during the re-engineering|system": "C",
    "the CRM to track engagement levels|crm": "C",

    # --- mis-typed by the miner ----------------------------------------------
    "the queue report to identify performance issues|queue": "A:invented_artefact",
    "the tools for building the ETL pipelines|tools": "X",
}

LEVEL = {"G": "generally_entailed", "S": "specifically_unentailed", "C": "contested"}


def _key(question: str, term: str) -> str:
    return f"{question}|{term}"


def _match_tool_label(question: str, term: str) -> str | None:
    if FALLBACK_MARK in question:
        return "X"
    for pattern, code in TOOL_LABELS.items():
        if pattern == "fallback":
            continue
        phrase, want_term = pattern.rsplit("|", 1)
        if want_term == term and phrase.lower() in question.lower():
            return code
    return None


def example_id(sub_type: str, question: str, term: str) -> str:
    digest = hashlib.sha256(f"{sub_type}|{question}|{term}".encode()).hexdigest()[:6]
    return f"p5_{digest}"


def load_observed() -> dict[str, tuple[str, str]]:
    """(question -> (human_verdict, note)) from the Phase 3 100-item review."""
    path = HERE.parents[1] / "studies/phase4/unsupported_premise_dataset.csv"
    out: dict[str, tuple[str, str]] = {}
    for row in csv.DictReader(path.open()):
        out[row["question"].strip()] = (row["human_verdict"], row["human_note"])
    return out


# ---------------------------------------------------------------------------
# Hand labels for the non-tool sub-types.
#
# The miner is a surface matcher and over-fires badly on two of them, which is
# itself the study's central measurement:
#
#   invented_outcome  75 candidates -> 9 survive. The rest are nominalisations
#                     the question legitimately introduces ("the success", "the
#                     impact") or the CLAIM'S OWN MOVEMENT in other words —
#                     "the latency reduction" against "Cut p95 latency from
#                     900ms to 180ms".
#   invented_event    33 candidates -> 4 survive. Twenty-nine are indefinite
#                     solicitations ("Describe A specific incident when…"),
#                     which is exactly what the INCIDENT probe level is for.
#
# Listed positively, by a question substring, so adding a candidate cannot
# silently promote it.
# ---------------------------------------------------------------------------

MINED_POSITIVE: dict[str, list[str]] = {
    "invented_outcome": [
        "improvement in confidence and performance of new hires",
        "improvement in new hires' confidence",
        "measure the improvement in conversion rates",
        "capture the jump in conversion rates from 15% to 25%",
        "performance improvement after deploying the APIs",
        "performance improvements after implementing the event pipelines",
        "improvement in user experience after launching a React interface",
        "reduction in abandon rate from 12% to 5%",
        "improvement in closing rates after coaching the reps",
    ],
    "invented_event": [
        "during the high-pressure week",
        "address the technical delays with stakeholders",
        "deciding to redesign the escalation workflow",
        "high-value leads to focus on after the delay",
        "retention strategies did you implement after the layoff",
    ],
    "invented_metric": [
        "impact of addressing the top pain points on user retention",
        "impact on user retention after improving the first-run flow",
        "calculate the 30% reopen rate",
        "measure the improvement in conversion rates",
        "jump in conversion rates from 15% to 25%",
        "increase in conversion rate was due to your coaching",
        "have on your compliance metrics",
        "measure the 70% adoption rate among branch staff",
        "instrumenting activation events have on conversion rates",
        "the callback SLA failed",
        "impact on user retention after addressing the top three pain points",
        "10% drop in reopen rate",
        "change you saw in conversion rates after implementing",
        "reduce attrition by 15%",
    ],
    "invented_artefact": [
        "review the reopen report",
        "combine in your marketing plan",
        "prioritize feedback from the interviews for the PRD",
        "queue report to identify performance issues",
    ],
    "invented_condition": [
        "P1 issue wasn't resolved in 2 hours",
        "P1 issue that took longer than 2 hours",
    ],
}


def distinct_candidates() -> list[dict]:
    seen: set[tuple[str, str]] = set()
    out: list[dict] = []
    for row in csv.DictReader(CANDIDATES.open()):
        key = (row["matched_term"], row["question"])
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def build() -> list[dict]:
    import sys

    sys.path.insert(0, str(HERE))
    import constructed

    observed = load_observed()
    examples: list[dict] = []
    used_questions: set[tuple[str, str]] = set()

    def add(sub_type, tool_level, claim, question, provenance, rationale,
            contested=0):
        key = (sub_type, question)
        if key in used_questions:
            return
        used_questions.add(key)
        verdict, note = observed.get(question.strip(), ("", ""))
        examples.append({
            "example_id": example_id(sub_type, question, tool_level),
            "sub_type": sub_type,
            "tool_level": tool_level,
            "provenance": "observed" if verdict else provenance,
            "human_verdict": verdict,
            "human_note": note,
            "contested": contested,
            "claim": claim,
            "question": question,
            "rationale": rationale,
        })

    # --- mined: invented_tool, hand-coded ---------------------------------
    for row in distinct_candidates():
        if row["sub_type_guess"] != "invented_tool":
            continue
        code = _match_tool_label(row["question"], row["matched_term"])
        if code in ("X", None):
            continue
        if code.startswith("A:"):
            add(code.split(":", 1)[1], "", row["claim"], row["question"],
                "mined", "re-typed from invented_tool by hand")
            continue
        add("invented_tool", LEVEL[code], row["claim"], row["question"],
            "mined", f"instrument: {row['matched_term']}",
            contested=1 if code == "C" else 0)

    # --- mined: the other sub-types, positives only ------------------------
    for row in distinct_candidates():
        sub_type = row["sub_type_guess"]
        if sub_type == "invented_tool":
            continue
        wanted = MINED_POSITIVE.get(sub_type, [])
        if not any(fragment in row["question"] for fragment in wanted):
            continue
        add(sub_type, "", row["claim"], row["question"], "mined",
            f"premise object: {row['matched_term']}")

    # --- constructed --------------------------------------------------------
    for (sub_type, tool_level), block in constructed.BLOCKS.items():
        for claim, question, note in block:
            add(sub_type, tool_level, claim, question, "constructed", note)

    return examples


if __name__ == "__main__":
    from collections import Counter

    rows = build()
    with OUT.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    print(f"{len(rows)} examples -> {OUT.name}\n")
    print(f"{'sub-type':<26}{'total':>7}{'obs':>6}{'mined':>7}{'cons':>6}{'contested':>11}")
    keys = Counter()
    for r in rows:
        keys[(r["sub_type"], r["tool_level"])] += 1
    for key in sorted(keys):
        sub = [r for r in rows if (r["sub_type"], r["tool_level"]) == key]
        label = key[0] + (f" / {key[1]}" if key[1] else "")
        prov = Counter(r["provenance"] for r in sub)
        print(f"{label:<26}{len(sub):>7}{prov['observed']:>6}{prov['mined']:>7}"
              f"{prov['constructed']:>6}{sum(int(r['contested']) for r in sub):>11}")
