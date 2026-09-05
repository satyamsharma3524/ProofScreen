# D11 — `unsupported_premise`: taxonomy derived from the data

**No validator code, corpus or published study was touched producing this.**

## Method

Categories were not assumed. They were derived twice, independently, and the two
derivations agree:

1. **From the reviewer's own verbs.** 100 free-text notes were written without
   any category list in front of them. Four verbs account for every
   premise-related rejection: **Assumes** (8), **Invents** (3+1 on TRANSFER),
   **Introduces** (3). The remaining verbs — *Hands back* (19), *Repeats*,
   *Bundles* — name defects the validator already has rules for.
2. **From the object each question asserts.** Independently sorting the 15
   premise rejections by *what kind of thing* is presupposed produces the same
   partition.

## The answer to the objective question

> Is `unsupported_premise` (A) a real rule candidate, or (B) multiple distinct
> categories being conflated?

**(B), and the conflation is measurable.** It is five sub-classes, and — the
finding that matters — **they do not behave alike.**

| Sub-class | What is presupposed | reject | accept | disputed? |
|---|---|---|---|---|
| **`invented_tool`** | A system, tool or mechanism used to do the work | 6 | 4 | **YES — this is the entire dispute** |
| `invented_outcome` | A result, or a movement in a number | 5 | 0 | no |
| `invented_event` | A specific episode that occurred | 2 | 0 | no |
| `invented_artefact` | A document or deliverable | 1 | 0 | no |
| `invented_condition` | A threshold, limit or constraint | 1 | 0 | no |

**Nine of the fifteen rejections sit in four sub-classes the reviewer treated
unanimously.** The 6/7 split reported in Phase 3 finding 4 is not a property of
`unsupported_premise`. It is a property of **`invented_tool` alone.**

---

## The sub-classes

### 1. `invented_tool` — 6 reject / 4 accept · **DISPUTED**

The question names a system, tool or mechanism the claim never mentions.

| | claim | question asserts | verdict |
|---|---|---|---|
| r0001 | Improved CSAT by redesigning the escalation workflow | *Zendesk* | reject |
| r0003 | Grew activation 41→63% by rebuilding the first-run flow | *the product analytics dashboard* | reject |
| r0036 | Reduced reopen rate by a third | *the macros* | reject |
| r0037 | Ran 40 user interviews | *the transcription tool* | reject |
| r0052 | Reacted quickly to shifting priorities | *project management tools* | reject |
| r0093 | Owned attrition, engagement surveys, onboarding | *the system* | reject |
| r0002 | Carrying a quota of $1.2M ARR | *your CRM* | **accept** |
| r0017 | Owned the recruiting funnel | *the recruiting software* | **accept** |
| r0072 | Reacted quickly to shifting priorities | *project management tools* | **accept** |
| r0090 | Managed a team of 35 agents across 4 pods | *the system* (attendance tracking) | **accept** |

Two pairs are direct collisions: **r0052 / r0072** (same claim, same tool,
opposite verdicts) and **r0090 / r0093** (same words, *"the system"*, both
OPERATIONAL, opposite verdicts).

**Branding does not explain it.** Zendesk is rejected; Salesforce and Excel are
accepted elsewhere in the sample. **Probe level does not explain it** — nine of
the ten are OPERATIONAL.

**One hypothesis survives the data: entailment.** Not *"is it in the claim?"* but
*"does the claimed work necessarily involve a thing of this kind?"* A seller
carrying a quota necessarily uses a CRM; a recruiter owning a funnel necessarily
uses recruiting software; a lead managing 35 agents across 4 pods necessarily has
somewhere to record attendance. Nobody who ran 40 user interviews necessarily
used a transcription tool, and nothing about reopen rate implies macros.

**It explains 10 of the 11 classifiable items.** The exception is r0003 — a PM
who moved activation two quarters almost certainly had product analytics, and it
was still rejected.

This hypothesis is **D12's proposed decision rule and is not yet evidence.** It
was formed by me, after the fact, from the labels it explains. Fitting a rule to
the data it must later be judged against is exactly the trap this phase exists to
avoid, so it is written down to be **tested by a second reviewer**, not adopted.

### 2. `invented_outcome` — 5 reject / 0 accept · undisputed

The question presupposes a result, or that a number moved.

- r0009 · *"the jump in conversion rates from 15% to 25%"* — claim: coached four reps
- r0041 · *"the increase in conversion rate"* — same claim, unquantified
- r0056 · *"the 20% improvement in employee satisfaction"* — claim owns attrition and surveys
- r0012 · *"your team's overall performance metrics"* as the result of campus hiring
- r0033 · TRANSFER, *"a 30% CSAT improvement"* — a target invented for the scenario

**This is the sub-class with the sharpest boundary and the highest stakes.** A
question that hands a candidate an outcome they never claimed invites them to
confirm it — which is the fabrication this product exists to detect. Two of the
five (r0009, r0041) are the same invented outcome, once with figures and once
without, and the reviewer rejected both.

### 3. `invented_event` — 2 reject / 0 accept · undisputed **but boundary-sensitive**

- r0018 · *"the technical delays"* — DECISION, claim: ran stand-ups, tracked deliverables
- r0025 · *"the temporary solution for the vendor delay"* — DECISION

**The boundary matters more than the count**, because an INCIDENT probe's *job*
is to ask about an episode. The reviewer accepted all of these:

- r0010 · *"Describe **a** specific time during the rebuild when you faced **a** major setback"* — INCIDENT
- r0031 · *"Describe **a** time when the new escalation workflow failed"* — INCIDENT
- r0047 · *"Describe **a** specific time when **a** vendor issue delayed your work"* — INCIDENT

The rejected pair uses **definite reference** (*"the* technical delays") which
presupposes the thing happened; the accepted set uses **indefinite solicitation**
(*"a* time when…") which invites the candidate to supply one or say there was
none.

**That is a linguistically crisp distinction and it has a counterexample in the
data**: r0061 asks about *"**the** high-pressure week"* on a claim that mentions
none, and was accepted. So it is a strong heuristic, not a law.

### 4. `invented_artefact` — 1 reject / 0 accept

- r0032 · *"which ideas to combine in **your marketing plan**"* — claim is an MBA
  graduate's objective statement with no marketing plan anywhere.

n=1. Recorded as a distinct shape rather than merged into `invented_tool`,
because a deliverable and an instrument are different things to be wrong about;
whether it earns its own name needs more data.

### 5. `invented_condition` — 1 reject / 0 accept

- r0100 · *"a P1 issue that **wasn't resolved in 2 hours**"* — the claim sets no
  SLA. Note the article: the *issue* is solicited indefinitely and correctly; the
  **two-hour threshold** is what is asserted.

Also n=1, and it is the sub-class most likely to be a variant of
`unsupported_metric` — an existing rule that already catches invented **numerals**
but only when they are absent from claim *and* prior answers.

---

## What the taxonomy rules out

**A single rule keyed on "the question names something not in the claim" is not
viable, and this is measured rather than argued.** That predicate fires on
**31.5%** of Phase 3's judged questions and **32.6%** of Phase 4's. In the
reviewed sample it fires 29 times:

| | n |
|---|---|
| Human rejected, and blamed the premise | **7** |
| Human rejected for a **different** reason (mostly `answer_leakage`) | 8 |
| Human **accepted** | 14 |

**Naive precision: 7/29 = 24.1%.** Against a current total reject rate of 20.7%,
a rule firing on a third of all questions would more than double rejections while
being wrong three times out of four. Worse than `multiple_fact_targets`, which
already reads 0%.

## A correction to Phase 3 finding 4

Phase 3 reported the reviewer splitting **6 accept / 7 reject** across 13
structurally similar items, and concluded the category may be too unstable to
encode. **That overstated the disagreement**, and the error was mine: I selected
items with a regex on the *pattern* and read the *verdict*, without reading the
*reason*.

- **r0002 / r0054 was never a contradiction.** Both assume a CRM. r0054 was
  rejected for *"Hands back the exact $1.2M ARR figure"* — `answer_leakage`. The
  reviewer never objected to its CRM premise. **The CRM premise was accepted
  twice, not split.**
- Seven of the original 13 were confounded the same way, or were detector noise —
  *"the success"*, *"the re-engineering"*, *"the work"* — abstractions a question
  legitimately introduces, several of which are the claim's own words in another
  inflection.

Corrected: **two genuine collisions**, both inside `invented_tool`.
Phase 3's `validator_disagreements.md` is a published artifact and is **not
edited**; this section is the correction of record.
