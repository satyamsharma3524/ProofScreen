# P1-13 — `why_ranked`

Ten-section artifact per `EXECUTION_STANDARD.md` §10. Owner **B**, task 3 of 7.
Depends on **P1-00** (landed).

---

## 1. Objective

Make the **first screen a recruiter opens** explain itself.

`GET /api/recruiter/candidates` currently answers *that* a candidate ranks
where they do, never *why*. The drill-down answers why in full — dimension
scores with `basis` strings, verbatim quotes, every Q&A turn — but a recruiter
scanning twenty rows does not open twenty drill-downs. Rule 12 says every score
is traceable without another model call; on the ranked list that traceability
exists in the database and not on the screen.

## 2. Current State

| | |
|---|---|
| Suite | **152 passing** |
| `CandidateSummary.why_ranked` | in `schemas.py` from P1-00, **always `null`** |
| `rank_candidates()` | loads candidates, profiles, claims, claim_scores, sessions — all batched, no N+1 |

`claim_scores.dimensions_json` already carries, per dimension: `score`,
`signal_count`, `basis`, `probed`. `claim_scores` also carries
`probed_dimensions` and `answers_count`. **Everything this sentence needs is
already in memory** by the time the loop runs.

**Must NOT be rebuilt:** the ranking maths, `_claim_score_under`, the lens
application. This task reads rows already loaded and formats a sentence.

## 3. Deliverables

| Artifact | Detail |
|---|---|
| `_why_ranked(...)` | Pure function: claims, claim scores, profile, lens weights → one sentence |
| Populated in `rank_candidates()` | Every row, non-null |
| 5 tests | `tests/test_pipeline.py` |

**It cites evidence, never restates the score.** B's contract requires exactly
this: *"that it cites stored evidence rather than restating the score in
words."* So `"competence 56, partial badge"` is a failure and
`"31 evidence signals across 3 claims, 6 of 6 dimensions probed"` is the
deliverable. A sentence that paraphrases the number adds a row of text and no
information.

**Zero new queries.** Derived from `dimensions_json`, which `rank_candidates`
already selects. Counting quantities and causal chains from
`responses.signals_json` instead would mean parsing ~12 JSON blobs per
candidate on the first screen a recruiter opens — for 500 candidates, 6000
parses per request. The per-dimension `signal_count` is exact and already
loaded: each rubric counts a disjoint bucket (specificity → quantities +
entities, process → steps, causal → chains, authenticity → incidents, tool →
tools, metric → definitions), so summing across the six is a true total with no
double counting.

## 4. Risks

| Risk | Mitigation |
|---|---|
| It restates the score in prose and adds nothing | Test asserts the sentence contains no score-like phrasing and does cite counts |
| **It reads identically for every candidate**, making it decoration | Test asserts two candidates with different evidence get different sentences |
| **It does not change with the lens**, so the ranked list and the lens disagree about what mattered | The sentence carries a lens clause naming the claim type this lens weights most and how that claim scored. Test asserts it changes with `role_id` |
| An N+1 on the busiest endpoint | Zero new queries, by construction. Test asserts `why_ranked` is populated for a candidate with no extra round trip |
| A candidate with no interview yields a confusing sentence | Explicit "not yet interviewed" branch, tested |

## 5. Deferred Work

- Per-dimension drill-down on the list view — that is the detail endpoint's job.
- Localisation. English only in Phase 1.
- Quantity-versus-entity split in the SPECIFICITY count, which needs
  `signals_json` and the query cost above. Logged; not worth it for one clause.

## 6. Success Metrics

Serves phase acceptance criterion **9**. B's contract measure: *how many
candidates get a non-null `why_ranked`, and that it cites stored evidence*.
Target: **100% of ranked rows non-null.**

Guardrails: zero model calls (asserted against `/api/dev/llm`); zero new
queries; no score changes.

Counter-metric: **C3** applies obliquely — a sentence tuned to sound generous
would be a regression. The sentence reports counts, and counts are not
flattering by construction.

## 7. Task Breakdown

| ID | Step | Files |
|---|---|---|
| a | `_dimension_totals()` — parse `dimensions_json` into structured counts | `api/engine/graph.py` |
| b | `_why_ranked()` — evidence clause, integrity clause, lens clause | `api/engine/graph.py` |
| c | Populate in `rank_candidates()` | `api/engine/graph.py` |
| d | 5 tests | `tests/test_pipeline.py` |

Migration impact: **none.**

## 8. Dependency Graph

```
P1-00 (done) ──▶ P1-13     independent of P1-09/P1-10/P1-11/P1-12 and P1-08b
```

Touches only `graph.py`, which is B's. Lands before P1-05 because it changes
what a regenerated fixture contains.

## 9. Acceptance Criteria

1. Every row in `GET /api/recruiter/candidates` has a non-empty `why_ranked` — 100%.
2. It cites counts, not the score.
3. Two candidates with different evidence get different sentences.
4. It changes when `role_id` changes.
5. No model call; no new query.
6. Suite green, 152 → 157.

## 10. Implementation Order

a → b → c → d, one commit with its ledger row. Tests verified to fail against
the pre-change file.
