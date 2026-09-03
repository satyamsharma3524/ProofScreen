# Developer B — Phase 1 Execution Contract

Paste this file into Developer B's session. Read it before making any code
change. It is subordinate to `EXECUTION_STANDARD.md`, `ARCHITECTURE_LOCK_v1.md`
and `PHASE_1_TASKS.md` — where they conflict, they win.

---

## Precondition — verify before starting

    git log --oneline -1
    OPENAI_API_KEY="" DATABASE_URL="sqlite+aiosqlite:///:memory:" pytest -q

You must see **126 passed** and a HEAD that contains P1-00 through P1-04.

If `git show HEAD:api/schemas.py | grep OutcomeDecision` returns nothing, the
Phase 1 baseline has not been merged yet. **Stop.** Do not branch. Do not
recreate the missing schemas yourself — they exist, they are just unmerged.

## Ownership

**You own — edit freely:**

| File | Used by |
|---|---|
| `api/models.py` | P1-09 |
| `api/ids.py` | P1-09 |
| `api/routers/recruiter.py` | P1-10, P1-12 |
| `api/engine/graph.py` | P1-13, P1-08b |
| `scripts/` | P1-11 |
| `seed.py` | P1-05 |
| `fixtures/` | P1-05 |
| `tests/test_pipeline.py` | all |

**You do not own — do not edit:**

`api/engine/orchestrator.py` · `api/engine/question.py` · `api/engine/signals.py`
· `api/engine/extract.py` · `api/taxonomy.py` · `api/config.py` ·
`api/routers/dev.py` · `tests/test_policy.py` · `tests/test_transfer.py` ·
`tests/test_taxonomy.py`

If a task appears to need one of these: **stop, state the dependency, wait.**

**Shared, by announcement only:** `tests/conftest.py` — append-only, never
restructure, tell Developer A before you touch it. Its BPO vocabulary is
load-bearing for family detection; changing it silently collapses weight
assertions across the suite.

**`api/schemas.py` — frozen, and Phase 1 needs zero edits to it.** P1-00
pre-landed `OutcomeDecision`, `OutcomeIn`, `OutcomeOut`, `ValidationCohort`,
`ValidationOut`, `CandidateSummary.why_ranked` and
`CandidateGraph.routing_confidence` precisely so neither developer would have to
open this file. **If a task seems to require editing it, the task is wrong —
stop and raise it.** This file is the tripwire for the whole split.

`api/main.py` also needs no edit: the `recruiter` and `dev` routers are already
registered, so new routes require no shared-file change.

## Already complete — do not reopen

P1-00 · P1-01 · P1-02 · P1-03 · P1-04. Baseline **126 tests passing**.

Do not refactor, improve, move or rename this code. Architecture is frozen.

## Your tasks, in this order

| # | Task | Files | Depends on |
|---|---|---|---|
| 1 | **P1-09** `candidate_outcomes` table | `api/models.py`, `api/ids.py` | — |
| 2 | **P1-10** outcome endpoints | `api/routers/recruiter.py` | P1-09 |
| 3 | **P1-13** `why_ranked` | `api/engine/graph.py` | — |
| 4 | **P1-11** `scripts/validation_report.py` | `scripts/` | P1-09, P1-10 |
| 5 | **P1-12** `GET /api/recruiter/validation` | `api/routers/recruiter.py` | P1-11 |
| 6 | **P1-08b** populate `routing_confidence` | `api/engine/graph.py` | ~~A's P1-06~~ **landed** |
| 7 | **P1-05** fixture regeneration | `seed.py`, `fixtures/`, `tests/test_pipeline.py` | A's P1-06, P1-07 |

**P1-05 goes last on purpose.** Developer A's P1-06 (`detect_family` rewrite)
and P1-07 (requisition precedence) both change what the fixture contains.
Regenerating before they land means regenerating twice.

**P1-08 is split.** Developer A ships `GET /api/dev/detect` in `dev.py`; you
ship the `routing_confidence` field on the graph.

**Your dependency is already satisfied.** `FamilyMatch` landed in P1-06:

    from api.taxonomy import match_family
    match_family(text).confidence      # margin, 0.0-1.0

`build_candidate_graph()` already selects the candidate's `Resume` — see the
`raw_text` it loads around `graph.py:368` — so populating the field needs no new
query, no schema change and no further call into A's modules. `confidence` is a
**margin** `(top1 − top2) / top1`, not a probability: it says how close the call
was, not how likely it is to be right. Present it that way, and note that a
`GENERAL` route always reports `0.0`.

Do not change the shape of `FamilyMatch`. It is the only interface between the
two streams.

## P1-09 requires a coordinated reset

There is no Alembic — `create_all()` at startup. Adding `candidate_outcomes`
means:

    docker compose down -v && docker compose up --build
    docker compose exec api python seed.py

That wipes Developer A's local database too. **Announce before you run it.**

## Per-task output — produce before coding

The seven-section form P1-00 shipped under:

1. **Task** · 2. **Current State** · 3. **Files To Change** ·
4. **Implementation Steps** · 5. **Tests** · 6. **Verification Commands** ·
7. **Risks**

Coding begins after approval, not before.

Verification commands must be executable and must actually test the claim. A
command that asserts something the architecture does not do is a wrong command,
not a failing feature — see the P1-00 OpenAPI note in `PHASE_1_TASKS.md`.

## Branches and merging

One task per branch: `p1-09-candidate-outcomes`, `p1-10-outcome-endpoints`,
`p1-13-why-ranked`, `p1-11-validation-report`, `p1-12-validation-endpoint`,
`p1-08b-routing-confidence`, `p1-05-fixture-regen`.

Never stack unfinished tasks in one branch.

Mergeable only when: acceptance criteria pass · full suite green · no
owned-file violations · no architecture change · no TODO placeholders.

## Forbidden

New architecture · new modules · extracted services · new planners · moved or
renamed files · repositories · dependency injection · abstractions for future
phases · Phase 2 work · optimisation beyond scope.

Also forbidden by product rule, everywhere and always: scoring presentation —
accent, fluency, grammar, vocabulary, polish, speaking speed, perceived
confidence. And: the model never produces a score. If you find yourself parsing
a rating or a percentage out of a model response, stop.

## Done when

P1-09, P1-10, P1-13, P1-11, P1-12, P1-08b, P1-05 all merged, with:

- suite green after every merge
- zero edits to `api/schemas.py`
- zero owned-file violations
- zero merge conflicts with Developer A
