# Phase 3 — Real Interview Validation Study

**Status: APPROVED 2026-09-05. In execution.**
Five decisions ruled on; recorded verbatim in §0 D. Two amendments came with
them (κ, and the bound on statistical machinery) and are folded in below —
struck text is left visible rather than deleted, because a plan that quietly
becomes what it ended up being is not a plan.

Format: the ten-section §10 artifact, per C1 (phase level ⇒ full form).
This is the phase's **only** new planning document — C2 budget: 1 document
against 5 tasks.

---

## 0. Blockers and findings — read before §1

Raised under §9 (*State · Why · Impact · Options · Recommendation*) and §12.

### B1 — ~~There is no `OPENAI_API_KEY`~~ **CLEARED 2026-09-05**

**Key supplied.** `settings.llm_mode -> live`, `gpt-4o`. First live call
measured: **417 in / 26 out**, a valid model question, `source="model"`,
`attempts=1`, no violations. The section below is kept because it is why the
fixture-mode smoke test proves plumbing and nothing else.

**State (as measured before the key landed).**

```
settings.llm_mode      -> fixture
.env OPENAI_API_KEY    -> present, length 0
generate_question(...) -> source="fallback", attempts=1, violations=()   [all 3 levels tried]
```

**Why.** `llm.complete_json()` returns `fallback()` immediately when
`llm_enabled` is false. `generate_question()` sees `text == fallback.question`,
takes the `from_fallback` branch and **returns before `validate()` is ever
called** (`api/engine/question.py:710-718`).

**Impact.** A study run today produces N rows of which **100% are
`source=fallback`, 0% carry a validator decision, and 0% are model-generated**.
The dataset would be a transcript of six hard-coded strings. Every deliverable
downstream of it — confusion matrix, disagreement analysis — would be empty or,
worse, computed over fallbacks and reported as if it said something about the
validator.

**Options.**
1. Supply a real `OPENAI_API_KEY` and run the study as specified.
2. Run the harness in fixture mode as a **plumbing smoke test only**, clearly
   labelled, and hold the study until a key exists.
3. Cancel the phase.

**Resolved: (1).** Key supplied. (2) survives as `--fixture`, which the smoke
test uses and which is labelled in the file as measuring nothing.

**Budget is now a first-class constraint** — see §0 C.

### B2 — "Phase 3" already means something else in this repo

**State.** `docs/PHASE_2_EXECUTION_PLAN.md` designates D6–D10 (Evaluation
entity, versioning, replay, tenant isolation, score history) as **Phase 3**,
re-designated there because its own entry condition — M4a has produced a number
— is unmet. `docs/README.md` line 47 points at it under that name.

**Impact.** Two documents both called Phase 3 is the drift `EXECUTION_STANDARD`
C3 exists to prevent, and the one that bites is a future session reading the
wrong plan.

**RESOLVED (Decision 1).** This study is **Phase 3**; D6–D10 is **Phase 4**,
entry condition unchanged. Applied to `docs/README.md`, `CLAUDE.md` and
`PHASE_2_EXECUTION_PLAN.md`, with a renumber banner on the heading so a reader
arriving from an old link knows what moved.

### B3 — "Phase 4" now collides too, and this one is new

**State.** Decision 1 sends D6–D10 to Phase 4. The same message then sketches
**"Phase 4 — Interview Intelligence Quality"** (E1 claim-extraction quality ·
E2 scoring quality · E3 evaluation stability · E4 recruiter trust). Two Phase 4s.

**Impact.** Identical to B2, one number along. Left alone it recreates the drift
B2 was raised to kill, in the same week.

**Applied, minimally and reversibly:** the explicit ruling wins, so D6–D10 **is**
Phase 4 and E1–E4 is recorded as **Phase 5 (proposed)**.

**But the recommendation runs the other way, and it is worth thirty seconds.**
E1–E4 can start the day Phase 3 ends. D6–D10 cannot start at all — its entry
condition is *M4a has produced a number*, and M4a is at n = 0. Numbering phases
by when they can actually begin is the more useful convention, which argues for
**E1–E4 = Phase 4, D6–D10 = Phase 5**. It is a two-line swap either way. Say the
word and I do it; otherwise the explicit ruling stands.

**E1–E4 is the right next question regardless of its number.** This phase closes
`resume → claims → questions → validator`. It says nothing about
`interview → evaluation`, which is where the business value and — as the brief
says — the highest risk both sit. Noted here so it is not re-derived later.

### F1 — The rejected question text is never persisted, so the matrix cannot be built from stored rows

**State.** `orchestrator.ask_next()` writes `text=generated.question` — the
**final** question (`api/engine/orchestrator.py:802`). `QuestionAttempt` carries
attempt-1's *violations* but not attempt-1's *text*, and `generate_question()`
discards it (`question.py:735`).

**Impact.** Every validator **reject** is a question whose text no longer
exists anywhere. The brief's §4 — *"For every disagreement: quote question"* —
is unsatisfiable from the database. So is half the confusion matrix: the reject
stratum has no text to review.

**Options.**
1. Persist rejected attempts (new column or new table) — a schema change, a
   migration reset, and production storage for a research need.
2. Re-implement the two-attempt loop inside the harness — duplicates production
   logic and drifts from it the first time anyone edits `generate_question()`.
3. **Instrument `validate()` from the harness.** It is called once per attempt
   with that attempt's exact text and full context. Wrapping it records every
   attempt, accepted and rejected, with **zero production change**.

**Recommendation: (3).** It is a measurement instrument, not a behaviour
change; it cannot drift because it reads the real call; and it keeps `api/`
untouched, which is the state this phase should end in.

### F2 — Fallback questions have no validator decision and must not be scored as accepts

Two paths return `source="fallback"` (`question.py:718`, `:737`). Neither
question was validated — by design, and the comment at `:712` says why. A
fallback is not "the validator accepted it"; it is "the validator was never
asked."

**Consequence for the study:** fallback rows are **excluded from the confusion
matrix** and reported separately as **coverage** (M7e). Counting them as
accepts would inflate agreement with a number the validator never produced.
This is the same distinction `PHASE_1_SUCCESS_METRICS.md` M4a draws between a
result and `insufficient data`.

### F3 — A 50/50 blind sample is not the population, and naive recall from it is wrong

**State.** The brief specifies 50 accepts + 50 rejects. If the live reject rate
is, say, 8%, that sample over-represents rejects **~11×**.

**Impact.** Precision, recall and accuracy read off a 2×2 table built from a
stratified sample are **not** the population's precision, recall and accuracy.
Recall and accuracy would be badly wrong; only precision survives unweighted.

**Recommendation.** Keep the 50/50 sample — it is the right design, because it
buys statistical power exactly where rejects are scarce — and **reweight**.
Defining *positive = validator REJECTS* (the discriminative act, and the one
with an operational consequence):

```
N_R, N_A   population counts of validator rejects / accepts   (from the dataset)
r_R        fraction of SAMPLED rejects the human also rejects
r_A        fraction of SAMPLED accepts the human rejects

TP = N_R·r_R    FP = N_R·(1-r_R)    FN = N_A·r_A    TN = N_A·(1-r_A)

precision = r_R                       <- base-rate free, read directly
recall    = N_R·r_R / (N_R·r_R + N_A·r_A)
accuracy  = (TP+TN) / (N_R+N_A)
F1        = 2·precision·recall / (precision+recall)
```

`score` emits **both** tables — the raw sample 2×2 *and* the reweighted
population estimate — and labels which is which. At n=50 per stratum a Wilson
95% interval is roughly **±14 pp near 50%**, so every figure is published with
its interval. A point estimate without one invites reading 0.86 and 0.79 as
different numbers when they are not.

### F4 — One reviewer produces labels with no reliability estimate

With a single human, reviewer noise and validator error are indistinguishable.
A second reviewer labels a **20-item overlap** drawn from the same sample;
report Cohen's κ.

**AMENDED (Decision 5). ~~If κ < 0.6 the headline numbers are withheld.~~**
Metrics are **always published**; a low κ attaches a warning banner to the top
of `confusion_matrix.md` and to every affected figure, and does not suppress
anything.

**The amendment is right and my original was wrong.** Withholding assumed the
output is a verdict, so a noisy verdict is worse than none. The output is a
*learning artifact*, and a noisy number that says so beats no number — you can
still read it, you simply read it with the error bar the banner names. The
suppression rule also had a failure mode I had not thought through: it makes
the second reviewer's diligence able to *destroy* the study, which is a bad
incentive to build into a measurement.

The κ overlap stays, because κ is the thing that tells you how hard to squint.

### C — Budget, and the bound on statistical machinery

**C-i — Cost is a constraint, not a footnote.** The instruction is *"don't spend
too much on testing, but I want a real run."* So:

- Every model call is token-counted by wrapping the client from the harness
  (**zero `api/` change**), and `generate` prints tokens and dollars at exit and
  on every `--limit` pilot.
- **A costed pilot runs before the full run, always.** `--limit 2` first, its
  real cost reported, and the full run sized from that measured number rather
  than from an estimate.
- The study targets the **low end** of the 300–1000 band. 300–400 attempt rows
  answers "is the validator behaving sensibly on real output" as well as 1000
  does, and the blind sample is capped at 100 items either way — the human
  review, not the dataset, is the binding constraint on what can be learned.
- The **candidate simulator is not under test**, so it runs on the cheapest
  adequate model. Question generation — the thing under test — stays on
  `gpt-4o`, production's model, because a study of a cheaper model's questions
  would be a study of a system nobody ships.

**C-ii — Statistical machinery is bounded (Simplification 2).** Keep stratified
sampling, reweighting and confidence intervals. Stop there. The estimator is
~40 lines and is already specified in F3; it is not a research project, and no
time goes into narrowing an interval from ±14 pp to ±11 pp.

**The finding budget goes to `validator_disagreements.md`.** One example of the
validator rejecting *"What did you decide and why?"* where a human accepts it
teaches more than any interval ever will. D6 is the deliverable that gets the
attention; D5 is arithmetic.

### D — Decisions, as ruled 2026-09-05

| # | Decision | Effect here |
|---|---|---|
| 1 | This study is Phase 3; D6–D10 → Phase 4 | §0 B2 resolved, renumber applied. **B3 raised** — E1–E4 collides |
| 2 | Validator instrumentation; no production schema change | §0 F1 option 3. Guardrail: `git diff --stat api/` stays empty |
| 3 | Candidate simulator for Tier B | §3 fork resolved to (b). Family-neutral pool survives as `--no-simulator` |
| 4 | Stratified 50/50 sample, reweight at scoring | §0 F3 as written |
| 5 | Publish metrics regardless of κ, warn if low | §0 F4 amended; acceptance criterion 12 rewritten |

---

## 1. Objective

Evaluate `engine/question.validate()` against **naturally generated** interview
questions rather than the synthetic corpus it was built from, and publish the
agreement — whichever way it points.

**Why now.** `tests/data/question_golden.json` reads 100% on M6a/M6b/M6c/M6h.
That is a regression detector, not a quality measurement: the corpus was
authored by the same person who wrote the rules, so it can tell you the
validator got *worse* and cannot tell you whether it is *good*. This is the
measurement `CLAUDE.md` already names as next, and the risk ChatGPT's review
named as the largest unresolved one.

**Pre-commitment, in the M4a tradition: the confusion matrix is published
before it is seen.** A validator that disagrees with a human is a finding about
the validator, and a number you only publish when it flatters you is not a
number.

## 2. Current State — including what must NOT be rebuilt

| Exists, frozen for this phase | Where |
|---|---|
| `validate()` — 7 rules, pure Python, no model call | `api/engine/question.py:411` |
| The two-attempt regeneration flow | `api/engine/question.py:709` |
| The repair turn | `orchestrator._maybe_repair`, `question.repair_question` |
| `questions.source / attempts / violations_json / is_repair` | `api/models.py:169` |
| The question corpus, 76 entries | `tests/data/question_golden.json` |
| M6a–M6h | `scripts/validation_report.py:compute_m6` |
| 4 authored personas with real answer pools | `seed.py` |
| 64 labelled resumes, 8 families + general | `tests/data/routing_golden.json` |

**Must not be rebuilt or touched:**

- **`api/` is not modified by this phase.** Every deliverable is achievable
  from `scripts/` plus an instrument around `validate()`. If a task appears to
  need an `api/` edit, the task is wrong — raise it (same discipline as the
  `schemas.py` tripwire).
- **No new corpus entries.** Your instruction, and independently counter-metric
  C6. A rule that gains entries because it lost an argument with a human is
  overfitting the referee.
- **No threshold tuning during the study.** `DUPLICATE_JACCARD = 0.37` and the
  stopword lists are measured constants. Tuning them *before* the disagreement
  analysis is complete is fitting to the test set. Any change is Phase 3's
  **output**, proposed with evidence, applied after.

## 3. Deliverables

| # | Artifact | Produced by | Committed |
|---|---|---|---|
| D1 | `scripts/interview_study.py` — `generate` · `sample` · `score` | P3-01/02/04 | yes |
| D2 | `studies/phase3/real_question_dataset.csv` | `generate` | yes |
| D3 | `studies/phase3/human_review_sample.csv` (blind) | `sample` | yes |
| D4 | `studies/phase3/.sample_key.csv` (sealed un-blinding key) | `sample` | yes |
| D5 | `studies/phase3/confusion_matrix.md` | `score` | yes |
| D6 | `studies/phase3/validator_disagreements.md` | `score` | yes |
| D7 | `tests/test_study.py` — harness tests | P3-01 | yes |

All committed: `EXECUTION_STANDARD.md` §7 — *if it is not reproducible, it is
incomplete*. The dataset is the evidence; a matrix without it is an assertion.
Personas are synthetic, so there is no PII to withhold.

### D2 row schema — one row per **generated attempt**, not per persisted question

A regenerated question is two generated questions. Per-attempt is what makes
the reject text exist at all (F1), and it is a superset of the brief's columns.

```
interview_id, run_seed, tier, persona, family, answer_fidelity,
claim_id, claim, claim_type, claim_metric,
probe_level, target_dimension, order_index, attempt_index,
generated_question,
validator_ran, validation_result, accepted_by_validator, violations, primary_rule,
source, attempts, is_repair, is_final,
model, temperature
```

`validation_result ∈ {accept, reject, not_evaluated}`. `not_evaluated` is the
F2 case and is the only value for which `accepted_by_validator` is blank —
never `false`.

### The interview matrix

| Tier | Source | n | `answer_fidelity` | Purpose |
|---|---|---|---|---|
| **A** | 4 `seed.py` personas × 2 repeats | 8 interviews | `authored` | Realistic multi-turn threads. Includes Rohit, who stalls — so TRANSFER and the repair turn actually fire |
| **B** | 60 labelled `routing_golden.json` resumes | 60 interviews | see fork below | Family breadth: 8 families + `general` |

Measured: golden resumes are **103 chars median** and yield **exactly 2
heuristic claims each** (all 64), so ~6–10 questions per Tier-B interview.
Tier A runs 9–14. **Projection ≈ 480 + 100 ≈ 580 attempt rows**, inside the
300–1000 target with `--repeats` as the dial. Model-mode extraction returns up
to 3 typed claims, so the real figure is at or above this.

Question wording is `temperature=0.4` with `cache=False`, so repeats of the
same persona genuinely vary — that variance is the thing being sampled.

### Open fork — how Tier B answers the questions (**decide before P3-01**)

A software-engineering resume answered from a BPO answer pool produces nonsense
`prior_qa`, and every question generated after turn 1 is generated against
nonsense. That would make the generator look worse than it is and contaminate
the study.

| | Method | Cost | Fidelity | Risk |
|---|---|---|---|---|
| **(a)** | One family-neutral answer pool per probe level, hand-written once | zero | low — bland context after turn 1 | Understates the generator; blandness is not what a real thread looks like |
| **(b)** | A **candidate simulator**: one model call per turn, role-playing the resume | ~+30% calls | high, family-correct | Introduces a model into the study loop |
| **(c)** | Per-family authored pools, all 8 | high authoring | high | The per-cohort authoring cost the whole architecture exists to avoid |

**Recommendation: (b), with (a) kept as `--no-simulator` for a zero-model run.**
The simulator is the *candidate*, not the validator and not the scorer — the
validator stays pure Python, and rule 1 of `CLAUDE.md` is untouched. It will
confabulate specifics from a 103-char resume, which is realistic (it is what
Rohit does) and is recorded as `answer_fidelity=simulated` so results stratify.
Answers are study **input**; nothing in the study treats them as ground truth.

## 4. Risks

| Risk | Mitigation |
|---|---|
| **Rejects are scarce.** If the model is good, the reject stratum may hold < 50 rows | `sample` takes `min(50, available)`, prints both n's, and `score` widens every interval accordingly. If rejects < 20, the study reports precision only and says recall is unestimable |
| **The 50/50 sample misleads** (F3) | Reweighted estimator + Wilson intervals, both tables published |
| **One reviewer** (F4) | 20-item κ overlap; low κ warns loudly, publishes anyway |
| **Reviewer sees the validator's opinion** | `sample` writes only `claim · probe_level · question`. Column order is shuffled-stable, row order seeded-shuffled, and the un-blinding key is a separate file — `score` refuses to run if the reviewed file carries a validator column |
| **Fallbacks read as accepts** (F2) | Excluded from the matrix; published as M7e coverage |
| **Study becomes threshold-tuning** | No `api/` edit this phase. Any tuning is Phase 3's output, evidenced, applied after |
| **Cost surprise** | `--limit` pilot **before every full run**, live token counter, dollars printed at exit; simulator on the cheap model, generator on production's |
| **Non-determinism makes the run unreproducible** | Every row carries `run_seed`, `model`, `temperature`; `generate` is resumable and never overwrites an existing dataset without `--force` |
| **A model outage mid-run** | Rows are flushed per interview; `--resume` continues from the last complete `interview_id` |

## 5. Deferred Work

- Threshold recalibration from the findings — **Phase 3's output, not its
  method.**
- Any new validator rule the disagreement analysis motivates.
- Corpus expansion. Explicitly out of scope; revisit only after the
  disagreement analysis names a defect class the corpus cannot express.
- `extract._metric_of` seconds unit (owner A, known, unrelated).
- D6–D10 → **Phase 4**, entry condition unchanged (M4a has produced a number).
- **E1–E4 Interview Intelligence Quality** — claim-extraction quality, scoring
  quality against recruiter judgement, evaluation stability across reruns,
  recruiter trust. **Phase 5 (proposed)**, see §0 B3. This is the
  `interview → evaluation` half, and E3 in particular (does the same candidate
  score 82, 61, 77 across runs?) is a **deployability gate**, not a metric.

## 6. Success Metrics · Guardrails · Counter-metrics

**The phase succeeds when the numbers exist and are published — not when they
are high.**

| | Definition | Source | Target |
|---|---|---|---|
| **M7a Precision** | Of questions the validator rejected, % a blind human also rejects | reject stratum, `r_R` | **Reported.** No target |
| **M7b Recall** | Of questions a human rejects, % the validator caught | reweighted (F3) | **Reported.** No target |
| **M7c Accuracy** | Reweighted agreement over the population | F3 estimator | **Reported** |
| **M7d F1** | Harmonic mean of M7a/M7b | derived | **Reported** |
| **M7e Coverage** | % of generated questions that received a validator decision | `validator_ran` | **≥ 90%.** Below that the pipeline is running on fallbacks and M7a–M7d describe a minority path |
| **M7f Per-rule precision** | For each of the 7 rules, % of its rejects a human agrees with | `primary_rule` ⋈ labels | **Reported per rule.** A rule below 0.5 is a named finding |
| **M7g Reviewer agreement** | Cohen's κ on the 20-item overlap | second reviewer | **Reported.** < 0.6 warns, never withholds (Decision 5) |
| **M7h Live reject rate** | % of first attempts the validator rejects, in the wild | dataset, `attempt_index=1` | **Reported.** This is M6d measured live for the first time |

**Guardrails — must not regress**

| Guardrail | Baseline | Limit |
|---|---|---|
| Test suite | 307 passing | Never red |
| `api/` diff | 0 lines | **0 lines.** A non-zero diff means the plan was wrong — stop and raise |
| Corpus | 76 entries | **76.** Unchanged for the whole phase |
| Validator constants | `DUPLICATE_JACCARD=0.37`, both stopword lists | Unchanged for the whole phase |
| M6a–M6h | 100 / 100 / 100 / 100 | Unchanged — the corpus did not move, so these must not either |

**Counter-metrics — what NOT to optimise**

- **C7 — Do not optimise agreement.** Raising M7a by tuning a threshold against
  the review sample is fitting to the test set, and it is the one move that
  makes the study worthless while making it look successful.
- **C8 — Do not drop hard cases from the sample.** A question the reviewer
  finds genuinely ambiguous is the most informative row in the study.
  `human_ambiguity` is a first-class root cause in D6, not an excluded row.
- **C9 — Do not read a high M7a as validator quality if M7e is low.** Precision
  over 6% of the questions is a statement about 6% of the questions.
- **C6 (standing) — do not add corpus entries reactively.**

## 7. Task Breakdown

| ID | Task | Owner | Files | Deps | Migration | Tests |
|---|---|---|---|---|---|---|
| **P3-01** | Generation harness + dataset | **A** | `scripts/interview_study.py`, `tests/test_study.py` | B1, fork | **none** | new: harness unit tests, fixture-mode smoke |
| **P3-02** | Blind sampler + sealed key | **A** | `scripts/interview_study.py` | P3-01 | none | blinding invariants |
| **P3-03** | Human review | **you + 2nd reviewer** | `human_review_sample.csv` | P3-02 | n/a | n/a — the gate |
| **P3-04** | Confusion matrix + reweighting | **A** | `scripts/interview_study.py` | P3-03 | none | estimator tests against hand-computed fixtures |
| **P3-05** | Disagreement analysis + write-up | **A** | `validator_disagreements.md` | P3-04 | none | n/a |

**Ownership note.** `scripts/validation_report.py` is B's. `interview_study.py`
is new and measures A's validator, so **owner A** — proposed, not assumed. Same
gap as `api/db.py`: neither contract mentions `scripts/` as a directory.
Announce to B either way; it lands next to his file.

**Root-cause taxonomy for D6** — the brief's ten, adopted verbatim: the seven
rule names, plus `threshold_issue`, `transfer_issue`, `human_ambiguity`. Every
disagreement gets exactly one, and the count per cause is the finding.

## 8. Dependency Graph

```
B1 (API key)  ─┐
B2 (renumber) ─┤
Tier-B fork   ─┴─> P3-01 generate ──> P3-02 sample ──> P3-03 HUMAN ──> P3-04 score ──> P3-05 analysis
                        │                                  ▲
                        └── fixture smoke test ────────────┘ (runs today; proves plumbing, measures nothing)
```

**Critical path:** B1 → P3-01 → P3-02 → **P3-03** → P3-04 → P3-05.
**P3-03 is the long pole** and the only step no code can shorten: 100 questions
plus a 20-item overlap, at maybe 30–45 seconds each, is **~1.5 hours of human
attention**, and it must happen before any number exists.
**Parallelisable:** P3-04's estimator and its tests can be written against
hand-computed fixtures while the review is in flight — recommended, since it is
the step most likely to contain an arithmetic error nobody catches.

## 9. Acceptance Criteria — binary

1. `git diff --stat api/` is **empty** for the whole phase.
2. `pytest -q` is **307 + new** and green, with **no existing test edited**.
3. `tests/data/question_golden.json` is byte-identical to `c3d5d0f`.
4. `DUPLICATE_JACCARD`, `_STOP_PHRASING`, `_STOP_SUBJECT` are byte-identical to `c3d5d0f`.
5. `generate` produces ≥ 300 attempt rows, ≥ 8 distinct families, all 6 probe
   levels present, ≥ 1 `is_repair=true` row, ≥ 1 `attempt_index=2` row.
6. Every row has a non-empty `generated_question` and an `interview_id` that
   joins to a real `sessions.id`.
7. M7e ≥ 90%.
8. `human_review_sample.csv` contains **exactly** `claim, probe_level,
   question` (plus an opaque `row_id`) — asserted by a test, not by eye.
9. `score` **refuses to run** on a reviewed file containing any validator
   column, and its refusal is asserted by a test.
10. `confusion_matrix.md` carries **both** the raw-sample and reweighted tables,
    each with Wilson 95% intervals, and states n per stratum.
11. `validator_disagreements.md` accounts for **100%** of disagreements, one
    root cause each, no row unclassified.
12. κ is reported, and **M7a–M7d are published whatever it says** (Decision 5).
    κ < 0.6 adds a warning banner to `confusion_matrix.md` and to each affected
    figure. No metric is ever suppressed.
13. Re-running `generate --run-seed S` twice with the same key produces the same
    row **count** and the same interview/claim/probe skeleton. Wording will
    differ — temperature 0.4 — and that is recorded, not asserted away.

## 10. Implementation Order

0. **Approve this plan.** Clear B1 (key), B2 (renumber), and the Tier-B fork.
1. **P3-01** harness. Merge with the fixture-mode smoke test only — the smoke
   test proves the plumbing and is labelled, in the doc and in the file, as
   measuring nothing about the validator.
2. **Costed pilot:** `generate --limit 5` with a real key. Inspect ~40 rows by
   hand. **Stop.** This is the moment a design error is cheap.
3. **Full run.** Commit `real_question_dataset.csv`.
4. **P3-02** sample. Commit the blind file and the sealed key as one commit, so
   the diff proves the blinding was built before the labels existed.
5. **P3-03** review. Both reviewers. In parallel: **P3-04** estimator + tests
   against hand-computed fixtures.
6. **P3-04** run `score`. Commit `confusion_matrix.md`.
7. **P3-05** disagreement analysis. Commit `validator_disagreements.md`.
8. **Phase exit:** M7a–M7h published, D6 accounts for every disagreement, `api/`
   diff empty. Any recalibration the study motivates is a **separate**,
   evidenced change — after.

---

## 11. Execution log

Kept here rather than in a new document (C2). Appended as the phase runs, so a
reader sees what actually happened rather than what was planned.

### P3-01 — harness (`scripts/interview_study.py`, `tests/test_study.py`)

`api/` diff: **empty**, as required. Suite **307 → 330**, no existing test edited.

**The costed pilot earned its keep three times over.** Plan §0 C-i mandates a
`--limit` run before any full run; it found three defects that would each have
corrupted or destroyed a paid run, and none of them were visible in fixture
mode — which is the point of the fixture smoke test being labelled as measuring
nothing.

**Bug 1 — 85% of validator decisions were being thrown away.**
Symptom: the pilot reported **M7e coverage 14.8%** while `questions.source` on
the same rows said 45 `model` + 9 `regenerated`. Both cannot be true — a
question with `source="model"` was validated by definition.

Root cause: `orchestrator.submit_answer()` calls `ask_next()` itself
(`orchestrator.py:1047`), so question N+1 is generated at the **tail of turn N**.
The harness cleared its generation buffer at the top of each turn, which threw
that generation away; `ask_next()` then returned the already-open question
without generating, so the row fell through to the database branch and recorded
`validator_ran=False` on a question the validator *had* judged.

Fix: `_take_generation()` matches on question text and consumes once, so it is
correct whatever order the orchestrator generates in. Pinned by three tests.
After the fix, a single interview reads **M7e coverage 100.0%**.

**This is the failure mode the plan's own guardrail was written for.** M7e has a
90% floor precisely so that "the validator is barely running" cannot be mistaken
for "the validator is fine". Had the pilot been skipped, the full run would have
produced a dataset with a 15% coverage figure and a reject stratum missing six
sevenths of its rows.

**Bug 2 — one bad interview killed every interview after it.**
A `FOREIGN KEY constraint failed` on an `evidence` insert left the shared
`AsyncSession` in *"transaction has been rolled back"*, and the harness caught
the exception without rolling back. Interviews 3, 4, 5 and 6 then failed on the
same dead statement. The run **wrote 0 rows after paying for 21 model calls**.

Fix: one session per interview, explicit `db.rollback()` on failure, and a
failure count printed at exit — a run that silently drops a quarter of its
interviews is reporting a coverage number that is not true.

**Bug 3 — failures were being reported only as a per-line message.** A run that
loses interviews has a coverage fact to declare, so the count is now summarised
at exit and recorded here.

**A fourth thing the pilot settled, which is a finding rather than a bug: the
repair turn did not fire once.** `evidence.is_non_answer()` matches a canned
phrase or a string under 12 characters, and neither the authored personas nor a
competent simulator produce those — Rohit's *"I don't remember the details, it
was a while ago."* reads as a real answer to it. So acceptance criterion 5's
`is_repair` clause is expected to fail, and **it is not being engineered around**:
authoring a persona that says "ok" to make a criterion pass would be fitting the
data to the test. What it suggests is worth a separate measurement — the repair
turn shipped in P2-04 and may almost never trigger on real candidates.

### The pilot, after all three fixes

Same six interviews, nothing else changed:

| | before | after |
|---|---|---|
| Rows | 61 | **76** |
| Validator ran on | 9 | **71** |
| **M7e coverage** | **14.8%** | **92.1%** |
| Accepts / rejects | 6 / 3 | **53 / 18** |
| Interviews that failed | 4 of 6 | **0 of 6** |
| Cost | $0.4738 | $0.4866 |

**M7h live reject rate: 25.4%** — far higher than the ~8% the plan used as its
worked example, which is good news for the study: a 50-item reject stratum is
comfortably available rather than scarce, and F3's reweighting matters *less*
than feared at a 2.9x over-representation instead of 11x. It is also a finding
in its own right: **one generated question in four fails validation on the first
attempt**, against a corpus that says the validator is at 100%.

Per-rule, on the pilot: `answer_leakage` 11, `no_claim_anchor` 2,
`unsupported_metric` 2, `duplicate_content` 2, `scope_drift` 1. Reading anything
into that at n=18 would be premature; it is here because the histogram existing
at all is what M6's per-rule counts were built for.

### Measured cost

| | calls | in | out | USD |
|---|---|---|---|---|
| One question generation (`gpt-4o`) | 1 | 417 | 26 | **0.0013** |
| One interview, end to end (mean of 6) | 25 | 20,888 | 3,277 | **0.081** |
| Pilot: 6 interviews, 76 rows | 150 | 125,330 | 19,660 | **0.4866** |

Roughly **$0.0064 per dataset row**, so a 68-interview full run costs about
**$5.50**. `gpt-4o-mini` for the candidate simulator is
**0.3% of the bill** — the interview itself (question generation plus evidence
extraction, both on production's `gpt-4o`) is essentially all of it, which is
why moving the simulator to the cheap model was worth doing and moving anything
else would not be.

### Two production observations, neither fixed here

Recorded because a live run surfaces things fixture mode cannot. **Neither is in
scope**: acceptance criterion 1 is an empty `api/` diff, and both belong to
owner A as separate, evidenced changes.

1. **`AnswerSignals` fell back on a 240-character quote limit.** Evidence
   extraction returned `causal_links[1].quote` longer than the `max_length=240`
   in the frozen `api/schemas.py`, failed validation twice, and used the
   heuristic fallback. That is rule 5 working — no stack trace, the interview
   continued — but it means a long verbatim quote silently downgrades an answer
   to heuristic scoring. Worth a measurement of its own: how often does this fire
   on real answers?
2. **A `FOREIGN KEY constraint failed` on an `evidence` insert** (bug 2's
   trigger). SQLite now arms `PRAGMA foreign_keys=ON`, so this would previously
   have passed under test and failed only on Postgres. Not yet reproduced in
   isolation, and it may be an artifact of the shared session rather than a
   production defect — **stated as unexplained rather than explained away.**
