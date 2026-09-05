# P2-02 — `question.validate()`

Seven-section spec. Owner **A**, task 2 of 5. **Depends: P2-01.**

The same pattern as `evidence.enforce_verbatim()`: the model produces, Python
decides whether to accept it. No LLM call in this file's new code.

---

## 1. Task

Add a pure function to `api/engine/question.py`:

```python
def validate(
    question: str,
    *,
    claim_text: str,
    claim_metric: str | None,
    probe_level: ProbeLevel,
    prior_questions: Sequence[str] = (),
    transfer: TransferSpec | None = None,
    target_claim_text: str | None = None,
) -> QuestionValidation
```

returning `QuestionValidation(accepted: bool, violations: tuple[str, ...])`.

A `NamedTuple`, in `question.py`, **not** in `api/schemas.py` — that file is
frozen and this is an internal contract, the same call `FamilyMatch` made in
P1-06. Violation names are stable strings, because they are stored in a DB
column (P2-03) and counted in a metric (P2-05); renaming one later invalidates
history.

## 2. Current State

- `generate_question()` returns `GeneratedQuestion(question, probe_level)` and
  nothing inspects the text. Whatever the model returns is what the candidate
  is asked.
- `FALLBACK_QUESTIONS` (6) and `TRANSFER_FALLBACKS` (2 templates) are the
  no-model path. **Three of them would fail a naive validator**, verified by
  reading them: VALIDATION opens *"Tell me more about this…"*, INCIDENT opens
  *"Tell me about one specific time…"*, and all three transfer strings open with
  *"Suppose"*. They are exempt by construction — `validate()` is called on model
  output only (P2-03) — and a test pins that.
- `plan_next()` already supplies everything the validator needs: the claim, the
  probe level, a single `target_dimension`, and on TRANSFER a `TransferSpec`
  carrying `target_claim_id`. **No new plumbing into the planner.**
- `PROBE_BRIEFS[DECISION]` is *"What did you decide to do about it, and what did
  you consider but decide against?"* — two clauses, one subject. Rule 3 must
  accept this shape.

## 3. Files To Change

| File | Change |
|---|---|
| `api/engine/question.py` | `QuestionValidation` NamedTuple, `validate()`, seven rule predicates, `_content_words()` helper |
| `tests/test_questions.py` | Rule tests + the three M6 metrics over the golden set |

Not `api/schemas.py`. Not `orchestrator.py` (that is P2-03/P2-04). Not
`taxonomy.py`.

## 4. Implementation Steps

**Shared primitive first.** `_content_words(text) -> set[str]`: lowercase,
strip punctuation, drop a small stopword list and drop pure numerals. Used by
rules 2, 6 and 7. One implementation, so three rules cannot disagree about what
a word is.

**The numeral rule, stated once because rules 1 and 5 are two halves of it.**
Every numeral token in a generated question comes from exactly one of three
places, and two of them are defects:

| numeral appears in | verdict | rule |
|---|---|---|
| `claim_metric` or `claim_text` | **reject** | 1 `answer_leakage` — we supplied the answer |
| a prior *answer* (candidate's own words) | accept | — |
| nowhere | **reject** | 5 `unsupported_metric` — we invented evidence |

So the practical shape is: **a generated question should contain no numerals at
all**, unless the candidate said them first. That is a sharp, testable line, and
it is why rule 7 must anchor on *words* — see below.

| # | Rule | Deterministic definition |
|---|---|---|
| 1 | `answer_leakage` | any numeral token in the question also appears in `claim_metric` or `claim_text` |
| 2 | `duplicate_content` | content-word Jaccard against any prior question ≥ the threshold **measured in P2-01** (not guessed) |
| 3 | `multiple_fact_targets` | the question resolves to **≥ 2 distinct fact keys** for the family, via `fact_keys(family)` labels and aliases. **Not evaluated on TRANSFER** — see below |
| 4 | `hypothetical_misuse` | matches `suppose · imagine · what would you · if you were · hypothetically` **and** `probe_level != TRANSFER`. Asserted both ways |
| 5 | `unsupported_metric` | a numeral token appearing in neither the claim nor any prior answer |
| 6 | `scope_drift` | non-TRANSFER: question shares no content word with the claim but ≥ 2 with another claim. TRANSFER: question shares no content word with `target_claim_text` |
| 7 | `no_claim_anchor` | question shares **zero** non-numeric content words with `claim_text` or the claim-type label |

**Rule 3 is a set-cardinality test, not a grammar test.** It was specified as
`double_barrel` and renamed before anything persisted it. Grammar was the wrong
axis: `PROBE_BRIEFS[DECISION]` deliberately asks *"What did you decide to do
about it, and what did you consider but decide against?"* — two clauses, one
subject — and a grammar rule rejects it. Counting **resolved fact keys** gets
both of the review's examples right:

    "How did you reduce AHT and improve CSAT?"     -> {aht_seconds, csat_pct} = 2  reject
    "What did you decide, and what did you reject?" -> {}                      = 0  accept

Two surface forms of one metric collapse correctly — "AHT" and "average handle
time" both resolve to `aht_seconds`, so that is one target, not two. Token
counting gets this wrong; key resolution gets it right. The vocabulary is
already config, so the rule costs no new data and stays cohort-neutral.

`job_family` therefore reaches `validate()`. That is permitted: A's contract
forbids family reaching **`select_transfer()`**, the planner, and explicitly
allows it reaching the wording call, which already receives it. Validation is
not selection.

**RULE 3 IS NOT EVALUATED ON TRANSFER.** Found while authoring the corpus
(`q63`): a valid T1 probe pairs the method from one claim with the problem from
another, so when both subjects are metrics it names **two fact targets by
construction**. Rule 6 already constrains which second subject is permitted, so
running rule 3 here would be two rules on one boundary — the double-counting
that corrupts the reject-rate metric.

**Rule 2's threshold is 0.37, measured not guessed.** The corpus carries the
ladder under `rule_2_threshold`. The measurement also inverted an intuition:
**aggressive stopword removal destroys the signal** (bands overlap by −0.083, no
threshold exists), because the interrogative frame *is* what repeats. Use the
minimal stopword list the corpus records.

**Rules 1 and 7 pull in opposite directions and that is intentional.** 1 forbids
the claim's numbers, 7 requires the claim's words. A question is well-formed when
it names the subject and withholds the figures — which is exactly what a probe
is for. P2-01's adversarial pairs pin the boundary.

**Rule 6 on TRANSFER is stronger than an exemption.** `select_transfer()` picks
`target = others[0]`, deliberately a *different* claim, and T1 is the majority
path — so scope drift **is** the mechanism, and exempting TRANSFER wholesale
would leave it unchecked. Instead the rule inverts: a transfer question must
reference **the planner's** target claim. Drift to a third claim is still a
defect.

**Order of evaluation is fixed and all rules run.** `violations` collects every
rule that fired, not the first — P2-05 counts them per rule, and short-circuiting
would bias every rule after the first toward zero.

**No rule may read fluency, grammar, register, politeness or length-as-quality.**
Structural test, mirroring the three existing anti-bias invariants.

## 5. Tests

**Per-rule, 2 tests each (14):** one `reject` case, one adversarial `accept` case
that a naive implementation would reject. Each verified to fail with its own rule
predicate stubbed to `False`.

**Metric tests over the golden set — the acceptance gate:**

| Test | Asserts | Target |
|---|---|---|
| `test_validator_precision_on_golden_set` | of rejections, % truly `reject` | ≥ 95% |
| `test_validator_recall_on_golden_set` | of `reject` entries, % caught | ≥ 90% |
| `test_validator_accepts_good_questions` | of `accept` entries, % accepted | ≥ 95% |
| `test_reject_everything_validator_fails_the_corpus` | a stub returning always-reject scores ~0% on M6c | **must fail** |
| `test_validator_makes_no_model_call` | `/api/dev/llm` call count unchanged | 0 |
| `test_validator_is_deterministic` | same inputs, same violations, 50 iterations | exact |
| `test_violation_names_are_stable` | the seven literals, since they are persisted | exact |
| `test_every_fallback_question_would_pass_or_is_exempt` | documents which fallbacks fail and pins the exemption as the reason | — |
| `test_validator_never_reads_presentation` | two questions differing only in fluency get identical violations | exact |

## 6. Verification Commands

```bash
OPENAI_API_KEY="" DATABASE_URL="sqlite+aiosqlite:///:memory:" pytest -q tests/test_questions.py
OPENAI_API_KEY="" DATABASE_URL="sqlite+aiosqlite:///:memory:" pytest -q      # full suite, >= 186

# M6a/M6b/M6c printed for the ledger row
python - <<'EOF'
import json
from api.engine.question import validate
from api.schemas import ProbeLevel
g = json.load(open("tests/data/question_golden.json"))["questions"]
tp = fp = fn = ok_accept = n_accept = 0
for e in g:
    c = e["context"]
    v = validate(e["question"], claim_text=c["claim"], claim_metric=c.get("claim_metric"),
                 probe_level=ProbeLevel(c["probe_level"]),
                 prior_questions=c.get("prior_questions", ()),
                 target_claim_text=c.get("transfer_target_claim"))
    rejected = not v.accepted
    if e["verdict"] == "reject":
        tp += rejected; fn += not rejected
    else:
        n_accept += 1; ok_accept += v.accepted; fp += rejected
print(f"M6a precision {100*tp/(tp+fp):.1f}%  M6b recall {100*tp/(tp+fn):.1f}%  "
      f"M6c accept {100*ok_accept/n_accept:.1f}%")
EOF
```

## As built — 2026-09-05

| Metric | Target | Measured |
|---|---|---|
| M6a precision | ≥ 95% | **100%** (32 true / 0 false rejections) |
| M6b recall | ≥ 90% | **100%** (0 missed) |
| M6c accept-rate | ≥ 95% | **100%** (0 good questions rejected) |
| M6h attribution | ≥ 90% | **100%** |
| Tests | — | 93 in this file, **279** total |
| Model calls | 0 | 0, asserted structurally and via `/api/dev/llm` |

**100% on all four is a warning, not a result.** `routing_golden.json`'s own
header says a scorer that aces its own golden set has usually been tuned until
it did. Four fixes were made after the first run (75% precision, 79.5%
accept-rate) and each is a general defect rather than a special case:

1. **No inflection handling** — `users`/`user` and `interviewed`/`interviews`
   read as different subjects, so rule 7 mis-fired 9 times. Fixed with a crude
   auditable `_stem()`, the same approach as `taxonomy._INFLECTION`. This was
   the single biggest cause.
2. **`p95_latency_ms` resolved from neither "latency" nor "p95 latency"**, so
   rule 3 missed a genuine two-metric question. Percentile prefixes added to
   `_LABEL_MODIFIERS`.
3. **Rule 4 was English-only.** `q73` — *"Agar activation gir jaata to aap kya
   karte?"* — is a textbook hypothetical and the pattern list missed it
   entirely. `agar` added. This completes a marker list for the language the
   product operates in; it is **not** a judgement about register, which no rule
   here may make.
4. **Rule 7's anchor set was too narrow.** A question may anchor to the claim,
   its type label, **the last answer** (this is a WhatsApp thread — *"you
   mentioned it jumped to 520 seconds"* is anchored by any reasonable reading),
   and on TRANSFER the planner's target claim. Scope stays rule 6's job.

**The finding the metrics could not see.** With all four at 100%, rule ablation
showed **`duplicate_content` was worth ZERO recall**: every entry authored for it
was an unanchored fallback-style string that rule 7 caught anyway, so rule 2
fired but was never *necessary*. The corpus could not distinguish "rule 2 works"
from "rule 2 does nothing". Three anchored duplicates (`q74`–`q76`) were added
in this task so rule 2 is the only rule standing between them and acceptance.
Every rule now earns recall:

| rule disabled | recall lost |
|---|---|
| `answer_leakage` | 18.8 pts |
| `multiple_fact_targets` | 15.6 pts |
| `hypothetical_misuse` | 12.5 pts |
| `duplicate_content` | 9.4 pts |
| `unsupported_metric` | 9.4 pts |
| `scope_drift` | 6.2 pts |
| `no_claim_anchor` | 6.2 pts |

`test_every_rule_earns_its_place` keeps it that way, and
`test_no_single_rule_carries_the_whole_corpus` guards the opposite failure.

**Fallback violation snapshot shipped**, per the runtime/CI split agreed in
review: all six rendered fallbacks violate exactly `("answer_leakage",)` — they
quote the claim including its figures — and a companion test proves the base
text is otherwise clean, so a future reader cannot conclude the fallbacks are
simply bad.

## 7. Risks

| Risk | Mitigation |
|---|---|
| **Rule 3 is not deterministically separable** from the two-clause DECISION/OUTCOME briefs | P2-01 measures it first. If the corpus shows no clean separation, **drop rule 3 and report the measurement.** Six rules that fire correctly beat seven where one is a coin flip. This is a legitimate outcome of this task, not a failure |
| **Rules 1 and 7 conflict on a question that quotes the claim verbatim** — it anchors (7 passes) and leaks (1 fires) | Correct behaviour: quoting the claim including its numbers *is* leakage. The adversarial `accept` pair — claim words, no claim numbers — pins it |
| **Tuning rules until the corpus passes** — the failure `routing_golden.json` warns about in its own header | A rule change that raises M6b must not lower M6c, and both are printed on every run. Any threshold change is recorded in the ledger with both numbers before and after |
| **Rule 2's threshold guessed instead of measured** | Taken from P2-01's authored near-duplicate pairs. Guessing is what `MARGIN_FLOOR` avoided by measuring the 0.397/0.321 band first |
| Validator rejects so much that live interviews run mostly on fallbacks | M6e caps fallback rate at 5% in P2-05. If it exceeds that, the **rules** are wrong, not the fallback — do not weaken the fallback (counter-metric C5) |
| Latency: seven rules on every question | Pure string work on one short string, no I/O. Measure once; if it is not negligible the implementation is wrong |
