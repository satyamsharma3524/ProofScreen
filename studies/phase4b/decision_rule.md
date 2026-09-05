# D12 — Decision rule for labelling `unsupported_premise`

**A specification to be tested, not a finding.** It was written after seeing the
labels it explains, so it fits them by construction. Its only honest test is
whether a second reviewer, given this document and nothing else, agrees with the
first on items neither has discussed — which is D13.

**Not implementable as written.** Several clauses need world knowledge ("does a
quota imply a CRM?"). If κ comes back strong, the *next* question is whether a
deterministic approximation exists. If κ comes back weak, that question never
arises.

---

## The one question, asked in order

For each **thing the question refers to as though it exists** — a tool, a result,
an episode, a document, a threshold — ask:

> **1. Is it in the claim?** → **ACCEPT.** Stop.
> **2. Is it solicited rather than asserted?** ("*a* time when…", "*any*
>    week where…") → **ACCEPT.** Stop.
> **3. Does the claimed work necessarily involve a thing of this kind?**
>    → **ACCEPT** if yes, **REJECT** if no.

Rule 3 is the load-bearing one and the one under test.

**Judge the premise only.** If the question is bad for another reason — it hands
back a figure, asks two things at once — that is a different rule's business.
Here, label the premise. A question can have a sound premise and still be a bad
question.

---

## Per sub-class

### `invented_tool` — the disputed one

**ACCEPT** when the named instrument is a *category* the claimed work cannot be
performed without.

- *Carrying a quota of $1.2M ARR* → **"your CRM"** — quota-carrying sellers track
  pipeline somewhere. ACCEPT.
- *Owned the recruiting funnel from sourcing through offer* → **"the recruiting
  software"** — ACCEPT.
- *Managed a team of 35 agents across 4 pods* → **"the system"** for attendance —
  35 people's attendance is not tracked from memory. ACCEPT.

**REJECT** when the instrument is one *particular choice* among many, or when the
work does not require an instrument at all.

- *Ran 40 user interviews* → **"the transcription tool"** — plenty of people take
  notes. REJECT.
- *Reduced reopen rate by a third* → **"the macros"** — one specific mechanism of
  many. REJECT.
- *Owned attrition, engagement surveys and onboarding* → **"the system to manage
  attrition"** — attrition is an outcome, not a system-mediated task. REJECT.

**Edge — a named vendor.** Branding is *not* the test, and the data says so:
Zendesk was rejected while Salesforce and Excel were accepted. Apply rule 3 to the
**category**, then ask whether naming the vendor adds an assumption. *"Ran the
deal desk" → Salesforce* passes because a deal desk runs on a CRM and Salesforce
is the category's default. *"Improved CSAT by redesigning the escalation
workflow" → Zendesk* fails because CSAT work implies **no particular helpdesk**.

**Counterexample, unresolved — r0003.** *Grew activation 41→63% by rebuilding the
first-run flow* → **"the product analytics dashboard"**. Rule 3 says accept: a PM
who moved activation two quarters had analytics. The reviewer rejected it.
**Reviewer 2 should be shown this item and their answer treated as diagnostic.**

**Counterexample, unresolved — r0052 / r0072.** Same claim (*"Reacted quickly to
shifting priorities and supported multiple workstreams through the transition"*),
same tool, opposite verdicts. The questions differ in what *else* they assume:
r0072 asks what you did *in* the tools; r0052 asks why you prioritised
*updating* them, which asserts an updating task as well as the tool. Under this
document r0072 accepts and r0052 rejects — but on the **second** premise, not the
tool. Both reviewers should label both.

### `invented_outcome` — REJECT, near-unconditionally

**REJECT** whenever the question refers to a result the claim does not state,
whether or not it carries a number.

- *Coached four inside sales reps* → *"the jump in conversion rates from 15% to
  25%"* — REJECT (r0009)
- same claim → *"the increase in conversion rate"* — REJECT (r0041). **The absence
  of figures does not make it acceptable.** This pair is the sub-class's anchor.

**ACCEPT** when the outcome is solicited, not asserted: *"What happened
afterwards?"*, *"Which number moved, if any?"*, *"How did you know it worked?"*

**Edge — OUTCOME probes.** The OUTCOME level asks about results by design. The
line is between **asking for** one and **asserting** one. *"How did you measure
the success of X?"* asserts nothing (success is the thing being asked about);
*"How did you measure the 20% improvement?"* asserts a 20% improvement.

**Edge — TRANSFER.** r0033 invents a 30% CSAT target for the scenario. A TRANSFER
probe legitimately invents a *situation*; it may not invent an *achievement the
candidate reached*. If reviewers disagree here, TRANSFER needs its own clause.

### `invented_event` — turns on the article

**REJECT** definite reference to an unstated episode: *"the technical delays"*,
*"the temporary solution for the vendor delay"*.

**ACCEPT** indefinite solicitation: *"**a** specific time when…"*, *"**a** week
where…"*, *"**a** major setback"*. This is what INCIDENT is *for*, and a rule that
rejected it would delete the probe level.

**Counterexample, unresolved — r0061.** *"during **the** high-pressure week"* is
definite, the claim mentions no such week, and the reviewer accepted it. Either
definiteness is a heuristic rather than a test, or this item is an error.
**Include it; the answer is diagnostic.**

### `invented_artefact` — REJECT

A document, plan or deliverable the claim never produces. n=1 (r0032, *"your
marketing plan"* on an MBA objective statement). Too thin to have edges yet.

### `invented_condition` — REJECT the threshold, not the episode

r0100: *"a P1 issue that wasn't resolved in **2 hours**"*. The issue is solicited
correctly; the two-hour SLA is asserted. **Label the threshold.**

Overlaps `unsupported_metric`, which already catches invented numerals unless
they appear in the claim or a prior answer. Reviewers should label it here anyway;
where the existing rule already covers it is an implementation question.

---

## What NOT to label

Kept explicit because the naive predicate's 24.1% precision comes almost entirely
from these:

- **Abstractions the question introduces** — *"the success"*, *"the work"*, *"the
  data"*, *"the core logic"*, *"your strategies"*. Nominalisations, not business
  objects.
- **The claim's own words in another form** — *"the re-engineering"* on
  *"Re-engineered the intake process"*, *"the rebuild"* on *"rebuilding user
  onboarding"*. Rule 1 covers these; a word-match test does not.
- **Anything wrong for another reason.** Eight of the 29 detector hits in the
  Phase 3 sample were rejected for `answer_leakage` and merely happened to
  contain a definite noun phrase. Labelling those here would double-count a
  defect and corrupt every per-rule number downstream.

## How to use this

Label `studies/phase4b/kappa_sample.csv`: `verdict` = `accept` / `reject`,
`category` = the sub-class name (or `none` on accept), `note` = one line, and
**especially** a note wherever this document did not tell you what to do. The
items it fails to decide are the finding.

Two reviewers, independently, no discussion first. Do not consult
`studies/phase3/human_review_sample_completed.csv` — 14 of the 24 items are in
it, and reading it converts a reliability test into a memory test.
