# Phase 1 — Task Breakdown

Execution detail for `PHASE_1_EXECUTION_PLAN.md`. Every task: files, tests,
migration, acceptance. Owners per the README file map (**A** = conversation /
channel / infra, **B** = evidence / scoring / dashboard-facing).

**Baseline: 103 passing. Migration story: no Alembic — `docker compose down -v`
→ `up` → `seed.py` → `dump_fixture.py`.**

**One correction to the phase plan:** `select_transfer()` goes in
`engine/orchestrator.py` beside `plan_next()`, **not** a new `engine/planner.py`.
Planner extraction is deferred under the lock; creating the module now would be
the architecture change we agreed not to make.

---

## Shipped ledger

**This section is the record of what actually shipped.** The task sections below
are the plan; they are not updated as work lands. Two developers and several
sessions work in parallel, so a plan that silently doubles as a status report
leaves everyone guessing which it is.

**Every merged task adds a row, including work that was not a planned task.**
The `product` family below is exactly that case: it was the right thing to do
and it was invisible to the plan until it was written down here.

Numbers are **measured, not estimated** — see *Recording what shipped* in both
developer contracts for what a row has to carry.

| Commit | Task | Owner | Tests | Measured effect |
|---|---|---|---|---|
| `f0d47a7` | *(unplanned)* role dimension weights applied, not discarded | A | 102 → 103 | Dimension lenses were accepted, stored and returned with **no effect on any score**. Two roles with identical claim weights now rank differently |
| `d52f223` | *(unplanned)* cohort-neutral prompts and dev placeholders | A | 103 | Every worked example on the primary LLM path was call-centre. Removed, not parameterised — per-family examples would break the one-taxonomy-entry criterion |
| `ba43ba1` | **P1-00** frozen-file contract surface | A | 103 → 104 | All Phase 1 `schemas.py` additions in one commit. Zero further edits to that file have been needed since |
| `7f326e0` | **P1-01 – P1-04** transfer probe | A | 104 → 126 | Stalled claims earn one transfer probe. Closes the hole where the fabricator got **fewer** questions than the honest candidate |
| `df9fbf8` | **P1-06** `FamilyMatch` routing | A | 126 → 133 | Golden-set accuracy **90.7% → 98.1%** (M5b target 95%). Cause was substring matching, not the specified IDF: `hr` ⊂ *through*, `api` ⊂ *rapid*, `arr` ⊂ *arranged* |
| `034b7a6` | **P1-07** requisition precedence | A | 133 → 136 | Routing is deterministic across disagreeing model runs. All three tests verified to **fail** against the previous implementation |
| `e321265` | *(unplanned)* `product` family + `y → ies` matching | A | 136 → 137 | Family added with **zero Python edits** — the "cohort #101" criterion, first exercised end to end. Inert for existing routing: 0 family changes across 57 pre-existing golden resumes. `y → ies` measured at 0 family changes and 0.0000 confidence drift on all 64 |
| `p1-08a` | **P1-08a** `GET /api/dev/detect` | A | 137 → 142 | Routing explainable — matched terms, per-family scores, margin and the family it is measured against — at **0 LLM calls** (verified before/after via `/api/dev/llm`). No `schemas.py` edit: returns a plain dict like the other dev GETs. **Completes Developer A's Phase 1 queue** |
| `p1-09` | **P1-09** `candidate_outcomes` | B | 142 → 146 | 12 → 13 tables. The row that makes the objective falsifiable: until a human decision is stored, M4a has no second column. Append-only by shape (no unique key on `candidate_id`), `role_id` `SET NULL` so deleting a lens cannot delete a rejection. All 4 tests verified to fail against the pre-change file. **Measured, and raised under §9:** SQLite runs `PRAGMA foreign_keys=0`, so all **17** `ondelete` clauses in `models.py` (15 CASCADE, 2 SET NULL) are inert under the suite and enforced only on Postgres — the SET NULL test asserts the *declaration* via metadata instead. Pragma left off: `api/db.py` is in neither ownership list and re-arming 17 clauses at once is not a table task |
| `p1-10` | **P1-10** outcome endpoints | B | 146 → 152 | Round trip verified: a decision recorded against a candidate **and a lens**, read back oldest-first, ordinal ladder intact. Unknown candidate and unknown `role_id` both 404 — an unknown lens is an error, not a null column, because "rejected under the Ops lens" and "rejected" group differently in M4a. **Circularity guard shipped:** `test_recording_an_outcome_changes_no_score` pins that recording a decision moves no score — an outcome endpoint that recomputed a profile would make M4a correlate the system with itself. All 6 tests verified to fail against the pre-change file; 2 initially passed both ways (a missing route also 404s, and a 404 spends no tokens) and were strengthened to assert the detail string and the 201 |
| `p1-13` | **P1-13** `why_ranked` | B | 152 → 157 | **100%** of ranked rows now carry a reason (was 0% — the field existed since P1-00 and was always null). Cites evidence, never the score: *"51 evidence signals across 3 claims, 6 of 6 dimensions probed; strongest on concrete figures (100); no contradictions"* against *"0 evidence signals…; no concrete figures in any answer; 3 claims stalled"*. Changes with the lens — same candidate reads *Team handling (80%), scored 65* under one and *AHT (80%), scored 52* under the other. **Zero new queries**: derived from `dimensions_json`, already loaded by `rank_candidates`; counting quantities from `signals_json` instead would be ~12 JSON parses per candidate on the busiest endpoint. All 5 tests verified to fail against the pre-change file |
| `p1-11` | **P1-11** `scripts/validation_report.py` | B | 157 → 164 | Every metric in `PHASE_1_SUCCESS_METRICS.md` computed from stored rows, **0 model calls**. Spearman, quantiles and precision@5 hand-rolled — scipy is not a dependency and one rank correlation does not earn one. On seeded data: **M1b = 100%** on 3 stalled claims, M1c 100%, M3a 21 pts, M3b 0%, M3c 66.7%, M5b 98.3%, M5c 0%. **M4a: `insufficient data (n < 30)` at n = 0** — published as the floor requires, not estimated. **Two bugs found in my own first cut and fixed before commit:** (1) I proxied *stalled* as `claim_scores.score == 0`, which reported 0 stalled while 3 TRANSFER probes had fired — a claim can earn signals early and stall later, so M1b, a correctness invariant, was unmeasurable; now uses the orchestrator's rule (≥2 answers, last one `signals_found == 0`) and reports 3. (2) M2b's tercile lookup silently returned n/a. Also disaggregated M5a: 4 of 64 golden entries are deliberately ambiguous and **should** fall back, so counting them as failures made correct behaviour look like an 82.8% defect. **Reported, not fixed:** M5a is defined in the metrics doc as margin-based, but P1-06 ships no margin threshold — `match_family` falls back on a two-term floor. Computed as floor-based and labelled as such; adding a threshold is a change to A's `taxonomy.py` |
| `p1-12` | **P1-12** `GET /api/recruiter/validation` | B | 164 → 168 | One implementation, two surfaces: the endpoint calls the same `build_report()` the script prints, and a test compares them field for field. `minimum_n` defaults to **30** and is echoed in the payload, so a correlation computed under a lowered floor cannot be quoted as the real M4a. `ValidationOut` and `ValidationCohort` now appear in `/openapi.json` — correctly absent until a route referenced them, exactly as P1-00's verification note predicted. 0 model calls |
| `p1-08b` | **P1-08b** `routing_confidence` | B | 168 → 173 | Populated from the resume `build_candidate_graph` already loads — **0 new queries, 0 model calls**. **Distribution measured, per contract: 0.171 / 0.397 / 0.719** across the three seeded personas, so the field discriminates rather than decorating — Arjun routes to `bpo_operations` on a margin of **0.17**, a near coin-flip that is nonetheless confidently placed, which is exactly the case the field exists to surface. A test fails if the values ever collapse to one. `0.0` is disambiguated by the `job_family` pair (`general` = never cleared the floor; a real family = exact tie) rather than by a second field, since `schemas.py` is frozen. All 5 tests verified to fail against the pre-change file |
| `p1-05` | **P1-05 + P1-05a** fixture regen + non-BPO persona | B | 173 → 180 | **Step 1 verified a no-op before anything was added:** moving `job_family`/`jd` out of the literal at `seed.py:259` left the three BPO personas byte-identical — 56 / 46 / 14 competence, unchanged. `product` persona (Maya) added: routes to `product` at **0.774**, coverage 60%, competence **61** on outcome_ownership 71 / experimentation 59 / discovery 51 — the first end-to-end exercise of a cohort A added with zero Python edits. **TRANSFER INVARIANT RE-MEASURED AND UNCHANGED: 3 probes, all Rohit, all `signals_found = 0`** — the `seed.py:288` answer-repeat that stalls his claims is untouched. Resume/competence inversion holds (Rohit 1st of 4 by resume, 4th by competence). Two-lens flip holds, and the product lens gives a **third distinct order**: Maya > Arjun > Priya > Rohit. Fixture regenerated — now carries `routing_confidence` 0.719, previously null. 5 of 7 tests fail without the change; the other 2 are guards against future breakage and are labelled as such rather than claimed as proofs |

**Current measured state**

| | |
|---|---|
| Tests | **180 passing** |
| Families | **10** (9 real + `general`) |
| Golden set | 64 entries — 60 labelled, 4 ambiguous |
| Routing accuracy | **98.3%** (M5b target 95%) |
| Seeded cohorts | **2** — `bpo_operations` (3 personas) + `product` (1) |
| Role lenses | **3** — two BPO, one product |
| Developer A queue | **closed** through P1-08a |
| Developer B queue | **closed** through P1-05 |
| Known miss | `g21` — one keyword (`npa`) is below the two-term floor. Correct behaviour, generous label |


**Open, logged, not fixed**

- **`seed.py` is single-family.** All three personas are `bpo_operations`,
  hardcoded at `seed.py:259`. A one-cohort seed cannot demonstrate cohort
  neutrality, which is the product's central claim. Specced as P1-05a.
- **The seed answer-repeat and the transfer probe are coupled.** `seed.py:288`
  repeats the last answer once a pool is exhausted; that repetition is what
  makes Rohit's claims stall, which is what makes his three TRANSFER probes
  fire. Measured: only the fabricator is transfer-probed, and he answers with
  authored evasions scoring `signals_found=0` — the thesis demonstrating
  itself. **Anyone "fixing" the repetition must re-verify that TRANSFER still
  fires**, or the demo loses the moment it exists for.

---

## P1-00 — The single frozen-file commit ★ *(gate for the whole phase)*

Every `api/schemas.py` change in Phase 1, batched into one reviewed commit so
the frozen two-owner file is touched exactly once.

| | |
|---|---|
| **Owner** | A + B together, one commit |
| **Files** | `api/schemas.py` |
| **Adds** | `ProbeLevel.TRANSFER` · `CandidateSummary.why_ranked: str \| None` · `CandidateGraph.routing_confidence: float \| None` · `OutcomeIn` · `OutcomeOut` · `ValidationOut` |
| **Migration** | None. `questions.probe_level` is `String(20)`; `"TRANSFER"` fits. Enum columns are strings by design |
| **Tests** | All 103 pass **unchanged** — every addition is inert until a later task reads it. `PROBE_ORDER` deliberately untouched, so no selection behaviour changes |
| **Acceptance** | `/openapi.json` regenerates additively; `python -c "import api.main"` clean; 103 green |

> **Verification note (found during execution).** FastAPI publishes only schemas
> reachable from a route, so `OutcomeIn/Out`, `OutcomeDecision` and
> `ValidationOut/Cohort` are **correctly absent** from `/openapi.json` until
> their endpoints land in P1-10 and P1-12. Verify route-referenced additions
> (`ProbeLevel.TRANSFER`, `why_ranked`, `routing_confidence`) through OpenAPI;
> verify the rest by import and construction. Do not add placeholder endpoints
> to make them publish — that is P1-10/P1-12 scope.

**Status: MERGED.** 103 → **104 passing**; `test_p1_00_additions_are_inert`
pins the inertness contract.

Everything below is unblocked once this lands.

---

## D1 — Transfer probe

### P1-01 Transfer brief and offline fallback
| | |
|---|---|
| **Owner** | A · **Depends** P1-00 |
| **Files** | `api/engine/question.py` |
| **Detail** | `PROBE_BRIEFS[TRANSFER]` and `FALLBACK_QUESTIONS[TRANSFER]`. The fallback is a `string.Template` with `$their_method` / `$other_problem` filled from the candidate's own claims. **No prompt-file edit** — the template already interpolates `$probe_level_brief` and `$family_label` |
| **Tests** | `test_transfer_question_poses_an_unseen_situation` · `test_transfer_question_works_with_no_api_key` |
| **Migration** | None |
| **Acceptance** | `fallback_question(TRANSFER)` returns a question about a situation the candidate has **not** described. Hard prerequisite for P1-03: both dicts are bare lookups, so activating TRANSFER first raises `KeyError` in fixture mode |

### P1-02 `select_transfer()`
| | |
|---|---|
| **Owner** | A · **Depends** P1-00 |
| **Files** | `api/engine/orchestrator.py` (beside `plan_next`) |
| **Detail** | `select_transfer(claim, evidence, other_claims) -> TransferSpec`. **No `job_family` parameter** — family branching unrepresentable by signature. Operators **T1** (their method → their *other* claim's problem) when a second claim exists, **T3** (invert the outcome) otherwise |
| **Tests** | `test_transfer_selection_is_family_invariant` (identical evidence tagged `bpo_operations` and `software_engineering` ⇒ byte-identical operator and target) · `test_t1_used_when_a_second_claim_exists` · `test_t3_used_when_it_does_not` |
| **Migration** | None |
| **Acceptance** | Pure, deterministic, no DB, no LLM. Same inputs ⇒ same spec, every run |

### P1-03 Activation and stall exemption
| | |
|---|---|
| **Owner** | A, **B reviews the `signals.py` hunk** · **Depends** P1-01, P1-02 |
| **Files** | `api/engine/signals.py` (`PROBE_ORDER`, `PROBE_LEVEL_DIMENSIONS[TRANSFER] = (CAUSAL_REASONING, PROCESS)`) · `api/engine/orchestrator.py` (`ClaimState.transfer_used`, `exhausted`, `plan_next`) · `api/config.py` + `.env.example` (`TRANSFER_PROBE`) |
| **Detail** | `exhausted` becomes `saturated or (stalled and transfer_used) or not levels_left`. TRANSFER never opens a claim |
| **Tests** | `tests/test_policy.py` — expect 2–3 assertions to move; **review each by hand, never edit one to make it green**. New: stalled claim gets exactly one transfer probe · saturated claim gets none · never an opening probe · `TRANSFER_PROBE=false` reproduces the pre-phase interview exactly |
| **Migration** | None |
| **Acceptance** | Metric **M1b = 100%** on seeded data. `plan_next` still pure and deterministic |

### P1-04 Wire selection into question generation
| | |
|---|---|
| **Owner** | A · **Depends** P1-03 |
| **Files** | `api/engine/orchestrator.py` (`ask_next`) · `api/engine/question.py` (`generate_question` accepts a `TransferSpec`) |
| **Tests** | End-to-end: a stalled claim produces a transfer question referencing the candidate's other claim |
| **Migration** | None |
| **Acceptance** | The generated question is visibly about a problem the candidate did not describe |

### P1-05 Regenerate fixture, verify demo moments
| | |
|---|---|
| **Owner** | B · **Depends** P1-03 |
| **Files** | `fixtures/sample_graph.json` (generated) |
| **Commands** | `python seed.py --reset && python scripts/dump_fixture.py` |
| **Tests** | `tests/test_pipeline.py` fixture assertions |
| **Migration** | Full reset |
| **Acceptance** | Resume/competence inversion still holds · two role lenses still produce two orders · all three candidates' numbers recorded in the PR description |

---

## D2 — Deterministic family routing

### P1-06 `detect_family` rewrite
| | |
|---|---|
| **Owner** | A · **Depends** none |
| **Files** | `api/taxonomy.py` |
| **Detail** | Returns a `FamilyMatch` **NamedTuple defined in `taxonomy.py`** (not `schemas.py` — no second frozen-file touch): `family · confidence · matched_terms · per_family_scores`. IDF-style weighting computed at load time from the taxonomy itself. Confidence = margin `(top1 − top2) / top1`. Normalise by family vocabulary size |
| **Tests** | `tests/data/routing_golden.json` — 50 labelled resumes across all 8 families · `test_routing_accuracy_on_golden_set` (≥95%) · `test_ambiguous_resume_returns_low_confidence` · `test_detection_is_deterministic` |
| **Migration** | None |
| **Acceptance** | Metrics **M5a ≥ 90%**, **M5b ≥ 95%**, **M5c ≤ 2%**. Existing resumes route identically unless deliberately changed — any diff reviewed, not accepted |

### P1-07 Requisition precedence; close the LLM-override deviation
| | |
|---|---|
| **Owner** | A · **Depends** P1-06 |
| **Files** | `api/engine/extract.py` (lines ~196–199) |
| **Detail** | Caller-supplied `job_family` always wins. The model may no longer override the detected family; its proposal is logged, not honoured |
| **Tests** | `test_supplied_family_always_wins` · `test_model_cannot_override_detected_family` |
| **Migration** | None |
| **Acceptance** | Two runs over the same resume route identically. Closes the deviation logged in `ARCHITECTURE_LOCK_v1.md` §2 |

### P1-08 Surface routing confidence; `/api/dev/detect`
| | |
|---|---|
| **Owner** | B (graph) · A (endpoint) · **Depends** P1-06, P1-00 |
| **Files** | `api/engine/graph.py` (populate `routing_confidence`) · `api/routers/dev.py` (`GET /api/dev/detect?text=…`) |
| **Tests** | `test_low_confidence_routing_is_visible_in_the_graph` · `test_detect_endpoint_explains_without_a_model_call` (assert `/api/dev/llm` call count unchanged) |
| **Migration** | None |
| **Acceptance** | Routing explainable — terms hit, per-family scores, margin — with no model call |

---

## D3 — Outcome capture

### P1-09 `candidate_outcomes` table
| | |
|---|---|
| **Owner** | A · **Depends** none |
| **Files** | `api/models.py` · `api/ids.py` (prefix `o_`) |
| **Schema** | `id · candidate_id (FK, cascade) · role_id (FK, nullable) · decision · stage · decided_by · note · decided_at`. Append-only; index `(candidate_id, decided_at)` |
| **Tests** | `test_outcome_rows_are_append_only` |
| **Migration** | **New table — full reset required.** `docker compose down -v` → `up` → `seed.py` → `dump_fixture.py`. The only migration in Phase 1 |
| **Acceptance** | `create_all()` builds it; no existing test affected |

### P1-10 Outcome endpoints
| | |
|---|---|
| **Owner** | B · **Depends** P1-09, P1-00 |
| **Files** | `api/routers/recruiter.py` |
| **Endpoints** | `POST /api/recruiter/candidates/{id}/outcome` · `GET /api/recruiter/candidates/{id}/outcomes` |
| **Tests** | `test_outcome_can_be_recorded_and_retrieved` · `test_outcome_history_is_ordered` · `test_invalid_decision_is_rejected` |
| **Migration** | None beyond P1-09 |
| **Acceptance** | A decision is recordable against a candidate **and a role lens**, and retrievable in order |

---

## D4 — Validation report

### P1-11 `validation_report.py`
| | |
|---|---|
| **Owner** | B · **Depends** P1-10 |
| **Files** | `scripts/validation_report.py` (new) |
| **Detail** | Computes M1–M5 and guardrails, per cohort and overall. Spearman correlation, precision@5, inversion count. **Minimum n = 30**, else prints `insufficient data`. No model call |
| **Tests** | `test_validation_report_runs_on_seeded_data` · `test_report_withholds_below_minimum_n` · `test_report_makes_no_model_calls` |
| **Migration** | None |
| **Acceptance** | Runs clean on seeded data; prints every metric in `PHASE_1_SUCCESS_METRICS.md` |

### P1-12 `GET /api/recruiter/validation`
| | |
|---|---|
| **Owner** | B · **Depends** P1-11, P1-00 |
| **Files** | `api/routers/recruiter.py` |
| **Tests** | `test_validation_endpoint_matches_the_script` |
| **Acceptance** | Endpoint and script return identical numbers — one implementation, two surfaces |

---

## D5 — Ranked-list explainability

### P1-13 `why_ranked`
| | |
|---|---|
| **Owner** | B · **Depends** P1-00 |
| **Files** | `api/engine/graph.py` |
| **Detail** | One sentence per candidate from stored rows: signal counts, causal chains, contradictions, stalled claims. Changes when `role_id` changes, because the weights changed |
| **Tests** | `test_every_ranked_candidate_explains_itself` · `test_why_ranked_makes_no_model_calls` · `test_why_ranked_changes_with_the_role_lens` |
| **Migration** | None |
| **Acceptance** | Every row in `GET /api/recruiter/candidates` carries a non-empty `why_ranked` |

---

## Dependency graph

```
P1-00 (frozen commit) ──┬──▶ P1-01 ──▶ P1-02 ──▶ P1-03 ──▶ P1-04
                        │                          └──▶ P1-05 (fixture gate)
                        ├──▶ P1-08
                        ├──▶ P1-10 ──▶ P1-11 ──▶ P1-12
                        └──▶ P1-13

P1-06 ──▶ P1-07 ──▶ P1-08        (independent of P1-00 except for P1-08)
P1-09 ──▶ P1-10                  (independent)
```

**Critical path:** P1-00 → P1-01 → P1-02 → P1-03 → P1-04 → P1-05.
**Parallel throughout:** A on D1/D2, B on D3/D4/D5 — disjoint files except the
`signals.py` hunk in P1-03, which B reviews.

## Migration summary

| Task | Migration |
|---|---|
| P1-09 | **New table `candidate_outcomes` — full reset.** The only one in Phase 1 |
| All others | None. Enum values are strings; new schema fields are optional |

Reset procedure, run once when P1-09 lands:
`docker compose down -v && docker compose up --build && docker compose exec api python seed.py && python scripts/dump_fixture.py && pytest -q`

## Phase exit checklist — measured 2026-09-04

All fourteen tasks are merged. Six criteria are met, four are not, and the
four are reported rather than worked around.

| | Criterion | Measured | Verdict |
|---|---|---|---|
| ✅ | 103 → ≥ 118 tests | **180** | met |
| ✅ | **M1b = 100%** *(correctness invariant)* | 100% on 3 stalled claims | met |
| ❌ | M1a ≥ 80% | **25%** | **unreachable as specified** — see below |
| ✅ | M1c ≥ 70% | 100% | met |
| ❌ | M2a ≥ +15% | **0%** | see below |
| ❌ | M2b ≥ 2.0× | **n/a** | no transfer probe reaches the top tercile |
| ⚠️ | M3a ≥ 20 | **19.2 pts** | 0.8 short at n = 4 |
| ✅ | M3b < 15% | 0% | met |
| ✅ | M3c ≥ 40% | 50% | met |
| ❌ | M5a ≥ 90% | **81.7%** | floor-based; no margin threshold exists |
| ✅ | M5b ≥ 95% | 98.3% | met |
| ✅ | M5c ≤ 2% | 0% | met |
| ✅ | **M4a published** | `insufficient data (n < 30)` at n = 0 | **met** — published as the floor requires |
| ✅ | Guardrails green, no anti-bias test edited | `test_scoring.py` diff = 0 lines | met |
| ✅ | `TRANSFER_PROBE=false` reproduces the pre-phase system | 0 probes; competence 46 / 61 / 56 / 14 **identical** both ways; suite green | met |

### The four that are not met, and why none of them is a code defect

**M1a (25% vs ≥ 80%) — the target contradicts the mechanism.** TRANSFER fires
*only* on a stalled claim; that is the activation rule D1 specified and
acceptance criterion 1 pins. So M1a is bounded by the stall rate, and reaching
80% would require 80% of candidates to stall — which on a healthy pipeline
would be alarming rather than good. One of the two numbers is wrong, and it is
not the code: **M1b (reach *on stalled claims*) is the metric that measures
what the probe was built to do, and it is at 100%.** Recommend M1a be
re-specified against stalled sessions, or dropped. Not changed here —
`PHASE_1_SUCCESS_METRICS.md` is frozen and the activation rule is A's.

**M2a (0%) and M2b (n/a) — correct behaviour, wrong population.** Only the
fabricator is transfer-probed, and his three transfer answers score
`signals_found = 0`. That is **C1 working exactly as written**: *"a fabricator
should produce near-zero signals on a transfer probe."* M2a's +15% target and
M2b's separation ratio both need a transfer-probed candidate who *does* have
evidence, and the seed has none because the three honest personas never stall.
Both become measurable with real candidates; neither is measurable on authored
demo data by construction.

**M5a (81.7% vs ≥ 90%) — the metric names a threshold that does not exist.**
It is defined as "% routed above the margin threshold", but P1-06 ships no
margin threshold: `match_family()` falls back on a two-term floor. Reported
floor-based and labelled as such in the report output. Configuring a threshold
is a change to A's `taxonomy.py` and belongs with the low-confidence *flag*
that D2 describes and P1-06 did not ship.

**M3a (19.2 vs ≥ 20) — an artifact of n = 4.** It was 21 pts on three personas
and fell when Maya (competence 61) landed between Priya and Arjun, compressing
the interquartile range. An IQR over four candidates moves several points per
candidate added; the number is honest and the sample is too small for it to
mean much either way.

### What Phase 1 cannot exit on, and what would fix it

**M4a needs 30 decided candidates per cohort and has 0.** The apparatus is
built and tested end to end — table, endpoints, report, HTTP surface, the
minimum-n guard — and it correctly reports `insufficient data`. No synthetic
decisions were seeded, deliberately: the metrics document says *do not
estimate*, and a correlation over four authored personas would look like
evidence while being none.

Two honest routes to the number, both already named in the plan's risk register:

1. Record real decisions through
   `POST /api/recruiter/candidates/{id}/outcome` as recruiters work.
2. Run the **blind panel** — three reviewers rank candidates from resumes
   alone, then from evidence graphs, and correlate.

Until one of those produces n ≥ 30, M4a stays published as insufficient. That
is the finding, and it is the honest one.
