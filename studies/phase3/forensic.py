"""Impostor-parity instrument.

A signal type is scored by INVENTION COST: how hard is it for a smart stranger
who read only the resume to produce this signal convincingly?

  CHEAP  a plausible value can be guessed from the claim alone
  MID    requires committing to a specific that could be checked
  DEAR   requires having been there; a wrong answer is visibly wrong
"""
import json, sqlite3, collections, statistics as st

COST = {
    "quantities":         "cheap",   # "about 3 months", "around 150"
    "entities":           "mid",     # names a team/system/person
    "tools":              "mid",     # naming is cheap; the extractor stores usage separately
    "process_steps":      "mid",     # a generic sequence is guessable
    "causal_links":       "dear",    # requires a mechanism that holds together
    "incident_markers":   "dear",    # a specific episode
    "metric_definitions": "dear",    # only when how_measured is present
}

def bucket(sig):
    """Return {cheap, mid, dear} counts for one stored signals_json blob."""
    out = collections.Counter()
    for key, cost in COST.items():
        items = sig.get(key) or []
        if key == "metric_definitions":
            defined = [m for m in items if m.get("how_measured")]
            named   = [m for m in items if not m.get("how_measured")]
            out["dear"]  += len(defined)
            out["cheap"] += len(named)      # a metric NAME is free
            continue
        if key == "tools":
            used  = [t for t in items if t.get("usage") or t.get("how_used")]
            named = [t for t in items if not (t.get("usage") or t.get("how_used"))]
            out["mid"]   += len(used)
            out["cheap"] += len(named)
            continue
        if key == "quantities":
            # a quantity TIED to a named metric is harder than a bare count
            tied = [q for q in items if q.get("refers_to")]
            out["mid"]   += len(tied)
            out["cheap"] += len(items) - len(tied)
            continue
        out[cost] += len(items)
    return out

def load():
    db = sqlite3.connect("study.sqlite3"); db.row_factory = sqlite3.Row
    recs = json.load(open("recs.json"))
    sig = {r["question_id"]: r["signals_json"]
           for r in db.execute("select question_id, signals_json from responses")}
    for r in recs:
        raw = sig.get(r["qid"])
        r["buckets"] = bucket(json.loads(raw)) if raw else collections.Counter()
    return recs
