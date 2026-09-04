# P1-09 — `candidate_outcomes`

Ten-section artifact per `EXECUTION_STANDARD.md` §10. Owner **B**, task 1 of 7.
No dependencies.

> **Ownership contradiction, resolved.** `PHASE_1_TASKS.md` lists P1-09 as Owner
> **A** with files `api/models.py` / `api/ids.py`. But `DEVELOPER_A_CONTRACT.md`
> names both files under *"You do not own — do not edit"* and omits P1-09 from
> A's queue, while `DEVELOPER_B_CONTRACT.md` claims both files and lists P1-09
> as B's task #1. `docs/README.md` rules on exactly this: *"For Phase 1 the
> contracts win."* Executed as **B**. A's ledger row for P1-08a confirms their
> queue is closed, so there is no contention.

---

## 1. Objective

Give the system somewhere to record **what a human actually decided**.

This is the deliverable that makes the phase objective falsifiable. Every other
number in Phase 1 is ProofScreen measuring itself — `resume_score` 59 against
`competence_score` 14 is divergence, and divergence is a demo, not evidence that
the second number is the right one. Until a recorded recruiter decision exists,
M4a has no second column and *"evidence-based verification produces a stronger
hiring signal"* stays an assertion.

## 2. Current State

Measured, not assumed:

| | |
|---|---|
| Suite | **142 passing** (A's queue complete through P1-08a) |
| Tables | **12**; `candidate_outcomes` absent |
| `api/ids.py` | 11 prefixed generators; `o_` unused |
| Contract | `OutcomeDecision`, `OutcomeIn`, `OutcomeOut` already in `schemas.py` from P1-00 |

`OutcomeDecision` is ordinal — `rejected < shortlisted < interviewed < offered
< hired` — and its own docstring records that the order is load-bearing because
the validation report rank-correlates against it.

**Must NOT be rebuilt:** the enum, `OutcomeIn/Out`, the id scheme. P1-00
pre-landed the contract so this task is a table and nothing else. Zero
`schemas.py` edits.

## 3. Deliverables

| Artifact | Detail |
|---|---|
| `CandidateOutcome` | `id · candidate_id (FK CASCADE) · role_id (FK SET NULL) · decision · stage · decided_by · note · decided_at` |
| `ids.outcome_id()` | Prefix `o_` |
| `ix_candidate_outcomes_candidate_decided` | `(candidate_id, decided_at)` — the query P1-11 runs per candidate |
| 4 tests | `tests/test_pipeline.py` (B's) |

**`role_id` is `SET NULL`, not `CASCADE`.** A recruiter deleting a scoring lens
must not delete the record that a person was rejected. The decision happened;
the lens it was viewed through is context. `CASCADE` here would silently destroy
exactly the rows M4a is computed over.

## 4. Risks

| Risk | Mitigation |
|---|---|
| **Append-only is a claim with no enforcement.** Nothing stops a later task issuing an `UPDATE` | Enforced by *shape*: deliberately no unique constraint on `candidate_id`, so a second decision is a second row. Pinned by a test asserting the earlier row is untouched. A trigger is not expressible under `create_all()` |
| **`ondelete` is not enforced where the suite runs.** Measured: SQLite reports `PRAGMA foreign_keys = 0`, so **all 17** `ondelete` clauses in `models.py` (15 CASCADE, 2 SET NULL) are inert under test. Only Postgres enforces them | The `SET NULL` test asserts the **declaration** via SQLAlchemy metadata — environment-independent, and it tests the design decision rather than SQLite's defaults. Runtime enforcement is a Postgres property, verified there. Flipping the pragma is **out of scope**: `api/db.py` is in neither developer's ownership list, and changing 17 clauses' semantics at once is not a table task. Raised under §9, logged, not fixed |
| `stage` becomes a second contradictory status | Documented on the column as the recruiter's own pipeline naming, free text, never read by scoring |
| The reset wipes A's local database | Announced in the commit; A's queue is closed so nothing of theirs is in flight |

## 5. Deferred Work

- `Evaluation` as an entity, so an outcome points at *the evaluation it
  disputes* rather than a candidate plus a lens
  (`PROOFSCREEN_DOMAIN_MODEL.md` F3). Phase 2.
- `tenant_id` — ships with auth or not at all. Phase 2.
- DB-level append-only enforcement, and `PRAGMA foreign_keys=ON` for the test
  path, with the schema reset that brings real migrations.

## 6. Success Metrics

Enables **M4a / M4b / M4c** in full; produces no metric itself. A table with no
rows moves nothing, which is why P1-10 follows immediately.

Guardrail: **no existing test changes behaviour** — the table is inert until
P1-10 writes to it, the same inertness contract P1-00 shipped under.

Counter-metric note: none of C1–C3 apply. This task cannot be gamed; it stores
a human's decision verbatim.

## 7. Task Breakdown

| ID | Step | Files | Migration |
|---|---|---|---|
| a | `ids.outcome_id()` | `api/ids.py` | none |
| b | `CandidateOutcome` | `api/models.py` | **schema change — new table** |
| c | Composite index | `api/models.py` | with (b) |
| d | 4 tests | `tests/test_pipeline.py` | none |

**Migration impact: full reset.** The only one in Phase 1.

    docker compose down -v && docker compose up --build
    docker compose exec api python seed.py
    python scripts/dump_fixture.py && pytest -q

## 8. Dependency Graph

```
P1-09 ──▶ P1-10 ──▶ P1-11 ──▶ P1-12
```

Head of the D3→D4 chain. Independent of D1/D2 and of P1-13/P1-08b. Touches no
file on A's side.

## 9. Acceptance Criteria

1. `create_all()` builds `candidate_outcomes` — 12 → 13 tables.
2. `ids.outcome_id()` returns an `o_`-prefixed id.
3. Two decisions for one candidate coexist; the earlier row is unchanged.
4. `role_id` is **declared** `SET NULL` and the outcome survives lens deletion.
5. Suite green, 142 → 146. No existing test edited.

## 10. Implementation Order

a → b → c → d, one commit with its ledger row. Tests written before the model
and verified to fail against the pre-change file.
