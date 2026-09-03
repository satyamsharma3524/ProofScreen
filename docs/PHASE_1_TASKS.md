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

## Phase exit checklist

- [ ] 103 → **≥ 118** tests passing
- [ ] M1b = 100% · M1a ≥ 80% · M1c ≥ 70%
- [ ] M2b ≥ 2.0×
- [ ] M3a ≥ 20 · M3b < 15% · M3c ≥ 40%
- [ ] M5a ≥ 90% · M5b ≥ 95% · M5c ≤ 2%
- [ ] **M4a published**, whichever direction it points
- [ ] All guardrails green; no anti-bias test edited
- [ ] `TRANSFER_PROBE=false` reproduces the pre-phase system exactly
