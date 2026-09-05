# Phase 4A vs Phase 3 — comparison

Two validator changes, each traced to a Phase 3 finding. No corpus entry added
(C6). No threshold moved (C7) — `DUPLICATE_JACCARD` is still 0.37.

## The headline, stated before the tables

| Success criterion | Status |
|---|---|
| κ reported | **NOT MET — blocked on a second human.** See `reviewer_agreement.md` |
| No regression in corpus metrics | **MET** — M6 100 / 100 / 100 / 100, 76 entries, 0 mismatches |
| Precision > 54% | **IN-SAMPLE ONLY: 65.8%.** Out-of-distribution, unmeasured — needs labels |
| Recall > 50.7% | **NOT MET: 46.9% in-sample**, and the reason is understood (below) |
| Every change justified by a Phase 3 finding | **MET** — findings 3 and 2, both cited in code |
| No threshold tuning against the Phase 3 sample | **MET** — 0.37 unchanged, asserted by a test |

**Two of six are unmet and one is only half-answered. None is being quietly
closed.**

---

## 1. What can be measured without labels — and it is a clean 2×2

Comparing Phase 3's reject rate to Phase 4A's compares two things at once: a
changed validator *and* a different population (seed 20260906, 44 interviews
against 68, 8 families against 9). So each validator was run over each dataset.

### Overall reject rate

| | Phase 3 data (486 judged) | Phase 4 data (304 judged) |
|---|---|---|
| **Old validator** | 25.5% | 26.3% |
| **New validator** | **19.3%** | **20.7%** |

**The data barely moves it (25.5 → 26.3); the validator moves it about six
points, consistently, on both.** That is the isolation the 2×2 exists to give.

### `duplicate_content` fire rate — the rule that was redesigned

| | Phase 3 data | Phase 4 data |
|---|---|---|
| Old validator | 8.23% | 6.58% |
| **New validator** | **2.88%** | **1.64%** |

A **75–80% reduction on both datasets.** In Phase 3 this rule was the second
most-fired and ran at 38.5% precision — it was firing three times for every two
times it was right.

### `answer_leakage` — the `P1`/`p95` fix

| | Phase 3 data | Phase 4 data |
|---|---|---|
| Old validator | 11.32% | 12.83% |
| New validator | 10.49% | 11.84% |

About one point on both, which is the right size: severity labels and
percentiles are a narrow slice of questions, and the fix was meant to be narrow.

### Unchanged rules, unchanged rates

`no_claim_anchor`, `multiple_fact_targets`, `scope_drift`,
`unsupported_metric` and `hypothetical_misuse` fire at **identical** rates under
both validators on both datasets. Nothing leaked sideways.

`hypothetical_misuse` is **still zero** — now 0 fires in 790 judged questions
across two independent runs. Still not an argument for deleting it; see the
Phase 3 analysis.

## 2. What needs labels, and the honest in-sample number

Precision, recall, accuracy and F1 all require a human verdict. The 100 Phase 3
labels can be reused by re-running the **new** validator over the **same**
questions — but the sample was stratified on the *old* verdicts, so each item
carries a design weight from its old stratum (362/50 = 7.24 for accepts,
124/50 = 2.48 for rejects) and the cells are Horvitz–Thompson sums.

| | Phase 3 | Phase 4A in-sample | Δ |
|---|---|---|---|
| **Precision** | 54.0% | **65.8%** | **+11.8** |
| **Recall** | 50.7% | **46.9%** | **−3.8** |
| **Accuracy** | 74.9% | **78.9%** | **+4.0** |
| **F1** | 52.3% | **54.8%** | **+2.5** |

**This number is optimistically biased and must not be quoted as the result.**
Both changes were derived by a human reading these exact disagreements, which is
the slow version of overfitting. It is reported for direction.

Per-rule precision, same caveat:

| rule | Phase 3 | Phase 4A |
|---|---|---|
| `answer_leakage` | 79.2% | **86.4%** |
| `duplicate_content` | 38.5% | **100%** (weighted n=7) |
| `no_claim_anchor` | 28.6% | 28.6% |
| `multiple_fact_targets` | 0% | 0% |
| `scope_drift` | 0% | 0% |

## 3. Why recall went DOWN, and why no change here could have prevented it

Recall lost exactly two sampled true rejects: **r0009** and **r0037**.

| | claim | question | human said |
|---|---|---|---|
| r0009 | Coached four inside sales reps on closing technique | *"How did you capture the jump in conversion rates from 15% to 25%?"* | reject — invents the figures |
| r0037 | Ran 40 user interviews to find the top three pain points | *"What specific actions did you take in the transcription tool during the interviews?"* | reject — invents the tool |

Neither is a duplicate. **`duplicate_content` was blocking them by accident**,
and both are `unsupported_premise` — the defect class Phase 3 found has no rule
and which Phase 4A was explicitly told **not** to implement yet.

So the recall criterion is **not reachable within this phase's mandate.** The
two changes removed a rule's incidental catches; only the missing rule can
replace them legitimately. This is the strongest available evidence for building
`unsupported_premise`, and it is quantified: **two of the five true rejects the
old rule caught were caught for the wrong reason.**

The alternative — keeping a rule that is right 38.5% of the time because it
sometimes stumbles onto the right answer — is not a validator, it is a
coincidence.

## 4. The first design of the rule-2 fix was wrong, twice

Recorded because the failed attempts carry more information than the fix.

**Attempt 1 — compare only same-claim priors.** Phase 3 finding 2 read eight
false rejects, all shaped *"How did you measure the success of X?"*, and
concluded the rule was penalising a reused frame across different claims.
Measured over all 519 rows: **every one of the eight triggers was same-claim and
not one was cross-claim.** The eight sat in eight different interviews and were
never compared to each other — they only looked alike to a human reading a
shuffled sample. Claim-id gating changed no verdict in the entire dataset and
cost two true rejects. Reverted, with a test asserting the parameters are gone.

**What was actually wrong** is a conflict between two rules. Rule 7 *requires* a
question to share subject words with its claim. Rule 2 then counted those same
words as duplication evidence. The ladder walks one claim through five probe
levels, so the better anchored a question is, the more likely rule 2 called it a
repeat.

**Attempt 2 — subtract the claim's words from both sets.** Also wrong, also
measured: when the claim's words are what *distinguishes* two questions,
stripping them collapses the remainder to near-identity and the score goes **up**.
It turned three accepts into rejects.

**The fix that shipped** subtracts the claim's words from the *shared* set only.
Monotone non-increasing, so it can never newly condemn a pair. For a rule sitting
at 38.5% precision, "cannot create a new false reject" is worth more than the
extra sensitivity.

## 5. Also fixed, found in passing

`(interview_id, attempt_index)` is not a unique dataset key — **136 distinct
across 519 rows**, because `attempt_index` restarts at 1 for every planner slot.
The confusion matrix keys on `row_id` and never used this index, **so no
published Phase 3 number moved**; the auto-generated disagreement listing did
use it and would have quoted the wrong question against the right verdict.
`order_index` now travels in the sealed key.

## 6. To finish this phase

1. **Label `studies/phase4/human_review_sample.csv`** — 100 blind items from the
   new dataset, 50/50, seed 11. This is what settles precision and recall
   out-of-distribution and turns the in-sample figures above into a real result.
2. **`kappa_overlap_sample.csv`** — 20 items, a second rater, ~10 minutes.
3. **`contested_pattern_relabel.csv`** — 13 items against a written decision
   rule. This is the gate on `unsupported_premise`: a category that cannot be
   labelled consistently cannot be specified.

## Cost

| | |
|---|---|
| Phase 4A out-of-distribution run | **$2.43** (44 interviews, 320 rows, 832 calls) |
| Phase 3 | $4.70 |
| **Running total** | **$7.13** |
