# ARCHITECTURE LOCK v1

**Status: FROZEN.** Locked 2026-09-03. Baseline at lock: **103/103 tests passing.**

This document supersedes all prior architecture reviews as the operative
reference. Those documents remain as rationale, not as instructions:
`ARCHITECTURE_AUDIT.md`, `IMPLEMENTATION_PLAN.md`, `PLAN_REVIEW.md`,
`SHIP_PLAN.md`, `TRANSFER_DESIGN_AUDIT.md`, `PLATFORM_ARCHITECTURE_REVIEW.md`,
`PRODUCTION_READINESS.md`, `PROOFSCREEN_DOMAIN_MODEL.md`,
`FAMILY_TAXONOMY_REVIEW.md`, `EVALUATION_ARCHITECTURE_PRINCIPLES.md`.

**We are in the execution phase.**

---

## Unfreeze conditions

Architecture is reopened for exactly three reasons, and nothing else:

1. **A production bug** is found that the architecture causes.
2. **A feature cannot be implemented** within these boundaries.
3. **A customer requirement conflicts** with a frozen decision.

Anything else — a better idea, a cleaner abstraction, a scaling concern for a
cohort we do not have — is logged against v2 and not acted on.

---

## 1. Family taxonomy — FROZEN

Ten keys. Nine cohorts plus one fallback.

| Key | Status |
|---|---|
| `software_engineering` | exists |
| `customer_support` | exists |
| `sales` | exists |
| `banking_operations` | exists |
| `hr_recruitment` | exists |
| `data_analytics` | exists |
| `bpo_operations` | exists — **key retained**, see note |
| `product_management` | **to author** (config only) |
| `finance_accounting` | **to author** (config only) |
| `general` | fallback, **not a cohort** — see note |

**Two implementation notes, not reopenings:**

- **`bpo_operations` keeps its key.** The proposed name `general_operations` is
  a relabel, and renaming a family key before the demo breaks `tests/conftest.py`
  (which pins the family with BPO vocabulary and is documented as load-bearing)
  and the seeded demo data. The *label* can read "BPO / General Operations"
  today at zero cost; the key changes at a schema reset, if ever.
- **`general` is retained and is not a cohort.** It is the unknown-family
  fallback that `resolve_family()` and `detect_family()` fall back to. Removing
  it removes the fallback path.

**Growth rule:** new cohorts are added only when they require a **distinct
evidence model** (different claim types and fact keys). Everything else is a
*specialization* — vocabulary only, may overlap freely, changes no scoring
semantics. Ten cohorts is the ceiling for v1.

## 2. Deterministic boundaries — FROZEN

| Stage | Owner |
|---|---|
| Family detection | **Deterministic** |
| Taxonomy resolution | Deterministic |
| Question **selection** (claim, probe level, target dimension) | **Deterministic** — `plan_next()`, pure |
| Dimension scoring, weights, consistency | Deterministic |
| Ranking and re-ranking | Deterministic |
| Claim extraction | LLM + deterministic fallback |
| Question **wording** | LLM + deterministic fallback |
| Signal extraction | LLM + deterministic fallback |

**The line that must never move:** question *selection* is code, question
*wording* is generative. The moment claim or probe-level choice enters a prompt,
the interview stops being reproducible and explainability goes with it.

**Known deviation, logged not fixed:** `extract.py:196` allows the model to
override the detected family. This violates the boundary above. It is **not** a
demo blocker because the demo pins `job_family` explicitly, and the fix is
listed in v2 work below.

## 3. Evaluation principles — FROZEN

Full text in `EVALUATION_ARCHITECTURE_PRINCIPLES.md`. The inviolable five:

0. **The model never produces a score.** Countable signals in, arithmetic out.
1. **Quotes are verified in Python**, never requested in a prompt.
2. **Never score presentation** — accent, fluency, grammar, polish, speed.
3. **Every model call has a deterministic fallback.**
4. **Un-probed ≠ zero-earned.** Thin questioning shows as low confidence.

Plus:

5. **Every score is traceable** — Evaluation → Dimension → Evidence → Quote,
   with no second model call.
6. **The role lens applies late.** Same evidence, different weights, different
   ranking, no re-interviewing.
7. **Vocabulary is configuration, reasoning is code.** Adding a cohort requires
   a taxonomy entry and a weight definition — nothing else.

## 4. Domain model — FROZEN for v1

Current entities stand as implemented. Locked decisions:

| Entity | v1 position |
|---|---|
| `Candidate` | Remains person + candidacy in one row. Person/Candidacy split is v2 |
| `Claim` | Unit of verification. Unchanged |
| `VerificationSession` | Aggregate root for the interview. Unchanged |
| `Response` | The seam. Unchanged |
| Signal | Stays a JSON blob on `responses.signals_json`. No `evidence_nodes` table in v1 |
| `evidence` table | Holds **dimension readings**. Rename deferred to a schema reset |
| `Contradiction` | Stays session-scoped. Claim scoping is v2 |
| `Profile` | Stays a default-lens cache. `Evaluation` as an entity is v2 |
| `JobRole` | The **scoring lens**. Job/Requisition split is v2 |
| Tenant / Organization / Recruiter | Absent in v1 |

**Vocabulary is locked even though the schema is not:** *Signal* = one extracted
item · *DimensionReading* = what the `evidence` table holds · *EvidenceGraph* =
the assembled read model. Use these words in all new code and documents.

---

## Fixed at lock time

**V1 — role dimension weights were silently ignored.** `resolve_weights()`
returned them and `build_candidate_graph` bound them to `_dim_weights` and never
used them, so a recruiter could configure a lens, see it stored and returned by
the API, and observe no effect on any score.

Fixed in `engine/graph.py`:

- `resolve_weights()` now returns the role's **explicit** dimension override
  (`{}` when unset) rather than silently substituting family defaults.
- New `_claim_score_under()` re-scores a stored claim through the lens's
  dimension weights — pure arithmetic over stored dimension scores, no model
  call.
- Applied in **both** `build_candidate_graph()` and `rank_candidates()`, so the
  detail view and the ranked list can never disagree.
- With no override the stored score is returned unchanged, so the default path
  is byte-identical and the voice blend applied at scoring time is preserved.

**Regression test:** `test_role_dimension_weights_actually_change_the_score` —
two roles with **identical claim weights** and different dimension lenses must
produce different rankings, and the detail view must match the list view. This
test fails against the old code by construction.

**Demo impact: none.** Seeded roles set only `claim_weights`, so the two
headline demo moments are unchanged. Suite: 102 → **103 passing**.

---

## v2 backlog — logged, not scheduled

In the order their triggers are likely to fire:

1. Family detection: IDF weighting, margin-based confidence, visible
   low-confidence fallback; stop the model overriding the detected family
2. `tenant_id` on every table, with auth *(the only item whose cost multiplies
   with data — do it the day a second customer is real)*
3. `Evaluation` as a first-class entity — unblocks provenance, score history,
   replay and disputes in one change
4. Person / Candidacy split *(fixes the dormant WhatsApp routing ambiguity)*
5. Job / RoleProfile split
6. Claim-scoped consistency; re-point `Contradiction` at two facts
7. Prompt, rubric and taxonomy versioning stamped on evaluations
8. Dimension-set redesign *(must precede real data accumulation — it is the one
   change that requires historical re-scoring)*
9. `evidence_nodes` / signal rows; rename `evidence` → `dimension_readings`
10. Data protection, retention, adverse-impact monitoring, candidate rights

---

## Now executing

Per `EXECUTION_PLAN.md`, remaining demo work:

| Task | Blocked on |
|---|---|
| PS-001 `ProbeLevel.TRANSFER` | **Frozen-file sign-off from both owners** |
| PS-002 transfer brief + offline fallback | PS-001 |
| PS-003 activation + stall exemption + `TRANSFER_PROBE` flag | PS-002 |
| PS-004 cohort-neutral demo vehicle | done in part — `PLACEHOLDER_ANSWERS` de-BPO'd |
| PS-005 verify | PS-003 |
| PS-006 acceptance dry run | PS-005 |

**One gate remains: PS-001 needs both `schemas.py` owners for one added enum
value.** Everything else is unblocked.
