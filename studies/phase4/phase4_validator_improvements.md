# Phase 4A — Validator improvements

Two changes to `api/engine/question.py`. Each traces to a numbered Phase 3
finding, and each is pinned by tests naming the study rows that motivated it.

**Constraints honoured:** no corpus entry added (C6) · no threshold tuned
against the review sample (C7) · M6 unchanged at 100 / 100 / 100 / 100 over all
76 corpus entries, 0 mismatches.

Results, cost and the 2×2 isolation: `phase4_vs_phase3_comparison.md`.
κ status: `reviewer_agreement.md`. Research data: `unsupported_premise_dataset.csv`.

---

## Change 1 — a severity label is not a leaked figure

**Phase 3 finding 3. Study rows r0023, r0067.**

```python
# before
_NUMERAL = re.compile(r"\d+(?:[.,]\d+)?")
_numerals("Owned resolution time for P1 issues.")   # -> {'1'}
_numerals("Cut p95 latency from 900ms to 180ms.")   # -> {'95', '180', '900'}
```

`answer_leakage` compares the question's numerals against the claim's. With `P1`
yielding `1`, a question about P1 issues on a claim about P1 issues was blocked
for handing back a figure — where the figure was a severity label. The blind
reviewer accepted both questions.

The file already disagreed with itself: `_LABEL_MODIFIERS` strips `p95` from a
fact-key label *as a statistical modifier* two screens below.

```python
# after
_NUMERAL = re.compile(r"(?<![A-Za-z0-9])\d+(?:[.,]\d+)?")
```

**The digit in the lookbehind is not redundant.** With a letters-only guard,
`p95` merely fails to match at the `9`; the engine advances one character and
matches the `5`. Measured — the first cut produced `{'5'}`.

**The boundary is on the left only.** `480s`, `900ms`, `$1.2M` and `78%` are
real figures with a unit or symbol attached, and a trailing-letter guard would
drop every one of them. There is a test for exactly that.

**Effect:** `answer_leakage` fire rate down about one point on both datasets
(11.32 → 10.49% and 12.83 → 11.84%); in-sample precision 79.2 → 86.4%. A narrow
fix with a narrow effect, which is what it was meant to be.

## Change 2 — a question is not a duplicate for repeating the claim it must anchor to

**Phase 3 finding 2. Study rows r0014, r0029, r0045, r0053, r0055, r0080, r0091,
r0096 — all eight of the rule's false rejects.**

### The diagnosis in the Phase 3 analysis was wrong

It read eight false rejects, all shaped *"How did you measure the success of
X?"*, and concluded rule 2 was penalising a reused interrogative frame **across
different claims**. The first fix compared only priors belonging to the same
claim.

Measured over all 519 study rows: **every one of the eight triggers was
same-claim; not one was cross-claim.** The eight questions sat in eight
different interviews and were never compared to each other at all — they only
looked alike to a human reading a shuffled sample. Claim-id gating changed no
verdict anywhere in the dataset and cost two true rejects. It was reverted, and
a test asserts the parameters are absent so nobody re-adds it as an obvious
improvement.

### What is actually wrong: two rules in conflict

**Rule 7 requires a question to share subject words with its claim** — that is
what being anchored means. **Rule 2 then counts those same words as evidence of
duplication.** The probe ladder walks one claim through five levels, so every
question after the first is compared against a sibling that must, by rule 7,
repeat the claim's vocabulary.

**The better anchored a question is, the more likely rule 2 calls it a repeat.**

```
prior : "How many chat support tickets did you handle daily?"
now   : "How did you measure success in managing the chat support queue?"
claim : "Ran the chat support queue."              -> 0.385, tripped   (r0045)
```

The shared words are `how · did · you · chat · support` — and three of those five
are the claim's own.

### The fix, and the version of it that was also wrong

The obvious implementation subtracts the claim's words from **both** word sets.
That is wrong and was measured wrong: when the claim's words are what
*distinguishes* two questions, stripping them collapses the remainder to
near-identity and the score goes **up**. It turned three accepts into rejects.

What shipped subtracts them from the **shared set only**:

```python
shared = wa & wb
if discount:
    shared = shared - discount        # numerator only
return len(shared) / len(wa | wb)
```

Monotone non-increasing, so it can only ever forgive a pair, never newly condemn
one. For a rule already at 38.5% precision, *cannot create a new false reject* is
worth more than the extra sensitivity. r0045 goes 0.385 → 0.231 and passes; a
genuine reask still trips at 0.875.

**The threshold is untouched at 0.37.** The change is to what is compared, not to
where the line sits — which is the difference between a redesign and tuning
against the sample that measured it.

**Effect:** fire rate down 75–80% on both datasets (8.23 → 2.88% and
6.58 → 1.64%); in-sample precision 38.5 → 100% at weighted n=7.

## What was deliberately NOT changed

- **`unsupported_premise` was not implemented.** Task 4 says research first, and
  Phase 3 finding 4 is why: the reviewer split 6/7 on the very pattern the rule
  would encode. `unsupported_premise_dataset.csv` holds all 100 reviewed items
  with the 9 candidates flagged; `contested_pattern_relabel.csv` is the 13-item
  experiment that decides whether the category is specifiable at all.
- **`hypothetical_misuse` was not removed.** Now 0 fires in 790 judged questions
  across two independent runs. That is evidence `gpt-4o` does not make the
  mistake, not evidence the rule is wrong.
- **`multiple_fact_targets` and `scope_drift` were not touched**, despite 0%
  precision in Phase 3. n was 3 and 2. A rule is not condemned at n=3, and
  neither has a Phase 3 finding proposing a mechanism — only a count.
- **No corpus entry was added**, for anything. C6.

## Files changed

| File | Owner | Change |
|---|---|---|
| `api/engine/question.py` | A | `_NUMERAL` lookbehind; `_jaccard(discount=)`; rule 2 discounts claim words |
| `tests/test_questions.py` | A | 9 tests, each naming its study rows |
| `tests/test_study.py` | A | 2 tests for the dataset-key bug |
| `scripts/interview_study.py` | A | unique dataset key; `order_index` in the sealed key; `STUDY_DIR` |
| `scripts/phase4_rescore.py` | A | new — in-sample re-score with the HT estimator |
| `scripts/revalidate_dataset.py` | A | new — label-free rates, fills the 2×2 off-diagonal |

**`api/engine/orchestrator.py` was NOT changed by this phase.** The claim-id
plumbing was added and then reverted when the measurement said it did nothing.
