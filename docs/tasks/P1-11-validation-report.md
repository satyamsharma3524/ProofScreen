# P1-11 — `scripts/validation_report.py`

Ten-section artifact per `EXECUTION_STANDARD.md` §10. Owner **B**, task 4 of 7.
Depends on **P1-09** (`60855a5`) and **P1-10** (`72d243d`).

---

## 1. Objective

Turn the phase objective from an assertion into a number.

Everything else ProofScreen produces is the system measuring itself:
`resume_score` 59 beside `competence_score` 14 shows the two numbers *disagree*,
never which one was right. M4 is the only metric that answers that, because it
is the only one correlated against a decision a human made.

## 2. Current State

| | |
|---|---|
| Suite | **157 passing** |
| `candidate_outcomes` | writable via P1-10; **0 rows** in seeded data |
| `scripts/` | `dump_fixture.py` only; not a package |
| scipy | **not installed**, and not a dependency |
| Golden set | `tests/data/routing_golden.json` — 64 entries, 60 labelled (A's, read-only) |

**Must NOT be rebuilt:** `merge_signals`, `total_signals`, `is_non_answer`,
`match_family`. All are imported from A's modules read-only — ownership governs
editing, not importing.

## 3. Deliverables

| Artifact | Detail |
|---|---|
| `scripts/validation_report.py` | M1–M5 + guardrails, per cohort and overall |
| `build_report(snap, minimum_n) -> ValidationOut` | The **shared** implementation P1-12 serves |
| `scripts/__init__.py` | So the router can import it |
| Hand-rolled `spearman`, `quantile`, `median`, `precision_at_k` | No new dependency |
| 8 tests | `tests/test_pipeline.py` |

`scripts/__init__.py` is the one judgment call. P1-12's acceptance is *"endpoint
and script return identical numbers — one implementation, two surfaces"*, and
the plan puts the implementation in `scripts/`. Re-implementing the maths in the
router would guarantee drift and make that criterion unverifiable, so the
package marker is the smaller cost. It adds no layer and no abstraction.

## 4. Risks

| Risk | Mitigation |
|---|---|
| **A correlation is reported over a handful of candidates** and reads as evidence | `MINIMUM_N = 30`. Below it, `sufficient=False` and both correlations are `None`. No estimate, no interpolation |
| **A negative M4a is quietly not published** | No branch in the file suppresses a result. The metrics doc pre-commits to publishing before seeing it; the renderer prints the margin whichever way it points, including `NOT MET` |
| Hand-rolled statistics are subtly wrong | Pinned against values computable by hand, including tie-averaging and the undefined cases |
| **A flat variable reports 0.0** and reads as "no relationship found" | `spearman` returns `None` when undefined. `0.0` and "not computable" are different claims |
| M1b's denominator is wrong, so a correctness invariant measures the wrong claims | Uses the orchestrator's own stall rule, pinned by a test. **This risk fired** — see §Findings |

## 5. Deferred Work

- Guardrail automation (median turn latency, fallback-quality comparison) —
  needs a timing column and a paired model/fallback run. Out of scope.
- Adverse-impact distributions (`PRODUCTION_READINESS.md` §8) — needs real
  candidates.
- A configured margin threshold for M5a — A's `taxonomy.py`.

## 6. Success Metrics

This task *is* the measurement apparatus. Its own acceptance: every metric in
the metrics document prints, from stored rows, with **zero model calls**.

B's contract measure: **M4a with its n, published whichever direction it
points.** Delivered as `insufficient data (n < 30)` at n = 0 — a statement of
fact, not a placeholder.

## 7. Task Breakdown

| ID | Step | Files |
|---|---|---|
| a | Pure statistics | `scripts/validation_report.py` |
| b | `Snapshot` + `collect()`, one batched read | same |
| c | `build_report()` — M4, shared with P1-12 | same |
| d | `compute_m1/m2/m3/m5` | same |
| e | `render()` with targets and verdicts | same |
| f | 8 tests | `tests/test_pipeline.py` |

Migration impact: **none.**

## 8. Dependency Graph

```
P1-09 ──▶ P1-10 ──▶ P1-11 ──▶ P1-12
```

## 9. Acceptance Criteria

1. Runs clean on seeded data and prints every metric.
2. Withholds below n = 30 and says so.
3. Zero model calls.
4. Computes M4 correctly once n is met (proven with a lowered floor, not with synthetic decisions).
5. Suite green, 157 → 164.

Satisfies phase acceptance criterion **8**.

## 10. Implementation Order

a → b → c → d → e → f, one commit with its ledger row.

---

## Findings during execution

Recorded because both developer contracts require measuring before claiming,
and because two of these were defects in this task's own first cut.

1. **`stalled` was proxied as `claim_scores.score == 0`** and reported **0**
   stalled claims while 3 TRANSFER probes had fired — contradicting the shipped
   ledger. A claim can earn signals early and stall later. Fixed to the
   orchestrator's rule (≥2 answers, last `signals_found == 0`): **3 stalled,
   M1b = 100%.**
2. **M2b's tercile lookup silently returned `n/a`.** Rewritten; it now
   distinguishes "no transfer probe reached a tercile" from a ratio of zero.
3. **M5a counted deliberately-ambiguous golden entries as failures.** Four of
   64 are labelled ambiguous and *should* fall back to `general`, so correct
   behaviour read as an 82.8% defect. Labelled-only and all-entries rates are
   now printed separately.
4. **M5a is specified as margin-based; no margin threshold exists.** P1-06's
   `match_family` falls back on a two-term floor. Computed as floor-based and
   labelled as such in the output rather than inventing a threshold. Adding one
   is a change to A's `taxonomy.py`.
