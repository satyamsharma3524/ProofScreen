# D15 — `unsupported_premise`: rule opportunity

Estimated from the Phase 3 review (100 labelled), the Phase 4A in-sample
re-score, and both out-of-distribution datasets (519 + 320 = 839 generated
questions, 790 judged). **Nothing was implemented.**

---

## The number that decides this

**100% of the validator's misses are this class.**

Phase 3's false-negative mass — questions the validator accepted and a human
rejected — is **65 weighted questions**, and every one of the nine sampled items
composing it was rejected with the words *Assumes*, *Invents* or *Introduces*.
Not most. All.

That is unusual and it is the whole business case: the validator's recall problem
is not spread across seven rules that each miss a little. It is one absent rule.

## Frequency

| | Phase 3 | Phase 4A OOD |
|---|---|---|
| Judged questions | 486 | 304 |
| Premise-rejected, weighted to population | **78 (16.0%)** | not yet labelled |
| Validator currently **accepts** them | 65 of 78 | — |

**About one generated question in six carries a premise a human would reject, and
the validator passes five of every six of those.**

## Upper bound on the gain

A hypothetical rule that catches exactly this class and nothing else — no false
positives, perfect recall on its target:

| | precision now | precision max | recall now | recall max |
|---|---|---|---|---|
| Phase 3 validator | 54.0% | **69.9%** | 50.8% | **~100%** |
| Phase 4A validator (in-sample) | 66.0% | **79.9%** | 47.0% | **96.3%** |

**+14 to +16 points of precision and roughly +49 points of recall.** No other
change available to this validator is worth anything close, because no other
change addresses any of the miss mass.

**This is a ceiling, not a forecast.** It assumes a rule that never fires wrongly,
which no rule in this validator achieves — the best, `answer_leakage`, runs at
86.4%.

## Upper bound on the risk — and it is the reason to stop

The obvious implementation is *"the question names a definite noun phrase absent
from the claim"*. **Measured, not estimated:**

| | Phase 3 | Phase 4A OOD |
|---|---|---|
| Fires on | 153 / 486 = **31.5%** | 99 / 304 = **32.6%** |
| Of which the validator already accepts | 117 (24.1%) | 82 (27.0%) |

In the 100-item reviewed sample it fires **29** times:

| | n |
|---|---|
| Rejected, blamed on the premise | **7** |
| Rejected for a **different** reason, mostly `answer_leakage` | 8 |
| **Accepted** | 14 |

**Naive precision: 7/29 = 24.1%.**

Shipping it would take the total reject rate from **20.7% to roughly 45%** —
nearly one question in two regenerated — while being wrong three times in four.
That is worse than `multiple_fact_targets` and `scope_drift`, which already read
0% precision at small n and which Phase 4A declined to touch.

**Second-order cost, and it is not small.** Every rejection buys a regeneration.
The regeneration cap is one, and the ceiling on it is the **+20% median
turn-latency guardrail** in `PHASE_1_SUCCESS_METRICS.md`. Doubling the reject rate
doubles second attempts, and pushes more questions into the fallback — which is
never validated and is thin by design. **A low-precision rule does not merely add
noise; it degrades the questions that get asked.**

## What the gap between the two bounds is worth

| | precision |
|---|---|
| Naive predicate, measured | **24.1%** |
| A rule that scoped to the four undisputed sub-classes | unmeasured |
| Perfect rule (ceiling) | 100% |

The taxonomy (D11) narrows this materially: **9 of 15 premise rejections sit in
four sub-classes the reviewer treated unanimously** — `invented_outcome` (5),
`invented_event` (2), `invented_artefact` (1), `invented_condition` (1). Zero
accepts among them.

`invented_tool` — 6 reject / 4 accept — is the entire dispute and the hardest to
specify, because the deciding test appears to be *entailment* ("does a quota imply
a CRM?"), which is world knowledge and not obviously reducible to a deterministic
predicate.

**A rule scoped to `invented_outcome` alone would be the highest-confidence
subset**: unanimous in the labels, and the defect with the worst consequence —
handing a candidate an achievement they never claimed invites them to confirm it,
which is the fabrication this product exists to detect. Its share of the miss mass
is **5 of 15 premise rejections**, so roughly a third of the ceiling above.

That is a Phase 5 question and is deliberately not answered here.

## Cost to find out

| | |
|---|---|
| D13 κ study | 24 items × 2 reviewers ≈ **40 minutes of human time**, $0 |
| A scoped implementation + OOD rerun | ~1 day + **~$2.50** of model calls |
| Shipping the naive rule and discovering the 24% later | a validator that rejects half its own questions, on a live demo |

## Recommendation

# → RESEARCH FURTHER

**Not** *implement*, and **not** *abandon*. Both are ruled out by measurement
rather than by caution.

**Why not `implement`.** The only currently specifiable predicate has **24.1%
measured precision** and would roughly double the reject rate. The refined
predicate that would fix that — entailment — exists only as a hypothesis I fitted
to the labels it explains, after the fact. Encoding it now would be encoding my
reading of one reviewer's 100 judgements. κ is **unmeasured**, and
`EXECUTION_STANDARD` is explicit: do not implement a rule whose labelling
standard is unclear.

**Why not `abandon`.** The class accounts for **100% of the validator's miss
mass** and roughly **16% of all generated questions**. Nothing else on the table
moves precision more than a point or two. Abandoning the largest measured defect
class because a first pass at defining it was imprecise would be giving up on the
strongest available result.

**And the ground for "further" is now much firmer than Phase 3 suggested.** Phase
3 reported 6/7 on "the same pattern" and inferred an unstable category. Re-reading
the reviewer's *reasons* rather than their *verdicts*: eight of those thirteen
were rejected for `answer_leakage` and never contested the premise at all, three
were selection artefacts, and **two are genuine — both inside `invented_tool`,
and both resolved in the direction the reviewer chose by a rule nobody had
written down.** Four of the five sub-classes show **zero** disagreement.

### The next step, and its decision rule, fixed in advance

Run D13: two reviewers, 24 items, holding `decision_rule.md` and not the Phase 3
labels.

| κ | conclusion |
|---|---|
| **≥ 0.7** | The category is crisp. Phase 5 = implement, scoped to the sub-classes the reviewers agreed on, then rerun the OOD evaluation. |
| **0.4 – 0.7** | Crisp in parts. Implement `invented_outcome` only — unanimous in the labels, worst consequence, ~⅓ of the ceiling — and leave `invented_tool` unencoded. |
| **< 0.4** | **Two people given a written rule cannot agree on what an unsupported premise is.** Do not encode it. Publish that as the finding: it is a stronger result than another rule, and it is the answer this phase was commissioned to be able to give. |

Thresholds set **before** the labels exist, so the conclusion cannot be chosen
after seeing the number.
