# P1-10 — outcome endpoints

Ten-section artifact per `EXECUTION_STANDARD.md` §10. Owner **B**, task 2 of 7.
Depends on **P1-09** (`60855a5`).

---

## 1. Objective

Let a recruiter record a decision, and read the history back. P1-09 built the
table; a table nobody writes to moves no metric. This is the surface that turns
`candidate_outcomes` from schema into data.

The phase risk register names the failure mode precisely: *"D3/D4 produce no
data — recruiters don't record outcomes, so the objective stays unproven."* Its
mitigation is that recording must be **one call**, not a workflow. Hence one
POST with a single required field.

## 2. Current State

| | |
|---|---|
| Suite | **146 passing** |
| `candidate_outcomes` | exists, **0 rows**, no way to write one |
| `api/routers/recruiter.py` | 5 routes, none about outcomes |
| Contract | `OutcomeIn` / `OutcomeOut` / `OutcomeDecision` already in `schemas.py` from P1-00 |

`OutcomeIn` requires only `decision`; `stage`, `role_id`, `decided_by` and
`note` are optional. That shape is the mitigation above, already decided in
P1-00 — this task must not add required fields to it.

**Must NOT be rebuilt:** the schemas, the table, `role_to_out`. Zero
`schemas.py` edits, and `api/main.py` needs none either — the recruiter router
is already registered.

## 3. Deliverables

| Artifact | Detail |
|---|---|
| `POST /api/recruiter/candidates/{id}/outcome` | 201 → `OutcomeOut` |
| `GET /api/recruiter/candidates/{id}/outcomes` | `list[OutcomeOut]`, oldest first |
| 6 tests | `tests/test_pipeline.py` |

**Ordering is oldest-first, and that is a decision.** The validation report
walks a candidate's decisions as a progression (`shortlisted` → `interviewed` →
`offered`), so chronological order is the order the data is consumed in.
Newest-first would be the better default for a UI feed and the wrong one for
P1-11.

**A `role_id` that does not exist is a 404, not a silently-null column.** The
lens is the context that makes a decision interpretable — "rejected under the
Ops lens" and "rejected" are different facts, and quietly dropping the first
into the second corrupts M4a's grouping without any error surfacing.

## 4. Risks

| Risk | Mitigation |
|---|---|
| An invalid `decision` reaching the ordinal scale | `OutcomeDecision` is an enum in `OutcomeIn`, so FastAPI rejects it with **422** before the handler runs. Tested, because the ordinal is load-bearing for M4a |
| Recording becomes a workflow and nobody does it | One POST, one required field. No session, no auth, no lookup step |
| An outcome written against a candidate who does not exist | 404 on the candidate before any insert. An orphan row is invisible to `rank_candidates` and would inflate `n_decided` without ever appearing in a correlation |
| **Recording an outcome must not touch a score.** A recruiter's decision is the independent variable; if it fed back into `competence_score`, M4a would correlate the system with itself | The handler writes one row and calls nothing in `engine/`. Pinned by a test asserting the candidate's graph numbers are byte-identical before and after |

That last risk is the one worth stating aloud: an outcome endpoint that
recomputed a profile would quietly make the headline metric circular.

## 5. Deferred Work

- Auth, so `decided_by` is the authenticated recruiter rather than a
  self-reported string. Phase 2, with `tenant_id`.
- Outcomes pointing at an `Evaluation` rather than a candidate + lens
  (`PROOFSCREEN_DOMAIN_MODEL.md` F3). Phase 2.
- Editing or retracting a decision. The table is append-only by design; a
  correction is a new row, and a UI that needs "undo" needs a `superseded_by`
  column, which is a schema change.

## 6. Success Metrics

Enables **M4a / M4b / M4c**; produces none itself. What it must demonstrate,
per B's contract: *an outcome written and read back round-trip, decision
ordering preserved.*

Guardrails: suite green; **zero model calls** (asserted against
`/api/dev/llm`); recording an outcome changes no score.

## 7. Task Breakdown

| ID | Step | Files |
|---|---|---|
| a | `POST …/outcome` with candidate + role validation | `api/routers/recruiter.py` |
| b | `GET …/outcomes`, oldest first | `api/routers/recruiter.py` |
| c | 6 tests | `tests/test_pipeline.py` |

Migration impact: **none** beyond P1-09.

## 8. Dependency Graph

```
P1-09 (done) ──▶ P1-10 ──▶ P1-11 ──▶ P1-12
```

Blocks the whole D4 chain. Independent of P1-13 and P1-08b.

## 9. Acceptance Criteria

1. A decision is recordable against a candidate **and a role lens**, and retrievable.
2. History returns oldest-first.
3. An invalid decision is rejected (422).
4. An unknown candidate is 404; an unknown `role_id` is 404.
5. Recording an outcome leaves every score unchanged and spends no model call.
6. Suite green, 146 → 152.

Satisfies phase acceptance criterion **7**.

## 10. Implementation Order

a → b → c, one commit with its ledger row. Tests verified to fail against the
pre-change file.
