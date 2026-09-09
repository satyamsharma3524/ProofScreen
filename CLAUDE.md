# ProofScreen API — working notes (v2)

FastAPI backend for the Shine 2026 hackathon (build day 10 Sep, demo 11 Sep).
Backend only; the recruiter dashboard is a separate Next.js app consuming
`/openapi.json`. WhatsApp Business Cloud API (Meta, direct) is the only
candidate channel.

## Read this before proposing code

**All process, architecture and phase documents live in `docs/`. Start at
[docs/README.md](docs/README.md)** — it carries the binding reading order and
marks which documents are superseded history rather than instructions. The
order is not advisory: `docs/EXECUTION_STANDARD.md` §1 requires the frozen
documents to be read *before* proposing code, and forbids new architecture, new
modules, new layers and new abstractions without explicit approval. Default
assumption: **the architecture is correct; the implementation fits inside it.**

`CLAUDE.md` and `README.md` are the only markdown at the repo root. This file
must stay here — Claude Code loads it from the root of the working tree, and
moving it drops these rules out of every session silently.

Do not restate a frozen document's contents in a new file. Cite it. A drifted
copy of a frozen decision is worse than a pointer to it
(`docs/EXECUTION_STANDARD.md` C3).

## Two developers, one `main`

Both push to `main` hourly, which only stays conflict-free because ownership is
strict. **Never edit the other developer's files** — that is rule 3 below, and
it is the whole mechanism.

- **Each developer has a brief: `docs/DEVELOPER_A_CONTRACT.md` (intelligence
  path — routing, questioning, evidence) and `docs/DEVELOPER_B_CONTRACT.md`
  (everything the recruiter reads).** Each carries ownership, task order,
  branch names, and a precondition to verify *before* branching. Both are
  subordinate to `EXECUTION_STANDARD.md`, `ARCHITECTURE_LOCK_v1.md` and
  `PHASE_1_TASKS.md`; where they conflict, they win.
- **The only interface between the two streams is `FamilyMatch`**, the
  NamedTuple A publishes from `taxonomy.py` in P1-06. Do not change its shape
  once B has started P1-08b without telling them.
- **Ownership has three sources and they disagree.** The table in `README.md`
  assigns `engine/signals.py` to B and `models.py` / `ids.py` to A; both
  contracts say the opposite. **For Phase 1 the contracts win** — they are
  per-file, explicit and mutually consistent. `PHASE_1_TASKS.md` P1-03 says why
  for `signals.py`: *A edits, B reviews the hunk.* Settled — do not
  re-litigate it per task.
- **`api/schemas.py` is the tripwire.** Frozen, two owners, and Phase 1 needs
  **zero** edits to it — P1-00 pre-landed every field both developers need. If
  a task seems to require opening it, the task is wrong. Stop and raise it.
- **`tests/conftest.py` is shared, append-only, by announcement.** Its BPO
  vocabulary is load-bearing for family detection; restructuring it silently
  collapses weight assertions across the suite.
- Anything touching the other owner's file — including a test of theirs that
  your change necessarily breaks — is **announced and reviewed, never silent.**

## Non-negotiable rules

1. **The model never produces a score.** It returns countable signals and
   quotes them; Python turns counts into numbers. If you find yourself parsing
   a rating, confidence or percentage out of a model response, stop. Two tests
   enforce this structurally (`test_scoring_modules_never_import_the_llm`,
   `test_answer_signals_carries_no_score_field`).
2. **`api/schemas.py` is frozen.** It is the contract between the two devs and
   between this service and the Next.js app. Adding an optional field is a
   conversation; changing or removing anything is not a solo decision.
3. **One owner per file** (table in README.md). Never edit the other dev's
   files — that is what keeps `main` conflict-free with both pushing hourly.
4. **Quotes are verified in Python, not requested in a prompt.**
   `evidence.enforce_verbatim()` drops any signal whose quote is not literally
   in the answer. A paraphrase is exactly the hallucination this product exists
   to kill.
5. **Every LLM call has a fallback.** `complete_json(..., fallback=...)` must
   always be given one. A stack trace on the projector is the failure mode the
   whole architecture exists to prevent.
6. **Never score presentation.** No accent, fluency, grammar, speaking
   confidence or personality — anywhere, ever. Those are bias vectors, and
   removing them is a stated product decision, not an oversight.
7. **No Alembic.** `create_all()` at startup. Schema change =
   `docker compose down -v` and re-seed. `create_all()` **cannot add a column
   to a table that already exists** — `db.verify_schema()` now fails at startup
   with the remedy printed rather than at the first query. Adding a column
   means adding it to `db._REQUIRED_COLUMNS` too.
8. **No handler writes a tenant predicate.** `api/tenancy.py` owns `scoped()`
   and `get_owned()`, and they are the only two places `tenant_id ==` appears.
   A cross-tenant id is **404, never 403** — 403 confirms the row exists.
   `TenantScope.system(reason=...)` is the one bypass; there is exactly one
   use, in the WhatsApp webhook, and an AST test fails if a second appears.
9. **A finalized `Evaluation` is immutable.** Any update to a row whose
   `finalized_at` was already set raises `EvaluationFinalized` from a
   `before_update` listener — not only through the service function. A new
   assessment is a new interview and a new row.

## Commands

```bash
docker compose up --build                    # api + postgres 16
docker compose exec api python seed.py       # 3 candidates + 2 role profiles
pytest -q                                    # 102 tests, sqlite + fixture mode, ~2s

# no-Docker loop
export DATABASE_URL="sqlite+aiosqlite:///./proofscreen.sqlite3"
python seed.py && uvicorn api.main:app --reload

# after changing any rubric or weight
python seed.py --reset && python scripts/dump_fixture.py && pytest -q
```

## Architecture in one paragraph

`routers/candidates.py` parses a resume (`ingest/parse.py`) and calls
`orchestrator.create_session`, which runs `engine/extract.py` (LLM #1) for a
job family plus up to 3 claims **typed against the taxonomy**. The session waits
in `AWAITING_OPT_IN` because Meta will not let us message first. The candidate
sends their opt-in code; `routers/whatsapp.py` binds the phone and
`orchestrator.ask_next` applies the policy — pure function
`plan_next(states, index)` — then calls `engine/question.py` (LLM #2) for
wording only. Answers land in `responses` (**the seam**), and
`orchestrator._persist_evidence` hands each to `engine/evidence.py` (LLM #3),
which returns *countable signals* plus *facts*, drops any non-verbatim quote,
and runs `engine/consistency.py` over the fact memory. `engine/signals.py`
turns counts into six dimension scores; `engine/scoring.py` applies dimension
and role weights and the consistency multiplier; `engine/graph.py` assembles
the tree and re-ranks live for any role profile.

## Conventions

- Async throughout — every request blocks on a model call. Async SQLAlchemy
  2.0, **no lazy relationships** (explicit `select()` everywhere) so there is no
  `MissingGreenlet` surprise at 2am.
- Prompts are `.txt` rendered with `string.Template` (`$var`), never
  `str.format` — every prompt contains a literal JSON schema full of braces.
- Short prefixed IDs (`c_`, `s_`, `cl_`, `q_`, `r_`, `e_`, `f_`, `x_`, `jr_`),
  not UUIDs, because on demo day you read them off a screen out loud.
- Enum DB columns are `String`; Pydantic enforces values. A native Postgres
  enum would need a migration to add a value and `create_all()` cannot.
- Heuristic fallbacks (`extract.heuristic_claims`,
  `question.FALLBACK_QUESTIONS`, `evidence.heuristic_signals`) are production
  code, not stubs — they are what runs when the model is down. They are
  deliberately more conservative than real extraction; if a fallback ever looks
  *better*, the fallback has become the product.
- `settings.openai_api_key = None` at the top of `seed.py` and
  `scripts/dump_fixture.py`: seeding must be free, instant and offline.

## Env flags that change behaviour

| Var | Effect |
|---|---|
| `OPENAI_API_KEY` empty | fixture mode: no network, deterministic heuristics |
| `WHATSAPP_ACCESS_TOKEN` empty | outbound dry-run; inbound webhooks still parse |
| `ADAPTIVE_PROBING=false` | strict VALIDATION→OUTCOME sweep |
| `QUESTION_VALIDATION=false` | no question validation, no regeneration — the Phase 1 question path |
| `REPAIR_TURN=false` | a non-answer consumes its budgeted question, as in Phase 1 |
| `SCORE_INLINE=false` | signal extraction moves to a background task |
| `VOICE_WEIGHT=0` | removes the text/voice asymmetry |
| `MAX_QUESTIONS`, `MAX_CLAIMS` | interview size |
| `REQUIRE_API_KEY=true` | no `X-API-Key`, no service (401). **Set it before the URL is public** |
| `BUILD_SHA` | stamped as `code_version`; `.git` is dockerignored, so in the container this is the only source |
| `WHATSAPP_VALIDATE_SIGNATURE=true` | requires a correct `WHATSAPP_APP_SECRET` |
| `ENABLE_DEV_ENDPOINTS=false` | hides `/api/dev/*` |

## Gotchas already paid for

- **Meta media needs the bearer token on BOTH calls** (id → URL, then URL →
  bytes). Missing it on the second is a 401 that looks like your own bug.
- **Meta retries webhooks.** Answers are de-duplicated on
  `provider_message_id`; without it one retry becomes a second answer and the
  interview desyncs mid-demo.
- **One webhook can carry several messages**, and most carry only delivery
  statuses. `parse_inbound` returns a *list* for that reason.
- **The webhook must 200 fast** — real work happens in a `BackgroundTask`.
- **X-Hub-Signature-256 is over the RAW body.** Re-serialising parsed JSON
  changes whitespace and key order and the digest never matches.
- **The 24-hour window**: free-form text only within 24h of the candidate's
  last message. The opt-in flow exists to open it.
- **CORS**: wildcard origins and `allow_credentials=True` are mutually
  exclusive; `main.py` handles the combination.
- **`pymupdf` renamed its module** — `import pymupdf`, falling back to `fitz`.
- **Resume heuristics**: a parenthesised year is a job-title heading, a
  comma-heavy line with no verb is a skills list, and bare `lead`/`design` are
  nouns on a resume as often as verbs. All three are excluded explicitly.
- **`y -> ies` is handled in the STEM, not the suffix group** (`taxonomy.
  _term_pattern`), because the plural replaces the y instead of following it —
  `story` + `ies` is not a word. 20 taxonomy terms end in `-y` across seven
  families, and before the fix each scored nothing for its own plural
  (`query` missed "queries", `user story` missed "user stories"). Fixed in
  `e321265`; the deferral that preceded it was measured at **0 family changes
  and 0.0000 confidence drift over 64 golden entries**, which is why it was
  cautious rather than correct. Do not re-add the suffix-group version.
- **A family's keyword must be a compound wherever another family holds the
  bare word.** `hr_recruitment` carries `onboarding` and `interview`; a product
  resume saying "rebuilt user onboarding after twenty user interviews" fed HR
  two hits and `product` none, and lost a real PM resume to HR by 0.016. Hence
  `user onboarding` / `user interview` / `user retention` / `feature launch` in
  the `product` family, and no bare `product` (it double-counts with `product
  manager` and fires on "Product Support Engineer"). When adding a family,
  check term collisions **in both directions** — a set intersection misses the
  case where one family's compound contains another's bare term.
- **Unit regexes must order alternatives longest-first** or `120ms` compresses
  to `120m`.
- **Weight renormalisation must absorb the rounding remainder** in its last
  key, or a recruiter typing 40/30/20/20 sees 99.9999 and assumes the product
  is broken.
- **Family detection is load-bearing in tests.** A resume saying
  "support / escalation / Zendesk" classifies as `customer_support`, which has
  no `team_handling` or `aht_control` claim type — and every weight assertion
  silently collapses. `tests/conftest.py` pins the family with BPO vocabulary
  and says so.

## Design decisions worth defending out loud

- **Evidence accumulates across a claim's answers** (union of signals, rubric
  run once) rather than taking the best per-answer score. Best-of
  under-credited candidates who spread evidence across probe levels — which is
  precisely what the 5-level protocol asks them to do.
- **Un-probed dimensions contribute 0**, with `probed_dimensions` reported.
  This is a confidence score; thin questioning should show as low confidence,
  and the dashboard can say "4 of 6 probed".
- **`role_coverage` is separate from the score** — "evidenced badly" and "never
  claimed it" are different facts.
- **Consistency is session-level, applied once.** It is a property of the whole
  interview, not of any claim, and counting it inside a claim *and* as a
  multiplier would penalise the same fact twice.
- **`stable` vs `variable` fact keys.** Without that split the engine flags
  every improvement a candidate describes as a contradiction.

## Where things stand

**Verify this section rather than trusting it** — it is the first thing to go
stale. `git log --oneline -5` and `pytest -q` are the source of truth.

Baseline: taxonomy (8 families + `general`), typed claim extraction,
deterministic family routing with requisition precedence, adaptive policy
capped at 12, the TRANSFER probe for stalled claims, signal extraction with
verbatim enforcement, six rubrics with gates, deterministic consistency, role
weight profiles with live re-ranking, `why_ranked` on every ranked row, the
`candidate_outcomes` loop and the M4 validation report, Meta Cloud API webhook
(verify, HMAC, batching, retry de-dup, two-step media), Whisper voice with
duration, `/api/dev/*` tooling, engine-generated fixture, seed showing the
resume/competence inversion and the ranking flip across three lenses, Docker.

**Phase 1 and Phase 2 are complete** (307 tests at Phase 2 exit; Phase 3's
harness took it to 332, a parallel validator commit to 344, and Phase 4 to
**457** — `pytest -q` is the source of truth, not this sentence). All fourteen tasks merged
(`docs/PHASE_1_TASKS.md`). The exit condition is the one written in
`PHASE_1_SUCCESS_METRICS.md` §Reporting, and all four parts hold: M1b = 100%,
M5c = 0%, guardrails green, and M4a **published** as `insufficient data
(n < 30)` at n = 0. Five *targets* are missed (M1a, M2a, M2b, M5a, M3a); none
is an exit criterion and none is a code defect — the reasons are recorded in
the exit checklist and summarised there as metric-definition problems or n = 4
artifacts. **Do not "fix" a missed target by editing the metric or the
scoring.**

`TRANSFER_PROBE=false` still reproduces the pre-phase interview exactly:
0 probes, competence 46 / 61 / 56 / 14 identical both ways.

**Phase 2 — Question Quality Infrastructure — is complete.** Question
generation is now `planner → model → validate() → one regeneration → fallback`,
with `engine/question.validate()` applying **seven rules in pure Python**:
`answer_leakage · duplicate_content · multiple_fact_targets ·
hypothetical_misuse · unsupported_metric · scope_drift · no_claim_anchor`. Same
pattern as `enforce_verbatim()` — the model produces, Python decides. A
non-answer earns one **off-budget** repair turn. `questions` records
`source · attempts · violations_json · is_repair`, which is what makes M6
computable from stored rows.

Three things about that layer are load-bearing and easy to break:

- **The regeneration cap is one, written as two explicit calls rather than a
  loop** — a loop invites raising the constant. The ceiling is the +20%
  median-turn-latency guardrail.
- **The fallback is never validated.** It is rendered `On "<claim>" — <base>`,
  so it quotes the claim including its figures and trips `answer_leakage` by
  construction. CLAUDE.md rule 5 requires every LLM call to have a fallback, so
  a validator able to reject it would leave no path at all.
- **Rule 3 is not evaluated on TRANSFER.** A valid T1 probe pairs one claim's
  method with another's problem, so two fact targets is the mechanism working.

`docs/PHASE_2_EXECUTION_PLAN.md` also holds **Phase 4** (D6–D10: Evaluation
entity, versioning, replay, tenant isolation, score history), re-designated
because its own entry condition — M4a has produced a number — is still unmet.
**Trigger for D9 tenant isolation: before the first customer's data lands.**

**Phase 4 — Evaluation Integrity & Production Readiness — is complete.**
D6–D10 merged; plan, task specs and the acceptance report are
`docs/PHASE_4_TASKS.md`. **457 tests passing** (344 at the Phase 4 baseline
`761959e`; the "332" this file used to claim was already stale). Backward
compatible: 0 paths removed, 0 fields removed or retyped, 0 new required
parameters — `HealthOut` and `OutcomeOut` each grew optional defaulted fields
and nothing else changed.

- **D9 tenancy.** 16 tables; 15 carry `tenant_id`. Enforcement is one module
  (rule 8 above), not a `where` clause per endpoint. Unkeyed requests are the
  **named development tenant `t_dev`**, never a global view.
- **D7 provenance.** Taxonomy is versioned twice — `tax_1` (declared) and a
  content hash (measured), because a weight tuned in data is the change most
  likely to move a score with nothing in git to show for it. Plus rubric,
  scoring, question-policy and three prompt hashes, `code_version`, the model
  requested, and eight allowlisted flags. `evaluation_version` =
  `evx_sha256(material)[:16]`. **`model_returned` is recorded and NOT hashed** —
  it is a per-process observation, so hashing it would make an evaluation's
  identity depend on whether anyone made a live call in that process.
- **D6 Evaluation.** `draft -> finalized`, and only those two. No `abandoned`:
  `SessionState.ABANDONED` is declared in `schemas.py` and **assigned nowhere**
  — three reads, zero writes. One evaluation per session, by UNIQUE constraint.
  It stores the result, the configuration and pointers; it stores **no
  evidence**, and there is still no `evidence_nodes` table.
- **D8 replay.** *Extraction is recorded; everything downstream of extraction is
  replayable.* Zero model calls, proved three ways including a poisoned wrapper.
  The four seeded personas all replay MATCH. Missing signals give a **409 that
  names what is absent** — scoring what remains would be a confident lower
  number produced by missing data.
- **D10 audit.** **No events table**, deliberately: its content would duplicate
  two columns on `evaluations` and the already-append-only `candidate_outcomes`.
  That table gained `evaluation_id` and `previous_decision`; the history
  endpoint assembles a deterministic timeline from the two sources.

Phase 4 things that look like bugs and are not:

- **`tenant_id` defaults to `t_dev`.** Required because
  `scripts/interview_study.py` writes `Candidate` rows directly and Phase 3 is
  frozen. Nothing in `api/` relies on it, and
  `test_a_tenant_scoped_pipeline_writes_no_development_tenant_rows` drives a
  whole interview under a second tenant and reads back every row to prove it.
- **The orchestrator's queries are not tenant-scoped.** The session is an
  aggregate root; every router-reachable entry point takes a **resolved row**,
  not an id, so possession is authorisation. Pinned by
  `test_the_orchestrator_is_entered_with_resolved_rows_not_ids`.
- **`qpol_2` is not the Phase 2 exit validator.** The constant was introduced in
  D7, after `761959e` ("P4A: two validator changes"), so it denotes the
  validator including those refinements.
- **Replay excludes `resume_score`.** It depends on
  `settings.default_job_description`, so it is a function of live configuration
  rather than of stored evidence.

Still open after Phase 4: auth is **one shared key per tenant** — no users, no
roles, no rotation, and user-level authorization does not exist and is not
claimed. `REQUIRE_API_KEY` defaults to `false`; **turn it on before the URL is
public.** `profiles` is still a mutable score cache with a pointer bolted on,
because making it a pure pointer means changing `rank_candidates`. The DPDP
workstream (`PRODUCTION_READINESS.md` §7) is untouched and outranks all of this
commercially.

**Pre-Hackathon MVP Enhancements — Complete (509 tests passing)**:
- **Execution-First Opening**: Every claim opens with `Move.OPERATING_CONTEXT` (Execution) to lead with operational work rather than bureaucratic validation questions.
- **Adaptability Reachability (`Move.PERTURB`)**: Saturation (`score >= 80`) no longer closes claims while `Move.PERTURB` is pending. `PERTURB` is placed as move #3 in `ARCHETYPE_LADDER`.
- **Authentic Practitioner Scoring Gates**: Operational evidence (`causal_links`, `incident_markers`, `process_steps`, `constraints`) opens Knowledge and Judgment gates (`gate_open=True`) in `engine/signals.py`, preventing authentic outage troubleshooting from being capped at 45.
- **Operational Evidence Bonus (`scoring.claim_score`)**: Implemented claim-level multiplier (+0.10 for incident markers, +0.10 for complete causal links, +0.05 for constraints) so authentic incident answers outscore textbook definition lists.
- **Conversational Fallback & Memory Exhaustion Steering**:
  - `is_memory_exhausted_or_skip()` in `engine/evidence.py` detects phrases like "I don't know", "Not sure", "I can't remember", "I forgot", "Skip", "Nothing else comes to mind", etc.
  - Bypasses repair turn re-interrogations on memory exhaustion; advances planner to next claim/move without penalizing the candidate (0 signals extracted).
  - Formats transition questions with warm human acknowledgements (`"That's okay."`, `"Makes sense."`, `"Got it."`, `"Understood."`, `"Fair enough."`, `"No worries."`) and strips robotic transition phrases (`"Let's move to another experience."`, etc.).
- **Question Prefix Cleanup & Prospective Adaptability**: Cleaned up double-prefix formatting (`On "On ..."`) and credited prospective transfer reasoning in `score_adaptability()`.

**Final Pre-Hackathon Audit & Recruiter Alignment Pass — Complete (518 tests passing)**:
- **Ownership False Negative Reduction**: Inferred ownership credit from first-person operational verbs ("I isolated", "I handled", "I led", "I deployed", "I configured", "I fixed") in `engine/signals.py`, opening the Ownership gate (`gate_open=True`) while preserving explicit `boundaries` as highest evidence.
- **Decision Quality & Troubleshooting Step Detection**:
  - Differentiated strong trade-off evaluations (`_is_strong_decision()` checking "evaluated", "compared", "versus", "tradeoff", "instead of", "alternative") at 1.0 weight from simple choices at 0.5 weight in `score_judgment()`.
  - Added `_is_troubleshooting_step(step)` detecting operational keywords (`fix`, `debug`, `investigate`, `diagnose`, `isolated`, `resolved`, `mitigated`, `restored`, `recovered`, `rollback`, `rolled back`, `root cause`, `outage`, `incident`, `failure`, `crash`, `degraded`, `leak`, `corruption`, `deadlock`, `timeout`, `exhaustion`). Weighted at 1.5x in `score_execution()` with basis annotation `• Operational troubleshooting step: <step>`.
- **Quantity Extraction & Strong Claim Prioritization**:
  - Extracted spelled-out numbers ("three engineers", "two quarters", "a dozen endpoints") and relative/multiplicative quantities ("cut latency in half", "doubled throughput") in `engine/evidence.py` heuristics & LLM prompts.
  - Added `claim_strength_bonus(text, metric)` boosting claims with incident markers (+3.0), causal/outcome language (+2.0), quantities (+2.0), constraints (+1.5), and ownership verbs (+1.5). Sorted/ranked claim inventory in `extract.py` and `build_claim_states()` in `orchestrator.py` so strongest operational claims are interviewed first.
- **Multi-Sentence Causal Chain Recall**: Added sliding window scan (sizes 4, 3, 2) in `engine/evidence.py` capturing Cause -> Action -> Outcome chains across adjacent sentences while maintaining verbatim quote enforcement.
- **Textbook Answer Detection Signal**: Added `_is_theoretical_only()` basis annotation (`• Answer style: Primarily theoretical (no operational incidents or causal chains)`) when concept/metric explanations are present without operational evidence. No score penalties; metadata only.
- **Recruiter Explanation Improvement**: Transformed raw count basis outputs (e.g. "3 process steps, 2 tools") into descriptive action summaries (e.g. `• Executed step: ...`, `• Evaluated decision tradeoff: ...`).
- **Recruiter Dimension Coverage Preference**: Verified role-weighted dimension scoring so candidates who demonstrate evidence across multiple dimensions outrank candidates with evidence on only 2 dimensions.

**A parallel session commits to `main`.** `761959e` landed mid-phase from
another agent. File ownership held, but the hourly-push discipline below assumes
humans coordinating. Check `git log` before assuming your baseline.

**Phase 3 — Real Interview Validation Study — is running.** That measurement
(the corpus reads 100%, so it detects regression and cannot say whether the
validator is *good*) is now half done. Plan and full execution log:
`docs/PHASE_3_VALIDATION_STUDY.md`. `scripts/interview_study.py` drives real
interviews, instruments `validate()` from outside, and writes
`studies/phase3/`. **`api/` is not modified by this phase** — that is
acceptance criterion 1, and it holds.

Measured over **519 generated questions, 68 interviews, 9 families, $3.67**:

- **M7h live reject rate 25.5%** — one question in four fails validation on the
  first attempt, against a corpus reading 100%. Different populations, not a
  contradiction; this is just the first time the second one has a number.
- **`duplicate_content` is the second most common rule in the wild (40 fires)** —
  the one P2-01's ablation found was worth *zero* recall on the corpus. The
  ablation was right that the corpus under-represented it.
- **`hypothetical_misuse` fired zero times in 486 decisions.** Not evidence the
  rule is wrong; evidence gpt-4o does not make that mistake. **Do not delete
  it** on this basis — see the plan's §11.
- **The repair turn fired zero times in 68 interviews.** `is_non_answer()` wants
  a canned phrase or <12 chars and no realistic candidate writes either. This
  fails an acceptance criterion and is reported as a failure, not fixed: a
  persona authored to reply "ok" would be fitting the data to the test.

**Blocked on a human.** `studies/phase3/human_review_sample.csv` is 100 blind
items (50 validator-accepts, 50 rejects) awaiting labels; §12 of the plan is the
reviewer brief. Nothing downstream — confusion matrix, disagreement analysis —
can be computed until they land. **Do not tune `DUPLICATE_JACCARD` or the
stopword lists during the study** (C7): that is fitting to the test set, and it
is the one move that makes the study worthless while making it look successful.

Do not add corpus entries reactively — that is counter-metric C6.

`M5a` reads 98.0%, not the 81.7% an older revision of the checklist recorded:
it is margin-based against `taxonomy.MARGIN_FLOOR`, over the 50 golden entries
a human says have a family. The 10 entries labelled `general` are *correctly*
routed to `general` and cap the metric at 83.3% if counted as failures.

Known and deliberately not fixed:

- **`extract._metric_of` has no seconds unit.** `_UNIT` covers `ms` and
  `minutes` but not `s`/`sec`/`seconds`, so "from 480s to 310s" compresses to
  `480` instead of `480s -> 310s` — and seconds is the unit BPO measures AHT
  in. Fixing it needs the alternation ordered longest-first *and* a trailing
  boundary, or "3 shifts" becomes `3 s`. Owner: A (`extract.py`).
- **The generated fixture is not a pure function of the seed data — it varies
  with id LENGTH.** Measured: `seed.py --reset && dump_fixture.py` is stable
  across repeated runs (same content hash 3×), but widening the machine ids
  from 6 to 10 hex chars changed exactly one field — the 4th entry of
  `claims[2].dimensions[0].quotes`, right on the `[:4]` truncation boundary in
  `signals.py:138`. The quote *set* is identical; only which four survive the
  cut moved. No score changed (56 / 46 / 14 / 61 both ways) and no assertion
  depends on it. Root cause not pinned — some ordering behind the merge is
  reading an id. Repro is exact: flip `_MACHINE` in `ids.py` and re-dump.

`api/db.py` **now arms `PRAGMA foreign_keys=ON`** for SQLite, so all 17
`ondelete` clauses execute under test instead of only on Postgres. It is still
in neither ownership list — that is a gap in the contracts, not a gap in the
code.

**HIRING MANAGER TEST Prompt Update**: Updated `api/prompts/forensic_question.txt` and `v2_forensic_question.txt` with the `HIRING MANAGER TEST` block to eliminate forensic category leakage into candidate-facing WhatsApp messages (518 tests passing).

Not done: Next.js dashboard, Render/Railway deploy, auth (deliberately none),
approved WhatsApp template for first contact (needs Meta approval), the
separate "Shine Verified" code-sandbox product from the strategy doc.
