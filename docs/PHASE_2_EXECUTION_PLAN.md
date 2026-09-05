# Phase 2 Execution Plan — Question Quality Infrastructure

**Objective owner:** Abhishek (A) · **Duration:** ~1.5 weeks · **Entry
condition: Phase 1 closed** — M1b = 100%, M5c = 0%, guardrails green, M4a
published as `insufficient data (n < 30)`. All four hold as of 2026-09-05.

Architecture frozen per `ARCHITECTURE_LOCK_v1.md`. **Nothing here proposes new
architecture.** The validator is the same pattern as `evidence.enforce_verbatim()`
and `taxonomy.normalise_claim_type()`: Python validates what the model returned.

Produced under `EXECUTION_STANDARD.md` §10. Task-level specs are the
seven-section form, in `docs/tasks/P2-0*.md`.

---

## 1. Objective

**Make question generation measurable, auditable and deterministic in quality.**

At completion, two questions are answerable from stored rows rather than
opinion:

- *"Why was this question accepted?"*
- *"How often does the system generate bad questions?"*

The question sits at the entrance of the evidence system. Everything downstream
— extraction, signals, consistency, scoring, ranking, outcomes — is bounded by
what the question managed to elicit. A perfect scoring engine over a bad
question set produces confident nonsense, and we currently have no way to know
which we have.

## 2. Current State — including what must NOT be rebuilt

**Already correct. Do not touch:**

| Mechanism | Where | Why it stays |
|---|---|---|
| Deterministic planner | `orchestrator.plan_next()` | Pure function of stored evidence. Structure is where interview validity comes from; moving selection into a prompt converts a structured interview into an unstructured one |
| LLM wording only | `question.generate_question()` | The split is load-bearing and already enforced by `select_transfer()` having no `job_family` parameter |
| Verbatim enforcement | `evidence.enforce_verbatim()` | The pattern this phase copies |
| `is_non_answer()` | `evidence.py:66` | Pure, no LLM. **P2-04 reuses it; do not write a second one** |
| `FALLBACK_QUESTIONS` | `question.py:130` | Production code, not stubs. **Exempt from validation by construction** — see §4 R1 |
| Five probe briefs + transfer templates | `question.py` | Cohort-neutral. No per-family examples, ever |

**The gap:** `Question` rows record `text`, `probe_level`, `target_dimension`,
`order_index`, `answered`. Nothing records *whether the question was any good*,
so no metric over question quality is computable today.

## 3. Deliverables

### D11 — Question golden set (defect corpus)

`tests/data/question_golden.json`. **Not a corpus of good questions** — a
labelled defect corpus, authored **before** the validator, per the contract rule
that a test written afterwards describes the implementation instead of testing
it.

Carries `accept` entries as well as `reject`. A validator that rejects
everything must **fail** the suite. This mirrors the routing floor lesson:
`test_every_ambiguous_resume_is_flagged` is worthless without
`test_no_confident_route_is_flagged`.

### D12 — `question.validate()`

Pure Python, no LLM, returns `QuestionValidation(accepted, violations)`.
Seven rules — see P2-02 for the full spec and each rule's deterministic test.

### D13 — Bounded regeneration

One retry maximum, then fallback. The retry prompt carries the **violated rule
names** — never examples, which would re-introduce cohort bias at config level.

### D14 — Repair turn

`is_non_answer()` on an inbound answer issues a repair question that does
**not** consume interview budget.

### D15 — M6 question metrics

`validator_accept_rate · validator_reject_rate · fallback_rate · repair_rate ·
repeat_rate`, computed from stored rows in `scripts/validation_report.py`.

## 4. Risks

| | Risk | Mitigation |
|---|---|---|
| **R1** | **A naive validator rejects the production fallback.** `FALLBACK_QUESTIONS[VALIDATION]` is literally *"Tell me more about this…"* and `[INCIDENT]` is *"Tell me about one specific time…"*. CLAUDE.md rule 5 requires every LLM call to have a fallback, so a validator that can reject the fallback leaves **no path at all** | The fallback path never enters the validator. Structural, not an exemption list: `validate()` is called on model output only, and P2-03's flow returns the fallback without re-validating. Pinned by a test |
| **R2** | **A naive scope rule rejects the entire TRANSFER mechanism.** `select_transfer()` picks `target = others[0]` — deliberately a *different* claim — and T1 is the majority path ("whenever a second claim exists"). Scope drift **is** the mechanism | Rule 6 is two rules in one: non-TRANSFER probes stay in claim scope; a TRANSFER probe must reference `plan.transfer.target_claim_id`. Stronger than an exemption — it enforces drift to *the planner's* target and nowhere else |
| **R3** | **A hypothetical rule rejects 100% of transfer probes.** All three transfer strings open with "Suppose" by design | Rule 4 is conditioned on `probe_level == TRANSFER`, and asserted in **both** directions: hypothetical on a non-TRANSFER level must reject |
| **R4** | **Unbounded regeneration breaks the latency guardrail** (+20% median turn ceiling, `PHASE_1_SUCCESS_METRICS.md` §G). Every turn already blocks on a model call | Hard cap of one retry, enforced in code and asserted by a test that counts LLM calls via `/api/dev/llm` |
| **R5** | **The repair turn changes when TRANSFER fires.** `ClaimState.stalled` is *answers ≥ 2 and last `signals_found == 0`*. A repair answer is an extra answer on the same claim, so a claim could reach `stalled` a turn earlier and pull its transfer probe forward | Repair answers are excluded from the `answers` count that feeds `stalled`. Measured against the seed: transfer probe count must stay at **3, all Rohit, all `signals_found = 0`** — the Phase 1 invariant |
| **R6** | **`order_index` currently means two things** — position in the transcript *and* budget consumed (`order_index=session.questions_asked`, `orchestrator.py:745`). A non-budget-consuming repair turn splits those apart | `order_index` derives from a count of the session's questions; `questions_asked` stays the budget counter. Stated in P2-04, tested by asserting a repair does not move `questions_asked` |
| **R7** | Validator rules that double-count. A "single evidence target" rule was proposed and **dropped**: its example is a double-barrel question (rule 3), and one-dimension-per-question is already guaranteed upstream by `plan_next` passing a single `target_dimension` | Seven rules, each with a distinct defect. Two rules firing on one defect corrupts the reject-rate metric this phase exists to produce |
| **R8** | Hinglish and code-switched answers mis-scored as defects | The golden set carries Hinglish entries. Rule 7 anchors on claim terms, which survive transliteration; no rule may read fluency, grammar or register — CLAUDE.md rule 6 |

## 5. Deferred Work

- **D6–D10** (Evaluation entity, versioning, replay, tenant isolation, score
  history) — now Phase 3, below. **Cost of deferring, stated honestly:** D9
  argues tenant isolation is *"the only deliverable whose cost grows with every
  day of real data."* That cost is ~0 today — four seeded personas, no customer,
  no accumulating production data — and becomes real the week a customer
  contract is drafted. **Trigger: do D9 before the first customer's data
  lands**, not on a calendar.
- **A question-quality *rubric*** (is this the *best* question?) — out of scope.
  Questions have no single correct answer, which is why D11 measures validator
  precision/recall against labelled defects instead.
- **LLM-as-judge on question quality** — rejected, not deferred. It would make
  the metric the model's opinion, violating §8 and rule 1.
- **M1a / M2 re-specification** — recorded as measured amendments in
  `PHASE_1_SUCCESS_METRICS.md` §A. Changing a frozen target is a separate
  decision.
- **`routing_status` enum** (`MATCHED · LOW_CONFIDENCE · CONFLICTING · GENERAL`)
  — the right eventual shape for what `routing_confidence` 0.0 now overloads,
  but `api/schemas.py` is frozen and dual-owned. `GET /api/dev/detect` already
  carries the disambiguation. Do it when the dashboard needs it.
- **`extract._metric_of` seconds unit** — a known defect (CLAUDE.md), and a
  claim-extraction concern rather than a question concern. Phase 2 does not
  touch extraction.

## 6. Success Metrics

Computable from stored rows. No model call. Published by
`scripts/validation_report.py`.

| | Definition | Source | Target |
|---|---|---|---|
| **M6a Validator precision** | Of golden entries the validator rejects, % a human labelled `reject` | `question_golden.json` | **≥ 95%** |
| **M6b Validator recall** | Of golden entries labelled `reject`, % the validator catches | same | **≥ 90%** |
| **M6c Accept-rate on good questions** | Of golden entries labelled `accept`, % accepted | same | **≥ 95%** — the anti-gaming guard. A validator that rejects everything scores 100% recall and fails here |
| **M6d Live reject rate** | % of generated questions failing attempt 1 | `questions.violations_json` | **Reported, not targeted** — see C4 |
| **M6e Fallback rate** | % of asked questions that came from `FALLBACK_QUESTIONS` | `questions.source` | **≤ 5%** in live mode |
| **M6f Repair rate** | % of answers triggering a repair turn | `questions.is_repair` | **Reported** |
| **M6g Repeat rate** | % of questions rejected for duplicate content | `questions.violations_json` | **Reported** |

**Guardrails — must not regress:**

| Guardrail | Baseline | Limit |
|---|---|---|
| Test suite | **186 passing** | Never red; ≥ 210 by phase end |
| Median turn latency | current | **+20% ceiling** — R4 is the live threat |
| Transfer probe invariant | 3 probes, all Rohit, all `signals_found = 0` | Unchanged (R5) |
| Anti-bias invariants | 3 structural tests green | Never edited to pass |
| Fixture / rubric agreement | exact | `test_pipeline` fixture assertions stay green |
| `TRANSFER_PROBE=false` reproduces the pre-phase system | competence 56/46/14/61 | Unchanged |
| Routing accuracy | 98.3% M5b | Unchanged — Phase 2 does not touch `taxonomy.py` |

**Counter-metrics — do NOT optimise:**

- **C4 — do not optimise the live reject rate downward.** A reject means the
  validator did its job. Driving M6d to zero by loosening rules produces a
  validator that accepts everything, which is indistinguishable from having no
  validator. M6a–M6c on the labelled set are the goal; M6d is a diagnostic.
- **C5 — do not optimise the fallback rate to zero by weakening the fallback.**
  The fallbacks are deliberately conservative. CLAUDE.md: *if a fallback ever
  looks better, the fallback has become the product.*
- **C6 — do not add validator rules to raise recall on the golden set.** Rules
  must describe defects that harm evidence elicitation, not defects that happen
  to be in our corpus. A rule with one supporting entry is overfitting.

## 7. Task Breakdown

| ID | Task | Owner | Files | Deps | Migration impact | Binary acceptance |
|---|---|---|---|---|---|---|
| **P2-01** | Question golden set (defect corpus, ≥ 60 entries) | A | `tests/data/question_golden.json`, `tests/test_questions.py` (new) | — | none | File exists, ≥ 60 entries, every rule represented, both verdicts present, Hinglish + all six probe levels covered; a stub validator that rejects everything **fails** the suite |
| **P2-02** | `question.validate()` — 7 rules, pure | A | `api/engine/question.py`, `tests/test_questions.py` | P2-01 | none | M6a ≥ 95%, M6b ≥ 90%, M6c ≥ 95% on the golden set, 0 LLM calls (asserted via `/api/dev/llm`) |
| **P2-03** | Bounded regeneration, 1 retry → fallback | A | `api/engine/question.py`, `api/models.py`, `tests/test_questions.py` | P2-02 | **schema change** + fixture regeneration | A rejected question triggers exactly **1** extra LLM call, never 2; second failure returns a fallback; `questions.source` recorded |
| **P2-04** | Repair turn on `is_non_answer()` | A | `api/engine/orchestrator.py`, `api/models.py`, `tests/test_policy.py` | P2-03 | **schema change** (same reset) | A non-answer issues a repair question and leaves `questions_asked` unchanged; transfer invariant still 3/3 Rohit |
| **P2-05** | M6 metrics in the validation report | A | `scripts/validation_report.py`, `tests/test_questions.py` | P2-01 … P2-04 | none | All seven M6 numbers printed, 0 model calls, endpoint and script agree field-for-field |

`api/models.py` is Developer B's file by contract. Abhishek has lifted the
restriction for this work; the schema change is still **announced to Satyam
before it lands**, because it forces a `docker compose down -v` on his machine.

## 8. Dependency Graph

```
P2-01  golden set  ──▶ P2-02  validate()  ──▶ P2-03  regeneration ──▶ P2-04  repair turn
   │                      │                       │                      │
   └──────────────────────┴───────────────────────┴──────────────────────┴──▶ P2-05  M6 metrics
```

**Critical path:** P2-01 → P2-02 → P2-03 → P2-04 → P2-05. Sequential by nature —
each task's acceptance depends on the previous one's output.

**Not parallelisable across two developers**, and that is deliberate: all five
tasks land in three files on the intelligence path. B's stream is idle for this
phase. **If B needs work in parallel, take D9 (tenant isolation) from Phase 3** —
it touches no file in this phase and its cost only grows.

**One schema reset serves P2-03 and P2-04.** Land the `questions` columns once,
in P2-03, including the `is_repair` column P2-04 needs but does not yet use. Two
resets for one phase is an avoidable demo-day hazard.

## 9. Acceptance Criteria

1. `question_golden.json` has ≥ 60 entries, both verdicts, all seven rules, all
   six probe levels, and Hinglish entries.
2. A deliberately broken validator that rejects every input **fails** the suite
   on M6c.
3. `validate()` makes **zero** LLM calls, asserted against `/api/dev/llm`.
4. M6a ≥ 95%, M6b ≥ 90%, M6c ≥ 95% on the golden set.
5. A rejected question causes **exactly one** regeneration, never more —
   asserted by call count, not by reading the code.
6. Two consecutive failures return a `FALLBACK_QUESTIONS` entry, and the
   fallback is **never** passed through `validate()`.
7. A non-answer issues a repair question and `session.questions_asked` is
   **unchanged**.
8. The transfer invariant holds: seed produces **3** transfer probes, all Rohit,
   all `signals_found = 0`.
9. `TRANSFER_PROBE=false` still reproduces competence 56 / 46 / 14 / 61.
10. All seven M6 numbers appear in `scripts/validation_report.py` output and in
    `GET /api/recruiter/validation`, from one implementation.
11. Suite green and larger: **≥ 210 tests**.
12. Median turn latency within +20% of the Phase 1 baseline.

## Shipped ledger

Developer B cannot read Developer A's session; this table is the only place
either learns what the other actually changed. **A task is not done until it has
a row here, added in the same commit as the code.** Every measured effect is a
number, not an adjective.

| Commit | Task | Owner | Tests | Measured effect |
|---|---|---|---|---|
| `p2-01` | **P2-01** question golden set (defect corpus) | A | 186 → 237 | **73 entries, 44 accept (60.3%) / 29 reject (39.7%)**, authored before the validator exists. 7 rules × 3–6 rejects and ≥ 2 adversarial accepts each; 6 probe levels × both verdicts; 3 families (bpo 32 · product 22 · swe 19); 9 Hinglish (6 accept / 3 reject). 51 tests, **0 production files touched**. **THREE FINDINGS, each encoded as an entry or a test rather than prose.** (1) **Rule 2's threshold is 0.37, measured over an authored 8-pair ladder** — and the measurement inverted the intuition: an *aggressive* stopword list collapses the duplicate and distinct bands into a **−0.083 overlap, so no separating threshold exists**, because the interrogative frame *is* what repeats. A minimal list separates at **+0.169** (distinct ≤ 0.231, duplicate ≥ 0.400); 0.37 is the midpoint above the highest borderline pair (0.333). Guessing the 0.6 the spec sketched would have made rule 2 catch nothing. (2) **A valid T1 transfer probe names two fact targets by construction** (`q63` — the method's metric plus the target claim's), so **rule 3 must not be evaluated on TRANSFER**; rule 6 already constrains which second subject is allowed. (3) **The rendered fallback fails rule 1** (`q60`) — `On "<claim>" — <base>` quotes the claim including its figures, which is the evidence for the runtime bypass and not a defect to fix in `question.py`. **Rule 3 renamed** `double_barrel` → `multiple_fact_targets` before anything persisted it: grammar was the wrong axis, since `PROBE_BRIEFS[DECISION]` deliberately asks a two-clause question about one subject. **Schema delta approved in review:** `rule` → `primary_rule` + `rules[]`, adding **M6h rule attribution** — precision and recall answer *"did we reject the right question?"* and not *"for the intended reason?"*, and without M6h a validator that rejects correctly via the wrong rule looks green while the team tunes the wrong rule. **Defect found in the corpus itself, by measuring it:** the first pass had 6 Hinglish entries and all 6 were accepts, which lets a validator pass the coverage test by learning *code-switched ⇒ accept* — the same bias with the opposite sign. Three Hinglish rejects added, test strengthened to require ≥ 2 |
| `p2-02` | **P2-02** `question.validate()` | A | 237 → 279 | Seven rules, pure Python, **0 model calls** (asserted structurally by AST and via `/api/dev/llm`). **M6a 100% · M6b 100% · M6c 100% · M6h 100%** — and 100% is treated as a warning, not a result: the first run was 75% precision / 79.5% accept-rate, and the four fixes were general defects, not special cases. Biggest: **no inflection handling**, so `users`/`user` and `interviewed`/`interviews` read as different subjects and rule 7 mis-fired 9 times — the same defect class `taxonomy._INFLECTION` exists for. Also `p95_latency_ms` resolved from neither "latency" nor "p95 latency"; rule 4 was **English-only** and missed `q73` (*"Agar activation gir jaata to aap kya karte?"*), so `agar` was added — completing a marker list for the language the product operates in, never a judgement about register; and rule 7's anchor set now includes the last answer and, on TRANSFER, the planner's target. **THE FINDING THE METRICS COULD NOT SEE:** with all four at 100%, rule ablation showed **`duplicate_content` was worth ZERO recall** — every entry authored for it was an unanchored string rule 7 caught anyway, so rule 2 fired but was never *necessary*. Three anchored duplicates (`q74`–`q76`) added; every rule now earns recall (18.8 / 15.6 / 12.5 / 9.4 / 9.4 / 6.2 / 6.2 pts) and two tests keep it that way. Rule 3 confirmed **not evaluated on TRANSFER** (P2-01 `q63`), pinned as behaviour. Fallback violation snapshot shipped: all six rendered fallbacks violate exactly `("answer_leakage",)`, with a companion test proving the base text is otherwise clean |
| `p2-03` | **P2-03** bounded regeneration | A | 279 → 290 | One retry, then fallback — **asserted by model-call count, never by reading the code**: a rejected question produces exactly 2 calls and two failures produce exactly 2, never 3. Written as two explicit calls rather than a loop, because a loop invites raising the constant while two calls make it a visible diff. `questions` gains `source · attempts · violations_json · is_repair`, so M6d–M6g become computable from stored rows — `is_repair` lands here unused so the phase needs **one** schema reset rather than two. **CORRECTED FROM THE SPEC: no fixture regeneration is needed.** The new columns live on `questions` and `CandidateGraph` surfaces none of them; verified by content hash over three consecutive regenerations against the committed file, all four `b60bd896322d4663`. The Phase 1 fixture diff stays the only one in the log. `QuestionAttempt` carries the validation outcome to the row because `GeneratedQuestion` is in the frozen `schemas.py`; it reuses the two attribute names every call site reads, so nothing else changed. The retry brief carries **rule names and a one-line instruction each, never worked examples** — a structural test greps the rendered prompt for every corpus question and fails if one appears. **The fallback is never validated**, asserted with a spy over `validate()`. `QUESTION_VALIDATION=false` reproduces the Phase 1 path: 290 green, seed competence 56/46/14/61 and all three lens orderings unchanged |
| `p2-04` | **P2-04** repair turn | A | 290 → 298 | A non-answer earns **one** more go at the same probe, off-budget. **Measured on the evasive persona: 9 budgeted questions against the strong persona's 12, across 14 turns versus 12** — fewer questions spent, more chances given. **0 model calls** (`REPAIR_PROMPTS` is a fixed table; the candidate has just shown low engagement and there is nothing to word creatively). Capped at one repair per parent question, because without it a disengaged candidate loops inside one probe forever — the same class of bug as unbounded regeneration. **THE PHASE 1 TRANSFER INVARIANT RE-MEASURED, NOT ASSUMED: 3 probes, all Rohit, all `signals_found = 0`, 0 repairs on the seed**; repairs are excluded from the `answers` count that feeds `stalled`, or a candidate saying "ok" twice would stall a claim that was never probed and pull TRANSFER forward onto a claim with no evidence to transfer. **`order_index` no longer means two things** — it was set from `questions_asked`, making it both transcript position and budget consumed; it is now a question count, and a test asserts the transcript stays dense and unique with repairs interleaved. **Two existing tests broke and both were proxies, not invariants:** the evasive test measured turns as a stand-in for budget (now asserts both, in both directions), and the transfer test counted TRANSFER *turns* where the invariant is one TRANSFER *probe* — `levels_used` still records it once, so the exemption is still spent once. Suite green under all five behaviour flags |

## 10. Implementation Order

| Step | Task | Gate before proceeding |
|---|---|---|
| 1 | **Commit Phase 1** (12 modified files, 186 green) | `git log` shows it; contract rule *commit before you measure* |
| 2 | P2-01 golden set | Reviewed by Satyam. **Authored before any validator code exists** |
| 3 | P2-02 `validate()` | M6a/M6b/M6c pass; every rule verified to fail without its implementation |
| 4 | Announce the `questions` schema change to Satyam | He must `docker compose down -v` |
| 5 | P2-03 regeneration + schema | Call-count test passes; fixture regenerated once |
| 6 | P2-04 repair turn | Transfer invariant re-measured, not assumed |
| 7 | P2-05 M6 metrics | Script and endpoint agree field-for-field |
| 8 | Re-run the full Phase 1 validation report | No M1–M5 number moved |

---

# Phase 3 Execution Plan — Make the Signal Durable and Sellable

> **Re-designated 2026-09-05.** This was the approved Phase 2 plan. It is
> unchanged below — not one deliverable was cut and none of the reasoning is
> retracted. It moved because **its own entry condition is not met**: it
> requires *"the validation report has produced a number — positive or
> negative"*, and M4a stands at `insufficient data (n < 30)` with n = 0.
> D6–D10 make a score *defensible to a paying customer*; nothing here makes
> the score better, and question quality caps how good the score can be.
> See Phase 2 above for the re-scope, and §Deferred there for what this
> costs.

**Duration:** ~7 weeks · **Team:** 2 engineers · **Entry condition: Phase 1
acceptance criteria all green, and the validation report has produced a number
— positive or negative.**

Architecture frozen per `ARCHITECTURE_LOCK_v1.md`. Nothing here proposes new
architecture; every item is drawn from the approved documents.

---

## Objective

**After Phase 2, a score can be explained, defended, reproduced and sold.**

Phase 1 proves the signal exists. Phase 2 makes it survive contact with a paying
customer, which introduces three demands the current system cannot meet:

1. *"Why did this candidate score 82 in March and 71 today?"* — needs an
   **Evaluation** that is a record, not a computation thrown away.
2. *"Re-run that evaluation and show me."* — needs **replay**.
3. *"Our candidates must never be visible to another customer."* — needs
   **tenant isolation**, which is the one item whose cost multiplies with every
   day of real data.

Business capability unlocked: **ProofScreen can be sold to and operated for a
paying customer.**

---

## Deliverables

### D6 — `Evaluation` as a first-class entity

The single change that unblocks provenance, history, replay and disputes at
once. Today an evaluation is implicit — computed on demand by
`build_candidate_graph(candidate_id, role_id)` and discarded, with `profiles`
caching one variant and overwriting it in place.

| Artifact | Detail |
|---|---|
| `evaluations` table | `id · tenant_id · candidate_id · role_id · weighted_evidence · competence · badge · consistency_score · role_coverage · dimension_profile_json · computed_at` — **append-only, never updated** |
| Provenance columns | `taxonomy_version · rubric_version · scoring_version · prompt_versions_json · code_sha · model_requested · model_returned · feature_flags_json · evaluation_version` |
| `evaluation_version` | A **hash of the provenance fields**, not a hand-maintained counter. Two evaluations are comparable iff the hashes match; when they differ, the components say *which* part moved |
| `Profile` → pointer | `profiles` keeps `latest_evaluation_id` and stops being a mutable score store. Resolves the `profiles.status` / `sessions.state` duplication |
| `GET /api/recruiter/candidates/{id}/evaluations` | History for one candidate, newest first |
| `EvaluationOut` | Additive schema model |

### D7 — Versioning of everything that influences a score

| Artifact | Detail |
|---|---|
| `data/taxonomy_v1.json` | Taxonomy shipped as a versioned artifact, loaded at startup, **content hash recorded** |
| Version semantics | **Additive** changes (new fact key, new claim type) = minor, history stays valid. **Weight or claim-type changes** = major, scores not comparable across the bump |
| Prompt version | Content hash of each prompt template, computed at load, recorded per call in `llm.py` |
| `RUBRIC_VERSION`, `SCORING_VERSION` | Module constants, stamped on every evaluation |
| `GET /api/health` extension | Reports the active version set |

### D8 — Replay

**Scoped correctly.** Full replay is impossible — LLM extraction is
non-deterministic and models are deprecated on the provider's schedule.
Everything *downstream of extraction* is fully deterministic, because signals are
persisted verbatim. That covers 100% of the scoring-dispute surface.

| Artifact | Detail |
|---|---|
| `engine/replay.py` | `replay(evaluation_id, versions=None) -> EvaluationDiff` — re-runs rubrics, weights and consistency over **stored signals**, under the original or a supplied version set |
| `POST /api/dev/replay/{evaluation_id}` | Returns the diff: which dimensions moved, which claims moved, and the delta on the headline score |
| `scripts/replay.py` | CLI for support use |
| Contract, stated in the API docs | *Extraction is recorded. Everything downstream of extraction is replayable.* Never promise more |

### D9 — Tenant isolation and authentication

**Do this first in Phase 2, not last.** It is the only deliverable whose cost
grows with every day of real data.

| Artifact | Detail |
|---|---|
| `tenants` table | `id · name · created_at` |
| `tenant_id` column | On every domain table, indexed, non-null |
| Query enforcement | A single session-scoped filter applied in `session_repo`/`graph`/`ranking` query paths — not per-callsite `where` clauses |
| API-key auth | `api_keys` table, `Depends(current_tenant)` on every recruiter and dev route |
| `Person` remains global | A person is one human across tenants **by identity only** — their evidence, scores and the fact of their candidacy never cross |
| Isolation test suite | Two tenants, identical candidate data; every recruiter endpoint asserted to return only its own rows |

### D10 — Score history

| Artifact | Detail |
|---|---|
| `claim_score_history` | Append-only rows per recomputation, carrying the provenance stamp |
| `GET /api/recruiter/candidates/{id}/score-history` | Timeline a recruiter can read |

---

## Dependency Graph

```
D9  tenant_id + auth        ← do FIRST; every later table inherits the column
 │
 ├──▶ D7  versioning         (taxonomy/prompt/rubric hashes)
 │        │
 │        └──▶ D6  Evaluation entity + provenance
 │                  │
 │                  ├──▶ D8   replay (needs an evaluation_id to replay)
 │                  └──▶ D10  score history (needs the provenance stamp)
 │
 └──▶ isolation test suite
```

D7 precedes D6 because an Evaluation with nothing to stamp is a table of nulls.
D9 precedes everything because adding `tenant_id` to `evaluations` and
`claim_score_history` after they hold data is a backfill instead of a column.

## Implementation Order

| Week | A | B |
|---|---|---|
| 1 | D9: `tenants`, `tenant_id` on every table, schema reset | D9: query-path enforcement |
| 2 | D9: API-key auth, `Depends(current_tenant)` | D9: two-tenant isolation suite |
| 3 | D7: taxonomy artifact + content hash; prompt hashes in `llm.py` | D7: rubric/scoring constants, `/api/health` |
| 4 | D6: `evaluations` table + write path in `recompute_profile` | D6: `Profile` → pointer, history endpoint |
| 5 | D6: provenance stamping end to end | D8: `engine/replay.py` + diff model |
| 6 | D8: endpoint + CLI | D10: `claim_score_history` + endpoint |
| 7 | Buffer · migration rehearsal on a full reset | Buffer · acceptance |

## Acceptance Criteria

1. **An evaluation can be recreated from stored signals** — `replay(evaluation_id)` reproduces the original headline score exactly, with **zero model calls** (assert against `GET /api/dev/llm` call count).
2. **Replaying under a different version set produces a diff, not a silent overwrite** — the original evaluation row is unchanged afterwards.
3. **Two evaluations of the same candidate carry different `evaluation_version` hashes iff a version input changed.**
4. **A candidate's score history is retrievable** and no historical row is ever mutated.
5. **Tenant A cannot read tenant B's candidates, evaluations, roles or rankings** — asserted on every recruiter endpoint, not sampled.
6. **Every recruiter and dev endpoint requires a valid API key.**
7. **`GET /api/health` reports the active taxonomy, rubric, scoring and prompt versions.**
8. **A taxonomy minor bump does not change any historical evaluation's score**; a major bump marks prior evaluations as not-comparable rather than recomputing them.
9. **Score explainability is unchanged** — Evaluation → Dimension → Evidence → Quote, still with no model call.
10. **Suite green and larger:** ≥ 145 tests.

## Risks

| Risk | Mitigation |
|---|---|
| **`tenant_id` retrofit misses a query path**, causing cross-tenant leakage — the worst possible bug for this product | Enforce at the session/repository layer, not per callsite. The two-tenant isolation suite asserts every endpoint, and a new endpoint without an isolation test does not merge |
| Replay drifts from live scoring — two code paths computing "the same" number | Replay must call the **same** `signals`/`scoring` functions as the live path. If it needs its own copy of any formula, the design is wrong |
| Provenance stamping is added to the write path but not to every recompute site | One choke point: nothing writes an evaluation except a single `record_evaluation()` |
| Schema reset loses demo data mid-phase | `seed.py` still regenerates everything, and the fixture is generated. Rehearse the reset in week 7 |
| Versioning turns into ceremony — versions nothing reads | Every version field must be consumed by replay or the health endpoint. A field nothing reads is deleted |
| Auth breaks the demo path | `/api/dev/*` stays gated by `ENABLE_DEV_ENDPOINTS`; demo keys are provisioned, not bypassed |

## Deferred Work

Still explicitly out of scope after Phase 2:

- **Person / Candidacy split** — the dormant WhatsApp routing ambiguity. Fires only when one phone holds two open candidacies; do it the week a customer runs two requisitions
- **Job / RoleProfile split**
- **Claim-scoped consistency**; re-pointing `Contradiction` at two facts
- **Dimension-set redesign** — must precede large-scale data accumulation, since it is the one change requiring historical re-scoring. Trigger: recruiter feedback that the current six do not describe their roles
- **`evidence_nodes` / signal rows**; renaming `evidence` → `dimension_readings` (do at a schema reset)
- **Event sourcing** — every analytics question on the roadmap is answerable from current tables
- **Percentile calibration** — needs n ≥ 30 per cohort
- **Data protection, retention, adverse-impact monitoring, candidate rights** — a Phase 3 workstream, and a *legal* gate rather than an engineering one. It becomes blocking the moment a real customer's contract is drafted
- **Embeddings, vector search** — permanently out of runtime
- **Orchestrator/planner/ranking extraction, `api/contracts/`, observability subsystem** — code organisation with no customer-visible effect
