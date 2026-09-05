# Phase 4B — Validator Ground Truth & Unsupported Premise Research

**Recommendation: RESEARCH FURTHER.** Justification and the pre-committed
decision thresholds are in `unsupported_premise_business_case.md`.

## Success criteria — as they stand

| | status |
|---|---|
| κ measured | **NOT MET — needs a second human.** Sample built and ready (`kappa_sample.csv`) |
| Contested pattern receives written labelling rule | **MET** — `decision_rule.md` |
| Second blind review completed | **NOT MET — needs a second human.** Same file |
| Unsupported premise quantified | **MET** — `unsupported_premise_business_case.md` |
| No validator changes | **MET** — `git diff` on `api/` is empty for this phase |
| No threshold tuning | **MET** — nothing in `api/` was touched at all |

Two of six require a person who is not me. Everything that does not is done.

## Files

| file | what it is |
|---|---|
| `unsupported_premise_taxonomy.md` | **D11.** Five sub-classes derived from data. Four are undisputed; the dispute is confined to `invented_tool` |
| `decision_rule.md` | **D12.** Accept/reject/edges/counterexamples per sub-class. A specification to be tested, not a finding |
| `kappa_sample.csv` | **D13.** 24 blind items — 6 probe levels, 7/7 accept-reject balance on the labelled half, **10 never-labelled OOD items** |
| `.kappa_key.csv` | Sealed. Reviewer 1's verdicts. **Do not open before labelling** |
| `disagreement_matrix.md` | **D14.** Why humans disagreed — four causes, measured. Of 13 apparent disagreements, **2 are genuine** |
| `unsupported_premise_business_case.md` | **D15.** Frequency, upper-bound gain, upper-bound risk, recommendation |

## The three numbers

- **100% of the validator's misses are this class.** Phase 3's entire
  false-negative mass is premise rejections.
- **24.1%** — precision of the only currently specifiable predicate. It fires on
  ~32% of all questions and would roughly double the reject rate.
- **2, not 13** — genuine human disagreements, once reasons are read rather than
  verdicts. Phase 3 overstated this, and the correction is in D11 and D14.

## To run D13

Two reviewers, independently, no discussion first. Each labels
`kappa_sample.csv` holding `decision_rule.md` and **not**
`studies/phase3/human_review_sample_completed.csv` — 14 of the 24 items are in
it, and reading it turns a reliability test into a memory test.

Then:

```
python scripts/interview_study.py score \
  --reviewed  <reviewer1 file> \
  --reviewer2 <reviewer2 file>
```

κ thresholds are fixed in advance in the business case, so the conclusion cannot
be chosen after the number is seen.
