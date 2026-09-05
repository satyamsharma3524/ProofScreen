# Phase 3 — Validator disagreements

**32 disagreements out of 100 blind-labelled questions.** This is the
deliverable the plan (§0 C-ii) says carries the finding, and it does: the
confusion matrix says the validator is weak, this says *how* and *why*.

> Written by hand over the harness's output. Re-running
> `interview_study.py score` overwrites this file with the auto-generated
> skeleton — the analysis lives in git, not in the script.

**Nothing here has been applied.** Every proposal below is Phase 3's *output*,
to be taken as a separate evidenced change after the phase closes. Counter-metric
C7: tuning a threshold against the sample that measured it is fitting to the test
set, and it is the one move that makes the study worthless while making it look
successful.

---

## Headline

| | |
|---|---|
| M7a Precision | **54.0%** [40.4%, 67.0%] |
| M7b Recall | **50.7%** |
| M7c Accuracy | 74.9% |
| M7d F1 | 52.3% |

**Roughly half of what the validator blocks, a human would have sent; roughly
half of what a human would block, the validator passes.** On its rejects it is
barely better than a coin. The corpus reads 100% on M6a–M6c and M6h. Both
numbers are correct and they are about different populations — which is exactly
what this phase existed to find out, and why a corpus authored by the person who
wrote the rules can only ever detect regression.

## Root causes — all 32, one each

| root cause | n | direction |
|---|---|---|
| **`unsupported_premise`** — no rule exists for it | **9** | false accept |
| `threshold_issue` — `duplicate_content` frame reuse | 8 | false reject |
| `no_claim_anchor` — lexical anchoring cannot see synonymy | 5 | false reject |
| `answer_leakage` — figure as reference point, not as answer | 3 | false reject |
| `multiple_fact_targets` — the claim itself owns both metrics | 3 | false reject |
| `tokenisation` — `P1` and `p95` parsed as claim figures | 2 | false reject |
| `scope_drift` — lexical, same cause as `no_claim_anchor` | 2 | false reject |

`transfer_issue` and `hypothetical_misuse`: **zero**. Both TRANSFER items in the
sample (r0065, r0087) were labelled correctly by the validator.

**The taxonomy I briefed was incomplete, and that is a finding about my own
method.** Eight of its ten causes are rule names, so a defect class with *no
rule* cannot appear in it. The largest single cause below is exactly that.

## M7f — per-rule precision

| rule | agreed / rejected | precision |
|---|---|---|
| `unsupported_metric` | 1 / 1 | 100% (n=1, ignore) |
| **`answer_leakage`** | **19 / 24** | **79.2%** |
| `duplicate_content` | 5 / 13 | 38.5% |
| `no_claim_anchor` | 2 / 7 | 28.6% |
| `multiple_fact_targets` | 0 / 3 | **0%** |
| `scope_drift` | 0 / 2 | **0%** |

`answer_leakage` is the only rule pulling its weight — and it is also the most
frequently fired (55 of 127 violations in the full dataset). **The validator's
useful behaviour is concentrated in one rule.**

---

## Finding 1 — the biggest defect class has no rule (9 of 9 false accepts)

Every single question the validator passed and the human blocked is the same
thing: **the question asserts a fact the claim never established.**

| | claim | question asserts |
|---|---|---|
| r0003 | Grew activation 41% → 63% by rebuilding the first-run flow | *a product analytics dashboard* |
| r0036 | Reduced reopen rate by a third. | *macros* |
| r0037 | Ran 40 user interviews… | *a transcription tool* |
| r0093 | Owned attrition, engagement surveys, onboarding | *"the system"* |
| r0052 | Reacted quickly to shifting priorities | *project management tools* |
| r0018 | Ran daily stand-ups, tracked deliverables | *technical delays* |
| r0025 | Handled vendor coordination, invoice follow-up | *a temporary solution for a vendor delay* |
| r0041 | Coached four inside sales reps | *an increase in conversion rate* |
| r0012 | Led campus hiring for 120 offers | *team performance metrics* |

This is the **non-numeric sibling of `unsupported_metric`**, which today catches
only numerals (`_NUMERAL` → `\d+`). A question that invents *"a 20% improvement"*
is caught; a question that invents *"the macros"* is not, and the second is more
dangerous — a candidate who never used macros must either say so and look
evasive, or play along and be scored on fiction.

It is also the exact defect the *product* exists to eliminate. Rule 4 of
`CLAUDE.md` kills hallucinated **quotes**; nothing kills a hallucinated
**premise** in the question that solicits them.

**Proposed (not applied):** an eighth rule, `unsupported_premise`. Hard, because
the legitimate version is indistinguishable at the lexical level — see Finding 4.

## Finding 2 — `duplicate_content` fires on frame reuse across different claims (8)

Five of the eight are the identical frame:

- r0029 *"How did you measure the success of addressing the top three pain points?"*
- r0045 *"How did you measure success in managing the chat support queue?"*
- r0055 *"How did you measure the success of the event pipelines after implementation?"*
- r0080 *"How did you measure the success of these quarterly reviews?"*
- r0091 *"How did you measure the success of your CASA growth strategies?"*

These are **different claims in the same interview**. `DUPLICATE_JACCARD = 0.37`
was measured on the corpus ladder, where distinct pairs sat ≤ 0.231 and duplicate
pairs ≥ 0.400. Live OUTCOME questions land in the gap.

The deeper issue is not the constant. **The rule compares question to question
and never looks at which claim is being probed.** Re-asking the same frame about
the *same* claim is the defect; re-using it on a *different* claim is a house
style. The rule cannot tell them apart because it is not given the information.

**Proposed:** condition rule 2 on `claim_id` before touching the threshold.
Raising 0.37 blindly would trade these 8 false rejects for the 5 true ones it
currently catches.

**Note what this does *not* overturn.** P2-01's ablation found `duplicate_content`
worth zero recall on the corpus; the full run found it the second most-fired rule
in the wild. Both were right. The corpus under-represented it, *and* what it
fires on in the wild is mostly wrong. Those are compatible and neither is an
argument for deleting it.

## Finding 3 — `P1` and `p95` are being read as claim figures (2, and it is a bug)

```
_numerals("Owned resolution time for P1 issues.")  ->  {'1'}
_numerals("Cut p95 latency from 900ms to 180ms.")  ->  {'95', '180', '900'}
```

`P1` is a severity label. `p95` is a percentile. Neither is a claimed figure, and
`answer_leakage` fires on both. r0023 and r0067 are blocked for "leaking" the 1
in P1.

Worse, `p95` interacts with `_LABEL_MODIFIERS`, which already strips `p95` from
fact-key *labels* — so the codebase knows `p95` is a modifier in one place and
treats it as a number in another.

**Proposed:** require a word boundary that is not a letter before the digits.
Cheap, contained, and the only proposal here that is unambiguously a bug fix
rather than a judgement call. Owner A; `question.py`.

## Finding 4 — the human's own labels split 6/7 on the biggest defect class

This is the most important thing in the document and it limits every number above.

Filtering the sample to *"the question names a tool or system the claim never
states"* — the Finding 1 pattern — gives **13 items the human split 6 accept / 7
reject.** Two pairs are decisive:

| | claim | question | verdict |
|---|---|---|---|
| r0052 | *Reacted quickly to shifting priorities…* | "…prioritize updating **project management tools**…" | **reject** |
| r0072 | *Reacted quickly to shifting priorities…* | "…actions did you take in the **project management tools**…" | **accept** |
| r0090 | *Managed a team of 35 agents…* | "What steps did you take in **the system** for daily attendance tracking?" | **accept** |
| r0093 | *Owned attrition, engagement surveys…* | "What specific actions did you take in **the system** to manage attrition?" | **reject** |

Same claim, same invented tool, opposite verdicts.

**So a meaningful part of the 46% precision gap is ground-truth noise, not
validator error — and with no second reviewer there is no κ to say how much.**
Plan §0 F4 specified a 20-item overlap for exactly this; it was not run. Under
Decision 5 the metrics are published anyway, which is right, but they should be
read as **a lower bound on the validator with an unmeasured error bar**.

**The inconsistency is itself a product finding.** If a thoughtful reviewer
cannot apply "does the question assume something not in the claim?" consistently
across 13 items, then `unsupported_premise` cannot be specified as a crisp rule
either, and Finding 1's fix needs a sharper definition before it needs code.

**Recommended, cheap:** re-label just those 13 items with a written decision rule
(*"reject if the assumed tool/event could plausibly not exist for this
candidate"*), then have a second person label 20. That is ~15 minutes and it
converts the largest finding from suggestive to solid.

## Finding 5 — `answer_leakage` earns its keep, with one clean exception (3)

79.2% precision, best of the six, and 19 of its 24 rejects were things like
r0006 *"How long did you maintain the 110% target achievement?"* — the exact
defect, correctly caught.

The three misses share one principle. The human accepts a figure used as a
**reference point** and rejects one used as **the thing being asked for**:

- r0030 *"a week when SLA dropped **below 97%**"* — 97 locates the question; the answer is the week
- r0068 *"keeping occupancy **above 85%** was challenging"* — same
- r0066 *"How long did each of the **18** experiments take?"* — 18 identifies the set; the answer is duration

That is a real, learnable distinction, and the rule as written cannot make it —
it compares numeral sets and nothing else. **Not proposing a fix.** At n=3, and
against a rule that is the only one working, the risk of breaking 19 good rejects
to rescue 3 is plainly bad odds. Recorded for whoever revisits it with more data.

## Finding 6 — `multiple_fact_targets` and `scope_drift` are 0-for-5

Both fail the same way: the claim itself spans the two things the rule objects to.

- r0034 *"shrinkage **or** occupancy numbers were unexpectedly high or low"* on a
  claim that says *"Owned shrinkage **and** occupancy"* — one question about one
  claim.
- r0040 *"reducing AHT **and** maintaining occupancy"* on *"Brought AHT down… and
  kept occupancy above 85%"* — same.
- r0085 *"prioritize **P1 issues**"* on *"Led the **escalation desk**"* — scored as
  drift because the words do not overlap; P1 triage *is* escalation-desk work.

Rule 3 counts fact keys in the question without checking how many the **claim**
names. Rule 6 intersects word sets and has no synonymy. n is small (3 and 2), so
these are directional — but both read 0%, and neither has a single confirmed
true reject in the sample.

---

## What must not happen next

- **Do not tune `DUPLICATE_JACCARD` against this sample.** C7. Finding 2's fix is
  structural (condition on `claim_id`), and the threshold should be re-measured
  afterwards on *new* data.
- **Do not delete `hypothetical_misuse`** because it fired zero times, or
  `multiple_fact_targets`/`scope_drift` because they went 0-for-5 at n≤3. A rule
  that costs nothing and guards against a cheaper model or a prompt regression is
  not dead, and n=3 is not a verdict.
- **Do not add corpus entries for anything here.** C6. The corpus is a regression
  detector; feeding it this study's findings makes it a memory of this study.
- **Do not treat 54% as the validator's ceiling.** Finding 4 says an unmeasured
  part of the gap is the referee.

## Recommended order, if this becomes Phase 3's output

1. **Finding 3** — the `P1`/`p95` tokenisation bug. Unambiguous, contained, no
   judgement call.
2. **Finding 4** — 15 minutes of re-labelling plus a 20-item κ. Everything else
   is worth less until the ground truth is solid.
3. **Finding 2** — condition rule 2 on `claim_id`; re-measure the threshold on new
   data, never on this sample.
4. **Finding 1** — `unsupported_premise`, but only after Finding 4 produces a
   definition crisp enough to test.
