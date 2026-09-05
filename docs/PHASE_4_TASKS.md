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

---

# Phase 4 acceptance report

Produced by the integration review, 2026-09-05. Every number below was measured
in this repository, not estimated.

**Baseline correction first.** Phase 4 started from **`761959e` (344 tests)**,
not from `bcc7375` (332). A parallel session committed *"P4A: two validator
changes"* to `api/engine/question.py`, `tests/test_questions.py` and
`tests/test_study.py` at 15:13 while this work was in flight, and Phase 4 is
stacked on top of it. `git diff --name-only 761959e HEAD` was audited: no Phase
4 commit touches a Phase 3 study file, `tests/test_questions.py` or
`tests/test_study.py`. The only Phase 4 edit to `api/engine/question.py` is the
twelve-line `QUESTION_POLICY_VERSION` constant. **CLAUDE.md's "332 tests" was
already stale before Phase 4 began.**

## A. The chain, verified end to end

Walked in one process against a fresh tenant, with the numbers printed at every
hop:

```
Candidate    c_9d2815
Interview    s_fa367336a3   state=COMPLETE  12 questions
Claims       3
Q&A turns    12
Quotes       38 verbatim, across 6 dimensions
Claim scores [74, 52, 65]
Evidence     65  x consistency 1.0  =  competence 65 (partial)
Evaluation   ev_14c0022ce3  finalized
Provenance   tax_1@4e0f5b9b2fae rub_1 score_1 qpol_2 -> evx_7c1936571a953c36
Replay       MATCH   0 model calls, 3 claims, 12 answers, 0 differences
Decision     rejected (was shortlisted), 2 recorded
History      [created, finalized, decision, decision]
```

| # | Question | Answer |
|---|---|---|
| 1 | Can every recruiter-facing number be traced to persisted evidence? | **Yes.** competence ← weighted evidence × consistency multiplier ← claim scores ← dimension scores ← `responses.signals_json` ← verbatim quotes in `responses.raw_text`. Replay walks that chain from the bottom with no model call and reproduces the headline exactly. |
| 2 | Is a finalized evaluation distinguishable from the live interview? | **Yes.** `status`, `finalized_at` and immutability. The evaluation does not echo `sessions.state`, and a test asserts it does not — that echo is the `profiles.status` duplication D6 exists to end. |
| 3 | Can we say which versions produced it? | **Yes.** Eleven typed provenance fields plus two structured dicts, and `provenance.drift()` names the component that moved rather than just reporting a different hash. |
| 4 | Can the deterministic tail be replayed without an LLM? | **Yes.** `0` model calls, asserted three ways: the response's own `llm_calls`, the `/api/dev/llm` counter before and after, and a run with `complete_json`, `_raw_completion` and `_get_client` all monkeypatched to raise. |
| 5 | Is the original result preserved? | **Yes.** Every column of the evaluation row and every `claim_scores` row compared before and after three replays and three decisions: byte-identical. |
| 6 | Can tenant A reach tenant B? | **No**, on every surface tested — graph, ranked list, session, dev start, dev answer, dev replay, roles, outcomes, outcome history, evaluations, evaluation history and the validation report. Cross-tenant 404s are byte-identical to not-found 404s. |
| 7 | Can decisions be reconstructed historically? | **Yes.** All six audit questions from one call, ordered deterministically down to the row id. |
| 8 | Hidden mutable dependencies? | **None in the scoring path.** `signals.py`, `scoring.py` and `consistency.py` contain zero references to `settings`, `datetime.now`, `utcnow`, `random`, `time` or `os.environ`. Two were found in the wider path and both are closed — see §G. |
| 9 | Accidental model calls in replay? | **None.** `replay.py` has no module-scope import of `api.llm`, `openai` or `engine.evidence`; the wrapper is imported inside one function purely to read its counter, and replay raises if the counter moved. |
| 10 | Unnecessary abstractions? | Four new modules for five deliverables, each named or implied by the approved plan. Reviewed and kept — see §G. |

## B. Test counts

| | Baseline `761959e` | Now | Δ |
|---|---|---|---|
| **Total** | **344** | **457** | **+113** |

| File | Tests | |
|---|---|---|
| `test_tenancy.py` | 34 | new — D9 |
| `test_provenance.py` | 26 | new — D7 |
| `test_evaluation.py` | 23 | new — D6 + persisted D7 |
| `test_replay.py` | 16 | new — D8 |
| `test_audit.py` | 14 | new — D10 |
| `test_questions.py` | 123 | unchanged |
| `test_pipeline.py` | 79 | unchanged |
| `test_scoring.py` | 30 | unchanged |
| `test_taxonomy.py` | 28 | unchanged |
| `test_study.py` | 27 | unchanged |
| `test_policy.py` | 25 | unchanged |
| `test_transfer.py` | 17 | unchanged |
| `test_consistency.py` | 15 | unchanged |

**457 passed in ~12s**, still SQLite + fixture mode, still no Docker and no
network. Zero pre-existing tests were modified, skipped or deleted.

Code: **+2,804 / −92** across 22 files in `api/`, plus 2,275 lines of tests.
More test than implementation, which for a phase whose deliverable is
*trustworthiness* is the right ratio.

## C. Schema and migration

**16 tables, up from 13.** New: `tenants`, `api_keys`, `evaluations` (35
columns, 8 indexes). **15 tables carry `tenant_id`** — every domain table plus
`api_keys`. Columns added to existing tables: `profiles.latest_evaluation_id`,
`candidate_outcomes.evaluation_id`, `candidate_outcomes.previous_decision`.

| Scenario | Result |
|---|---|
| **Empty database** | `verify_schema()` → `[]`, `create_all()` builds all 16 tables, `t_dev` is created. Verified on a fresh SQLite file. |
| **Existing pre-Phase-4 database** | `verify_schema()` reports all six missing columns and `init_models()` raises `SchemaOutOfDate` naming each one and the remedy. Verified against a database seeded by the `bcc7375` build. |
| **The remedy** | `seed.py --reset` against that same legacy file rebuilds and re-seeds correctly. Verified. |
| **Fixture stability** | `seed.py --reset && dump_fixture.py` reproduces `fixtures/sample_graph.json` byte-identically after normalising random ids and timestamps. Seed scores unchanged at **56 / 46 / 14 / 61** and all three role rankings unchanged. |

There is no Alembic, by design (`CLAUDE.md` rule 7). Phase 4 does not add one;
it adds the error message that was missing when the rule bites.

## D. API backward compatibility

Machine-diffed, old spec against new:

- **Paths removed: 0.** Six added.
- **Operations removed: 0. New required parameters: 0. Response codes removed: 0.**
- **Schemas removed: 0.** Twelve added.
- **Fields removed: 0. Fields retyped: 0. New required fields: 0.**
- Two existing models grew optional defaulted fields: `HealthOut` +6 version
  fields, `OutcomeOut` +`evaluation_id`.

`X-API-Key` is optional while `REQUIRE_API_KEY=false`, so an existing client
keeps working with no change at all. A Next.js client generated from the old
`openapi.json` still validates against the new server.

## E. Security and data isolation findings

**Enforced**

1. One enforcement point. `scoped()` and `get_owned()` are the only two places
   the tenant predicate is written; an AST scan proves no `select()` on an
   owned model in `api/` escapes them.
2. Fail closed. `TenantScope.require()` raises rather than returning None, so a
   missing context can never become an unfiltered query.
3. One trusted path, asserted by AST to be exactly one, in the WhatsApp
   webhook, where a business number genuinely serves every tenant.
4. Aggregate-root discipline. The orchestrator's inner queries are not
   re-filtered; instead every router-reachable entry point takes a resolved row
   or a `TenantScope`, pinned by
   `test_the_orchestrator_is_entered_with_resolved_rows_not_ids`.
5. No route drift. Every route is walked and asserted to declare
   `Depends(current_tenant)`, against an explicit allowlist of the nine that
   touch no tenant data.
6. No credential is stored. Only the sha256 of an API key; the raw value is
   returned once. No credential can enter a provenance record — the flag set is
   eight hard-coded names, verified structurally over the AST and by a canary
   scan of a stored row.
7. No tenant identifier leaks into any recruiter payload. Verified by scanning
   the serialised graph, evaluation, history, ranked row and replay result.
8. Existence does not leak: cross-tenant 404 bodies are byte-identical to
   not-found 404 bodies.

**Open, and deliberately so**

| # | Finding | Severity | Why it stands |
|---|---|---|---|
| S1 | Auth is one shared API key per tenant. No users, no roles, no rotation, no expiry. | Medium | D9 says do not build an authentication system the repo has no foundation for. Tenant isolation is real; **user-level authorization does not exist and is not claimed.** |
| S2 | `REQUIRE_API_KEY` defaults to `false`, so an unkeyed request is served as `t_dev`. | High **if deployed as-is** | Keeps the demo and 457 tests working. **It must be `true` before the URL is public**, and `.env.example` says so. This is a deployment gate, not a code defect. |
| S3 | Opt-in codes are matched across all tenants by the webhook. | Low | Six characters over a 28-character alphabet. A collision binds a phone to the wrong session; it discloses no stored data. Sized for a demo. |
| S4 | `tenant_id` has a column default of `t_dev`. | Low | Required because `scripts/interview_study.py` (Phase 3, frozen) writes rows directly. Nothing in `api/` relies on it, proved by driving a full interview under a second tenant and reading back every row it produced. |
| S5 | Deleting a tenant that holds data raises rather than cascading. | Informational | Deliberate. There is no offboarding path yet, and a stray DELETE must not remove a customer's evidence corpus. |
| S6 | The DPDP Act workstream (`PRODUCTION_READINESS.md` §7) is untouched. | Blocking for sale | Consent, retention, erasure and the processor DPA remain unaddressed. **This outranks everything in Phase 4 commercially** and is a legal gate, not engineering work. |

## F. Replay limitations, stated plainly

1. **Extraction is never replayed.** Claim extraction, question generation and
   the candidate's answers are historical artifacts, read and never recreated.
   Promising more would be broken by a provider's deprecation schedule.
2. **`resume_score` is excluded from the comparison.** It is keyword overlap
   against `settings.default_job_description` whenever a resume carries no JD,
   which makes it a function of live configuration. It is recorded on the
   evaluation and not diffed; comparing it would report environment drift as
   evaluation drift.
3. **A taxonomy change makes replay mismatch, correctly.** `score_claim` reads
   the family vocabulary, so a retuned taxonomy changes the replayed number.
   That is the intended signal, and `provenance_drift` names it as the cause.
4. **`model_returned` is a per-process observation.** In fixture mode it is
   null. It is recorded but excluded from the fingerprint.
5. **Replay needs the recorded `VOICE_WEIGHT`.** An evaluation without one is
   refused rather than replayed against today's setting.
6. **Provenance is stamped at finalization.** A configuration change *during*
   an interview is attributed to the final stamp. Not currently detectable.
7. **Replay does not verify quotes against answers.** `enforce_verbatim()` ran
   at extraction time and its result is what is stored; replay trusts the
   stored signals as its input, by definition.

## G. Architecture debt found

**Fixed during the review** (both were Phase 4's own defects, smallest scope):

- **`taxonomy_hash()` could describe bytes the process never parsed.** `_raw()`
  and the hash were two independently cached file reads. A provenance record
  that hashes content the running code did not load is the one thing provenance
  must never do. Now one `_load()` returns both.
- **`_qa_rows` ordered on `order_index` alone**, and `session_contradictions`
  on `created_at` alone. Unique in practice; "in practice" is not determinism.
  Both now carry an `id` tiebreaker.

**Recorded, not fixed**

- **`tests/test_pipeline.py:845` uses `pytest.skip` without importing pytest**
  in that scope. Pre-existing (present at `bcc7375`), and it only fires on the
  non-SQLite branch — i.e. the first time the suite runs against Postgres it
  becomes a `NameError` instead of a skip. Not a Phase 4 defect, so it was left
  alone; it is a one-line fix for whoever owns that file.
- **`profiles` is still a mutable score cache.** The plan's "Profile becomes a
  pure pointer" is not done: `rank_candidates` reads its cached scores, and
  changing that is a scoring rewrite this phase forbids. It gained the pointer
  column, so the follow-up is a read-path change and nothing else.
- **`scoring.merge_dimension_scores` is dead.** Documented as deprecated since
  Phase 1 and called from nowhere. Pre-existing.
- **Four new modules, reviewed for necessity.** `tenancy.py` is D9's stated
  enforcement layer; `replay.py` is named in the approved plan; `evaluation.py`
  and `provenance.py` are two deliverables the plan states as separate
  artifacts. Folding provenance and evaluation into `graph.py` would put the
  write path for an immutable record inside the module that recomputes mutable
  ones. `replay._Recomputed` and the `EvaluationOut`/`EvaluationSummary` split
  were both examined as candidates for removal and kept — one is a local
  accumulator, the other is the ordinary list/detail distinction.
- **`replay.required_state()` is read only by tests and by this document.** It
  is the documented contract behind a 409, so it stays; if it ever stops being
  cited, delete it.
- **A parallel session is committing to `main`.** `761959e` landed mid-phase.
  The two-developer ownership model held — no file was edited by both — but the
  hourly-push discipline in `CLAUDE.md` assumes humans coordinating, and two
  agents do not. Worth a rule before the next parallel phase.

## H. What Phase 4 did NOT do

Unchanged and deliberately so: the six dimensions, the rubrics, the gates, the
weights, the consistency arithmetic, the question policy's behaviour, the
TRANSFER probe, the repair turn, `enforce_verbatim()`, and every Phase 3
artifact. No threshold was tuned, no corpus entry was added (C6), and
`DUPLICATE_JACCARD` is still 0.37 (C7).

`TRANSFER_PROBE=false` still reproduces the pre-Phase-1 interview, and the four
seeded personas still score 56 / 46 / 14 / 61.

## I. Commit-attribution note — read before `git blame`

Two agent sessions committed to `main` concurrently on 2026-09-05, and the
history does not read the way it happened.

- `761959e` and `2c68669` are the parallel **P4A** stream (validator changes
  and an out-of-distribution study run).
- The Phase 4 deliverables are `6fe2177` (D9), `a627d08` (D7), `a37960b` (D6),
  `873ea60` (D8), `ff9979c` (D10).
- **The integration review's own changes are inside `2c68669`, not in a commit
  of their own.** The other session ran `git commit` against a shared index
  while this session's review changes were staged, so its message covers them:
  the `taxonomy.py` `_load()` fix, the `orchestrator.py` aggregate-root note,
  the `question.py` `qpol_2` correction, the `tests/test_tenancy.py` additions,
  §A–§H of this document, and the CLAUDE.md and README.md updates.

History was **not** rewritten to separate them. Rebasing under a peer that is
still committing risks destroying their work, and a wrong commit message is a
smaller problem than a lost one. Everything was verified intact afterwards:
457 tests green, all four seeded evaluations replay MATCH with zero model
calls.

**The operational lesson outranks the tidying.** `CLAUDE.md`'s hourly-push
discipline assumes humans who notice each other. Two agents sharing one working
tree and one index do not. Before the next parallel phase, either give each
session its own worktree or serialise the commits.
