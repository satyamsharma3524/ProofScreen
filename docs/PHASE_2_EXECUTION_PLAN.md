# Phase 2 Execution Plan — Make the Signal Durable and Sellable

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
