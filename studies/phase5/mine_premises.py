"""
Phase 5 research instrument. NOT VALIDATOR CODE.

Nothing here is imported by `api/`, nothing here is a rule, and nothing here
decides anything about a live interview. It reads the two published question
datasets and extracts the noun phrases a question refers to as though they
exist, so the taxonomy in `unsupported_premise_research.md` can be built from
text a model actually generated rather than from text I invented.

    python studies/phase5/mine_premises.py

Writes `studies/phase5/premise_candidates.csv`.

WHY MINE RATHER THAN CONSTRUCT. Phase 5 asks for 50 examples per sub-type. The
labelled review contains 15 premise rejections in total, so 50 each has to come
from somewhere. Inventing 300 examples would produce a taxonomy that fits my
imagination — and a written rule tested only against examples written by its
own author is a tautology with a κ attached. 839 real generated questions exist
across Phase 3 and Phase 4A. Mining them costs nothing, keeps the text honest,
and means the sub-type frequencies mean something.

WHAT THIS IS NOT. The extractor below is a crude surface matcher, and its
output is CANDIDATES, not labels. Every published example was read and
classified by hand afterwards; the script's own guess is kept in the CSV
alongside so the two can be compared, which is how §7's determinism ceiling is
computed.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCES = [
    ("P3", ROOT / "studies/phase3/real_question_dataset.csv"),
    ("P4", ROOT / "studies/phase4/phase4_question_dataset.csv"),
]
OUT = Path(__file__).resolve().parent / "premise_candidates.csv"

# ---------------------------------------------------------------------------
# the six sub-type lexicons
#
# Head nouns only. Deliberately NOT exhaustive and deliberately NOT tuned: the
# point is to surface candidates for a human to sort, and a lexicon tuned until
# it agreed with my labels would be the fitting this phase exists to avoid.
# ---------------------------------------------------------------------------

TOOL_CATEGORY = {
    "crm", "system", "systems", "tool", "tools", "software", "platform",
    "dashboard", "dashboards", "tracker", "portal", "spreadsheet", "database",
    "ticketing system", "helpdesk", "help desk", "queue", "console",
    "recruiting software", "ats", "erp", "cms", "ide", "repository",
    "project management tools", "project management tool", "analytics tool",
    "reporting tool", "bi tool", "monitoring tool", "transcription tool",
}
TOOL_BRAND = {
    "zendesk", "salesforce", "jira", "excel", "genesys", "tableau", "figma",
    "slack", "confluence", "hubspot", "freshdesk", "servicenow", "workday",
    "greenhouse", "lever", "notion", "asana", "trello", "looker", "power bi",
    "powerbi", "amplitude", "mixpanel", "segment", "datadog", "sentry",
    "github", "gitlab", "jenkins", "sql", "python", "avaya", "nice", "verint",
    "kustomer", "intercom", "zoho", "sap", "oracle", "tally", "finacle",
}
TOOL_MECHANISM = {
    "macros", "macro", "triggers", "trigger", "saved views", "filters",
    "tags", "canned responses", "templates", "template", "scripts", "script",
    "automations", "automation", "workflows rules", "views", "queries",
    "alerts", "webhooks", "integrations", "plugins", "add-ons",
}
OUTCOME = {
    "improvement", "increase", "jump", "lift", "reduction", "drop", "gain",
    "growth", "uplift", "decline", "turnaround", "success", "win", "result",
    "results", "impact", "savings", "boost", "rise", "fall", "recovery",
    "improvements", "gains", "wins",
}
METRIC = {
    "csat", "nps", "aht", "frt", "sla", "conversion rate", "churn rate",
    "attrition rate", "reopen rate", "occupancy", "shrinkage", "utilisation",
    "utilization", "throughput", "activation rate", "retention rate",
    "engagement score", "quality score", "performance metrics", "kpi", "kpis",
    "metrics", "score", "scores", "ratings", "satisfaction score",
    "resolution rate", "close rate", "win rate", "fill rate", "error rate",
    "defect rate", "productivity", "efficiency score",
}
EVENT = {
    "incident", "outage", "escalation", "delay", "delays", "breach",
    "failure", "setback", "crisis", "migration", "launch", "rollout",
    "transition", "audit", "escalations", "spike", "backlog", "surge",
    "attrition wave", "peak season", "high-pressure week", "downtime",
    "rework", "regression", "churn event", "complaint",
}
ARTEFACT = {
    "plan", "report", "document", "deck", "prd", "sop", "playbook",
    "runbook", "roadmap", "charter", "spec", "specification", "policy",
    "checklist", "matrix", "framework", "presentation", "dashboard report",
    "mis", "scorecard", "tracker sheet", "business case", "proposal",
    "marketing plan", "training plan", "hiring plan", "test plan",
}
CONDITION = {
    "threshold", "limit", "cap", "budget", "deadline", "sla target",
    "target", "quota", "benchmark", "cutoff", "cut-off", "tolerance",
    "ceiling", "floor", "window", "turnaround time",
}

SUBTYPES = [
    ("invented_tool", TOOL_CATEGORY | TOOL_BRAND | TOOL_MECHANISM),
    ("invented_metric", METRIC),
    ("invented_outcome", OUTCOME),
    ("invented_event", EVENT),
    ("invented_artefact", ARTEFACT),
    ("invented_condition", CONDITION),
]

# Two sub-types are not head nouns behind an article, so a lexicon alone cannot
# see them. Added after a first pass returned 3 metrics and 0 conditions from
# 839 questions — a number that would have been a finding about my regex rather
# than about the data.
#
#   invented_metric     a named measure appearing in the question and not in
#                       the claim, with or without an article
#   invented_condition  a threshold: a comparator plus a quantity, or a
#                       bare quantity with a time or percentage unit
METRIC_WORD = re.compile(
    r"\b(csat|nps|aht|frt|sla|conversion rate|conversion rates|churn|"
    r"attrition|retention|activation|occupancy|shrinkage|utilisation|"
    r"utilization|throughput|reopen rate|adoption rate|response time|"
    r"handle time|resolution time|fill rate|win rate|close rate|error rate|"
    r"defect rate|first response|time to offer|time to hire|quality score|"
    r"engagement score|satisfaction score)\b",
    re.IGNORECASE,
)
THRESHOLD = re.compile(
    r"\b(?:within|under|over|below|above|less than|more than|at least|"
    r"no more than|longer than|shorter than|exceeding)\s+\d+(?:\.\d+)?\s*"
    r"(?:%|percent|hours?|minutes?|days?|weeks?|months?|seconds?)?"
    r"|\b\d+(?:\.\d+)?\s*(?:hours?|minutes?|days?|weeks?|seconds?)\b",
    re.IGNORECASE,
)

# "the X", "your X", "their X" — DEFINITE reference. `a`/`any`/`some` are
# solicitations and are collected separately, because the article is the whole
# of the invented_event boundary (D12) and a miner that dropped indefinites
# could not show that.
DEFINITE = re.compile(
    r"\b(?:the|your|their|its|his|her)\s+((?:[a-z][\w\-]*\s+){0,3}[a-z][\w\-]*)",
    re.IGNORECASE,
)
INDEFINITE = re.compile(
    r"\b(?:a|an|any|some)\s+((?:[a-z][\w\-]*\s+){0,3}[a-z][\w\-]*)", re.IGNORECASE
)
WORD = re.compile(r"[a-z][a-z0-9\-]*")
NUMERAL = re.compile(r"\d+(?:\.\d+)?%?")


def _stems(text: str) -> set[str]:
    out: set[str] = set()
    for w in WORD.findall((text or "").lower()):
        out.add(w)
        for suffix in ("s", "es", "ed", "ing"):
            if w.endswith(suffix) and len(w) > len(suffix) + 2:
                out.add(w[: -len(suffix)])
    return out


def _head_terms(phrase: str) -> list[str]:
    """Longest-first n-grams from a captured phrase, so 'conversion rate' wins
    over 'rate'."""
    words = [w for w in WORD.findall(phrase.lower()) if w]
    grams: list[str] = []
    for size in (3, 2, 1):
        for i in range(len(words) - size + 1):
            grams.append(" ".join(words[i : i + size]))
    return grams


def classify(phrase: str) -> tuple[str, str]:
    """(sub_type, matched_term) or ('', '')."""
    for term in _head_terms(phrase):
        for name, lexicon in SUBTYPES:
            if term in lexicon:
                return name, term
    return "", ""


def tool_second_level(term: str, claim: str) -> str:
    """The generally_entailed / specifically_unentailed split, MECHANICALLY.

    This is the deterministic approximation of D12's entailment test, and its
    disagreement with the hand labels is exactly what §7 reports. It is not a
    proposal to ship.
    """
    if term in TOOL_BRAND:
        return "specifically_unentailed"      # a vendor is one choice of many
    if term in TOOL_MECHANISM:
        return "specifically_unentailed"      # a mechanism inside a category
    if term in TOOL_CATEGORY:
        # A category instrument attached to an OUTCOME noun rather than to a
        # performed activity. "the system to manage attrition" vs "the system
        # for attendance tracking".
        claim_terms = _stems(claim)
        if claim_terms & (OUTCOME | METRIC) and not (claim_terms & {
            "managed", "manage", "ran", "run", "handled", "handle", "owned",
            "own", "led", "lead", "coordinated", "tracked", "track",
            "processed", "process", "maintained", "supported",
        }):
            return "specifically_unentailed"
        return "generally_entailed"
    return "unclassified"


def rows():
    for source, path in SOURCES:
        if not path.exists():                                # pragma: no cover
            continue
        for row in csv.DictReader(path.open()):
            question = (row.get("generated_question") or "").strip()
            claim = (row.get("claim") or "").strip()
            if not question or not claim:
                continue
            claim_terms = _stems(claim)
            seen: set[str] = set()

            base = {
                "source": source,
                "interview_id": row.get("interview_id", ""),
                "family": row.get("family", ""),
                "probe_level": row.get("probe_level", ""),
                "claim": claim,
                "question": question,
                "question_numerals": " ".join(
                    sorted(set(NUMERAL.findall(question)))
                ),
                "validator_verdict": row.get("validation_result", ""),
                "validator_rules": row.get("violations", ""),
            }

            # --- pattern sub-types, which no article-lexicon can reach ------
            for match in METRIC_WORD.finditer(question):
                term = match.group(1).lower()
                if term in seen or _stems(term) & claim_terms:
                    continue
                if METRIC_WORD.search(claim or ""):
                    # The claim names SOME measure; whether this is the same
                    # one is a judgement, so it is surfaced, not filtered.
                    pass
                seen.add(term)
                yield {
                    **base, "phrase": match.group(0), "matched_term": term,
                    "sub_type_guess": "invented_metric",
                    "definite": 1 if re.search(
                        r"\b(the|your|their)\s+" + re.escape(term), question, re.I
                    ) else 0,
                    "tool_level_guess": "",
                }
            for match in THRESHOLD.finditer(question):
                term = match.group(0).lower().strip()
                if term in seen:
                    continue
                # A threshold the CLAIM already states is not invented.
                if re.search(re.escape(term), (claim or "").lower()):
                    continue
                digits = set(NUMERAL.findall(term))
                if digits and digits <= set(NUMERAL.findall(claim or "")):
                    continue
                seen.add(term)
                yield {
                    **base, "phrase": term, "matched_term": term,
                    "sub_type_guess": "invented_condition",
                    "definite": 1, "tool_level_guess": "",
                }

            for definite, pattern in ((1, DEFINITE), (0, INDEFINITE)):
                for match in pattern.finditer(question):
                    phrase = match.group(1).strip()
                    sub_type, term = classify(phrase)
                    if not sub_type or term in seen:
                        continue
                    # Presupposition requires the object to be ABSENT from the
                    # claim. Present = rule 1 of the decision procedure, accept.
                    if _stems(term) & claim_terms:
                        continue
                    seen.add(term)
                    yield {
                        **base,
                        "phrase": phrase,
                        "matched_term": term,
                        "sub_type_guess": sub_type,
                        "definite": definite,
                        "tool_level_guess": (
                            tool_second_level(term, claim)
                            if sub_type == "invented_tool"
                            else ""
                        ),
                    }


def main() -> None:
    found = list(rows())
    fields = [
        "source", "interview_id", "family", "probe_level", "claim", "question",
        "phrase", "matched_term", "sub_type_guess", "definite",
        "tool_level_guess", "question_numerals", "validator_verdict",
        "validator_rules",
    ]
    with OUT.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(found)

    from collections import Counter

    print(f"{len(found)} candidate premise objects -> {OUT.relative_to(ROOT)}")
    for name, count in Counter(r["sub_type_guess"] for r in found).most_common():
        print(f"  {name:<22} {count:>4}")
    print("  --- invented_tool second level ---")
    for name, count in Counter(
        r["tool_level_guess"] for r in found if r["tool_level_guess"]
    ).most_common():
        print(f"  {name:<22} {count:>4}")
    print("  --- definite vs solicited ---")
    for name, count in Counter(
        "definite" if r["definite"] == 1 else "indefinite" for r in found
    ).most_common():
        print(f"  {name:<22} {count:>4}")


if __name__ == "__main__":
    main()
