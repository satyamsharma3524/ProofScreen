"""Factual audit A-E. Measurements only."""
import json, re, sqlite3, csv, collections, statistics as st
from forensic import load, bucket

R = load()
B = [r for r in R if r["tier"] == "B"]          # simulator conditioned on question
db = sqlite3.connect("study.sqlite3"); db.row_factory = sqlite3.Row

SIG = {}
for qid, sj in db.execute("select question_id, signals_json from responses"):
    if sj: SIG[qid] = json.loads(sj)

CONTRA_RESP = {r[0] for r in db.execute("select later_response_id from contradictions")}
RESP_BY_Q = {r["question_id"]: r["id"] for r in db.execute("select id, question_id from responses")}

def sig_of(r): return SIG.get(r["qid"], {})
def has(r, key, pred=lambda x: True):
    return any(pred(x) for x in (sig_of(r).get(key) or []))

# ---- 10-category question classifier -------------------------------------
CUES = {
 "TRANSFER":   [r"suppose", r"imagine", r"what would you", r"how would you", r"if you (?:were|had)", r"\bagar\b"],
 "EXCLUSION":  [r"not (?:cache|include|automate|do|cover)", r"decide[d]? against", r"did ?n[o']?t (?:include|cover|automate|change|touch)",
                r"left out", r"rule[d]? out", r"turn(?:ed)? down", r"deprioriti", r"what did ?n[o']?t improve",
                r"what (?:else )?did you (?:reject|exclude)", r"chose not to"],
 "TRADEOFF":   [r"what specific criteria", r"criteria did you use", r"did you decide to implement", r"what factors", r"what criteria", r"trade[- ]?off", r"why did you (?:choose|pick|select)",
                r"what (?:else )?did you consider", r"what alternativ", r"over other", r"instead of",
                r"led you to (?:choose|prioriti|deprioriti)", r"deciding (?:which|what|whether)",
                r"how did you decide", r"what did you decide", r"prioriti[sz]e"],
 "FAILURE":    [r"went wrong", r"go wrong", r"what broke", r"failed", r"failure", r"did ?n[o']?t (?:work|go) as planned",
                r"struggl", r"hardest", r"worst", r"unexpected", r"setback", r"exceeded expectations",
                r"unusually", r"delay", r"disagree", r"overcame", r"challenging", r"almost fell through",
                r"caused .{0,20}(?:issues|problems)", r"inaccurate", r"escalat"],
 "INCIDENT":   [r"describe a specific", r"tell me about a (?:specific )?(?:time|week|day|occasion|incident)",
                r"a specific (?:time|week|day|occasion|instance|case)", r"one specific"],
 "MEASUREMENT":[r"what impact did", r"what specific change in .{0,40}(?:impact|improvement)", r"what specific process changes led", r"how (?:did|do|was|were) .{0,25}(?:measure|calculat|comput|captur|track|defin)",
                r"how did you (?:know|verify|confirm|validate|ensure)", r"which (?:number|metric|figure)",
                r"what (?:number|metric) moved", r"what specific metric", r"what changes did you see",
                r"what was the impact", r"what measurable", r"what specific outcome", r"what was the result",
                r"where did (?:that|the) (?:number|figure) come from", r"baseline"],
 "DEPENDENCY": [r"depend", r"rely on", r"relied on", r"waiting on", r"wait for", r"blocked", r"blocker",
                r"hand(?:ed)? off to", r"other teams?", r"another team", r"upstream", r"downstream",
                r"vendor", r"external", r"approval from"],
 "PEOPLE":     [r"who (?:else )?(?:was|were) involved", r"who did you", r"who were the", r"who reported",
                r"who had to", r"stakeholder", r"which team", r"who owned", r"who signed"],
 "WORKFLOW":   [r"what specific system did you use", r"walk me through", r"what steps", r"what specific steps", r"day to day", r"day-to-day",
                r"what (?:specific )?(?:tasks|actions) did you (?:perform|take)", r"what did you (?:actually )?do",
                r"how did you (?:do|run|handle|manage|structure|organi[sz]e|go about|approach|set up|build|implement|track|monitor)",
                r"what systems? did you use", r"which systems? did you use", r"what tools? did you use",
                r"which tools? did you use", r"how did you use", r"daily (?:steps|tasks)",
                r"each morning", r"what were (?:your|the) daily", r"in the (?:system|tool)", r"what specific changes did you make"],
 "METADATA":   [r"what was the size", r"how many", r"how much", r"how long", r"how often", r"how large", r"how big",
                r"what year", r"over what period", r"what (?:was|were) your scope", r"what (?:was|were) the numbers",
                r"team size", r"headcount"],
}
COMPILED = {k: [re.compile(p, re.I) for p in v] for k, v in CUES.items()}
PREC = ["TRANSFER","EXCLUSION","DEPENDENCY","PEOPLE","INCIDENT","FAILURE",
        "TRADEOFF","MEASUREMENT","WORKFLOW","METADATA"]

def classify10(q):
    hits = []
    for cat, pats in COMPILED.items():
        best = None
        for p in pats:
            m = p.search(q or "")
            if m and (best is None or m.start() < best): best = m.start()
        if best is not None: hits.append((best, PREC.index(cat), cat))
    if not hits: return "UNCLASSIFIED"
    hits.sort()
    return hits[0][2]

for r in R: r["cat10"] = classify10(r["text"])
