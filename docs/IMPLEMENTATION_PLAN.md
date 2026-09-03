# ProofScreen — Pre-Implementation Design (Phases 2–9)

**Status: awaiting implementation approval. No production code has been changed.**

Companion to [ARCHITECTURE_AUDIT.md](ARCHITECTURE_AUDIT.md) (Phase 1, complete).
Baseline re-verified today: **102/102 tests pass in 1.69s**.

This document is the ten required pre-coding artifacts. Four decisions in it
are **breaking** and need explicit sign-off before any code moves — they are
collected in §0 so they are not buried.

---

## §0 — Decisions that need your sign-off first

### D1. The six dimensions change identity, not just names — this breaks the frozen contract

The brief's dimension set is not the repo's dimension set. Three survive, one
is renamed, two are **deleted**, two are **new**:

| Current (`Dimension` in schemas.py) | Target | Disposition |
|---|---|---|
| `SPECIFICITY` | `specificity` | Survives. Rubric unchanged; absorbs incident markers + named tools. |
| `PROCESS` | `operational_depth` | **Rename.** Rubric survives; absorbs tool-usage and metric-definition signals. |
| `CAUSAL_REASONING` | `causal_reasoning` | Survives, untouched. |
| `METRIC_OWNERSHIP` | — | **Deleted.** "Can they define the metric" ≠ target `ownership` ("what did they personally do"). Its signals split: `how_measured` → `operational_depth`, referring quantities → `specificity`. |
| `AUTHENTICITY` | — | **Deleted.** Incident markers → `specificity` (target definition explicitly includes "situations"). |
| `TOOL_FAMILIARITY` | — | **Deleted.** Named tool → `specificity`; tool *with described usage* → `operational_depth`. |
| — | `ownership` | **New.** Needs a new signal type and a new rubric. |
| — | `scenario_transfer` | **New.** Needs a new signal type, a new rubric, **and a new probe level** (see D2). |
| — | `consistency` | **New as a dimension**, alongside the existing session-level adjustment (see D3). |

Blast radius, measured not estimated — files containing dimension identifiers:
`api/schemas.py`, `api/taxonomy.py`, `api/engine/{signals,scoring,question,orchestrator}.py`,
`data/claim_taxonomy.json` (8 families, partial dimension-weight overrides),
`fixtures/sample_graph.json` (generated), `tests/test_scoring.py` (24 tests),
`tests/test_policy.py` (12 tests), `tests/test_taxonomy.py` (8 tests), and
`tests/test_pipeline.py` (37 tests) indirectly. Roughly **36 of 102 tests touch
dimension identifiers directly.**

`Dimension` lives in `api/schemas.py`, which CLAUDE.md rule 2 declares frozen and
rule 3 gives two owners. **This change cannot be made solo.**

Options considered:

- **A — full re-map in one commit (recommended).** Rename, re-home the orphaned
  signals, add the two new rubrics, regenerate the fixture, update tests. The
  Next.js dashboard does not exist yet, so there is nothing downstream to break
  — and that is exactly why this should happen *now* rather than after Dev B
  starts. Cost rises steeply once a dashboard is built against the old names.
- **B — keep six, add two, ship eight.** Rejected: the brief specifies six, and
  eight dimensions dilutes every weight and weakens "six dimensions" as a pitch
  artifact.
- **C — alias layer, old names externally / new internally.** Rejected: two
  live vocabularies is permanently worse than one migration, and there is no
  existing consumer to be compatible *with*.

**Recommendation: A. Needs both `schemas.py` owners to sign off before Phase 2 starts.**

### D2. `scenario_transfer` has no probe level that elicits it — gap in the brief

The brief lists six dimensions including `scenario_transfer`, and separately
lists five question levels: validation, operational detail, incident/example,
decision/tradeoff, outcome. **None of those five asks a transfer question.** All
five ask about work the candidate has already described. A dimension that no
probe elicits scores 0 for every candidate, and under the repo's existing rule
("un-probed dimensions contribute 0") that would silently drag every score down
by one-sixth.

Options:
- **A — add a sixth probe level, `TRANSFER` (recommended).** "Here is a
  situation you haven't mentioned — how would you handle it?" This is also the
  strongest available signal for the actual A2 problem statement: a candidate
  who did not do the work can recite a decorated resume, but cannot transfer it
  to a novel situation. It is worth arguing this is the highest-value *new*
  capability in the whole brief, not merely spec compliance.
- **B — fold transfer into the `DECISION` probe.** Cheaper, but conflates
  "what did you decide then" with "what would you do now", and the rubric can't
  tell the two apart in the answer.

Cost of A: `MAX_QUESTIONS` is 12 across up to 3 claims. Six levels × 3 claims =
18 possible probes against a 12 budget, so the adaptive policy is already the
thing deciding what gets cut — but the breadth-first phase plus a transfer probe
on the heaviest claim needs the budget re-checked. **Recommendation: A, with a
policy rule that `TRANSFER` is only spent on claims that already have evidence
worth transferring (never as an opening probe).**

### D3. Claim-scoped consistency reverses a documented, defended design decision

CLAUDE.md currently states, as a decision to defend out loud: *"Consistency is
session-level, applied once… one fabricated area lowering trust globally is the
intended behaviour of a trust product."* The brief now says the opposite: *"Do
NOT globally destroy a candidate's score because of one weak or forgotten fact.
Uncertainty should primarily propagate to related claims."*

Both are defensible. The brief wins (it is the newer product decision), but the
change must be deliberate, and it needs a rule that prevents double-counting now
that `consistency` is *also* one of the six dimensions. Proposed rule — every
contradiction is assigned to exactly one bucket, by scope:

| Contradiction scope | Where it is counted | Effect |
|---|---|---|
| Both facts sourced from responses about the **same claim** | `consistency` **dimension** of that claim only | Lowers that claim's confidence. No candidate-level penalty. |
| Facts from **different claims**, severity MINOR | Candidate-level adjustment, **scoped to the two claims involved** | Lowers both claims' confidence; other claims untouched. |
| Facts from different claims, severity **MAJOR** | Candidate-level adjustment, **global** | Preserves "serious contradictions can cause broader penalties". |

This is implementable with data that already exists: `SessionFact.claim_id` is
already populated (`models.py:248`). `ContradictionRow` does **not** carry claim
ids and will need two new columns (see §4).

**Demo impact, which must be re-verified rather than assumed:** the seeded
ranking flip depends on Rohit's contradiction dropping him from evidence 24 to
competence 14 via a global ×0.6. Under scoped rules his team-size contradiction
lands on his team-handling claim only, so his competence lands higher — likely
high teens to low twenties. He still ranks last (Priya 56, Arjun 46), so the
resume-vs-competence inversion survives, but **`python seed.py --reset` must be
run and the three numbers re-read before this is called done.**

### D4. `effort_score` blends a speaking-rate-derived number into the score

`engine/voice.py:36-45` computes `effort_score` from duration and word count,
and `scoring.claim_score()` blends it at `VOICE_WEIGHT` (10%) into every
voice-answered claim. The brief's anti-bias list explicitly forbids scoring
**speaking speed**. Duration and word count are not accent or polish — the
existing file argues this carefully and honestly — but their ratio *is* speaking
rate, `VoiceSignals.words_per_minute` already computes it, and a fast speaker
saturates both halves of `effort_score` sooner than a slow one saying the same
thing.

Options:
- **A — `VOICE_WEIGHT=0` by default; keep the measurement, stop scoring it
  (recommended).** Voice then contributes transcript, duration and completeness
  as *evidence inputs*, never as a score component. The env flag already exists,
  so this is a config default change plus removing the blend from the claim
  score path. Matches the brief's "voice analytics must focus on transcription,
  completeness, semantic content, evidence extraction, technical metadata."
- **B — keep the 10% blend and argue duration ≠ speed.** Defensible today, but
  it is the one place a judge or a candidate could point at and say "you scored
  how they spoke," and the product's whole position is that it does not.

**Recommendation: A.** It removes the last presentation-adjacent term from the
score at a cost of one config default and roughly ten lines.

---

## §1 — Current architecture vs target architecture

```
CURRENT (verified)                          TARGET (brief)

resume                                      ResumeSignal
  │ ingest/parse.py                           │ Module 1  Resume/Claim Engine
  │ engine/extract.py         (LLM #1)        ▼
  ▼                                         ClaimSet
claims (typed to taxonomy)                    │ Module 2  Verification Planner
  │                                           ▼
  │ orchestrator.plan_next()  ── policy ──▶ VerificationPlan
  │ engine/question.py        (LLM #2)        │ Module 3  Adaptive Question Engine
  ▼                                           ▼
question ──▶ WhatsApp ──▶ answer            QuestionSignal ──▶ ResponseSignal (Module 4)
  │                                           │
  │ engine/evidence.py        (LLM #3)        │ Module 5  Evidence Engine
  ▼                                           ▼
AnswerSignals (JSON blob on responses)      EvidenceSignal ──▶ evidence_nodes (rows, provenance)
  │ engine/consistency.py                     │ Module 6  Consistency Engine
  │ engine/signals.py         (rubrics)       │ Module 7  Signal/Rubric Engine
  │ engine/scoring.py         (weights)       │ Module 8  Scoring Engine
  ▼                                           ▼
ClaimScore / Profile rows                   ScoreSignal (versioned, append-only)
  │ engine/graph.py                           │ Module 9  Evidence Graph (read model)
  ▼                                           │ Module 10 Ranking
CandidateGraph / ranked list                CandidateRanking
```

**What already matches and must not be rewritten:** the LLM-never-scores
boundary (structurally tested); the planner/wording split (the repo already
separates "policy picks claim+level+target dimension" from "LLM words it" —
this is precisely the brief's "extremely important" separation, already built);
verbatim quote enforcement; heuristic fallbacks on all three LLM calls; the
channel abstraction; per-family taxonomy config; role weight profiles with live
re-ranking; the adaptive stop.

**Gap table:**

| # | Area | Current | Target | Severity |
|---|---|---|---|---|
| G1 | Dimension set | 6 (different identities) | 6 (per brief) | **Breaking** — D1 |
| G2 | Transfer probe | none | 6th probe level | **Breaking** — D2 |
| G3 | Consistency scope | global multiplier | dimension + scoped propagation | **Breaking** — D3 |
| G4 | Voice in score | 10% effort blend | evidence input only | **Breaking** — D4 |
| G5 | Evidence grain | dimension readings + JSON blob | evidence node per item, with provenance | New table |
| G6 | Versioning | none | rubric/prompt/role/formula versions persisted | New columns + config |
| G7 | Observability | `cache_stats()` only | trace id + per-stage latency + model metadata | New module + table |
| G8 | Planner module | inside 816-line orchestrator | `engine/planner.py`, typed `VerificationPlan` | Refactor (Phase 4) |
| G9 | Ranking module | inside `graph.py` | `engine/ranking.py` | Refactor |
| G10 | Coefficients | hardcoded constants | versioned config file | Move |
| G11 | Module contracts | implicit dicts at 3 boundaries | typed contracts package | New (Phase 2) |
| G12 | Job families | 8 | 3 required (BPO, Sales, IT) | **None — already a superset** |

---

## §2 — Module ownership map

Extends the README's Dev A / Dev B split rather than replacing it. New files
are assigned to whichever owner already owns the code they are extracted from —
so the split stays conflict-free with both devs pushing hourly.

| # | Module | File(s) | Owner | Status |
|---|---|---|---|---|
| 1 | Resume / Claim Engine | `ingest/parse.py`, `engine/extract.py` | A | Exists |
| 2 | Verification Planner | `engine/planner.py` **(new, from orchestrator)** | A | Extract |
| 3 | Adaptive Question Engine | `engine/question.py` | A | Exists (+ TRANSFER level) |
| 4 | Response / Voice Layer | `channels/*`, `stt.py`, `engine/voice.py` | A | Exists (+ hardening) |
| 5 | Evidence Engine | `engine/evidence.py` | B | Exists (+ 2 signal types) |
| 6 | Consistency Engine | `engine/consistency.py` | B | Exists (+ claim scoping) |
| 7 | Signal / Rubric Engine | `engine/signals.py` | B | Rubrics re-mapped (D1) |
| 8 | Scoring Engine | `engine/scoring.py` | B | Exists (+ versioned config) |
| 9 | Evidence Graph | `engine/graph.py` | B | Exists (+ evidence nodes) |
| 10 | Ranking | `engine/ranking.py` **(new, from graph)** | B | Extract |
| — | Orchestration | `engine/orchestration/*`, `engine/session_repo.py` **(new)** | A | Extract (Phase 4) |
| — | Contracts | `api/contracts/*` **(new)** | **Shared — like schemas.py** | New |
| — | Observability | `api/observability.py` **(new)** | A | New |
| — | Rubric config | `data/rubric_v1.json` **(new)** | B | New |

`api/schemas.py` remains the frozen HTTP/dashboard contract. `api/contracts/`
holds *internal* module signals and **re-exports** existing types rather than
redefining them — no duplicate `DimensionScore`, no duplicate JSON codec, per
the code-quality rules.

---

## §3 — Signal contract table

Ten typed contracts, one per module. Types that already exist are reused, not
re-declared.

| Module | Input | Output | Reuses / New | Failure behaviour |
|---|---|---|---|---|
| 1 Claim | `ResumeSignal{candidate_id, raw_text, filename?, job_description?}` | `ClaimSet{job_family, claims[ClaimOut], expected_evidence}` | `ClaimOut` exists; `ResumeSignal`/`ClaimSet` new | `extract.heuristic_claims` fallback; never raises |
| 2 Planner | `ClaimSet + RoleProfile + EvidenceState` | `VerificationPlan{claim_id, probe_level, target_dimension, gaps[], priority, reason}` | supersedes `orchestrator.Plan` | Pure function. Returns `None` = interview over. Cannot fail |
| 3 Question | `VerificationPlan + ConversationState + EvidenceState` | `QuestionSignal{text, probe_level, target_dimension, prompt_version}` | `GeneratedQuestion` exists | `question.FALLBACK_QUESTIONS`; never raises |
| 4 Response | inbound channel event | `ResponseSignal{response_id, candidate_id, session_id, question_id, modality, text, transcript?, duration_s?, source, provider_message_id, received_at, trace_id}` | new; wraps existing `Response` fields | STT failure ⇒ `modality=voice, transcript=None` ⇒ treated as non-answer, never a crash |
| 5 Evidence | `QuestionSignal + ResponseSignal + Claim` | `EvidenceSignal{nodes[EvidenceNode], facts[], summary, dropped_quotes, model, prompt_version}` | `AnswerSignals` exists; `EvidenceNode` **redefined** (§4) | `evidence.heuristic_signals` fallback; non-verbatim quotes dropped in Python |
| 6 Consistency | `ExistingFactSet + NewEvidence` | `ConsistencySignal{contradictions[], per_claim_penalty{}, global_multiplier, facts_tracked}` | `Contradiction` exists; per-claim map new (D3) | Pure. Deterministic |
| 7 Rubric | `EvidenceSignal + ClaimType + RoleProfile` | `DimensionSignals = dict[Dimension, DimensionScore]` | `DimensionScore` exists; **alias named once** (audit Phase 2 #2) | Pure. No LLM (structurally tested) |
| 8 Scoring | `DimensionSignals + ConsistencySignal + ClaimImportance + RoleWeights` | `ScoreSignal{claim_confidence, dimension_scores, candidate_score, verification_status, rubric_version, role_profile_version, computed_at}` | `ClaimScore`/`Profile` rows exist; versions new | Pure. No LLM |
| 9 Graph | all of the above | `EvidenceGraph` | `CandidateGraph` exists — reuse as the read model | Read-only; missing scores render as "not probed" |
| 10 Ranking | `CandidateScoreSignal + JobRequirement + RoleProfile` | `CandidateRanking{scored_for, candidates[CandidateSummary]}` | `RankedCandidates` exists | Pure over stored rows; no model calls |

Two contract fixes carried over from the Phase 1 audit, both still required:
name `DimensionScores` once and use it everywhere (kills the
`dict[Dimension, "object"]` at `evidence.py:286`), and share one JSON codec
instead of three near-duplicate `_load_dimensions` implementations.

---

## §4 — Database / domain model changes

No Alembic (project rule): every change below is `create_all()` + `docker
compose down -v` + re-seed.

**New table — `evidence_nodes` (append-only, canonical, vector-ready):**

| Column | Type | Note |
|---|---|---|
| `id` | `String(32)` PK | prefix `en_` |
| `candidate_id`, `session_id`, `claim_id`, `question_id`, `response_id` | FK | full provenance chain |
| `modality` | `String(10)` | text \| voice |
| `evidence_type` | `String(24)` | quantity \| process_step \| causal_link \| tool \| metric_definition \| incident \| **ownership** \| **transfer** \| entity \| fact |
| `extracted_fact` | `Text` | the normalised claim of this item |
| `verbatim_quote` | `String(240)` | verbatim-enforced in Python |
| `weight` | `Float` | this item's rubric contribution |
| `dimension_signals` | `Text` (JSON) | which dimensions it fed, and how much |
| `rubric_version`, `prompt_version`, `model` | `String` | reproducibility |
| `trace_id` | `String(32)` | ties to the turn trace |
| `created_at` | `DateTime(tz)` | append-only; rows are never updated |

This is a **grain change**: today the individual signals exist only inside the
`Response.signals_json` blob, so there is nothing to attach provenance to and
nothing to embed later. Promoting them to rows is what makes both the recruiter
drill-down and the future embedding path possible without redesigning the
domain model. **No vector column, no `embedding_id` placeholder, no pgvector** —
per the brief and per "no abstractions without a real consumer." The row is
self-contained text + stable id + provenance, which is all a future embedding
job needs.

**Kept, not replaced:** the existing `evidence` table (one row per
answer × dimension) stays as the derived *dimension reading* / fast read path.
`evidence_nodes` is canonical; readings are recomputable from it. Both are
written in one transaction.

**Altered tables:**

| Table | Change | Why |
|---|---|---|
| `contradictions` | + `claim_a_id`, `claim_b_id`, + `scope` (`intra_claim`\|`cross_claim`\|`global`) | D3 needs to know which claims a contradiction touches |
| `claim_scores` | + `rubric_version`, `role_profile_version`, `consistency_adjustment`, `formula_version` | brief: never overwrite historical scores invisibly |
| `profiles` | + `rubric_version`, `role_profile_version` | same |
| `job_roles` | + `profile_version` | role weights must be versioned |
| `responses` | + `trace_id` | observability propagation |
| `questions` | + `trace_id`, `prompt_version` | same |
| **new** `turn_traces` | `id`, `trace_id`, `session_id`, `response_id`, per-stage latency ms (stt, extraction, consistency, scoring, question_gen, send, total), `fallback_used`, `error`, `created_at` | brief: "do not hide total latency behind one metric" |

**Explicitly unchanged:** `candidates`, `resumes`, `sessions`, `claims`,
`questions` (beyond two columns), `session_facts`. And ProofScreen keeps its own
domain model — nothing from Stride Dash's `users` table is imported, per brief.

**Score history:** `claim_scores`/`profiles` remain current-value rows (updated
in place) but now carry the versions that produced them; a full append-only
score history table is deferred as out of 24-hour scope, and is noted in §9 as
the first thing to add after the MVP.

---

## §5 — Dependency graph (target)

```
routers/*            HTTP boundary — Depends(get_db) everywhere except
   │                 whatsapp.py's BackgroundTask (documented exception)
   ▼
engine/orchestration/*  ← the only place that opens transactions
   │  (thin: receive signal → call module → persist → emit next signal)
   ├──▶ engine/session_repo.py ──▶ api/models.py   (reads)
   ├──▶ engine/planner.py        PURE
   ├──▶ engine/question.py       LLM
   ├──▶ engine/evidence.py       LLM
   ├──▶ engine/consistency.py    PURE
   ├──▶ engine/signals.py        PURE
   ├──▶ engine/scoring.py        PURE
   ├──▶ engine/graph.py     ─┐   reads models
   └──▶ engine/ranking.py   ─┘   reads models
                │
                ▼
        api/contracts/*  ← every arrow above is a typed contract
                │
                ▼
        api/schemas.py (HTTP)   api/taxonomy.py + data/*.json (config)
```

**Enforced rules** (extending the audit's Phase 3, now testable):

1. `planner.py`, `signals.py`, `scoring.py`, `consistency.py`, `voice.py` may
   import only `api.contracts`, `api.schemas`, `api.taxonomy`, config. Never
   `api.llm`, `api.models`, `sqlalchemy`. *(Extend the existing structural test
   to all five.)*
2. `extract.py`, `question.py`, `evidence.py` may call the LLM, may import the
   pure layer, may never import `api.models` or `sqlalchemy`.
3. Only `orchestration/*`, `session_repo.py`, `graph.py`, `ranking.py` import
   `api.models`.
4. **The domain engine must not know WhatsApp exists** (brief): no module under
   `engine/` may import `api.channels.*`. *Verified true today — worth a test so
   it stays true.*
5. No deferred/in-function imports between engine modules (the audit proved none
   of the three current ones guard a real cycle).

---

## §6 — Migration plan

No Alembic. Sequence per environment:

```bash
docker compose down -v                 # drop volumes — schema changes only land this way
docker compose up --build
docker compose exec api python seed.py --reset
docker compose exec api python scripts/dump_fixture.py   # regenerate, never hand-edit
pytest -q                              # gate: was 102, must be ≥102 and green
```

Data migration is not required — there is no production data, and seed +
fixture are both generated. The real migration risk is **fixture drift**:
`fixtures/sample_graph.json` is asserted against in `test_pipeline.py`, so it
must be regenerated in the same commit as any rubric change, or the suite fails
in a way that looks like a scoring bug.

Ordering constraint: D1 (dimensions) must land **before** the fixture is
regenerated, and both must land before Dev B starts the Next.js dashboard, since
`/openapi.json` is the dashboard's generated contract.

---

## §7 — Exact file changes

**New files (11):**

| Path | Purpose | ~LOC |
|---|---|---|
| `api/contracts/__init__.py` | re-exports; single import surface | 30 |
| `api/contracts/signals.py` | `ResumeSignal`, `ClaimSet`, `VerificationPlan`, `QuestionSignal`, `ResponseSignal`, `EvidenceSignal`, `ConsistencySignal`, `DimensionSignals`, `ScoreSignal`, `CandidateRanking` | 220 |
| `api/engine/planner.py` | Module 2, extracted from `orchestrator.plan_next` + `ClaimState` | 200 |
| `api/engine/session_repo.py` | read-only DB helpers extracted from orchestrator | 180 |
| `api/engine/orchestration/__init__.py` | façade | 20 |
| `api/engine/orchestration/session.py` | `create_session`, `finalize`, lookups | 200 |
| `api/engine/orchestration/turn.py` | `submit_answer`, `ask_next`, `_persist_evidence`, `recompute_claim` | 300 |
| `api/engine/ranking.py` | Module 10, extracted from `graph.rank_candidates` | 150 |
| `api/observability.py` | trace ids, `TurnTrace`, stage timers, structured logs | 140 |
| `data/rubric_v1.json` | targets, gates, partial credits, badge thresholds, saturation, consistency thresholds/penalties/floor | data |
| `api/rubric_config.py` | loads + validates `rubric_v1.json` (mirrors `taxonomy.py`) | 90 |

**Modified files (16):**

| Path | Change | Risk |
|---|---|---|
| `api/schemas.py` | `Dimension` enum re-mapped (D1); `+ProbeLevel.TRANSFER` (D2) | **High — frozen, two owners** |
| `api/engine/signals.py` | 6 rubrics re-mapped; +`ownership`, +`scenario_transfer`, +`consistency` rubrics; constants → `rubric_config`; `DimensionScores` alias + shared JSON codec | **High** |
| `api/engine/scoring.py` | consistency applied per D3; versions persisted; voice blend removed (D4); delete dead `merge_dimension_scores` | **High** |
| `api/engine/consistency.py` | claim-scoped classification (`intra_claim`/`cross_claim`/`global`) | **High** |
| `api/engine/evidence.py` | +`OwnershipStatement`/`TransferReasoning` extraction; emits `EvidenceSignal` + evidence nodes; typed `DimensionScores` | Medium |
| `api/engine/orchestrator.py` | slimmed to a façade re-exporting the public surface (audit §4 table) | Medium |
| `api/engine/graph.py` | reads `evidence_nodes` for drill-down; shared codec; top-level import; ranking extracted out | Medium |
| `api/engine/question.py` | TRANSFER wording + prompt version metadata | Low |
| `api/engine/voice.py` | keep measurement, drop score contribution (D4) | Low |
| `api/models.py` | new `evidence_nodes`, `turn_traces`; columns per §4 | Medium |
| `api/taxonomy.py` + `data/claim_taxonomy.json` | dimension-weight keys renamed across 8 families | Medium |
| `api/prompts/extract_signals.txt` | +ownership, +transfer signal blocks | Medium |
| `api/prompts/generate_question.txt` | +TRANSFER level guidance | Low |
| `api/llm.py` | model/prompt version + latency + fallback metadata on every call | Low |
| `api/routers/whatsapp.py` | trace id; debounce; stale-question guard; PII-safe logging | Medium |
| `seed.py`, `scripts/dump_fixture.py` | re-seed + regenerate under new rubrics | Low |

**Deleted:** `scoring.merge_dimension_scores` (audit confirmed zero callers).

---

## §8 — Risks

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R1 | **24h scope is not achievable as written.** ~2,000 LOC of new/changed engine code plus ~36 test rewrites plus prompt retuning, on a working 7.9k-line system | High | Demo slips | Cut line in §9: Phases 2–6 are the acceptance test; 7–9 are hardening. Do not start 7 before 6 is green |
| R2 | Rewriting ~36 tests to match new dimensions masks a real regression | High | Silent scoring bug on stage | Convert the **invariant** tests first and leave them unedited: `test_scoring_modules_never_import_the_llm`, `test_answer_signals_carries_no_score_field`, `test_a_blunt_specific_answer_beats_a_polished_vague_one`. If those three ever need editing to pass, stop — the change is wrong |
| R3 | Seeded demo numbers shift under D3/D4 and the ranking inversion weakens | Medium | Loses the strongest 20s of the demo | Re-run `seed.py --reset` and re-read all three candidates immediately after D3 lands, not at the end |
| R4 | Two new signal types (`ownership`, `transfer`) extract poorly at first | Medium | Two dimensions score ~0 for everyone | Write both heuristic fallbacks **before** the prompts, so fixture mode is honest; keep targets low (2–3 signals) as the existing rubrics do |
| R5 | `ownership` becomes a new bias vector by counting first-person pronouns | Medium | **Directly contradicts the product's core promise** | Rubric credits a *described personal decision or responsibility*, not pronoun choice. "We did X, my part was Y" scores the same as "I did Y". Collectivist phrasing is normal in Indian workplaces and must not be penalised. Needs its own explicit test |
| R6 | Frozen `schemas.py` changed without both owners | Medium | Breaks the two-dev contract, merge conflicts | D1 sign-off gate before Phase 2 |
| R7 | Six probe levels × 3 claims vs a 12-question budget | Medium | Transfer probes never get asked, or depth is lost | D2's rule: TRANSFER only on claims with existing evidence, never an opening probe. Re-check the policy tests' budget assertions |
| R8 | Evidence-node writes double the per-turn write volume | Low | Latency on the realtime loop | Same transaction, batch insert; measure with the new per-stage timers rather than guessing |
| R9 | Stride Dash patterns copied as code rather than as patterns | Low | Couples two products | Brief is explicit; nothing is imported. Adapter stays ProofScreen's own |

---

## §9 — Test plan

Baseline **102 passing** is the floor; the suite must never be red between
steps.

**Invariant tests — must pass unchanged throughout (the tripwire):**
- `test_scoring_modules_never_import_the_llm` — extend to `planner.py`, `consistency.py`, `voice.py`
- `test_answer_signals_carries_no_score_field`
- `test_a_blunt_specific_answer_beats_a_polished_vague_one`
- **New:** no module under `engine/` imports `api.channels.*` (brief's "domain engine must not know WhatsApp exists")

**Per-module tests to add:**

| Module | Unit | Integration | Edge cases |
|---|---|---|---|
| 2 Planner | gap ordering by weight; TRANSFER never opens; budget respected | plan → question → answer → re-plan | all claims saturated; 1 claim; 0 claims |
| 5 Evidence | ownership credited without pronoun counting (**R5**); transfer signals extracted | node rows written with full provenance | non-answer; quote not verbatim; model down |
| 6 Consistency | intra vs cross vs global classification (**D3**); no double-count with the dimension | contradiction scoped to the right claims | same fact twice; variable key; 10%/50% boundaries |
| 7 Rubric | each of the six rubrics + gates; re-homed signals land in the right dimension | claim-level union across answers | empty signals; un-probed dimension |
| 8 Scoring | versions persisted; voice no longer blended (**D4**) | full recompute reproducible from stored rows | all-zero; saturated |
| 9/10 Graph & Ranking | drill-down resolves node → quote → dimension | two role profiles ⇒ two orders, same evidence | no claims; no scores |
| Obs | trace id propagates end to end | per-stage latencies all recorded | LLM timeout still records a trace |

**Acceptance test (the brief's own):** one scripted BPO/Ops Team Lead run —
resume → claims → 3–5 verification claims → adaptive question → **voice**
answer → evidence → consistency → scoring → graph → ranking → drill-down, with
the final assertion being the product's defining property: for two candidates,
the API response alone must let a recruiter answer *"why is this one above that
one"* as claim → evidence → dimension signals → confidence → role relevance,
with every number reproducible from stored rows and no LLM call involved in the
comparison.

---

## §10 — Implementation sequence

Each step ends with `pytest -q` green and is independently revertible.

| Phase | Work | Gate |
|---|---|---|
| **0** | **Sign-off on D1–D4.** No code until then | Your approval |
| **2** | `api/contracts/`; `DimensionScores` alias; shared JSON codec; no behaviour change | 102 pass, zero diff in fixture |
| **3** | Boundary rules as tests; promote the 4 deferred imports; document the `whatsapp.py` exception | 102 + 4 new pass |
| **4** | Extract `planner.py`, `session_repo.py`, `orchestration/`; `orchestrator.py` → façade | 102 pass, public surface unchanged |
| **5a** | **D1** dimension re-map + **D2** TRANSFER + **D4** voice; regenerate fixture; re-run seed | suite green, 3 seeded numbers re-read |
| **5b** | **D3** claim-scoped consistency; `contradictions` columns | ranking inversion re-verified |
| **5c** | `evidence_nodes` table + writes + graph drill-down | acceptance test passes end to end |
| **6** | `ranking.py` extraction; recruiter/dashboard contracts frozen for Dev B | two role_ids ⇒ two orders |
| **7** | Voice path hardening (debounce, stale-question, STT failure) | voice acceptance run |
| **8** | `observability.py`, `turn_traces`, versions persisted everywhere | per-stage latencies visible |
| **9** | Test hardening; delete dead code; extend invariant tests | suite green, coverage on all 10 modules |

**Recommended cut line if time runs short:** Phases 2–6 deliver the brief's
final acceptance test. Phases 7–9 are hardening — valuable, but a demo survives
without per-stage latency metrics and does not survive a broken evidence graph.

---

## Appendix — Stride Dash pattern reuse (read-only audit, complete)

Pattern reuse only; nothing imported, no shared database, no shared model.
ProofScreen runs its own claim extraction and accepts the minimum handoff
`{phone, cv_text}`. Audited read-only at `/Users/212705/Stride/stride-backend`.

**Where ProofScreen is already equal or better — no work:**

| Pattern | Verdict |
|---|---|
| Inbound dedup | Stride uses a process-local dict + 300s TTL (`gateway/dedup.py`), which **duplicates across workers/pods**. ProofScreen's unique index on `responses.provider_message_id` is durable and multi-worker-safe. **Keep ours.** |
| HMAC verification | Stride skips verification entirely when secret or header is absent — it **fails open**. ProofScreen's `WHATSAPP_VALIDATE_SIGNATURE` flag is the stricter design. **Keep ours.** Copy only the ordering, which both already do: raw bytes read *before* any JSON parse. |
| LLM timeout | Stride's hard-won lesson (a 600s SDK default once hung an entire turn) is already handled here: `llm_timeout_seconds = 25.0`, applied at `api/llm.py:113`. **No change.** |

**Worth adopting — folded into Phases 7–8:**

| # | Pattern | Mechanism to copy | Lands in |
|---|---|---|---|
| S1 | **Burst debounce** (`gateway/message_handler.py:67-114`) | Rolling *generation* counter per phone: each inbound bumps a gen and sleeps 1.0s; only the newest task flushes, re-checking the generation **inside** the per-phone lock. Merged texts are **newline-joined, never last-wins**, and the merged turn's timestamp is `min(stamps)`. Directly relevant: a candidate typing "35 agents" then "across 4 pods" is one answer, and today ProofScreen would score the first and desync | Phase 7 |
| S2 | **Stale-answer protection** (`gateway/turn_policy.py:208-228`) | Compare the inbound's epoch timestamp against `question_asked_at`; if the answer predates the question, don't score it against that question. Their `_parse_ts` returns **`None`, never `now()`**, on a malformed timestamp — "a fabricated now would make every stale message look fresh." Fails open on every uncertainty. ProofScreen already stores `Question.asked_at`; the missing half is the inbound timestamp (see gate below) | Phase 7 |
| S3 | **Host-scoped bearer on media** (`http_client.py:48-56`) | Attach the Meta token only when the host matches `lookaside.fbsbx.com`/`fbcdn.net`/`facebook.com`/`whatsapp.net`, so a redirect can never carry it to a third party. ProofScreen fetches media with `follow_redirects=True` at `channels/whatsapp_cloud.py:260` — **verify** the token cannot follow a cross-host redirect, and host-scope it explicitly rather than relying on the HTTP client's default | Phase 7 |
| S4 | **PII scrubbed before the model, re-injected after** (`tools/resume.py:57-89`) | Regex email/phone/Aadhaar/PAN out of text sent to the LLM, keep the real values locally, re-attach after. Directly applicable to Module 5: candidate answers routinely contain phone numbers and IDs, and today they go to the model verbatim. Note their own gap as an anti-pattern: full phone numbers still land in analytics storage | Phase 8 |
| S5 | **Trace propagation** | Stride threads `trace_id` explicitly through ~40 call sites with no contextvars and no structlog. It works but is verbose. ProofScreen should use a `ContextVar` plus a logging filter instead — same guarantee, no signature churn across ten modules | Phase 8 |
| S6 | **Fallback that changes model, and 429-aware retry** (`llm/__init__.py:71-103`, `openai_compat.py:16-29`) | Their fallback deliberately **drops the model override**: "if a faster model failed to return parseable JSON, retrying it is not the move." Retries are **429-only**, delays `[2, 5, 15]`, honouring `Retry-After` over the local schedule. ProofScreen retries all exceptions equally today | Phase 8 |
| S7 | **Log truncation discipline** | Phone truncated to last 4, message id to last 12, inbound text capped at 200 chars | Phase 8 |

**Confirms a gap is real, not imagined:** Stride records model, token counts,
cache tokens, latency and trace id per LLM call — but **no prompt version or
prompt hash anywhere**. That is exactly G6/§4's `prompt_version` requirement,
and it is the one place ProofScreen should not follow Stride's lead, since
rubric and prompt changes must be attributable to a score.

**New sign-off gate discovered by this audit (belongs with D1–D4):** S2 needs
the inbound message timestamp, and `InboundMessage` in `api/schemas.py`
carries no timestamp field today. Adding `sent_at: datetime | None` is an
optional-field addition to the frozen file — per CLAUDE.md rule 2, "a
conversation," not a solo decision. Small, but it needs the same sign-off as D1.
