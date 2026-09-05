# Phase 5 — `unsupported_premise`: taxonomy, decision rules, and whether it can be specified

**Recommendation: DO NOT IMPLEMENT.** Not "not yet, pending more work" — the
research asked for in this phase has been done, and the answer it produced is
that the category as a whole is not specifiable to the standard this validator
requires. One narrowly-scoped exception is worth a decision and is set out in
§9; a second candidate is already covered by an existing rule and should never
be built.

**Nothing was implemented.** `git diff` on `api/` for this phase is empty. No
corpus entry was added (counter-metric C6). No threshold was moved — the
validator was *called*, read-only, to measure overlap, and `DUPLICATE_JACCARD`
is still 0.37 (C7).

| artifact | what it is |
|---|---|
| `decision_rules.md` | the written rules, given verbatim to the second reviewer |
| `taxonomy_examples.csv` | **364 labelled examples**, ≥50 per sub-type |
| `premise_candidates.csv` | 227 candidate premise objects (217 distinct) mined from 839 real questions |
| `reviewer_sample.csv` | 202 blind items · `.reviewer1_key.csv` sealed |
| `reviewer_model_labels.csv` | Reviewer M's independent labels |
| `measurements.txt`, `agreement.txt` | every number below, reproducible |
| `mine_premises.py`, `curate.py`, `constructed.py`, `reviewer_sample.py`, `reviewer_model.py`, `score_agreement.py`, `measure.py` | the instruments. None is imported by `api/` |

---

## 1. The three numbers

**1. The category is real, and it is the entire recall problem.** Of the nine
false negatives in the reviewed sample — questions the validator accepted and a
human rejected — **nine are premise rejections. All of them.** The validator's
miss mass is not spread thinly across seven rules. It is one absent rule.

**2. Two independent reviewers given the written rules agree at κ = 0.477 on
whether a premise defect is present at all.** Six-way sub-type agreement is
*higher* (κ = 0.656): reviewers who both see a defect largely agree on which
one it is. **They disagree about whether there is a defect.** That is the worst
possible shape for a rule whose job is to decide exactly that.

**3. The rules score 100% agreement on examples I wrote and 51% on real
generated text the rules say to accept.** That gap is the study's methodological
result and it invalidates any κ measured only on authored examples — including
every κ this phase could have reported had it not mined real data.

---

## 2. Analysis of all known examples

### 2.1 What was analysed

| source | n | what it contributes |
|---|---|---|
| Phase 3 reviewed sample | 100 items, human-labelled | the **only** set from which precision or recall may be computed |
| Phase 3 generated questions | 519 | frequency, real text |
| Phase 4A out-of-distribution run | 320 | frequency, real text |
| **Total real questions** | **839** | 229 candidate premise objects extracted |

The 15 premise rejections in the labelled sample are the entire directly
observed evidence base. Everything else in this document is either mined real
text I labelled, or constructed — and §4 keeps those apart, because conflating
them is how a taxonomy comes to describe its author.

### 2.2 The nine misses, individually

These are the items the business case rests on. Each is a question the validator
passed and a human rejected on premise grounds.

| id | claim (abbreviated) | the question asserts | sub-type |
|---|---|---|---|
| r0003 | Grew activation 41→63% by rebuilding the first-run flow | *the product analytics dashboard*, **used weekly** | `invented_tool` **contested** |
| r0012 | Led campus hiring for 120 offers | *your team's overall performance metrics* | `invented_metric` |
| r0018 | Ran stand-ups, tracked deliverables | *the technical delays* | `invented_event` |
| r0025 | Vendor coordination, invoice follow-up, daily MIS | *the temporary solution for the vendor delay* | `invented_event` |
| r0032 | MBA graduate, analytical and leadership abilities | *your marketing plan* | `invented_artefact` |
| r0036 | Reduced reopen rate by a third | *the macros* | `invented_tool` |
| r0041 | Coached four inside sales reps | *the increase in conversion rate* | `invented_outcome` |
| r0052 | Reacted quickly to shifting priorities | *prioritising **updating** project management tools* | `invented_tool` **contested** |
| r0093 | Owned attrition, engagement surveys, onboarding | *the system to manage attrition* | `invented_tool` |

Six further premise rejections were caught by an existing rule for a different
stated reason (r0001 by `duplicate_content`, r0009 by `duplicate_content`,
r0033 by `unsupported_metric`, r0037 by `duplicate_content`, r0056 and r0100 by
`no_claim_anchor`). **They are not part of the recall gain**, and counting them
would double-count one defect.

### 2.3 What the mining showed, and it is not what the taxonomy predicted

227 candidate premise objects — **217 distinct** — were extracted from 839 real
questions. Applying the decision rules to them collapses the count dramatically,
and the collapse is concentrated in two sub-types:

| sub-type | distinct candidates | survive the rules | why the rest fall away |
|---|---|---|---|
| `invented_tool` | 79 | **67** (59 clean + 8 contested) | 10 are the FALLBACK template asking *which* systems; 1 names a tool the claim states; 1 was a mis-typed artefact |
| `invented_outcome` | 75 | **9** | 45 are nominalisations (*the success*, *the impact*); 21 are the claim's own movement reworded |
| `invented_event` | 33 | **4** | 29 are indefinite solicitations — *"Describe **a** specific incident when…"* |
| `invented_metric` | 24 | 14 | the rest are TRANSFER scenarios, or measures the claim owns |
| `invented_artefact` | 4 | 5 (incl. 1 re-typed from `invented_tool`) | — |
| `invented_condition` | 2 | 2 | — |

**Eighty-eight per cent of the naive detector's `invented_outcome` hits are
false, and 88% of its `invented_event` hits.** A rule keyed on the surface
pattern would be wrong roughly nine times in ten on the two sub-types it fires
on most.

---

## 3. The taxonomy

Six sub-types. Five were derived in Phase 4B (`unsupported_premise_taxonomy.md`
D11) from the reviewer's own verbs; **`invented_metric` is added here**, on the
evidence of twelve mined examples that presuppose a *measure* without
presupposing a *movement in one* — which neither `invented_outcome` nor the
existing `unsupported_metric` rule describes.

| sub-type | presupposes | observed | mined | real total | frequency in 839 questions |
|---|---|---|---|---|---|
| `invented_tool` | an instrument used to do the work | 8 | 59 | 67 | **8.0%** — and most are entailed, i.e. acceptable |
| `invented_metric` | that a particular measure is tracked | 2 | 12 | 14 | **1.7%** |
| `invented_outcome` | a result, or that a number moved | 1 | 8 | 9 | **1.1%** |
| `invented_event` | a specific episode occurred | 2 | 2 | 4 | **0.5%** |
| `invented_artefact` | a document or deliverable exists | 1 | 4 | 5 | **0.6%** |
| `invented_condition` | a threshold, limit or SLA | 2 | 0 | 2 | **0.2%** |

`invented_tool`'s 8.0% counts the 8 contested items; 7.0% without them.

**The frequency column is the one that should drive the decision.** Four of the
six sub-types occur in fewer than one question in fifty. `invented_condition`
occurs **twice in 839**, and §8.4 shows an existing rule already catches it.

### 3.1 The distinction that separates `invented_metric` from `invented_outcome`

A **metric** is a measure; an **outcome** is a movement in one.

> *"How did you measure your one-touch resolution rate?"* — the rate is
> presupposed to exist and be owned. `invented_metric`.
>
> *"How did you measure the improvement in one-touch resolution?"* — an
> improvement is presupposed to have happened. `invented_outcome`.

They overlap when a numeral is attached (*"the 30% reopen rate"*), and there the
numeral decides: the offending part is the **value**, which puts it in
`invented_condition` or `invented_outcome`, and — critically — inside the reach
of the **existing** `unsupported_metric` rule.

---

## 4. Provenance, and why it is stated on every table

Three classes, kept separate throughout:

| class | n | what it may be used for |
|---|---|---|
| **observed** | 16 | precision, recall, ceilings. The only set with an independent human verdict |
| **mined** | 85 | frequency, and the reliability test on real text |
| **constructed** | 263 | **nothing quantitative.** Specification material only |

Constructed questions are written over **real claims** — all 84 distinct claims
in the two corpora — so at least one side of every pair is text I did not
choose. A fully invented pair lets an author pick the question *and* the answer.

**Why this matters, measured:** Reviewer M agreed with me on **100%** of the
constructed items (97% at six-way sub-type level) and on **51%** of the real
mined items the rules say to accept. Had this study been built the obvious way —
write 300 examples, hand them to a second reviewer, report κ — it would have
reported κ ≈ 0.95 and recommended implementation. That number would have been an
artefact of me writing both the rules and the examples.

---

## 5. The examples — ≥50 per sub-type

`taxonomy_examples.csv`, 364 rows: `example_id · sub_type · tool_level ·
provenance · human_verdict · contested · claim · question · rationale`.

| sub-type | total | observed | mined | constructed | contested |
|---|---|---|---|---|---|
| `invented_tool` / `generally_entailed` | 50 | 4 | 46 | 0 | 0 |
| `invented_tool` / `specifically_unentailed` | 50 | 3 | 6 | 41 | 0 |
| `invented_tool` / *contested* | 8 | 1 | 7 | 0 | 8 |
| `invented_outcome` | 50 | 1 | 8 | 41 | 0 |
| `invented_metric` | 56 | 2 | 12 | 42 | 0 |
| `invented_event` | 50 | 2 | 2 | 46 | 0 |
| `invented_artefact` | 50 | 1 | 4 | 45 | 0 |
| `invented_condition` | 50 | 2 | 0 | 48 | 0 |

The `generally_entailed` set is **entirely real** — 46 mined, 4 observed, none
written by me. That asymmetry is itself a result: real generated questions name
entailed category instruments constantly and unentailed ones rarely, which is
why the naive tool predicate is wrong most of the time it fires.

---

## 6. `invented_tool`, second level: `generally_entailed` vs `specifically_unentailed`

The distinction Phase 4B hypothesised is **entailment**: not *"is it in the
claim?"* but *"does the claimed work necessarily involve a thing of this
kind?"* Phase 5 operationalised it into four named shapes (`decision_rules.md`
§2), and then tested it.

**`generally_entailed` → accept.** A category instrument the claimed work cannot
be performed without at the scale claimed.

> *Carrying a quota of $1.2M ARR* → **your CRM**
> *Managed 35 agents across 4 pods* → **the system** for attendance
> *HR generalist handling payroll* → **the payroll system**

**`specifically_unentailed` → reject.** Four shapes, and shape 3 is new here:

| shape | example | claim |
|---|---|---|
| 1 · a named vendor where only the category is entailed | *"actions you took in **Zendesk**"* | Improved CSAT by redesigning the escalation workflow |
| 2 · a mechanism inside a category | *"monitor and adjust **the macros**"* | Reduced reopen rate by a third |
| 3 · **an instrument bolted to an OUTCOME, not an activity** | *"**the system** to manage attrition"* | Owned attrition, engagement surveys, onboarding |
| 4 · a category the work does not require | *"**the transcription tool** during the interviews"* | Ran 40 user interviews |

**Shape 3 resolves the collision Phase 4B recorded as unexplained.** `r0090`
(*"the system for daily attendance tracking"*, accepted) and `r0093` (*"the
system to manage attrition"*, rejected) use the same words on similar claims.
Attendance is a task performed in a system; attrition is a result. The
instrument is not the difference — what it is attached to is.

### 6.1 And it does not survive a second reader

| | |
|---|---|
| items where either reviewer considered an instrument | 54 |
| raw agreement | 68.5% |
| **Cohen's κ** | **0.403** |

The disagreement is **asymmetric**: of 32 instruments I judged entailed,
Reviewer M called 15 unentailed. It went the other way twice.

> *"Built pipeline through outbound prospecting and closed 34 deals last year"*
> → *"How did you use the CRM to track interactions…"*
> **R1: entailed.** A seller closing 34 deals tracks them somewhere.
> **RM: "the claim does not require a CRM for the work described."**

Both readings are defensible. That is the problem. Entailment is world
knowledge, it is graded rather than binary, and two careful readers holding the
same written rule place the line in different places on nearly half the items.
**A rule whose deciding test is a judgement two readers make differently is not
a deterministic rule**, and `EXECUTION_STANDARD.md` §8 is explicit about which
side of that line this validator lives on.

---

## 7. Reviewer agreement

### 7.1 Method, and what it does and does not measure

Two independent labellings of a **202-item blind sample** — 132 items the rules
call defects, 70 they call clean, shuffled, no sub-type shown.

- **Reviewer 1** — me, labels sealed in `.reviewer1_key.csv` before Reviewer M ran.
- **Reviewer M** — `gpt-4o`, temperature 0, **one call per item**, given
  `decision_rules.md` verbatim and nothing else: no examples, no distribution,
  no indication the sample is balanced. 202 calls, 502,764 input tokens,
  **$1.34**.

**This is not the human κ that Phase 4B's D13 still needs, and it does not
replace it.** `PHASE_2_EXECUTION_PLAN.md` §Deferred rejected LLM-as-judge for
question quality, and that rejection stands: no product metric here is a
model's opinion. What this measures is narrower and legitimate — **is
`decision_rules.md` self-sufficient?** Given the rules and nothing else, does a
competent reader reach the same verdicts? Disagreement is informative in one
direction only: it can show the rules are under-specified. It cannot show they
are right.

`.reviewer1_key.csv` stays sealed for a human reviewer, and the same
`reviewer_sample.csv` is ready for them.

### 7.2 Results

| question | raw agreement | Cohen's κ |
|---|---|---|
| Is there an unsupported premise **at all**? | 78.2% | **0.477** |
| **Which** sub-type? | 71.8% | **0.656** |
| `invented_tool`: entailed or not? | 68.5% | **0.403** |

Against the thresholds Phase 4B fixed *in advance* (`< 0.4` do not encode ·
`0.4–0.7` crisp in parts · `≥ 0.7` implement), the headline binary κ of **0.477
lands in the middle band**.

### 7.3 The shape of the disagreement matters more than its size

**Six-way κ (0.656) is higher than binary κ (0.477).** Reviewers who both see a
defect agree on which one. The disagreement is about **whether** a question has
a premise problem — the one judgement a rule must make.

| Reviewer 1 | | Reviewer M |
|---|---|---|
| defect | 122 | defect |
| clean | 36 | clean |
| defect | 10 | clean |
| **clean** | **34** | **defect** |

**All the mass is in one cell.** Reviewer M rejected 34 questions I accepted —
and 28 of them fall in exactly the two places the rules say most explicitly not
to fire.

**Fourteen are the INCIDENT probe.** Rule P2 says indefinite solicitation is
acceptable; the model rejected it anyway:

> *"Describe a specific incident when the deploy tooling failed."*
> **RM: "presupposes a specific incident of failure which the claim does not
> establish."**

The model is not being careless. *"A time when X failed"* does presuppose that
X failed — the subordinate clause is factive regardless of the article.
**My article test is linguistically wrong**, and the reason the human reviewer
accepted these anyway is pragmatic, not grammatical: an INCIDENT probe is
felicitous even when the honest answer is "that never happened". That
distinction is not one a written rule has yet captured, and it is not one a
regex can capture at all.

**Fourteen are the nominalisation carve-out.** Rule P3 lists *"the success"* as
explicitly not-to-label; the model labelled it:

> *"How did you measure the success of your ETL pipelines?"*
> **RM: "presupposes a result (success) that the claim does not state."**

**Both disagreement classes are on rules I wrote specifically to prevent them.**
That is the strongest evidence in this study: the failure is not that the rules
are missing, it is that written rules do not resolve these cases even when they
address them directly.

### 7.4 Agreement by provenance — the result that invalidates the easy study

| provenance | n | binary agreement | six-way |
|---|---|---|---|
| **constructed** (I wrote the question) | 72 | **100.0%** | 97.2% |
| mined, rules say *defect* | 49 | 87.8% | 67.3% |
| **mined, rules say *clean*** | 70 | **51.4%** | 51.4% |
| observed (real, human-labelled) | 11 | 63.6% | 54.5% |

Perfect agreement on my own examples; coin-flip agreement on real questions the
rules say to accept. **The false-positive surface is where the category is
undefined**, and it is invisible to any study built only from authored positives.

---

## 8. Ceilings and cost

All figures **population-weighted** — the review sample is stratified 50
validator-accepts / 50 validator-rejects, and counting it raw reports 75% recall
for a population whose true figure is 50.7%.

### 8.1 Precision and recall ceilings

| | share of the miss mass | precision | recall |
|---|---|---|---|
| validator today | — | 54.0% | 50.7% |
| **+ a PERFECT premise rule** (catches all 9, fires wrongly never) | 9 of 9 | **69.8%** | **100.0%** |
| + `invented_tool` / `specifically_unentailed` only | 2 of 9 | 58.8% | 61.6% |
| + `invented_tool` / *contested* only | 2 of 9 | 58.8% | 61.6% |
| + `invented_event` only | 2 of 9 | 58.8% | 61.6% |
| + `invented_outcome` **and** `invented_metric` | 2 of 9 | 58.8% | 61.6% |
| + `invented_outcome` only | 1 of 9 | 56.5% | 56.2% |
| + `invented_metric` only | 1 of 9 | 56.5% | 56.2% |
| + `invented_artefact` only | 1 of 9 | 56.5% | 56.2% |

**A correction to `unsupported_premise_business_case.md` (D15).** That document
put `invented_outcome` at *"5 of 15 premise rejections, roughly a third of the
ceiling"*. Fifteen is the count of premise rejections; **nine** is the count of
premise **misses**, and only misses can become recall. Three of the five
`invented_outcome` items D15 counted are already rejected by an existing rule
(r0009 `duplicate_content`, r0056 `no_claim_anchor`, r0033 `unsupported_metric`)
and one is `invented_metric`. `invented_outcome` alone is **1 of 9** — an
eleventh of the available gain, not a third. This materially weakens the
strongest remaining case for implementation, which is why it is stated here
rather than left in a footnote.

**These are ceilings, not forecasts.** They assume a rule that never fires
wrongly. No rule in this validator achieves that — the best, `answer_leakage`,
runs at 86.4%, and the two newest read 0%.

**The realistic figure is far below.** The only currently specifiable predicate
— a definite noun phrase whose head is absent from the claim — measures **36.4%
precision** on the reviewed sample (11 of the 22 questions it fires on were
accepted by the human, 3 more were rejected for a different reason).

### 8.2 Reject-rate impact

| | new rejections | reject rate | relative |
|---|---|---|---|
| today | — | 25.5% | — |
| a perfect rule | +13.4 pts | **38.9%** | +53% |
| the mechanical predicate | +16.4 pts | **41.9%** | +64% |

Even a **flawless** rule pushes more than one question in three into
regeneration. The mechanical one pushes two in five, and **45% of its new
rejections are wrong**.

### 8.3 Regeneration and fallback impact — the second-order cost

The regeneration cap is one. A question that fails twice lands on the
**fallback**, which is never validated and is deliberately thin.

| | regeneration rate | share reaching the fallback |
|---|---|---|
| today | 25.5% | 6.5% |
| a perfect rule | 38.9% | **15.1%** |
| the mechanical predicate | 41.9% | **17.6%** |

**Roughly one question in six would be asked by the fallback, up from one in
fifteen.** The fallback renders `On "<claim>" — <base>`, which quotes the claim
including its figures — so it trips `answer_leakage` by construction and is
exempt from validation for that reason. A premise rule therefore does not merely
add noise: **it replaces validated questions with unvalidated ones**, and it does
so most often on exactly the questions it was wrong about.

There is also the latency guardrail. `PHASE_1_SUCCESS_METRICS.md` caps median
turn latency at +20%; every additional rejection is an additional blocking model
call inside a turn that already makes one.

### 8.4 Overlap — how much of this is already caught

Measured by calling `validate()` read-only over all 364 examples.

| sub-type | n | already rejected by an existing rule | genuinely new |
|---|---|---|---|
| `invented_condition` | 50 | **48** | **2 (4%)** |
| `invented_metric` | 56 | 30 | 26 (46%) |
| `invented_tool` / `specifically_unentailed` | 50 | 25 | 25 (50%) |
| `invented_event` | 50 | 19 | 31 (62%) |
| `invented_outcome` | 50 | 16 | 34 (68%) |
| `invented_artefact` | 50 | 16 | 34 (68%) |

Rules already doing the work: `no_claim_anchor` (142 hits), `unsupported_metric`
(55), `answer_leakage` (4).

**`invented_condition` is 96% already covered**, by `unsupported_metric` — which
catches numerals absent from the claim and prior answers, and a threshold is a
numeral. **Building it would be building a rule that already exists.**

*Caveat, stated because it cuts against the convenient reading:* constructed
questions are short and written to isolate one premise, so they anchor to the
claim less than real generated text and inflate `no_claim_anchor`. On the
**mined** subset — real text — 64% would be new rather than 53%. The
`invented_condition` finding is unaffected: it rests on `unsupported_metric`,
which keys on numerals, not on anchoring.

---

## 9. Recommendation

# → DO NOT IMPLEMENT

Phase 4B recommended *research further* and fixed the decision thresholds in
advance. The research was done. This is what it returned.

**Why not implement the category.** Two reviewers holding the written rules
agree at **κ = 0.477** on the only question a rule must answer. The
disagreement is concentrated in **34 questions one reviewer accepted and the
other rejected**, 28 of them on the two rules written specifically to prevent
that. The one deciding test the taxonomy turns on — entailment — measures
**κ = 0.403** and fails asymmetrically. On real text the rules agree with a
second reader **51%** of the time about what is *clean*. Encoding this would
ship a rule that roughly **doubles the reject rate**, is wrong nearly half the
time it fires, and pushes **one question in six onto an unvalidated fallback**.

**Why the category should not be abandoned either.** It remains **100% of the
validator's miss mass** and the only available change worth more than a point or
two of precision. The finding is that *this* specification does not work, not
that no specification could.

### Three decisions that follow, in order

**1. `invented_condition` — close it. Do not build it.** 96% of its examples are
already rejected by `unsupported_metric`. Record it as covered and remove it
from the roadmap. This is free.

**2. `invented_outcome` — the one candidate worth a decision, and it is weaker
than Phase 4B thought.** It has the sharpest boundary of the six: once both
reviewers see a defect they agree on this sub-type **94%** of the time, the
highest of any. It has the worst consequence — handing a candidate an
achievement they never claimed invites them to confirm it, which is the exact
fabrication this product exists to detect.

Against that: it is **1 of the 9 misses**, not the third of the ceiling D15
implied; with `invented_metric` folded in it is 2 of 9, for a ceiling of
**58.8% precision / 61.6% recall**. And its entire false-positive surface is the
nominalisation carve-out — *"How did you measure the success of X?"* — which is
**exactly where the two reviewers disagreed 14 times**, on a rule written
explicitly to prevent that disagreement.

**Do not build it until the nominalisation boundary survives a second human
reader.** That is a 30-item test, not another phase. If it survives, this is the
one sub-type to encode; if it does not, the category is closed.

**3. `invented_tool` — stop.** It is the largest sub-type by frequency (8.0% of
real questions) and the only one whose deciding test is world knowledge. κ = 0.403.
Real questions name entailed instruments constantly; a rule here would fire
mostly on acceptable questions. **Leave it unencoded and say so in the product
documentation**, rather than shipping a rule that is wrong more often than right
about the most common case.

### What is still missing, and it is one thing

**A second human reviewer.** `reviewer_sample.csv` is 202 blind items and
`.reviewer1_key.csv` is sealed. Reviewer M's κ measures whether the rules are
*self-sufficient*; it cannot measure whether they are *correct*. Two humans
would answer a question this study cannot:

> When Reviewer M and I disagree about *"Describe a specific incident when the
> deploy tooling failed"*, **which of us is right?**

Cost: 202 items × 2 reviewers ≈ **90 minutes of human time, $0**. It is the
cheapest open item on the roadmap and it has now blocked three consecutive
phases.

**If that κ also lands below 0.7, the finding is complete and should be
published as a negative result.** Two people given a written rule cannot agree
on what an unsupported premise is. That is a stronger and more useful result
than a seventh rule, and it is the answer this line of research was commissioned
to be able to give.

---

## 10. Constraints

| | |
|---|---|
| Do not implement `unsupported_premise` | **held** — no rule was written |
| Do not modify validator code | **held** — `git diff api/` is empty for this phase; `validate()` was called, never changed |
| Do not modify the corpus | **held** — `tests/data/question_golden.json` untouched (C6) |
| Do not tune thresholds | **held** — `DUPLICATE_JACCARD` still 0.37 (C7) |
| Phase 3 not modified while under review | **held** — `studies/phase3/` untouched |

Cost of this phase: **$1.34** of model calls, all of it Reviewer M.
