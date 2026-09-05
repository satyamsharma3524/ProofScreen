# Phase 5 — `unsupported_premise` research

**Recommendation: DO NOT IMPLEMENT.** The full argument and every number are in
[`unsupported_premise_research.md`](unsupported_premise_research.md).

This is a *recommendation only*. Nothing was built, and the four standing
prohibitions were verified rather than asserted:

| | status |
|---|---|
| `unsupported_premise` not implemented | **held** — no rule written |
| validator code unmodified | **held** — `git status api/` empty; `validate()` was called read-only to measure overlap |
| corpus unmodified | **held** — `tests/data/question_golden.json` untouched (C6) |
| thresholds untuned | **held** — `DUPLICATE_JACCARD` still 0.37 (C7) |
| Phase 3 untouched while under review | **held** — `studies/phase3/` empty in `git status` |

## The three findings

1. **The category is real and it is the whole recall problem.** All nine of the
   validator's false negatives in the reviewed sample are premise rejections.
2. **Two reviewers given the written rules agree at κ = 0.477** on whether a
   premise defect is present. Six-way sub-type agreement is *higher* (0.656):
   they agree on *which* defect and disagree on *whether* there is one — the
   worst shape for a rule whose only job is to decide that.
3. **The rules score 100% on examples I wrote and 51% on real questions they say
   to accept.** Any κ measured only on authored examples would have reported
   ~0.95 and recommended shipping.

## Files

| file | what it is |
|---|---|
| `unsupported_premise_research.md` | **the deliverable.** Taxonomy, rules, agreement, ceilings, impact, recommendation |
| `decision_rules.md` | the written rules, handed verbatim to the second reviewer |
| `taxonomy_examples.csv` | 364 labelled examples, ≥50 per sub-type, provenance on every row |
| `premise_candidates.csv` | 227 candidate premise objects mined from 839 real questions |
| `reviewer_sample.csv` | 202 blind items, balanced 132 defect / 70 clean |
| `.reviewer1_key.csv` | **sealed.** Reviewer 1's labels. Do not open before labelling |
| `reviewer_model_labels.csv` | Reviewer M's independent labels ($1.34 of `gpt-4o`) |
| `agreement.txt`, `measurements.txt` | captured output of the two scoring scripts |

Instruments, none imported by `api/`: `mine_premises.py` · `curate.py` ·
`constructed.py` · `reviewer_sample.py` · `reviewer_model.py` ·
`score_agreement.py` · `measure.py`.

## Reproducing

```bash
python studies/phase5/mine_premises.py      # 839 questions -> candidates
python studies/phase5/curate.py             # candidates + constructed -> examples
python studies/phase5/reviewer_sample.py    # blind sample + sealed key
python studies/phase5/measure.py            # overlap, determinism, ceilings, impact
python studies/phase5/score_agreement.py    # kappa, once a second labelling exists
```

Only `reviewer_model.py --run` costs money, and it needs `OPENAI_API_KEY`.

## The one thing still missing

**A second human reviewer.** `reviewer_sample.csv` is ready and the key is
sealed. Reviewer M measures whether the rules are *self-sufficient*; it cannot
measure whether they are *correct*. Two humans, 202 items, ≈90 minutes, $0 — and
it is the item that has now blocked three consecutive phases.
