# Developer A — Phase 1 Execution Contract

Paste this file into Developer A's session. Read it before making any code
change. It is subordinate to `EXECUTION_STANDARD.md`, `ARCHITECTURE_LOCK_v1.md`
and `PHASE_1_TASKS.md` — where they conflict, they win.

Developer A owns the **intelligence path**: how a claim is routed, what gets
asked, and how an answer becomes evidence. Developer B owns everything the
recruiter reads. See `DEVELOPER_B_CONTRACT.md`.

---

## Precondition — verify before starting

    git log --oneline -5
    OPENAI_API_KEY="" DATABASE_URL="sqlite+aiosqlite:///:memory:" pytest -q

You must see **126 passed** and P1-00 through P1-04 in the log.

## Ownership

**You own — edit freely:**

| File | Module |
|---|---|
| `api/taxonomy.py` | Routing |
| `api/ingest/parse.py`, `api/engine/extract.py` | Claim Engine |
| `api/engine/orchestrator.py` | Verification Planner |
| `api/engine/question.py` | Question Engine |
| `api/engine/signals.py` | Signal / Rubric |
| `api/engine/evidence.py`, `consistency.py`, `scoring.py` | Evidence, Consistency, Scoring |
| `api/engine/voice.py`, `api/stt.py`, `api/channels/` | Response / Voice |
| `api/prompts/`, `api/llm.py` | LLM path |
| `api/config.py`, `.env.example` | Flags |
| `api/routers/candidates.py`, `sessions.py`, `whatsapp.py`, `dev.py` | Candidate-facing + dev tooling |
| `tests/test_policy.py`, `tests/test_transfer.py`, `tests/test_taxonomy.py` | Your tests |

**You do not own — do not edit:**

`api/models.py` · `api/ids.py` · `api/routers/recruiter.py` ·
`api/engine/graph.py` · `scripts/` · `seed.py` · `fixtures/` ·
`tests/test_pipeline.py`

If a task appears to need one of these: **stop, state the dependency, wait.**

**Shared, by announcement only:** `tests/conftest.py`. Its BPO vocabulary is
load-bearing — `detect_family()` scores by keyword, and a resume reading
"support / escalation / Zendesk" classifies as `customer_support`, which has no
`team_handling` or `aht_control` claim type, silently collapsing every weight
assertion in the suite. **P1-06 rewrites exactly that scoring function**, so
this is the single most likely place your work breaks Developer B's tests.
Announce before touching it, and re-run the full suite, not just your files.

**`api/schemas.py` — frozen, and Phase 1 needs zero edits to it.** P1-00
pre-landed `ProbeLevel.TRANSFER` and `CandidateGraph.routing_confidence`. **If a
task seems to require editing it, the task is wrong — stop and raise it.**

`tests/test_taxonomy.py` is a **new file you create in P1-06.** Family-detection
tests belong there, not in `test_pipeline.py` — that file is Developer B's, and
it already carries 13 family references.

## Already complete — do not reopen

P1-00 · P1-01 · P1-02 · P1-03 · P1-04. Baseline **126 tests passing**.

Do not refactor, improve, move or rename this code. Architecture is frozen.

## Your tasks, in this order

| # | Task | Files | Depends on |
|---|---|---|---|
| 1 | **P1-06** `detect_family` rewrite — IDF weighting, margin-based confidence, `FamilyMatch` | `api/taxonomy.py`, `tests/test_taxonomy.py` (new) | — |
| 2 | **P1-07** requisition precedence — close the LLM family-override deviation | `api/engine/extract.py` | P1-06 |
| 3 | **P1-08a** `GET /api/dev/detect` | `api/routers/dev.py` | P1-06 |

**P1-06 is the critical path of the whole phase.** Developer B's P1-08b
(`routing_confidence` on the graph) and P1-05 (fixture regeneration) are both
blocked on it. Land it first, and tell B the moment `FamilyMatch` is stable.

**What you owe Developer B — the one cross-stream contract:**

    FamilyMatch  (NamedTuple in api/taxonomy.py)

That is the entire interface between the two streams. B reads it in `graph.py`
and never calls into your modules for anything else. Do not change its shape
after B has started P1-08b without telling them.

**P1-07 is a behaviour change, not an addition.** `extract.py:196` currently
lets the LLM override the detected family. Closing that means an explicit
requisition family wins over both detection and the model. Expect existing
tests to move; the fixture will need regenerating afterwards, which is B's
P1-05 and must run **after** both P1-06 and P1-07 land.

**Out of scope for Phase 1**, however tempting: the Response/Voice, Evidence and
Consistency engines. You own those files, but they have no Phase 1 task. Editing
them now is Phase 2 work.

## Per-task output — produce before coding

The seven-section form P1-00 shipped under:

1. **Task** · 2. **Current State** · 3. **Files To Change** ·
4. **Implementation Steps** · 5. **Tests** · 6. **Verification Commands** ·
7. **Risks**

Coding begins after approval, not before.

Verification commands must be executable and must actually test the claim. A
command that asserts something the architecture does not do is a wrong command,
not a failing feature — see the P1-00 OpenAPI note in `PHASE_1_TASKS.md`.

## Recording what shipped — required, and it binds B too

Developer B cannot read your session. The **Shipped ledger** in
`PHASE_1_TASKS.md` is the only place either of you learns what the other
actually changed, so a task is not done until it has a row there.

**Add the ledger row in the same commit as the code.** A row written later is a
row written from memory.

Every row carries **Commit · Task · Owner · Tests (`before → after`, actual
counts) · Measured effect**, where the measured effect is **a number, not an
adjective**.

**Measure before you change, not after.** You cannot state an effect without a
baseline, and a baseline taken after the edit is not a baseline. This is how
P1-06 discovered that the IDF weighting it was specified to add would move
nothing, and that substring matching was the real defect — `hr` inside
*through*, `api` inside *rapid*. Neither fact was visible without measuring
first, and both would have been shipped as a confident guess.

Write the golden set, the fixture or the assertion **before** the code it
judges. A test authored afterwards describes the implementation instead of
testing it.

Wrong: *"routing is better"* · *"cleaner extraction"*
Right: *"90.7% → 98.1% on 60 labelled resumes"* · *"0 family changes, 0.0000 drift"*

**Log unplanned work too**, marked *(unplanned)*. The `product` family is the
cautionary case: correct work, taxonomy-only, and completely invisible to the
plan until someone wrote it down.

**A regression test must be verified to fail without the fix.** Run it against
the pre-change file and record that it failed — as P1-07's three tests were.

### Deferrals must be measured, not assumed

If you decide **not** to fix something, the reason has to survive a
measurement. `y → ies` was deferred as "changes routing for six families";
measured, it was **0 family changes and 0.0000 confidence drift across 64
golden entries**, so the deferral was cautious rather than correct. A deferral
is a claim about impact, and a claim about impact needs a number.

## Two sessions, one stream — the live hazard

Developer A's work has been running in **more than one Claude session at once**.
The A/B split does not protect against that: both sessions own the same files.
It has already cost real work — a throwaway measurement script mutated
`data/claim_taxonomy.json` while the `product` family was still uncommitted,
crashed before restoring, and destroyed it.

If you are one of several A sessions:

- **Commit before you measure.** Anything uncommitted is one crashed script
  away from gone.
- **Never mutate a tracked file from a scratch script.** Copy the repo file
  into the scratchpad and mutate that, or monkeypatch in memory. If you must,
  back it up on disk and restore in `try/finally`.
- **Announce which task you hold** before starting, and re-run `git log` and
  the full suite when you resume — the tree may have moved under you. P1-06
  landed mid-task for the other session, which is why `test_taxonomy.py`
  changed beneath them.
- **Two sessions will reach different judgments on the same call.** When you
  find one, resolve it with a measurement, not seniority.

## Branches and merging

One task per branch: `p1-06-detect-family`, `p1-07-requisition-precedence`,
`p1-08a-dev-detect`. Never stack unfinished tasks in one branch.

Mergeable only when: acceptance criteria pass · full suite green · no
owned-file violations · no architecture change · no TODO placeholders.

## Forbidden

New architecture · new modules (`engine/planner.py` in particular — that is why
`select_transfer()` lives in `orchestrator.py`) · extracted services · moved or
renamed files · repositories · dependency injection · abstractions for future
phases · Phase 2 work · optimisation beyond scope.

Also forbidden by product rule, everywhere and always:

- **Never score presentation** — accent, fluency, grammar, vocabulary, polish,
  speaking speed, perceived confidence. These are bias vectors and their absence
  is a product decision, not an oversight.
- **The model never produces a score.** It returns countable signals and quotes
  them; Python turns counts into numbers. If you find yourself parsing a rating,
  confidence or percentage out of a model response, stop.
- **Quotes are verified in Python, never requested in a prompt.**
  `evidence.enforce_verbatim()` drops any signal whose quote is not literally in
  the answer.
- **Every LLM call has a fallback.** `complete_json(..., fallback=...)` always.
- **Never add per-family examples to a prompt.** Neutralise instead. Per-family
  examples re-introduce cohort bias at config level and break the onboarding
  criterion: cohort #101 must cost one taxonomy entry and zero Python edits.

## Done when

P1-06, P1-07, P1-08a merged, with:

- suite green after every merge
- `FamilyMatch` published and stable for Developer B
- zero edits to `api/schemas.py`
- zero owned-file violations
- zero merge conflicts with Developer B
