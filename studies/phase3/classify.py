"""Question intent classifier for the Phase 3 audit.

Deliberately dumb, auditable regex cues. Two outputs per question:
  primary  - category of the EARLIEST cue in the string (the leading ask)
  labels   - every category that matched anywhere (for ambiguity reporting)
"""
import re

CUES = {
 "metadata": [
   r"who else was involved",
   r"who were the",
   r"how many", r"how much", r"how large", r"how big", r"how long",
   r"what year", r"which year", r"how often", r"how frequently",
   r"what was the (?:size|headcount|volume|count)", r"team size", r"headcount",
   r"how many people", r"what (?:was|were) your (?:scope|span)",
   r"over what (?:period|timeframe)", r"what (?:was|were) the numbers",
   r"how long did", r"for how long", r"what was your scope",
 ],
 "process": [
   r"what were (?:your|the) daily (?:steps|tasks)",
   r"what tasks do you perform",
   r"what specific changes did you make",
   r"what steps did you take",
   r"what specific actions did you perform",
   r"what systems? did you use",
   r"which systems? did you use",
   r"what tools? did you use",
   r"which tools? did you use",
   r"what specific actions did you take",
   r"what actions did you take",
   r"what specific tasks did you perform",
   r"what tasks did you perform",
   r"what specific steps",
   r"how did you use",
   r"what did you do inside",
   r"describe (?:your|the) (?:process|workflow|routine|approach)",
   r"walk me through", r"what steps", r"what was your approach",
   r"how did you (?:do|run|handle|manage|structure|organi[sz]e|carry|go about|approach|set up|build|implement|track|monitor|review|prioriti[sz]e)",
   r"how did (?:it|this|that) work", r"what did you (?:actually )?do",
   r"day to day", r"day-to-day", r"in what order", r"give me the steps",
   r"what (?:did|does) (?:your|the) (?:process|workflow|routine)",
   r"how was (?:it|this|that) (?:done|run|handled)",
 ],
 "decision": [
   r"what factors",
   r"what criteria",
   r"what led you to",
   r"led you to (?:choose|prioriti|deprioriti)",
   r"how did you prioriti[sz]e",
   r"what did you prioriti[sz]e",
   r"deciding (?:which|how|what|whether)",
   r"decide (?:which|how|what|whether)",
   r"when deciding",
   r"what factors led",
   r"why did you", r"why (?:was|were|do|does|is)", r"what made you",
   r"what alternativ", r"what (?:else )?did you consider",
   r"(?:consider|considered) but (?:reject|decide)", r"what did you (?:reject|turn down|rule out)",
   r"what (?:was|were) the trade[- ]?off", r"how did you decide",
   r"what did you decide", r"why that", r"why this", r"what drove",
   r"on what basis", r"what was the call",
 ],
 "failure": [
   r"describe a specific",
   r"tell me about a specific",
   r"almost fell through",
   r"(?:were|was) inaccurate",
   r"hardest",
   r"describe a specific (?:incident|time|week|day|challenge|occasion|instance|case|interview|situation|episode|moment)",
   r"tell me about a (?:specific )?(?:time|incident|week|occasion|case)",
   r"struggl",
   r"did ?n[o']?t (?:work|go) as planned",
   r"did ?n[o']?t go",
   r"unexpected",
   r"disagree",
   r"delayed",
   r"unusually (?:high|low|bad)",
   r"exceeded expectations",
   r"particularly challenging",
   r"was challenging",
   r"caused (?:unexpected )?(?:issues|problems)",
   r"overcame",
   r"went wrong", r"go wrong", r"what broke", r"broke down", r"failed",
   r"failure", r"hardest (?:week|time|part|case)", r"worst",
   r"a (?:specific )?time (?:it|this|that|things)", r"one specific (?:time|occasion|episode|instance|case)",
   r"push ?back", r"escalat", r"when (?:it|this|that) did ?n[o']?t",
   r"difficult(?:y|ies)?", r"problem(?:s)? (?:you|did you) (?:hit|face|run)",
   r"slipped", r"missed", r"complain",
 ],
 "metrics": [
   r"what changes did you see",
   r"what was the impact",
   r"what measurable outcome",
   r"what specific outcome",
   r"how did you confirm",
   r"how did you ensure",
   r"how did you capture",
   r"what was the result",
   r"led to the .{0,25}(?:improvement|reduction|increase)",
   r"what specific change in .{0,40}had the biggest impact",
   r"what specific metric",
   r"which metric",
   r"what impact did",
   r"how did you track",
   r"what did you track",
   r"how did you measure", r"how do you measure", r"how was (?:it|that|this) measured",
   r"how (?:was|were) (?:it|that|the .{0,30}) (?:calculated|computed|captured|tracked|defined)",
   r"how did you (?:know|verify|confirm|validate) (?:it|that|this)",
   r"which (?:number|metric|figure)", r"what (?:number|metric) moved",
   r"how did you calculat", r"what (?:was|were) the (?:baseline|before|after)",
   r"where did (?:that|the) (?:number|figure|data) come from",
   r"how (?:is|was) .{0,30}(?:csat|aht|sla|nps|churn|uptime|latency|conversion).{0,20}(?:calculated|measured|defined|tracked)",
 ],
 "transfer": [
   r"suppose", r"imagine", r"hypothetically", r"what would you",
   r"if you (?:were|had|was)", r"had you been", r"\bagar\b",
   r"how would you", r"where would you start", r"what would rule",
   r"instead of", r"first hypothesis",
 ],
}

COMPILED = {k: [re.compile(p, re.I) for p in v] for k, v in CUES.items()}

def classify(q):
    hits = []          # (position, category)
    labels = set()
    for cat, pats in COMPILED.items():
        best = None
        for p in pats:
            m = p.search(q or "")
            if m and (best is None or m.start() < best):
                best = m.start()
        if best is not None:
            hits.append((best, cat))
            labels.add(cat)
    if not hits:
        return "other", labels
    # earliest cue wins; ties broken by a fixed precedence so it is deterministic
    prec = {"transfer":0,"failure":1,"decision":2,"metrics":3,"process":4,"metadata":5}
    hits.sort(key=lambda h: (h[0], prec[h[1]]))
    return hits[0][1], labels


TOOLING = re.compile(r"(?:what|which)\s+(?:system|systems|tool|tools|software|platform)s?\b|inside (?:it|the system|the tool)|in the (?:system|tool|software|platform)\b|\bexcel\b|\bsql\b|\bzendesk\b|\bsalesforce\b|\bjira\b|\btableau\b|\bcrm\b", re.I)
def is_tooling(q): return bool(TOOLING.search(q or ""))
