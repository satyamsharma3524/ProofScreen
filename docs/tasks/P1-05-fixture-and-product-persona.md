# P1-05 / P1-05a — fixture regeneration and a non-BPO persona

Ten-section artifact per `EXECUTION_STANDARD.md` §10. Owner **B**, task 7 of 7
— **last on purpose.** Depends on A's P1-06/P1-07 (landed) and on B's P1-08b
and P1-13, both of which change what a regenerated fixture contains.

---

## 1. Objective

Two things in one regeneration:

- **P1-05** — regenerate `fixtures/sample_graph.json` so the reference graph
  Developer B's dashboard is built against matches the engine after six merged
  tasks.
- **P1-05a** — add one non-BPO persona, so the demo shows the same mechanism
  working in an unrelated job family.

`docs/TRANSFER_DESIGN_AUDIT.md` §6 PS-004 is the standing reason for the
second: *"the audit's whole point is undermined if the only demonstration is a
call centre."* A single-family seed cannot demonstrate that the six rubrics and
the transfer probe are cohort-neutral, and that neutrality is the product's
central claim.

## 2. Current State

Measured before touching anything:

| Persona | family | resume | evidence | consistency | competence | badge |
|---|---|---|---|---|---|---|
| Priya Raghavan | bpo_operations | 28 | 56 | 100 | **56** | partial |
| Arjun Mehta | bpo_operations | 34 | 46 | 100 | **46** | partial |
| Rohit Verma | bpo_operations | 59 | 24 | 60 | **14** | unverified |

- **TRANSFER: 3 probes, all Rohit, every one `signals_found = 0`.**
- People First → Priya > Arjun > Rohit. Ops Excellence → Arjun > Priya > Rohit.
- `seed.py:259` **hardcodes** `job_family="bpo_operations"`, and there is one
  `JD_BPO` constant — so this is a code change, not only data.
- A added the `product` family with **zero Python edits**: six claim types, six
  fact keys, and `CAUSAL_REASONING` weighted highest (0.238) with
  `TOOL_FAMILIARITY` near zero (0.048).

**Must NOT be rebuilt:** the personas' answers, the answer-repeat at
`seed.py:288`, the scoring engine. See §4 — the repeat looks like a bug and is
load-bearing.

## 3. Deliverables

| Artifact | Detail |
|---|---|
| `job_family` and `jd` from the persona dict | Defaulting to BPO, so the three originals are byte-identical |
| `JD_PRODUCT` | Beside `JD_BPO` |
| `MAYA` — Product Manager | `product` family, answers keyed to *its* claim types |
| `ROLE_PRODUCT_OUTCOME` | A product lens; claim weights sum to 100 |
| Regenerated `fixtures/sample_graph.json` | Now carries `routing_confidence` |
| 7 tests | `tests/test_pipeline.py` |

## 4. Risks

| Risk | Mitigation |
|---|---|
| **Step 1 silently changes the three existing personas** | Verified as a no-op against the §2 baseline *before* the persona was added: 56 / 46 / 14, unchanged |
| **TRANSFER stops firing.** `seed.py:288` repeats the last answer once a pool is exhausted; that repetition is what stalls Rohit's claims, which is what fires his three transfer probes. It looks like a bug and it is the demo's best moment | Re-measured after the change: **3 probes, all Rohit, all `signals_found = 0`. Unchanged.** B's contract requires reporting this number whether or not it moved |
| A product persona written like an engineer's scores oddly | Product weights `CAUSAL_REASONING` at 0.238 and `TOOL_FAMILIARITY` at 0.048, so the answers are built around cause→action→outcome chains and defined metrics, not tooling. That is the weights working |
| **The persona rewards presentation.** A PM invites "communicates well" | Forbidden everywhere, always. A test scans every seed answer for presentation language |
| Answers keyed to BPO claim types would fall through to the `"I don't remember"` default, and the persona would score like a fabricator | Test asserts `MAYA["answers"]` keys are a subset of `product`'s claim types |

## 5. Deferred Work

- More cohorts in the seed. One non-BPO family proves neutrality; a third adds
  runtime, not evidence.
- `tests/conftest.py` product vocabulary — a shared-file change requiring an
  announcement to A, and nothing in Phase 1 needs it.

## 6. Success Metrics

B's contract requires all four measured: **all four candidates' numbers · the
resume/competence inversion still holds · the two-lens flip still holds ·
TRANSFER still fires for the fabricator.**

| | |
|---|---|
| Priya | resume 28 · competence **56** · partial |
| Arjun | resume 34 · competence **46** · partial |
| Rohit | resume 59 · competence **14** · unverified · 1 contradiction |
| Maya | resume 50 · competence **61** · partial · `product`, routing 0.774, coverage 60% |
| Inversion | **holds** — Rohit is 1st of 4 by resume and 4th of 4 by competence |
| Two-lens flip | **holds** — People First: Priya > Maya > Arjun > Rohit · Ops: Arjun > Maya > Priya > Rohit |
| Third lens | Product: **Maya > Arjun > Priya > Rohit** — a third distinct order |
| TRANSFER | **3 probes, all Rohit, all `signals_found = 0`. Unchanged.** |

## 7. Task Breakdown

| ID | Step | Files |
|---|---|---|
| a | `job_family` / `jd` from the persona dict | `seed.py` |
| b | **Verify (a) is a no-op** | measurement, no files |
| c | `JD_PRODUCT` | `seed.py` |
| d | `MAYA` | `seed.py` |
| e | `ROLE_PRODUCT_OUTCOME` | `seed.py` |
| f | Regenerate the fixture | `fixtures/sample_graph.json` |
| g | 7 tests | `tests/test_pipeline.py` |

**Migration impact: fixture regeneration** (and a full reset, since P1-09 added
a table):

    python seed.py --reset && python scripts/dump_fixture.py && pytest -q

## 8. Dependency Graph

```
A's P1-06, P1-07  ┐
B's P1-08b, P1-13 ├──▶ P1-05  (last: everything above changes fixture content)
B's P1-09         ┘
```

## 9. Acceptance Criteria

1. The three BPO personas' numbers are unchanged.
2. Maya routes to `product` and scores on product weights.
3. Product lens claim weights sum to 100.
4. The resume/competence inversion holds.
5. The two-lens ranking flip holds.
6. TRANSFER still fires for the fabricator, three times, at zero signals.
7. Suite green, 173 → 180.

## 10. Implementation Order

a → **b (gate)** → c → d → e → f → g, one commit with its ledger row.
