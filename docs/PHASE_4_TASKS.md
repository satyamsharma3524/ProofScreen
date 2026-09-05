# Phase 4 Tasks — Evaluation Integrity & Production Readiness

Task-level spec and execution log for **D6–D10**, whose phase-level plan is
[PHASE_2_EXECUTION_PLAN.md](PHASE_2_EXECUTION_PLAN.md) §"Phase 4 Execution Plan
— Make the Signal Durable and Sellable". Per `EXECUTION_STANDARD.md` C1 and C3
this file does **not** restate that plan: deliverable definitions, dependency
graph, risks and deferred work live there and are cited, not copied.

**Entry condition, stated honestly.** The frozen plan gates Phase 4 on *"the
validation report has produced a number"*. M4a still reads `insufficient data
(n < 30)` at n = 0. The gate is **not met**; Phase 4 was directed anyway. That
is a recorded deviation, not an oversight — see §0.

---

## 0. State · Why · Impact · Options · Recommendation

Applying `EXECUTION_STANDARD.md` §9 to the two conflicts this phase opens.

### 0.1 The entry condition is unmet

**State.** D6–D10 require M4a to have produced a number. It has not; n = 0
recruiter outcomes exist outside the four seeded personas.

**Why it matters.** The plan's own re-designation note says *"nothing here makes
the score better"*. Phase 4 makes a score defensible; it cannot make an
undefended score correct.

**Impact.** None of the work is wasted — every artifact is inert with respect to
scoring — but the phase spends engineering time on durability before the signal
is proven valuable. It also front-loads the one item whose cost genuinely grows
with data (`tenant_id`), which the plan itself flags as *"do before the first
customer's data lands"*.

**Options.**
1. Refuse until M4a has a number. Correct by the letter; leaves the tenant
   retrofit to be paid for later at migration cost.
2. Do D9 only (the cost-curve item) and defer D6–D8/D10.
3. Do all of D6–D10 as directed, recording the deviation.

**Recommendation — option 3, taken.** The direction is explicit and repeated,
and D9's cost argument holds regardless of M4a. Recorded here so the ledger is
honest rather than silently re-written.

### 0.2 `api/schemas.py` is frozen and Phase 4 must add to it

**State.** Rule 2 of `CLAUDE.md`: *"Adding an optional field is a conversation;
changing or removing anything is not a solo decision."* The frozen Phase 4 plan
lists `EvaluationOut` as an *"additive schema model"*, so the plan already
anticipates edits.

**Why.** An evaluation with no response model cannot be returned.

**Impact.** Two owners share the file; a non-additive edit breaks the Next.js
client contract.

**Options.** (1) Return plain dicts, as `GET /api/dev/detect` does. (2) Add
models additively. (3) A new `api/contracts/` package — explicitly deferred by
the plan.

**Recommendation — option 2, constrained.** Every Phase 4 edit to `schemas.py`
is **additive only**: new models, plus optional fields with defaults on
`OutcomeOut` and `HealthOut`. No existing field is changed, retyped or removed,
so every existing client keeps working. The complete list is §6 below, so the
other owner reviews one table rather than a diff.

### 0.3 Three new engine modules

**State.** `EXECUTION_STANDARD.md` §1 forbids new modules without approval.
Phase 4 adds `api/tenancy.py`, `api/engine/provenance.py`,
`api/engine/evaluation.py`, `api/engine/replay.py`.

**Why.** `engine/replay.py` is named in the approved plan. D9 names a
*"session-scoped filter applied in `session_repo`/`graph`/`ranking` query
paths"* — `api/tenancy.py` is that. Provenance and Evaluation are two
deliverables the plan states as separate artifacts.

**Impact.** Four files. The alternative — folding provenance and evaluation into
`graph.py` — would put the write path for an immutable record inside the module
that recomputes mutable ones, which is the confusion D6 exists to end.

**Recommendation.** Take the four, and no fifth. `select_transfer()` staying in
`orchestrator.py` remains the precedent for *not* extracting a planner.

---

## 1. What already exists — the D6 "current gap" audit

Answering the brief's question C directly, from the code rather than from the
docs.

| Concept | Persisted today | Where | Gap |
|---|---|---|---|
| Candidate identity | `candidates` | `models.py` | No tenant |
| Interview identity | `sessions` (`s_` id, `state`, `started_at`, `completed_at`) | `models.py` | Mutable; no immutable result record |
| Claims | `claims`, typed against the taxonomy | `models.py` | — |
| Questions | `questions` + `source · attempts · violations_json · is_repair` | P2-03 | — |
| Responses | `responses`, deduped on `provider_message_id` | **the seam** | — |
| Signals | `responses.signals_json`, verbatim-enforced | `evidence.py` | — |
| Dimension readings | `evidence` (one row per answer × dimension) | `models.py` | — |
| Claim score | `claim_scores` | `models.py` | **Updated in place** — history lost |
| Candidate score | `profiles` | `models.py` | **Updated in place** — history lost |
| Ranking | computed on demand | `graph.rank_candidates` | Never stored; correct — it is a function of a lens |
| Recruiter outcome | `candidate_outcomes`, append-only | P1-09 | Not linked to any evaluation; no tenant |

**Already reconstructible deterministically, with no model call:** every
dimension score, every claim score, the weighted evidence score, the consistency
multiplier, the competence score, the badge, `role_coverage`, the dimension
profile and `why_ranked`. This is why D8 is scoped at replay-from-signals and
not replay-from-model.

**Where history is lost today:** (a) `claim_scores` and `profiles` are
overwritten on every answer, so no prior score survives; (b) nothing records
*which version of anything* produced a number; (c) a decision cannot be tied to
the assessment it was made against.

---

## 2. D9 — Tenant isolation *(first: every later table inherits the column)*

**Objective.** A tenant boundary enforced at the query layer, not per endpoint.

**Current gap.** No tenant concept and no authentication of any kind.

**Data model.** `tenants` (`t_` id, slug unique). `api_keys` (`ak_` id,
`key_hash` = sha256 hex — the raw key is returned once and never stored).
`tenant_id` on all 13 domain tables plus `evaluations`, non-null, indexed, FK to
`tenants` with no `ondelete` so deleting a tenant that still holds data fails
rather than cascading.

**The development tenant.** Fixed id `t_dev`, slug `dev`, created by
`init_models()` *and* `drop_all()`. `tenant_id` carries a Python-side default of
`t_dev` for one measured reason: `scripts/interview_study.py` constructs
`Candidate` and `Resume` directly and **Phase 3 is under review and must not be
edited**. The default is a named constant, not a nullable column, and
`test_a_tenant_scoped_pipeline_writes_no_development_tenant_rows` proves no
production path relies on it.

**Enforcement contract.** `api/tenancy.py`:
`scoped(stmt, Model, scope)` · `get_owned(db, Model, id, scope)` ·
`TenantScope` · `TenantContextMissing`. A scope with no `tenant_id` raises
rather than returning unfiltered rows — **fail closed**.
`TenantScope.system(reason=...)` is the one explicit trusted path, used by the
WhatsApp webhook (one business number serves every tenant, so an inbound message
carries no tenant until the session resolves it) and by `seed.py`.

**API.** `Depends(current_tenant)` on every recruiter route and every dev route
that touches tenant data. Resolution: `X-API-Key` → tenant; absent →
development tenant when `REQUIRE_API_KEY=false` (the default, so the demo and
the suite are unchanged); absent → **401** when `REQUIRE_API_KEY=true`.

**Invariants.** No recruiter or dev handler filters by `tenant_id` itself —
every one goes through `tenancy`. A cross-tenant id returns **404**, never 403,
so existence does not leak.

**Migration.** Schema change → `docker compose down -v` and re-seed. `db.py`
gains `verify_schema()`, which fails at startup with the remedy printed rather
than an opaque `OperationalError` on the first query.

**Ownership.** Shared: `models.py`/`ids.py` (A), `graph.py`/`recruiter.py` (B),
`orchestrator.py` (A), `tenancy.py` new (Shared, announced).

**Acceptance.** Tenant A cannot read or write tenant B's candidates,
evaluations, graphs, outcomes, rankings, roles or validation report; missing
context under `REQUIRE_API_KEY=true` is 401; same-tenant behaviour is byte
identical to today.

## 3. D7 — Provenance and versioning

**Objective.** Explain which versions produced a number.

**Current gap.** Nothing is versioned. The taxonomy file has no version key;
prompts have no hashes; rubric and scoring carry no constants.

**Data model.** Typed columns on `evaluations`, not a blob:
`taxonomy_version · taxonomy_hash · rubric_version · scoring_version ·
question_policy_version · prompt_versions_json · code_version · app_version ·
model_requested · model_returned · llm_mode · feature_flags_json ·
evaluation_version`. `prompt_versions_json` and `feature_flags_json` are the
only structured fields, because their key sets genuinely vary.

**Fingerprint.** `evaluation_version = "evx_" + sha256(canonical json of the
material inputs)[:16]`. Material = taxonomy version+hash, prompt hashes, rubric,
scoring and question-policy versions, code version, `model_requested`,
`llm_mode`, feature flags. **Excluded:** timestamps, candidate, and
`model_returned` — the last is a per-process observation and cannot honestly
claim to be a per-evaluation identity input. It is still recorded, because
provider aliasing is exactly what you need when explaining drift.

**Secrets.** `feature_flags_json` is a hard-coded allowlist of eight behavioural
settings. No credential, key, token or connection string can reach it, and
`test_provenance_persists_no_secrets` scans the stored row for the live values
of all four.

**Code version.** `BUILD_SHA` env → else `.git/HEAD` read directly (no
subprocess) → else the literal `"unknown"`. `.git` is in `.dockerignore`, so the
container path is the env var and the documented fallback is `"unknown"`. **No
fabricated SHA.**

**Invariants.** Same material inputs → same fingerprint. Any material change →
a different one. Provenance on a finalized evaluation cannot change.

**API.** `GET /api/health` reports the active version set (additive fields).
`GET /api/dev/provenance` renders the human-readable current stamp.

**Ownership.** A: `taxonomy.py`, `llm.py`, `signals.py`, `question.py`
constants. B: `scoring.py` constant, health. `provenance.py` new (A).

## 4. D6 — The Evaluation entity

**Objective.** One completed assessment, addressable and immutable.

**Data model.** `evaluations`: `id (ev_)· tenant_id · candidate_id · session_id
(unique) · role_id (SET NULL) · role_title · job_family · status · created_at ·
finalized_at · weighted_evidence_score · competence_score · badge ·
consistency_score · contradiction_count · role_coverage · resume_score ·
claims_scored · questions_asked · dimension_profile_json · claim_weights_json ·
dimension_weights_json` + the D7 provenance columns.

`claim_weights_json` is a **configuration** snapshot, not evidence: without it,
deleting a role (`SET NULL`, correctly) would make the evaluation
unexplainable. Evidence itself is referenced through `session_id` /
`candidate_id`, never copied — there is no evidence blob and no
`evidence_nodes` table.

**Lifecycle — two states, derived from repository behaviour.**
`draft → finalized`. A `draft` row is opened by `orchestrator.create_session`
(idempotent per session) and finalized by `orchestrator.finalize`.
**No `running`:** the live state is `sessions.state` and duplicating it is the
`profiles.status` / `sessions.state` mistake the plan wants ended.
**No `failed` / `abandoned`:** `SessionState.ABANDONED` is declared in
`schemas.py` and **never assigned anywhere in the codebase** — three reads, zero
writes. An unreachable state cannot be tested and would be invented, not
observed.

**Immutability.** Two layers. `evaluation.finalize_evaluation()` refuses a
second finalization, and a SQLAlchemy `before_update` listener raises
`EvaluationFinalized` on *any* update to a row whose `finalized_at` was already
set — so ORM writes from a future callsite fail deterministically, not just
service calls.

**Distinct per assessment.** One evaluation per session; a re-interview is a new
session and therefore a new `ev_` id. `session_id` is unique, so a duplicate
`open_evaluation` returns the existing row instead of overwriting it.

**API.** `GET /api/recruiter/evaluations/{id}` ·
`GET /api/recruiter/candidates/{id}/evaluations` (newest first) ·
`profiles.latest_evaluation_id` pointer. Existing graph drill-down is untouched.

**Deferred, explicitly:** turning `profiles` into a pure pointer. `rank_candidates`
reads its cached scores, and rewriting that is a scoring rewrite this task
forbids.

## 5. D8 — Deterministic replay · D10 — Decision audit

**D8 objective.** Recompute the deterministic tail from stored signals and diff
it against the finalized result.

**Minimum persisted state:** `responses.signals_json` per answered question, the
question's `probe_level` and `order_index`, `contradictions`, the claim rows,
and the evaluation's own `claim_weights_json` / `voice_weight`. Missing any of
it → `ReplayUnavailable`, never a number.

**Chain replayed:** stored signals → `signals.score_claim` →
`scoring.claim_score` → `scoring.weighted_evidence_score` →
`consistency.multiplier` → `scoring.competence_score` → `badge_for`. The same
functions the live path calls; replay owns no formula of its own.

**Determinism fixes made (smallest possible):** `_qa_rows` gains `Question.id`
as an order tiebreaker; `claim_score` is called with the **recorded**
`voice_weight` rather than the live setting. Both are noted in §7.

**Result.** `MATCH | MISMATCH` with a structured `differences` list and a
`provenance_drift` list. Read-only: replay opens no write, and
`test_replay_does_not_mutate_the_evaluation` compares the row before and after.

**D10 objective.** An auditable decision history per evaluation.

**Deliberately no new table.** `candidate_outcomes` is already append-only and
already correct. It gains `tenant_id`, `evaluation_id` and `previous_decision`.
Lifecycle is `evaluations.created_at` / `finalized_at` / `status`. The history
endpoint assembles a deterministically ordered timeline from those two sources.
A dedicated `evaluation_events` table was considered and rejected: its only
content would be `created` and `finalized` rows duplicating two columns that
already exist — the duplication `PRODUCTION_READINESS.md` §5 warns against.

**Idempotence.** A repeated *identical* decision (same decision, stage, note,
decided_by, role and evaluation as the immediately preceding row) returns the
existing row rather than appending a meaningless duplicate. A *different*
decision always appends; the ladder M4a correlates over is untouched.

**API.** `GET /api/recruiter/evaluations/{id}/history`. Both existing outcome
endpoints keep their paths, payloads and status codes.

---

## 6. Every `api/schemas.py` edit in Phase 4 — additive only

| Model | Change |
|---|---|
| `EvaluationStatus` | new enum (`draft`, `finalized`) |
| `ProvenanceOut` | new |
| `EvaluationOut`, `EvaluationSummary` | new |
| `ReplayStatus`, `ReplayDifference`, `ReplayResultOut` | new |
| `DecisionHistoryEntry`, `EvaluationHistoryOut` | new |
| `TenantOut`, `TenantCreateIn`, `ApiKeyOut` | new (dev provisioning) |
| `OutcomeOut` | **+`evaluation_id: str \| None = None`** — optional, defaulted |
| `HealthOut` | **+5 optional version fields, all defaulted** |

Nothing is renamed, retyped, reordered or removed.

## 7. Known limitations, recorded at delivery

1. **`create_all()` cannot add a column.** An existing development database
   needs `docker compose down -v`. `verify_schema()` now says so at startup
   instead of failing on the first query.
2. **`resume_score` is not replayed.** It depends on
   `settings.default_job_description` when a resume carries no JD, so it is a
   function of live configuration, not of stored evidence. It is stored on the
   evaluation as a recorded value and excluded from the replay comparison.
3. **`model_returned` is process-global**, captured from the last live
   completion. In fixture mode it is null. It is excluded from the fingerprint
   for exactly this reason.
4. **Opt-in codes are global.** Six characters over a 28-character alphabet,
   matched across every tenant by the webhook trusted path. A collision binds a
   phone to the wrong session; it discloses no stored data. Sized for a demo,
   not for a hundred tenants.
5. **`profiles` is still a mutable cache.** It gains a pointer, not immutability.
6. **Auth is a shared API key per tenant.** No users, no roles, no rotation
   endpoint, no expiry. Tenant isolation is real; user-level authorization does
   not exist and is not claimed.
