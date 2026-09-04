# P1-08b — `routing_confidence` on the graph

Ten-section artifact per `EXECUTION_STANDARD.md` §10. Owner **B**, task 6 of 7.
Depends on A's **P1-06** (`df9fbf8`, landed) and **P1-00**.

---

## 1. Objective

Show a recruiter **how close the routing call was**, on the record they are
already looking at.

Routing has the widest blast radius of any decision in the system: it selects
the claim weights, the dimension weights, the fact-key vocabulary and the
PROCESS rubric's domain-term credit. A wrong route silently collapses every
number downstream. `/api/dev/detect` (A's P1-08a) explains one route on demand;
this puts the number on the candidate record itself, where someone reviewing a
surprising score will actually see it.

## 2. Current State

| | |
|---|---|
| Suite | **168 passing** |
| `CandidateGraph.routing_confidence` | in `schemas.py` from P1-00, **always `null`** |
| `match_family(text) -> FamilyMatch` | A's published cross-stream contract, merged |
| `build_candidate_graph()` | already loads the candidate's `Resume` for `resume_score` |

**Must NOT be rebuilt:** `match_family`, the margin definition, the two-term
floor. And `FamilyMatch`'s shape must not change — it is the only interface
between the two streams.

## 3. Deliverables

| Artifact | Detail |
|---|---|
| `routing_confidence` populated | In `build_candidate_graph()`, from the already-loaded resume |
| 5 tests | `tests/test_pipeline.py` |

**Zero new queries and zero model calls.** The resume is already in hand for
`resume_score`, and `match_family` is a pure function of the text and the
taxonomy file.

## 4. Risks

| Risk | Mitigation |
|---|---|
| **Read as a probability** — "0.72 means 72% likely correct" | It is a margin: `(top1 − top2) / top1`. Documented at the call site; a confidently wrong router would report 1.00, which is the whole reason M5c exists as a separate metric |
| **The field is decorative** — every candidate reads 1.00 and nobody can act on it | Measured on the seeded pool: **0.17, 0.40, 0.72**, three distinct values. Pinned by a test that fails if the values collapse to one |
| `0.0` is ambiguous — floor fallback, or an exact tie | `job_family` disambiguates: `general` means it never cleared the floor; a real family with `0.0` means two families tied. `CandidateGraph` carries one float and `schemas.py` is frozen, so the pair of fields is the disambiguation. `/api/dev/detect` renders the full explanation |
| Drifts from what the router actually did | A test asserts parity with `match_family()` directly |

## 5. Deferred Work

- A configured margin threshold and a visible low-confidence *flag* rather than
  a bare number. The phase plan's D2 wording ("below margin threshold ⇒
  `general`, flagged in the graph response") presumes a threshold that P1-06
  did not ship; adding one is a change to A's `taxonomy.py`. Reported in P1-11
  under M5a and logged here.
- IDF against a background corpus, so terms ambiguous against ordinary English
  stop scoring as maximally distinctive. `taxonomy._idf()` documents this; not
  Phase 1.

## 6. Success Metrics

Serves **M5a/M5c** by putting the margin where a human sees it. B's contract
measure: *`routing_confidence` populated, and its distribution across the
seeded candidates — if every candidate reads 1.00, the field is decorative.*

**Measured: 0.170844 / 0.396977 / 0.718687 across the three seeded personas.**
Arjun routes to `bpo_operations` on a margin of 0.17 — a near coin-flip that is
nonetheless confidently placed, which is exactly the case this field exists to
surface.

## 7. Task Breakdown

| ID | Step | Files |
|---|---|---|
| a | Import `match_family` (read-only) | `api/engine/graph.py` |
| b | Compute from the loaded resume, populate the field | same |
| c | 5 tests | `tests/test_pipeline.py` |

Migration impact: **none.** Changes fixture content, so it lands before P1-05.

## 8. Dependency Graph

```
A's P1-06 (done) ──▶ P1-08b ──▶ (P1-05 regenerates the fixture)
```

Independent of the D3/D4 chain.

## 9. Acceptance Criteria

1. Every graph with a resume carries a non-null `routing_confidence`.
2. It equals `match_family(resume_text).confidence`.
3. A resume that clears no family's floor reads `general` with `0.0`.
4. Values are not all identical on the seeded pool.
5. No model call, no new query. Suite green, 168 → 173.

Serves phase acceptance criterion **5**.

## 10. Implementation Order

a → b → c, one commit with its ledger row.
