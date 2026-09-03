# Critical Review — IMPLEMENTATION_PLAN.md

Reviewed cold, as if by someone who did not write it. Assumption: **engineering
time is the scarcest resource**, the demo is in days, and the system currently
**works with 102 passing tests**.

**Headline verdict: the plan proposes ~2,500 lines of new and changed code, of
which roughly 200 lines deliver recruiter value.** It is a plan written for a
codebase with two years ahead of it, not two days. Most of it optimises the
*shape* of a system that already passes its own acceptance test.

---

## The finding that reframes everything

The plan's centrepiece — `evidence_nodes`, a new table justified by "recruiter
drill-down" — solves a problem that is already solved. Reading the **existing
generated fixture**, every claim already carries:

```json
"dimensions": [{ "dimension": "SPECIFICITY", "score": 100, "signal_count": 11,
                 "basis": "6 quantities, 5 named entities",
                 "quotes": ["Billing complaints were about 40% of our negative
                             feedback, so we redesigned the escalation workflow…"] }],
"facts":  [{ "key": "csat_pct", "value_num": 40.0, "unit": "%", "quote": "…" }],
"qa":     [5 turns, each with question, probe_level, answer, answer_score]
```

That is claim → evidence → dimension signals → confidence → quotes, with
provenance, **shipping today**. The acceptance test ("why did A rank above B,
without trusting an LLM score") passes against the current schema. The new
table would add queryability and embedding-readiness — and the brief explicitly
forbids building embeddings. **That is textbook YAGNI on the plan's largest
item.**

---

## Verdict table

| Feature | Original plan | Recommendation | Reasoning | Est. LOC saved |
|---|---|---|---|---|
| `api/contracts/*` | New package, 10 signal types, ~250 LOC | **REMOVE** | The repo already has typed boundaries: `ScoreRequest`/`ScoreResult`, `AnswerSignals`, `ClaimOut`, `DimensionScore`, `CandidateGraph`. The audit found exactly **one** untyped boundary — `dict[Dimension, "object"]` at `evidence.py:286`. That is a one-line annotation fix, not a package. Wrapping working types in new names to satisfy a spec bullet is ceremony, and it renames the one seam two devs explicitly agreed on | **250** |
| Planner extraction (`engine/planner.py`) | Move `plan_next` + `ClaimState` out | **POSTPONE** | `plan_next` is *already* pure, already separated from question wording — the brief's "extremely important" separation already exists in the code. Moving it changes no behaviour, delivers no recruiter value, and opens a merge-conflict window in the file Dev A edits hourly. Same edits are needed either way for a new probe level | **200** |
| Orchestration extraction (`orchestration/session.py`, `turn.py`, `session_repo.py`) | Split 816 lines into 3 files | **POSTPONE** | Highest-traffic file in the app; every router depends on it. ~700 lines of pure movement, zero behaviour change, zero recruiter value, maximum conflict surface, during the only week that matters. Refactor it after the demo, when the file's shape is known to be stable | **700** |
| `ranking.py` extraction | Move `rank_candidates` out of `graph.py` | **REMOVE** | `graph.py` is 512 lines. That is not a problem. Splitting it is filing, not engineering | **150** |
| `evidence_nodes` table | New append-only table + write path + graph reads + provenance columns | **POSTPONE** | See above — the drill-down already renders from `signals_json` + `Evidence`. Every "provenance" column is derivable by join. "Vector-ready" is satisfied without it: signals already carry text + verbatim quote and can be exploded into rows by a batch job later, with **no domain model change**. Building the table now costs a schema reset, a double-write path, and new failure modes on the critical turn path | **200** |
| Observability module + `turn_traces` table + trace columns on 3 tables | ~140 LOC + table + migration | **REMOVE (keep 20 lines)** | Nobody demos a latency table, and there is no production to debug. Cheapest 80%: one structured log line per turn with a request id and `perf_counter` deltas per stage. ~20 lines, no table, no schema change, no columns | **200** |
| Versioned rubric config (`data/rubric_v1.json`, `api/rubric_config.py`) | Move all constants to JSON + loader | **REMOVE** | There is no PM to retune weights and no deploy pipeline to avoid. Worse, it actively damages the pitch: the product's strongest projector moment is *opening `signals.py` and reading the commented rubrics*. A JSON blob is less legible, not more. Replace the whole idea with `RUBRIC_VERSION = "v1"` — one line | **90** |
| Version columns on `claim_scores`/`profiles`/`job_roles` | 8 new columns | **POSTPONE** | "Never overwrite historical scores invisibly" needs a history table to mean anything. There isn't one, and `docker compose down -v` wipes everything between runs anyway. Columns nothing reads are decoration | **40** |
| Claim-scoped consistency (D3) | Rewrite classification, +2 columns, rescope scoring | **POSTPONE** | **Re-read the existing thresholds before accepting the brief's premise.** A MINOR contradiction already costs only −15 with a floor of 20 — the current system does *not* "globally destroy" a score for one forgotten fact. It applies −40 only at ≥50% divergence on a *stable* key, which is precisely the "serious contradiction" the brief agrees should penalise broadly. The gap between built and specified is much smaller than the plan implied, and closing it means editing the one subsystem the headline demo moment depends on, 15 tests, plus re-verifying seeded numbers | **250** |
| New dimension set (D1) | Delete 3 rubrics, rename 1, add 3, re-home signals, retune 8 families, regenerate fixture | **POSTPONE / decide explicitly** | The single largest bug-injection surface in the plan: ~36 of 102 tests, 6 rubrics with tuned gates, 8 taxonomy families, the generated fixture, and a frozen two-owner enum. **A recruiter cannot tell whether a dimension is called `PROCESS` or `operational_depth`.** The genuine value is in two *new* signals (ownership, scenario transfer) — not in deleting three working, tested rubrics to make room. Do not pay a 36-test rewrite for a vocabulary change | **600** |
| Transfer probe (D2) | New probe level **plus** new dimension + rubric + signal type + prompts | **KEEP NOW — but decoupled** | This is the best idea in the plan and it is trapped inside the most expensive one. **A `TRANSFER` probe level does not need a `scenario_transfer` dimension.** Ask "here's a situation you didn't mention — how would you handle it," and the answer produces quantities, process steps and causal chains that score under the *existing* rubrics. A fabricator cannot produce them. Full anti-fabrication value: one enum value, one prompt block, one `PROBE_LEVEL_DIMENSIONS` entry, one fallback question — **zero rubric changes, zero test rewrites** | **300** (of the 600 above) |
| Voice scoring removal (D4) | `VOICE_WEIGHT=0`, drop the blend | **KEEP NOW** | ~10 lines. Removes the only remaining term in the score that a judge or candidate could call presentation-based. Cheap, principled, and it makes the anti-bias claim airtight rather than nearly airtight. 17 test lines mention voice; expect a handful to adjust | — |
| Stride: burst debounce | Phase 7 | **KEEP NOW** | The one Stride pattern with real demo risk attached: a candidate typing "35 agents" then "across 4 pods" as two messages currently burns two questions and desyncs the interview. ~40 lines of insurance on the live demo path | — |
| Stride: stale-question, PII scrub, host-scoped bearer | Phases 7–8 | **POSTPONE** | Stale-question needs a new field on the frozen `InboundMessage`; PII scrubbing matters when answers contain Aadhaar/PAN, which BPO competence answers rarely do; the bearer question is a *verification*, not a build | 80 |
| Delete dead `merge_dimension_scores` | Phase 9 | **KEEP NOW** | Confirmed zero callers. Deleting 25 lines is the cheapest win available | −25 |
| `DimensionScores` alias + shared JSON codec | Phase 2 | **KEEP NOW** | The only two items from the original audit that pay for themselves immediately: names one type once, and collapses three near-duplicate `_load_dimensions` implementations into one. Net code *reduction* | −40 |

**Estimated total avoided: ~2,500 lines of new/changed code.**
**Remaining MVP work: ~180 lines added, ~65 deleted.**

---

## What I got wrong in the original plan

Stated plainly, since the same blind spots will recur:

1. **I optimised module shape over recruiter outcomes.** Three of eleven new
   files (`planner.py`, `orchestration/*`, `ranking.py`) are pure code movement.
   None changes a single number a recruiter sees.
2. **I proposed `api/contracts/` to satisfy a brief bullet the repo already
   satisfied.** "Avoid untyped dicts at module boundaries" was ~95% true
   already; I planned a package to close the last 5%, which was one annotation.
3. **I never checked whether the drill-down already worked before designing a
   table for it.** It does. Reading the fixture first would have deleted the
   plan's largest item on day one.
4. **I accepted the brief's consistency premise without re-reading the
   thresholds.** MINOR is −15, not catastrophic. I designed a scoping system
   for a problem the existing tuning already mostly avoids.
5. **I bundled the best idea with the worst one.** Transfer probing is high
   value and nearly free; the dimension re-map is low value and expensive. I
   welded them together as D1+D2 and nearly lost the good one to the cost of
   the bad one.

---

## MVP Plan — build now

Ordered. Every step ends with `pytest -q` green. Total ≈ 180 lines added.

| # | Change | Files | ~LOC | Why it earns its place |
|---|---|---|---|---|
| 1 | `DimensionScores` alias + one shared JSON codec; fix `dict[Dimension, "object"]`; delete dead `merge_dimension_scores` | `signals.py`, `orchestrator.py`, `graph.py`, `evidence.py`, `scoring.py` | **−65** | Net code reduction; removes a duplicate-maintenance trap before anything else is built on it |
| 2 | **`TRANSFER` probe level** — enum value, `PROBE_LEVEL_DIMENSIONS` entry, prompt block, fallback question, policy rule (never an opening probe; only on claims with existing evidence) | `schemas.py`, `signals.py`, `question.py`, `generate_question.txt`, `orchestrator.plan_next` | **+50** | The strongest anti-fabrication signal available for the A2 problem, at ~5% of the cost of the dimension re-map. Scores under existing rubrics |
| 3 | **`VOICE_WEIGHT=0` default**, remove the effort blend from the claim score path (keep measuring duration/words as evidence metadata) | `config.py`, `scoring.py`, `voice.py` | **+10** | Closes the last presentation-adjacent term in the score |
| 4 | **Burst debounce** on inbound WhatsApp: coalesce messages from one number within ~1s, newline-joined, oldest timestamp wins | `routers/whatsapp.py` | **+40** | Direct demo-failure insurance on the live path |
| 5 | **Evidence list surfaced in the graph** — expose the already-stored signal items (type, text, quote) per claim from `signals_json`, so drill-down shows individual evidence items, not only dimension `basis` strings | `graph.py`, `schemas.py` (one optional field) | **+40** | Delivers the recruiter-facing half of `evidence_nodes` with no table, no migration, no write path |
| 6 | **One structured log line per turn** — request id + per-stage `perf_counter` deltas (stt, extract, consistency, scoring, question, send, total) | `orchestrator.py`, `llm.py` | **+20** | 80% of the observability value at 15% of its cost |
| 7 | `RUBRIC_VERSION = "v1"` constant in `signals.py`, included in the graph response | `signals.py`, `graph.py` | **+5** | Attributability without a config system |
| 8 | Re-run `seed.py --reset`, regenerate fixture, re-verify the ranking inversion and the two-role re-rank | `seed.py`, `scripts/dump_fixture.py` | — | The demo's two headline moments must be re-read, not assumed |

**Acceptance test after step 8 is unchanged and must still pass end to end:**
resume → claims → adaptive questions (now including a transfer probe) → voice
answer → evidence → consistency → deterministic scoring → graph → ranking →
drill-down, with every number reproducible from stored rows.

---

## Phase 2 Later — after recruiter feedback

| Item | Trigger that would justify it |
|---|---|
| Orchestrator / planner / repo extraction | A third developer joins, or the file crosses ~1,200 lines |
| `evidence_nodes` table | A real query needs it: cross-candidate evidence search, or the embedding work actually starts |
| Claim-scoped consistency (D3) | A recruiter says "one wrong number shouldn't have sunk this candidate" — with a real candidate to point at |
| New dimension set (D1) | A recruiter cannot interpret the current six, or the dashboard is about to be built (rename before it, never after) |
| Versioned rubric config | A non-engineer needs to retune weights, or two rubric versions must be compared on the same candidate |
| Stale-question protection, PII scrubbing, host-scoped bearer | Real candidate traffic, outside a controlled demo |
| Score history table | Anyone asks "what was this candidate's score last week" |
| `api/contracts/` package | A second service consumes these types — i.e. never, while this is a modular monolith |

---

## Do Not Build

| Item | Why |
|---|---|
| Embeddings, vector DB, `embedding_id` placeholder columns | Explicitly excluded by the brief; no consumer. The existing signal text + quotes are already embeddable later with zero domain change |
| `turn_traces` table | Logs answer every question it would, with no schema to maintain |
| Version columns nothing reads | Decoration until a history consumer exists |
| Microservices, provider ABCs, repository pattern over the `select()` helpers | Abstractions with one implementation and one caller |
| A second vocabulary of contract types wrapping existing schemas | Two names for one concept is a permanent tax |

---

## Risk register for the *revised* plan

| Risk | Mitigation |
|---|---|
| Adding a `TRANSFER` level competes for a 12-question budget across 3 claims | Rule: never an opening probe, only on claims with existing evidence. Re-check `test_policy.py`'s budget assertions — 12 tests, expect 2–3 to adjust |
| `VOICE_WEIGHT=0` shifts voice-answered claim scores | 17 test lines mention voice; re-run seed and fixture in the same commit |
| Debounce introduces a race on the webhook path | Coalesce per phone number with a lock, re-check the generation inside it, and keep the existing `provider_message_id` de-dup as the durable backstop |
| Exposing evidence items adds a field to frozen `schemas.py` | It is *additive and optional* — the lightest possible category of change to that file, but still needs the two owners' nod |
| Skipping D1 means renaming later costs more | True, and accepted: "later" is days, not years. The trigger to do it is the dashboard, not the demo |

---

## One-line summary

Keep the transfer probe, kill the voice blend, coalesce bursty messages, surface
the evidence that is already stored, and **do not refactor a working system in
the last week before a demo.**
