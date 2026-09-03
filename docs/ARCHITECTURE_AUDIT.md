# ProofScreen — Architecture Audit (Phases 1–4)

Scope: audit only. No production code was changed. Verified empirically against
the running repo — a throwaway venv was built from `requirements.txt`, both
`api.engine.graph` and `api.engine.orchestrator` were imported directly to
check for real import cycles, and the full suite was run.

**Baseline: 102/102 tests pass.** This is the regression gate for every phase
below and for any future implementation of Phases 5–9.

Phases 5 (complete vertical slice), 6 (recruiter ranking), 7 (embedding
sidecar), 8 (observability + versioning) and 9 (test hardening) are **not**
covered here, per instruction.

---

## Phase 1 — Architecture Audit

### What already matches the target and should not be touched

- **The no-LLM boundary is real, not aspirational.** `engine/signals.py`,
  `engine/scoring.py`, `engine/consistency.py` and `engine/voice.py` import
  only `api.schemas` and `api.taxonomy` — never `api.llm`, never
  `api.models`, never SQLAlchemy. Verified against the full import graph, not
  just the docstrings. `test_scoring_modules_never_import_the_llm` makes this
  structural rather than a promise.
- **The LLM-calling layer is itself clean.** `engine/extract.py`,
  `engine/question.py` and `engine/evidence.py` import `api.llm` and the pure
  scoring modules, but never `api.models` or SQLAlchemy — they have no idea a
  database exists. This is the correct dependency direction (LLM layer ➝ pure
  layer, never reversed) and it already holds throughout the codebase.
- **Persistence is already confined to two files.** Of all `engine/*` modules,
  only `orchestrator.py` and `graph.py` import `api.models`/SQLAlchemy. That's
  a much better starting position than the file sizes suggest.
- **Channel/ingest/stt adapters are boundary-clean.** `channels/*`,
  `ingest/parse.py` depend on nothing but `api.schemas` and `api.config`.

### Coupling findings

**1. `orchestrator.py` (816 lines) carries five distinct responsibilities in
one file with one owner.**
[`api/engine/orchestrator.py`](api/engine/orchestrator.py) currently holds:
   a. the pure policy (`Plan`, `ClaimState`, `plan_next`, lines 87–138,
      313–384) — genuinely side-effect-free already;
   b. a hand-rolled repository layer (`_claims_of`, `_questions_of`,
      `_open_question`, `_qa_rows`, `known_facts`, lines 146–220) — raw
      `select()` calls with no abstraction over them;
   c. JSON codec duplication (`_load_dimensions`/`_dump_dimensions`, lines
      286–305);
   d. lifecycle orchestration (`create_session`, `ask_next`, `submit_answer`,
      `finalize`, `score_pending`, lines 403–763);
   e. evidence-to-ORM mapping (`_persist_evidence`, lines 513–607).

   For a two-dev, hourly-push hackathon repo this is the single highest-risk
   file: a change to *how facts are stored* and a change to *which question
   gets asked next* land in the same file, by the same owner, with no
   internal boundary forcing them apart.

**2. The DimensionScore JSON codec is duplicated, not shared.**
`orchestrator._load_dimensions`/`_dump_dimensions`
([orchestrator.py:286–305](api/engine/orchestrator.py#L286)) and
`graph._load_dimensions` ([graph.py:70–81](api/engine/graph.py#L70)) are two
independently written functions doing the same job — deserialising
`ClaimScore.dimensions_json` into `dict[Dimension, DimensionScore]` — with
different signatures (one keyed by `Dimension`, one by `str`) and no shared
test that they agree. A rubric change that adds a field to `DimensionScore`
has to be remembered twice.

**3. Deferred/local imports exist with no real cycle behind them.**
`orchestrator.py` imports `graph as graph_engine` **inside** three functions
(`submit_answer` line 701, `score_pending` line 721, `finalize` line 750)
instead of at module scope, and `graph.py` imports
`api.engine.evidence.signals_of` **inside a per-row loop**
([graph.py:268](api/engine/graph.py#L268)) instead of once at the top of the
file. This was verified empirically, not assumed: a throwaway venv imported
`api.engine.graph` and `api.engine.orchestrator` at module scope with no
special ordering and it worked cleanly — neither module actually references
the other by name (`orchestrator` does not appear anywhere in `graph.py`'s
source; `graph` does not appear in `evidence.py`'s source). The deferred
imports are pure legacy caution, not a load-bearing guard — which means
nothing today would stop a *real* cycle from being introduced silently, since
the pattern already looks like "we did this on purpose."

**4. `signals_of()` / fact rehydration is read from two different tables
with no shared invariant.** Consistency's `known_facts` (used to detect
contradictions,
[orchestrator.py:193](api/engine/orchestrator.py#L193)) reads from the
`session_facts` table. The evidence graph's per-claim `facts` list
([graph.py:267–273](api/engine/graph.py#L267)) reads
`Response.signals_json` and pulls `.facts` back out through
`evidence.signals_of()`. Both are *supposed* to represent "facts this
candidate has stated," but they are read from two different persisted
representations of the same underlying `ScoreResult.facts`, and nothing
asserts they stay in agreement as the schema evolves.

**5. `scoring.claim_score()` is called from two different shapes of input,
and the signature itself is the evidence.** Its type is
`Mapping[Dimension, DimensionScore] | Mapping[Dimension, int]`
([scoring.py:114](api/engine/scoring.py#L114)). `evidence.score_response()`
calls it once per **answer**, over the six freshly-scored dimensions
([evidence.py:363](api/engine/evidence.py#L363)). `orchestrator.recompute_claim`
calls it again over the six **claim-level, merged-across-answers** dimensions
([orchestrator.py:630](api/engine/orchestrator.py#L630)). Same function name,
same module, two conceptually different callers ("answer score" vs "claim
score") sharing one union-typed signature. This is exactly the kind of
implicit contract Phase 2 should make explicit.

**6. `evidence._nodes_from()` types its own core input as `dict[Dimension,
"object"]`** ([evidence.py:286–287](api/engine/evidence.py#L286)) — a
deliberately untyped forward reference to `object`, for a value that is in
practice always `dict[Dimension, DimensionScore]`. This is the one place in
the "signal" pipeline where the type contract is dropped rather than
declared.

**7. `merge_dimension_scores()` in `scoring.py` is dead code.**
([scoring.py:79–105](api/engine/scoring.py#L79)) It is explicitly marked
`DEPRECATED` in its own docstring and superseded by
`engine.signals.score_claim()`. A repo-wide grep found zero callers, in
tests or production code. Flagged for removal — not removed here, since
removing working (if unused) code isn't part of this audit's mandate.

**8. `whatsapp.py` bypasses the `Depends(get_db)` convention used
everywhere else.** [`routers/whatsapp.py:30`](api/routers/whatsapp.py#L30)
imports `SessionLocal` directly, while `sessions.py`, `recruiter.py`,
`dev.py` and `candidates.py` all take `db: AsyncSession = Depends(get_db)`.
The reason is legitimate and already documented in `CLAUDE.md` ("the webhook
must 200 fast; real work happens in a `BackgroundTask`," which runs outside
the request's DB session lifecycle) — but it's an *undocumented-in-code*
exception to a convention a new contributor would otherwise "fix" and break.

**9. `schemas.py` freezes three different contracts under one rule.** The
574-line frozen file mixes: (a) the LLM output contract (`ClaimExtraction`,
`GeneratedQuestion`, `AnswerSignals` + its 8 sub-types) — never seen outside
this process; (b) the internal scoring/domain model (`DimensionScore`,
`EvidenceNode`, `ScoreRequest`/`ScoreResult`, `ConsistencyReport`) — also
never seen outside this process; (c) the actual external HTTP/dashboard
contract (`CandidateGraph`, `RankedCandidates`, `SessionOut`, `SimulateOut`,
`HealthOut`, …) — the one thing `/openapi.json` actually promises to the
Next.js app. "Adding an optional field is a conversation" is the right rule
for (c). Applying the same weight to (a)/(b), which no other process ever
sees, is more conservative than the stated reason for the rule requires.

### Verified, not just read

| Check | Result |
|---|---|
| `pytest -q` on a clean venv from `requirements.txt` | **102 passed** |
| `import api.engine.graph; import api.engine.orchestrator` at module scope | succeeds, no cycle |
| `"orchestrator"` string search inside `graph.py` source | absent |
| `"graph"` string search inside `evidence.py` source | absent (evidence.py does not import graph.py at all — only `graph.py` imports `evidence.py`, and only locally) |
| grep for `merge_dimension_scores(` callers repo-wide | zero, outside its own definition |

---

## Phase 2 — Signal Contracts

The "signal" actually flows through five typed stages today. Most of them are
already Pydantic models; the gaps are in what's **shared** between modules,
not in what's declared.

```
Stage A  Raw LLM/heuristic output      AnswerSignals  (untrusted quotes)
             │  enforce_verbatim()
             ▼
Stage B  Verified signals              AnswerSignals  (same type — see below)
             │  signals.score_answer() / signals.score_claim()
             ▼
Stage C  Scored dimensions             dict[Dimension, DimensionScore]
             │  evidence._nodes_from() / scoring.claim_score()
             ▼
Stage D  Persisted evidence            EvidenceNode (per answer×dimension row)
             │                         ClaimScore.dimensions_json (per claim, JSON)
             ▼
Stage E  Aggregate / dashboard         CandidateGraph, DimensionScore (radar), CandidateSummary
```

`ScoreRequest`/`ScoreResult` ([schemas.py:293–321](api/schemas.py#L293)) is
already the right model for a typed contract — it's the actual "the seam"
object the two devs agreed on, it's documented, and both directions (A→B,
B→A) are named types. The other four stages should be brought up to that
same standard.

### Gaps to close

1. **Stage A vs Stage B share one type with no marker.** `AnswerSignals`
   means "whatever the model said, unverified" before
   `evidence.enforce_verbatim()` and "verbatim-checked, safe to score" after
   it — with nothing in the type system distinguishing the two. In practice
   there is exactly one call site today
   ([evidence.py:341–348](api/engine/evidence.py#L341)) and it is
   disciplined about the order (`raw = await complete_json(...)` →
   `sig, dropped = enforce_verbatim(raw, answer)` → only `sig` reaches
   scoring). The risk is entirely about the *next* call site someone adds.
   **Recommendation:** a zero-cost `NewType`, not a new class:
   ```python
   VerifiedSignals = NewType("VerifiedSignals", AnswerSignals)
   ```
   returned by `enforce_verbatim()`, accepted by `signal_rubrics.score_answer`
   / `score_claim`. This costs nothing at runtime (it erases to `AnswerSignals`),
   adds no abstraction, and makes "you must verify before you score" a
   type-checker-enforced fact instead of a convention. Optional, not
   blocking — flagged for Phase 2 implementation, low priority.

2. **Stage C has no named type.** `dict[Dimension, DimensionScore]` is
   passed between `signals.py`, `scoring.py`, `evidence.py`, `orchestrator.py`
   and `graph.py` as a bare dict literal every time, and in one place
   ([evidence.py:286](api/engine/evidence.py#L286)) as `dict[Dimension,
   "object"]` — the type is dropped entirely. **Recommendation:** a single
   type alias,
   ```python
   DimensionScores = dict[Dimension, DimensionScore]
   ```
   declared once (natural home: `engine/signals.py`, which owns
   `DimensionScore`'s rubric logic) and imported everywhere it's currently a
   bare dict. This directly fixes finding #6 from Phase 1 and gives
   `scoring.claim_score`'s union signature (finding #5) a name for each of
   its two real shapes instead of `int` vs `DimensionScore` in the same
   union.

3. **No shared codec for Stage C ⇄ Stage D (JSON).** As found in Phase 1 #2,
   the same serialisation is written twice. **Recommendation:** two
   functions, `dump_dimension_scores(DimensionScores) -> str` and
   `load_dimension_scores(str) -> DimensionScores`, living next to the
   `DimensionScores` alias in `signals.py`, replacing
   `orchestrator._load_dimensions`/`_dump_dimensions` and
   `graph._load_dimensions`. This is a pure extraction — no behaviour change,
   same JSON shape in, same JSON shape out — and is the single highest-value,
   lowest-risk fix in this whole audit, because it turns "two places to
   remember" into "one function to test."

4. **Stage E's two fact sources (Phase 1 #4) don't have a stated contract.**
   Not proposing a schema change here (that would touch `schemas.py` and the
   data model, out of scope for "signal contracts, not a rewrite"). Flagging
   it as something a later phase (8 or 9) should either unify or add an
   explicit test asserting `known_facts()` and the graph's per-claim
   `facts` agree on the same session, so a future change to one doesn't
   silently desync the other.

### What should explicitly NOT change

- `ScoreRequest` / `ScoreResult` — already the right shape, already the
  contract the two devs agreed on. Do not touch.
- `AnswerSignals` and its eight sub-types — the LLM output contract is
  correct and well-documented (`schemas.py:1–30` explains *why* in detail).
  The gap is in how it's *labelled* across a verification boundary, not in
  its fields.
- Nothing about the six-rubric scoring math changes. This phase is about
  naming and de-duplicating existing types, not re-deriving them.

---

## Phase 3 — Module Boundaries

Stating explicitly, as enforceable rules, the boundaries that Phase 1 found
are *already true in practice* but nowhere written down — plus the two
changes needed to make the boundary around persistence match the one that
already exists around scoring.

### Rule 1 — the pure engine layer (already compliant)

`engine/signals.py`, `engine/scoring.py`, `engine/consistency.py`,
`engine/voice.py` may depend only on `api.schemas` and `api.taxonomy`. They
may never import `api.llm`, `api.models`, `sqlalchemy`, or any of
`engine/{extract,question,evidence,orchestrator,graph}`. This is the
boundary `test_scoring_modules_never_import_the_llm` already checks for
`scoring.py`/`signals.py` specifically — worth extending to `consistency.py`
and `voice.py` explicitly in Phase 9, since they currently comply by
accident of not having a reason to import more, not by an assertion.

### Rule 2 — the LLM-calling layer (already compliant)

`engine/extract.py`, `engine/question.py`, `engine/evidence.py` may depend on
`api.llm`, `api.config`, `api.schemas`, `api.taxonomy`, and the pure engine
layer (Rule 1) — never on `api.models` or `sqlalchemy`. Verified true today.
The value of stating it: it's what guarantees `evidence.score_response()`
stays a pure function of `ScoreRequest -> ScoreResult` with no hidden DB
dependency, which is what makes it independently testable and is the actual
reason `ScoreRequest`/`ScoreResult` exist as a seam at all.

### Rule 3 — the persistence layer (needs the two extractions from Phase 2)

Only `engine/orchestrator.py` and `engine/graph.py` may import `api.models`
and `sqlalchemy`. This is *already true* — the fix isn't "move persistence
somewhere new," it's removing the duplication between the two files that
currently makes this boundary leaky in practice even though it's clean on
paper:
- Both get the `DimensionScores` codec from `signals.py` (Phase 2 #3),
  instead of each having its own copy.
- `graph.py` promotes its per-row `from api.engine.evidence import
  signals_of` ([graph.py:268](api/engine/graph.py#L268)) to a top-level
  import — verified safe (Phase 1's empirical check), and it's also a minor
  performance fix since the import currently re-runs on every question/answer
  row in the loop.
- `orchestrator.py`'s three function-local `from api.engine import graph as
  graph_engine` imports are promoted to one top-level import — also verified
  safe. If a real cycle is ever introduced later (e.g. `graph.py` needing
  something orchestrator-only), that should surface immediately as an
  `ImportError` at app startup, which is a far better failure mode than a
  working-by-accident local import silently masking the coupling.

### Rule 4 — HTTP boundary (already compliant, one exception to document)

`routers/*` depend on `engine/orchestrator.py`, `engine/graph.py`,
`api.taxonomy`, `api.schemas`, and `Depends(get_db)` — never directly on
`api.models` for anything beyond simple reads already covered elsewhere.
`routers/whatsapp.py`'s direct `SessionLocal` import (Phase 1 #8) is kept
as-is — it's correct, not a boundary violation — but should get a one-line
comment at the import pointing at the `CLAUDE.md` gotcha ("BackgroundTask
runs outside the request's DB session; this is why we don't use
`Depends(get_db)` here") so it reads as a deliberate exception instead of an
inconsistency the next person "fixes."

### Rule 5 — `schemas.py`'s three contracts (documentation only, no field changes)

Recommend three explicit `# ---- section ----` banner comments already
partially present be made to state ownership/stability directly: **(a) LLM
output contract — internal, no external consumer, changes need only
LLM-side care; (b) internal scoring model — internal, no external consumer;
(c) HTTP contract — this is what `/openapi.json` promises the Next.js app,
this is what "frozen" in CLAUDE.md's rule 2 actually means.** This is
comment-only — zero risk to the frozen file's actual fields — but given
`schemas.py` is explicitly the one file with two owners, this suggestion
should be confirmed with both owners before it's applied, even though it
changes no types.

### What Phase 3 explicitly does not propose

- No new repository/DAO class layer. `orchestrator.py`'s raw `select()`
  helpers are appropriately lightweight for a codebase this size; wrapping
  them in a formal repository pattern would be exactly the kind of
  premature abstraction the project's own conventions warn against.
- No change to `channels/*`, `ingest/*`, `stt.py`, `llm.py` — already
  boundary-clean, nothing to fix.
- No change to the ORM models or table shapes.

---

## Phase 4 — Orchestrator Refactor Plan

**This is a plan only. No code is changed in this phase.**

### Constraint: the exact public surface that must not move

Verified by grepping every caller in `api/` and `tests/` for
`orchestrator.<name>` and for direct imports from
`api.engine.orchestrator`:

| Symbol | Called from |
|---|---|
| `create_session(db, candidate, resume, channel=...)` | `routers/candidates.py`, `routers/dev.py` |
| `ask_next(db, session)` | `routers/sessions.py`, `routers/whatsapp.py`, `routers/dev.py` |
| `submit_answer(db, session, *, ...)` | `routers/whatsapp.py`, `routers/dev.py` |
| `finalize(db, session)` | `routers/dev.py` |
| `session_out(db, session)` | `routers/sessions.py`, `routers/dev.py` |
| `find_session_by_opt_in_code(db, code)` | `routers/whatsapp.py` |
| `find_active_session_by_phone(db, phone)` | `routers/whatsapp.py` |
| `SessionClosed` (exception) | `routers/whatsapp.py`, `routers/dev.py` |
| `ClaimState` (dataclass) | `tests/test_policy.py` — constructed directly |
| `plan_next(states, index)` | `tests/test_policy.py` — called directly |

Every one of these must still resolve as `api.engine.orchestrator.<name>`
after the refactor — `tests/test_policy.py:12` does
`from api.engine.orchestrator import ClaimState, plan_next`, so even a
"pure" extraction has to re-export, not just relocate.

Not called from outside `orchestrator.py` today: `build_claim_states`,
`known_facts`, `recompute_claim`, `score_pending`, `Plan`, `_persist_evidence`,
`_claims_of`, `_questions_of`, `_open_question`, `_qa_rows`,
`_load_dimensions`, `_dump_dimensions`, `_claim_out`. These can move freely as
long as `orchestrator.py`'s own functions that use them still work.

### The split

**New file: `engine/policy.py`** — the pure state machine, extracted
verbatim (no logic changes): `Plan`, `ClaimState`, `plan_next`
([orchestrator.py:87–138, 313–384](api/engine/orchestrator.py#L87)). This is
the single highest-value move in the plan: `plan_next` takes
`list[ClaimState]` and an `int` and returns `Plan | None` — it already has
zero DB and zero LLM dependency, so this extraction promotes it to a fifth
member of the "no-LLM, pure, independently testable" family alongside
`signals.py`/`scoring.py`/`consistency.py`/`voice.py`, which is exactly the
category the project already puts on the projector as its strongest
argument. `orchestrator.py` re-exports `Plan`, `ClaimState`, `plan_next` at
module scope (`from api.engine.policy import Plan, ClaimState, plan_next`)
so `tests/test_policy.py`'s import is untouched.

**New file: `engine/session_repo.py`** — the raw-SQL helpers and the
DB-touching parts of state assembly: `_claims_of`, `_questions_of`,
`_open_question`, `_qa_rows`, `known_facts`, `build_claim_states`
([orchestrator.py:146–283](api/engine/orchestrator.py#L146)). These already
share one property today (they only read; `orchestrator.py` proper is where
writes happen) — separating them makes that property visible and testable
in isolation with an in-memory sqlite session and no LLM/scoring
involvement at all.

**Shared home for the codec (Phase 2 #3): `engine/signals.py`** — 
`dump_dimension_scores`/`load_dimension_scores`, replacing
`orchestrator._load_dimensions`/`_dump_dimensions`
([orchestrator.py:286–305](api/engine/orchestrator.py#L286)) and
`graph._load_dimensions` ([graph.py:70–81](api/engine/graph.py#L70)) with
one implementation each module imports.

**`engine/orchestrator.py` (slimmed, ~450–500 lines)** — keeps everything
with side effects and everything in the public-surface table above:
`create_session`, `ask_next`, `submit_answer`, `finalize`, `score_pending`,
`recompute_claim`, `_persist_evidence`, `_claim_out`, `session_out`,
`find_session_by_opt_in_code`, `find_active_session_by_phone`,
`SessionClosed`. Imports `Plan`/`ClaimState`/`plan_next` from `policy.py` and
`build_claim_states`/`known_facts`/query helpers from `session_repo.py`, and
re-exports the two symbols tests import directly. Promotes its three
function-local `graph` imports to one top-level import (Rule 3, Phase 3 —
verified safe).

### Ordering and verification gates

1. Extract `engine/policy.py` first (zero DB dependency — the safest move).
   Gate: `pytest tests/test_policy.py -q` passes unchanged, plus the full
   suite.
2. Extract `engine/session_repo.py` second (read-only DB helpers). Gate:
   full suite passes; specifically `test_pipeline.py`'s multi-answer /
   re-ranking assertions, since they exercise `build_claim_states` indirectly
   through `ask_next`.
3. Land the shared codec in `signals.py` and repoint both
   `orchestrator.py` and `graph.py` at it. Gate: full suite, plus a manual
   diff-check that `fixtures/sample_graph.json` (generated by
   `scripts/dump_fixture.py`) is byte-identical before/after, since that
   file is asserted against in tests and any drift here would mean the codec
   extraction wasn't actually behaviour-preserving.
4. Promote the three deferred `graph` imports in `orchestrator.py` and the
   one deferred `evidence.signals_of` import in `graph.py` to top-level.
   Gate: `python -c "import api.main"` succeeds (catches any real cycle
   immediately) plus full suite.
5. Re-run `pytest -q` after every step, not just at the end — each step above
   is independently revertible, and the 102-test baseline (1.69s) is cheap
   enough to run after each one.

At every step, `api.engine.orchestrator` continues to be the only import
path routers and tests use — nothing outside `engine/` needs to know the
split happened.

### Explicitly out of scope for this plan

- No change to `create_session`/`ask_next`/`submit_answer`'s signatures or
  behaviour.
- No change to `Claim`/`Question`/`Response`/etc. ORM models.
- No change to the question policy's actual decisions (breadth-first,
  gap-driven depth, adaptive stop) — `plan_next`'s logic moves file, its
  behaviour does not change by one bit.
- Deleting `scoring.merge_dimension_scores` (Phase 1 #7, confirmed dead) —
  flagged, not actioned; removing it is a one-line change but is a
  cross-file, two-owner-adjacent deletion better bundled with Phase 9's test
  hardening pass, where its absence can be asserted rather than assumed.

---

## Summary for planning purposes

| Phase | Deliverable | Risk if skipped |
|---|---|---|
| 1 | This document's 9 findings | None — audit only |
| 2 | `DimensionScores` alias + shared codec + (optional) `VerifiedSignals` marker | Rubric changes keep needing to be remembered in 2–3 places |
| 3 | Five stated boundary rules + 2 import promotions + 1 comment | Boundary stays correct by accident, not by contract |
| 4 | `engine/policy.py` + `engine/session_repo.py` split, orchestrator re-exports | 816-line single-owner file keeps concentrating unrelated changes |

Phases 5–9 (vertical slice, recruiter ranking hardening, embedding sidecar,
observability/versioning, test hardening) are intentionally not planned or
implemented here.
