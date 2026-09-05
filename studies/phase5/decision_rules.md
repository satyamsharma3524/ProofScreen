# Phase 5 — decision rules for labelling an unsupported premise

**A specification to be tested, not a finding.** Supersedes
`studies/phase4b/decision_rule.md` for Phase 5 labelling only; that document is
published and is not edited. What changed and why is §6.

A reviewer needs nothing except this file, a claim and a question.

---

## 0. What you are labelling

A question carries an **unsupported premise** when it refers to something *as
though it already exists* which the claim never establishes and which the
claimed work does not require.

You are labelling **the premise only**. A question can hand back a figure, ask
two things at once, or be badly worded — those are other rules' business. If a
question has no premise problem, label `none`, even if it is a bad question.

---

## 1. The procedure

For each thing the question refers to as though it exists, in this order:

> **P1 — Is it in the claim?** In any wording. *"the re-engineering"* against
> *"Re-engineered the intake process"* is in the claim. → **`none`. Stop.**
>
> **P2 — Is it solicited rather than asserted?** *"**a** specific time when…"*,
> *"**any** week where…"*, *"which systems did you use"*. An indefinite article
> or an open question invites the candidate to supply the thing, or to say
> there was none. → **`none`. Stop.**
>
> **P3 — Is it a nominalisation the question itself introduces?** *"the
> success"*, *"the work"*, *"the impact"*, *"the data"*, *"your approach"*.
> These name the topic of the question, not a business object. → **`none`.
> Stop.**
>
> **P4 — Does the claimed work, at the scale the claim states, necessarily
> involve a thing of this kind?** → **`none`** if yes. → **the sub-type** if no.

P4 is the load-bearing step and the one under test.

**If two things fail, label the one the question depends on most.** *"What did
you do in the coaching tracker to lift CSAT?"* asserts a tool and an outcome;
the outcome is the graver assertion.

---

## 2. The six sub-types

| sub-type | what is presupposed | one-line test |
|---|---|---|
| `invented_tool` | an instrument used to do the work | could the work be done with a different instrument, or none? |
| `invented_outcome` | that a result occurred, or a number moved | does the claim state this movement? |
| `invented_metric` | that a particular measure is tracked or owned | does the claim name this measure? |
| `invented_event` | that a specific episode happened | is it definite (*the* outage) or solicited (*an* outage)? |
| `invented_artefact` | that a document or deliverable exists | does the claim produce it? |
| `invented_condition` | a threshold, limit or SLA | does the claim set this number? |

### `invented_tool`

**Second level, and it is the whole difficulty.**

- **`generally_entailed`** — the instrument is a **category** the claimed work
  cannot be performed without at the scale claimed. *Carrying a quota* → a CRM.
  *Managing 35 agents' attendance* → some system. *Running payroll* → a payroll
  system. **Label `none`.**
- **`specifically_unentailed`** — **label `invented_tool`.** Four shapes:
  1. **a named vendor** where the category, not the brand, is entailed —
     Zendesk, Storybook, LinkedIn Recruiter;
  2. **a mechanism inside a category** — macros, saved views, branching logic,
     an alerting rule;
  3. **an instrument bolted to an OUTCOME rather than to a performed
     activity** — *"the system to manage attrition"* (attrition is a result,
     not a task done in a system) against *"the system for attendance
     tracking"* (attendance is a task);
  4. **a category the work does not require** — a transcription tool for user
     interviews; speech analytics for calibration.

**A vendor named in the claim is in the claim (P1).** A *different* vendor is
shape 1 and is the clearest case in the sub-type.

### `invented_outcome`

Reject whenever the question refers to a result the claim does not state,
**with or without a number**. *"the increase in conversion rate"* on *"Coached
four reps"* is as much an invented outcome as *"the jump from 15% to 25%"*.

**The claim's own movement in other words is not invented.** *"the latency
reduction"* against *"Cut p95 latency from 900ms to 180ms"* → `none` (P1).

**On OUTCOME probes the line is asking versus asserting.** *"How did you
measure the success of X?"* asserts nothing — success is the thing being asked
about (P3). *"How did you measure the 20% improvement?"* asserts one.

### `invented_metric`

The question presupposes the candidate **tracks, owns or can compute a
particular measure**. Distinct from `invented_outcome`: a metric is a
*measure*, an outcome is a *movement in one*.

**Where they overlap, the numeral decides.** *"the 30% reopen rate"* asserts
both a measure and a value; label `invented_condition` if the offending part is
the threshold, `invented_outcome` if it is a movement, `invented_metric` if the
measure itself is the intrusion.

**A metric the claim's own work is defined by is entailed.** *"Owned resolution
time for P1 issues"* → asking how resolution time was measured is `none`.

### `invented_event`

**The article decides it.** *"**the** technical delays"* presupposes they
happened → `invented_event`. *"**a** time when things went wrong"* solicits one
→ `none`. This is what the INCIDENT probe level exists to do, and a rule that
rejected indefinite solicitation would delete the probe level.

**Known counterexample: `r0061`.** *"during **the** high-pressure week"* is
definite, the claim mentions no such week, and the reviewer accepted it. Label
it as the rules say and note the disagreement.

### `invented_artefact`

A document, plan, deck, SOP or specification the claim never produces. A
deliverable and an instrument are different things to be wrong about; if you
cannot tell, ask whether it is *used* (tool) or *written* (artefact).

### `invented_condition`

A threshold, limit, SLA, cap or floor the claim never sets. *"a P1 issue that
wasn't resolved in **2 hours**"* — the issue is solicited correctly; the two
hours are asserted. **Label the threshold, not the episode.**

---

## 3. What NOT to label

The naive predicate's low precision comes almost entirely from these:

- **Nominalisations** (P3) — *the success, the work, the data, your strategies*.
- **The claim's own words in another form** (P1) — *the rebuild*, *the
  re-engineering*.
- **Indefinite solicitation** (P2) — *a time when*, *any week where*, *which
  systems*.
- **Anything wrong for a different reason.** A question that hands back the
  claim's figure is `answer_leakage`. Labelling it here double-counts one
  defect and corrupts every per-rule number downstream.
- **TRANSFER probes inventing a situation.** A transfer probe legitimately
  poses a scenario the candidate has not described. It may **not** invent an
  achievement they reached: *"how would you handle X"* is fine, *"how did you
  get the 30% improvement"* inside a scenario is not.

---

## 4. Output per item

`sub_type` — one of the six, or `none`.
`tool_level` — for `invented_tool` only: `generally_entailed` (which means you
labelled `none`) or `specifically_unentailed`.
`note` — one line, and **especially** a line wherever this document did not
tell you what to do. The items it fails to decide are the finding.

---

## 5. Known unresolved items

Carried forward from `studies/phase4b/decision_rule.md` §edges, unchanged:

- **r0003** *"the product analytics dashboard each week"* on a PM claim that
  moved activation two quarters. P4 says entailed; the reviewer rejected it.
- **r0052 / r0072** the same claim and the same tool, opposite verdicts. Under
  these rules the tool is entailed in both; r0052's offence is a second premise
  — that updating the tools was a competing task.
- **r0061** the definite *"high-pressure week"* that was accepted.

---

## 6. What changed from `studies/phase4b/decision_rule.md`

1. **`invented_metric` added as a sixth sub-type.** Phase 4B had five. Twelve
   real mined examples presuppose a *measure* without presupposing a
   *movement*, which neither `invented_outcome` nor `unsupported_metric`
   describes.
2. **P3, the nominalisation step, is promoted into the procedure.** It was
   prose in a "what not to label" list. Forty-four of the 75 mined
   `invented_outcome` candidates are nominalisations, so leaving it out of the
   ordered steps was the single largest source of over-firing.
3. **The `invented_tool` second level is written as four named shapes**, rather
   than as the single question *"does the work entail it?"*. Shape 3 — an
   instrument bolted to an outcome — is new, and it is what separates
   `r0090` from `r0093`, the pair Phase 4B recorded as an unexplained collision.
