# Phase 1 Execution Plan — Prove the Signal

**Duration:** ~6 weeks · **Team:** 2 engineers (A: conversation/channel/infra ·
B: evidence/scoring/dashboard-facing) · **Baseline at start: 103/103 tests.**

Architecture is frozen per `ARCHITECTURE_LOCK_v1.md`. Nothing here proposes new
architecture.

---

## Objective

**After Phase 1, ProofScreen can demonstrate — with numbers, not a narrative —
that evidence-based verification produces a stronger hiring signal than resume
screening.**

That sentence contains a capability the product does not currently have.
Today it can *show divergence* — `resume_score` 59 and `competence_score` 14 for
the same candidate — but it cannot show **which one was right**. Divergence is a
demo; correlation against real recruiter decisions is proof.

Phase 1 delivers three things in service of that:

1. The verification mechanism that resume screening cannot replicate (transfer probing).
2. Correct routing, so a candidate is measured against the right evidence model.
3. **Outcome capture and a validation report**, so the core claim becomes measurable.

## Starting line — already true, do not rebuild

| Capability | Status |
|---|---|
| Re-rank under two role lenses without re-interviewing | ✅ shipped |
| Dimension weights affect ranking | ✅ fixed at lock, `test_role_dimension_weights_actually_change_the_score` |
| Every score explainable without a model call | ✅ `basis` + verbatim quotes per dimension |
| Prompts cohort-neutral on the primary LLM path | ✅ shipped |
| `/api/dev/simulate` cohort-agnostic | ✅ shipped |
| Deterministic scoring, no LLM in `signals`/`scoring`/`consistency` | ✅ structurally tested |

---

## Deliverables

### D1 — Transfer probe *(the differentiator)*

| Artifact | Detail |
|---|---|
| `ProbeLevel.TRANSFER` | One enum value in `api/schemas.py` — frozen file, needs both owners |
| `PROBE_BRIEFS[TRANSFER]`, `FALLBACK_QUESTIONS[TRANSFER]` | `question.py`. Fallback is a `string.Template` filled from the candidate's own claims — no prompt-file change needed |
| `select_transfer(claim, evidence, other_claims) -> TransferSpec` | New pure function in `engine/planner.py`. **No `job_family` parameter** — family branching is unrepresentable, not merely discouraged. Operators T1 (their method → their *other* claim's problem) and T3 (invert the outcome) |
| Stall exemption | `ClaimState.exhausted` becomes `saturated or (stalled and transfer_used) or not levels_left`. A stalled claim earns exactly one transfer probe before being dropped |
| `TRANSFER_PROBE=true\|false` | Env flag, matching `ADAPTIVE_PROBING`. On-stage off switch requiring no revert |
| Tests | Family-invariance (identical evidence under two families selects a byte-identical operator); stalled claim receives one transfer probe; saturated claim receives none; never an opening probe |

### D2 — Deterministic family routing

| Artifact | Detail |
|---|---|
| `detect_family(text) -> FamilyMatch` | Returns `(family, confidence, matched_terms)`, not a bare string. IDF-style term weighting computed at load time from the taxonomy itself — no new data. Confidence is **margin** `(top1 − top2) / top1`, not hit count. Normalised by family vocabulary size |
| Requisition precedence | `job_family` supplied by the caller always wins. The model may no longer override the detected family (`extract.py:196` deviation, closed) |
| Low-confidence surfacing | Below margin threshold ⇒ `general`, **flagged in the graph response** rather than silently substituted |
| `GET /api/dev/detect?text=…` | Returns the full match explanation: terms hit, per-family scores, margin. Explainability for routing, no model call |
| Tests | Known resumes route correctly per cohort; an ambiguous resume returns low confidence rather than a confident wrong answer; explanation is reproducible |

### D3 — Outcome capture *(the missing half of the objective)*

| Artifact | Detail |
|---|---|
| `candidate_outcomes` table | `id · candidate_id · evaluation_role_id · decision · stage · decided_by · note · decided_at`. Append-only. `decision ∈ {shortlisted, rejected, interviewed, offered, hired}` |
| `POST /api/recruiter/candidates/{id}/outcome` | Recruiter records a decision |
| `GET /api/recruiter/candidates/{id}/outcomes` | History for one candidate |
| `OutcomeIn` / `OutcomeOut` | Additive schema models |

**This is the deliverable that makes the objective falsifiable.** Without a
recorded human decision to correlate against, "stronger hiring signal" is an
assertion.

### D4 — Validation report *(the proof)*

| Artifact | Detail |
|---|---|
| `scripts/validation_report.py` | Deterministic, no model call. Computes, per cohort and overall: rank correlation of `resume_score` vs outcome; the same for `competence_score`; **precision@5** for each; count of rank inversions where competence was right and resume was wrong |
| `GET /api/recruiter/validation` | Same numbers, served |
| Minimum-n guard | Withhold, never estimate, below **n = 30** decided candidates in a cohort. Report `"insufficient data"` explicitly |

**The headline number Phase 1 exists to produce:** *of the candidates a
recruiter shortlisted, competence score ranked them higher than resume score
did, X% of the time.*

### D5 — Ranked-list explainability

| Artifact | Detail |
|---|---|
| `CandidateSummary.why_ranked` | One generated sentence per candidate, from stored rows, no model call — *"3 complete causal chains and 6 quantities across 4 claims, no contradictions"* vs *"no quantity in any answer, 1 major contradiction, 2 claims stalled"* |

The drill-down already answers *why*; the ranked list is the first screen a
recruiter opens and currently answers only *that*.

---

## Dependency Graph

```
D1a  ProbeLevel.TRANSFER  (frozen file, both owners)  ── THE ONLY EXTERNAL GATE
      │
      ├──▶ D1b  brief + offline fallback
      │        └──▶ D1c  select_transfer() + stall exemption + flag
      │                    └──▶ D1d  regenerate fixture, verify demo moments
      │
D2  family routing        (independent — no dependency on D1)
      │
D3  outcome capture       (independent of both)
      └──▶ D4  validation report   (needs D3 + real decisions)
                │
D5  why_ranked  (independent; feeds recruiter comprehension, which feeds D3 quality)
```

`D1b` before `D1c` is a hard dependency, not sequencing preference:
`FALLBACK_QUESTIONS[probe_level]` and `PROBE_BRIEFS[probe_level]` are bare dict
lookups, so activating TRANSFER first raises `KeyError` in fixture mode — the
mode the demo falls back to.

## Implementation Order

| Week | A | B |
|---|---|---|
| 1 | **D1a** (together, one commit) → D1b | D3 table + endpoints |
| 2 | D1c: `select_transfer()`, stall exemption, flag | D5 `why_ranked` |
| 3 | D1d: regenerate fixture, verify both demo moments | D2 detector rewrite (IDF + margin) |
| 4 | D2 wiring: requisition precedence, close the `extract.py` deviation | D2 `/api/dev/detect` + routing tests |
| 5 | Live-run hardening: real candidates through WhatsApp | D4 validation report + minimum-n guard |
| 6 | Buffer · acceptance runs | Buffer · first validation read-out |

## Acceptance Criteria

Each is a test or a reproducible command.

1. **A stalled claim receives exactly one transfer probe before being dropped**; a saturated claim receives none; TRANSFER is never an opening probe.
2. **Transfer selection is family-invariant** — identical evidence tagged `bpo_operations` and `software_engineering` selects a byte-identical operator and target. Wording may differ; the question may not.
3. **`TRANSFER_PROBE=false` restores the pre-Phase-1 interview exactly** — same questions, same order, same scores.
4. **Family detection returns an explanation** — matched terms and per-family scores — and produces it without a model call.
5. **An ambiguous resume returns low confidence, not a confident wrong answer**, and the low confidence is visible in the API response.
6. **The model can no longer override a detected or supplied family.**
7. **A recruiter decision can be recorded and retrieved** against a candidate and a role lens.
8. **The validation report runs on stored data with no model call** and either reports correlations or states `"insufficient data (n < 30)"`.
9. **The ranked list explains itself** — every candidate carries a non-empty `why_ranked` derived from stored rows.
10. **Suite is green and larger:** ≥ 118 tests passing, including every criterion above.

## Risks

| Risk | Mitigation |
|---|---|
| **D3/D4 produce no data** — recruiters don't record outcomes, so the objective stays unproven | Recording must be one click in the recruiter flow, not a separate task. If real recruiters are unavailable in Phase 1, run a **blind panel**: three reviewers rank candidates from resumes alone, then from evidence graphs, and correlate. Slower, still falsifiable |
| **The validation result is negative** — competence score does *not* out-predict resume score | This is a *success* of the method and must be reported as such. Pre-commit to publishing the number before seeing it, or the report is worthless |
| Transfer answers extract poorly at first (new answer shape, no quantities) | Rubrics already score over the *union* of a claim's signals, so a transfer answer adds and never subtracts. Watch for anyone "fixing" transfer answers for missing numbers — that is a bug, not a fix |
| Detector rewrite changes existing routing and silently shifts scores | Golden-file test: current resumes must route identically unless deliberately changed; any diff is reviewed, not accepted |
| Frozen-file gate blocks week 1 | D2, D3, D5 are all independent of it — the week is not idle if D1a slips |
| Small n makes correlations meaningless | Minimum-n guard is a deliverable, not a caveat |

## Deferred Work

Explicitly out of Phase 1:

- `Evaluation` as an entity, provenance stamps, replay → **Phase 2**
- `tenant_id`, auth, multi-tenant isolation → **Phase 2**
- New cohorts (`product_management`, `finance_accounting`) — config authoring, no code, add when a customer needs one
- Person/Candidacy split, Job/RoleProfile split, claim-scoped consistency
- `evidence_nodes` / signal rows; renaming `evidence` → `dimension_readings`
- Dimension-set redesign
- Orchestrator/planner/ranking extraction, `api/contracts/`, observability subsystem
- Embeddings, vector search — permanently out of runtime
