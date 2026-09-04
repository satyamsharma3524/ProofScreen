# P1-12 — `GET /api/recruiter/validation`

Ten-section artifact per `EXECUTION_STANDARD.md` §10. Owner **B**, task 5 of 7.
Depends on **P1-11** (`f6c6ee8`) and **P1-00** (landed).

---

## 1. Objective

Serve M4 over HTTP so the number a recruiter or a judge sees is the same number
the script prints. The plan's phrasing is the whole requirement: **one
implementation, two surfaces.**

## 2. Current State

| | |
|---|---|
| Suite | **164 passing** |
| `build_report(snap, minimum_n) -> ValidationOut` | exists in `scripts/validation_report.py` |
| `ValidationOut` / `ValidationCohort` | in `schemas.py` from P1-00, **unreachable from any route** |
| `scripts/__init__.py` | added in P1-11 precisely so this import works |

`ValidationOut` is currently absent from `/openapi.json`, and correctly so —
P1-00's own verification note records that FastAPI publishes only schemas
reachable from a route. This task is what makes it reachable.

**Must NOT be rebuilt:** the report maths. The endpoint calls `collect()` and
`build_report()` and formats nothing.

## 3. Deliverables

| Artifact | Detail |
|---|---|
| `GET /api/recruiter/validation?minimum_n=` | `ValidationOut` |
| 4 tests | `tests/test_pipeline.py` |

`minimum_n` is exposed as a query parameter and **defaults to 30**. It exists so
a reviewer can inspect the maths on thin data deliberately and visibly — the
response echoes the `minimum_n` it used, so a number computed under a lowered
floor can never be mistaken for one computed under the real one. Lowering it
does not lower the standard; it makes the standard explicit in the payload.

## 4. Risks

| Risk | Mitigation |
|---|---|
| **The endpoint and the script drift**, and two surfaces report different numbers | One implementation. A test asserts the endpoint's payload equals `build_report()` field for field |
| A caller lowers `minimum_n` and quotes the result as the real M4a | The response carries the `minimum_n` used. `sufficient` is computed against that value, so a thin cohort is still labelled |
| It becomes a slow endpoint that scans everything | `collect()` is one batched read per table, already written that way. No per-candidate queries |
| A model call sneaks in | Asserted against `/api/dev/llm` |

## 5. Deferred Work

- Auth. The report exposes the whole pipeline's score distribution and there is
  no authentication anywhere in v1 — documented, deliberate, and Phase 2.
- Caching. Meaningless at current volume.
- M1/M2/M3/M5 over HTTP. `ValidationOut` is M4-shaped by P1-00's design, and
  widening it would mean editing the frozen file. The script prints the rest.

## 6. Success Metrics

Serves phase acceptance criterion **8** alongside P1-11. B's contract measure:
*endpoint returns the report; `minimum_n` honoured rather than reporting on thin
data.*

Guardrails: zero model calls; identical numbers to the script.

## 7. Task Breakdown

| ID | Step | Files |
|---|---|---|
| a | Import `collect` / `build_report` | `api/routers/recruiter.py` |
| b | `GET /validation` handler | same |
| c | 4 tests | `tests/test_pipeline.py` |

Migration impact: **none.**

## 8. Dependency Graph

```
P1-09 ──▶ P1-10 ──▶ P1-11 ──▶ P1-12   (end of the D4 chain)
```

## 9. Acceptance Criteria

1. Endpoint returns `ValidationOut`.
2. Its numbers equal the script's, field for field.
3. `minimum_n` defaults to 30 and is echoed in the response.
4. Below the floor, correlations are `null` and `sufficient` is `false`.
5. `ValidationOut` now appears in `/openapi.json`.
6. No model call. Suite green, 164 → 168.

## 10. Implementation Order

a → b → c, one commit with its ledger row.
