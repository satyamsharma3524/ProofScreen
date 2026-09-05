# Phase 4A — Reviewer agreement (κ)

**Status: BLOCKED ON A SECOND HUMAN. κ is not reported, and nothing here
substitutes for it.**

## Why this is empty rather than estimated

Cohen's κ measures agreement between two *independent raters*. There is one
rater. Three tempting substitutes were considered and rejected:

1. **Me as the second rater.** I wrote the rules under test and generated the
   pipeline that produced the questions. My labels would be anchored to the
   validator, which would inflate κ *and* inflate every downstream metric that
   uses it as a quality warrant. Not independent, so not a rater.
2. **A model as the second rater.** `CLAUDE.md` rule 1 — the model never judges.
   A κ produced this way would read on the page as "reviewer agreement" while
   measuring something else entirely, which is worse than no number.
3. **Re-labelling by the same person.** That is test–retest reliability, not
   inter-rater reliability. It is a real measurement and a useful one, but it
   answers "is this person consistent?", not "is this category shared?" — and
   Phase 3 finding 4 is specifically about whether the category is shared.

The machinery is built and tested (`interview_study.cohens_kappa`,
`score --reviewer2`). What is missing is one person and about 10 minutes.

## What to do — two files, two different questions

### 1. `kappa_overlap_sample.csv` — 20 items, the headline κ

A **random** sample of 20 from the 100 already labelled (seed 4), in the same
blind format. Random on purpose: a κ computed over items chosen because they
looked hard would not describe the sample it is meant to qualify.

Give it to a second person with §12 of `docs/PHASE_3_VALIDATION_STUDY.md` as
their brief and **without** showing them the first reviewer's labels. Then:

```
python scripts/interview_study.py score \
  --reviewed studies/phase3/human_review_sample_completed.csv \
  --reviewer2 studies/phase4/kappa_overlap_sample.csv
```

**Reading it, decided in advance so the threshold is not chosen after seeing the
number:** κ ≥ 0.6 means the Phase 3 and Phase 4 precision figures stand as
written. κ < 0.6 means an unmeasured share of the 46-point Phase 3 precision gap
belongs to the referee rather than the validator, a warning banner is attached to
both matrices (Decision 5 — published, never suppressed), and
`unsupported_premise` should not be specified until the category is sharper.

### 2. `contested_pattern_relabel.csv` — 13 items, the one that matters more

These are the 13 items on the pattern *"the question names a tool, system or
event the claim never states"*, which Phase 3 finding 4 measured the first
reviewer splitting **6 accept / 7 reject** — including the same claim and the
same invented tool labelled both ways (r0052 vs r0072, r0090 vs r0093).

That pattern is the whole of `unsupported_premise`, the largest defect class in
the study and all nine of its false accepts. **If it cannot be labelled
consistently it cannot be specified as a rule**, and building one anyway would
encode a coin flip.

Re-label these 13 against a written decision rule agreed *before* looking —
something operational rather than aesthetic, e.g.:

> **Reject** if the named tool, system or event could plausibly not exist for
> this candidate, so that a truthful answer would have to begin by correcting
> the question. **Accept** if it is a generic category the claim's work
> necessarily involves (a CRM for a quota, an ATS for a recruiting funnel).

That rule is a starting point, not a finding. Whether it survives 13 items is
the actual experiment.

## What is already known without a second rater

The first reviewer's **internal** inconsistency on the contested pattern is
measurable from the existing labels alone and does not need κ: 6 accept /
7 reject across 13 structurally similar items, with two exact contradictions.
That is reported in Phase 3 finding 4 and stands.

**It bounds the Phase 4A result.** In-sample precision rose 54.0% → 65.8%; part
of the remaining 34% "false rejects" may be labelling noise rather than validator
error, and there is currently no way to say how much.
