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

### P1-05a — a non-BPO seed persona (spec from Developer A)

Folded into P1-05; it is not a new task and does not change the order above.

**1. Task.** Add one non-BPO persona to the seed so the demo shows the same
mechanism working in an unrelated job family. Ships with P1-05's single
regeneration.

**2. Current state.** All three personas (`PRIYA`, `ARJUN`, `ROHIT`) are
`bpo_operations`, and `seed.py:259` **hardcodes** `job_family="bpo_operations"`
inside `seed_person()` — so this is a code change, not only data. There is one
job description constant, `JD_BPO` (`seed.py:52`). A persona dict carries
`name · role · phone · email · resume · answers`, where `answers` is keyed by
**claim type**, so a new family needs answers keyed to *its* claim types.

`docs/TRANSFER_DESIGN_AUDIT.md` §6 PS-004 is the standing reason: *"seed
answers must include one non-BPO family. The audit's whole point is undermined
if the only demonstration is a call centre."* A single-family seed cannot
demonstrate that the transfer probe and the six rubrics are cohort-neutral,
which is the product's central claim.

**3. Files to change.** `seed.py` (yours) · `fixtures/sample_graph.json`
(generated) · `tests/test_pipeline.py` (yours) if you assert on the new
persona. **No taxonomy change** — A has already added the `product` family
(9 total), collision-checked, with six product resumes in
`tests/data/routing_golden.json`.

**4. Implementation steps.**
1. Take `job_family` from the persona dict instead of the literal at
   `seed.py:259`, defaulting to `"bpo_operations"` so the three existing
   personas are byte-identical afterwards. Verify that before adding anything.
2. Add `JD_PRODUCT` beside `JD_BPO`, and pass the persona's JD rather than the
   constant.
3. Add one persona with `"job_family": "product"`. Claim types available:
   `outcome_ownership · discovery · launch_delivery · prioritisation ·
   experimentation · stakeholder_alignment`. Fact keys: `activation_pct ·
   retention_pct · adoption_pct · monthly_active_users · launch_count ·
   experiment_count`.
4. Write their answers to carry real signals — a quantity, a process sequence,
   one complete cause→action→outcome chain, a specific incident, a defined
   metric — mirroring how `STRONG_ANSWERS` is built in `tests/conftest.py`.
5. Optionally add a `product` role profile so the re-ranking demo has a second
   lens outside BPO. `claim_weights` **must sum to 100**.

**5. Tests.** The three BPO personas' numbers are unchanged (the strongest
assertion here — it proves step 1 was a no-op for them) · the product persona
routes to `product` and scores on the product weights · claim weights sum to
100 · the resume/competence inversion and the two-lens ranking flip still hold.

**6. Verification commands.**

    python seed.py --reset && python scripts/dump_fixture.py && pytest -q
    python -c "import json;g=json.load(open('fixtures/sample_graph.json'));print({c['job_family'] for c in g['candidates']} if 'candidates' in g else g.keys())"

Record all four candidates' numbers in the PR description, per P1-05.

**7. Risks.**
- **Do not score presentation.** A product persona invites "communicates well".
  Forbidden, everywhere, always.
- Adding `product` to `tests/conftest.py`'s vocabulary would be a **shared-file
  change** — announce it. The BPO terms there are load-bearing for family
  detection.
- `seed.py:259` currently guarantees every seeded candidate is BPO. Anything
  downstream that quietly assumes one family will surface here; that is the
  point of the exercise, but expect it.
- Product's `dimension_weights` cut `TOOL_FAMILIARITY` to a token share, so a
  product persona's score is driven by causal reasoning and metric ownership.
  A persona written like an engineer's will score oddly — that is the weights
  working, not a bug.

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

## Recording what shipped — required, and it binds A too

Developer A cannot read your session. The **Shipped ledger** in
`PHASE_1_TASKS.md` is the only place either of us learns what the other
actually changed, so a task is not done until it has a row there.

**Add the ledger row in the same commit as the code.** A row written later is a
row written from memory.

Every row carries:

| Field | Rule |
|---|---|
| Commit · Task · Owner | — |
| Tests | `before → after`, actual counts |
| Measured effect | **A number, not an adjective** |

**Measure before you change, not after.** You cannot state an effect without a
baseline, and a baseline taken after the edit is not a baseline. This is not
ceremony — it is how P1-06 discovered that the IDF weighting it was specified
to add would have moved nothing, and that substring matching was the real
defect. Neither fact was visible without measuring first.

Wrong: *"improved ranking explanations"* · *"routing is better"*
Right: *"90.7% → 98.1% on 60 labelled resumes"* · *"0 family changes, 0.0000 drift"*

**Log unplanned work too.** If you do something that was not a task — you find
a bug, you fix something adjacent — it gets a row marked *(unplanned)*. Work
that is invisible to the plan is work A will contradict or redo.

**A regression test must be verified to fail without the fix.** Run it against
the pre-change file and record that it failed. A test that passes both ways
records nothing.

### What each of your tasks has to measure

| Task | The number A needs from you |
|---|---|
| **P1-09** | Table created; the reset was announced before it ran; existing row counts after re-seed |
| **P1-10** | An outcome written and read back round-trip; decision ordering preserved (`rejected < shortlisted < interviewed < offered < hired`) |
| **P1-13** | How many candidates get a non-null `why_ranked`, and that it **cites stored evidence** rather than restating the score in words |
| **P1-11** | **M4a with its n**, published whichever direction it points — a negative correlation is a finding, not a failure. State it plainly |
| **P1-12** | Endpoint returns the report; `minimum_n` honoured rather than reporting on thin data |
| **P1-08b** | `routing_confidence` populated, and its distribution across the seeded candidates — if every candidate reads 1.00, the field is decorative |
| **P1-05 / P1-05a** | All four candidates' numbers · the resume/competence inversion still holds · the two-lens ranking flip still holds · **TRANSFER still fires for the fabricator** |

That last one is not optional. `seed.py:288` repeats the last answer once a
pool is exhausted, and that repetition is what makes the fabricator's claims
stall — which is what makes his three TRANSFER probes fire. It is the demo's
best moment and it rests on behaviour that looks like a bug. Measured before
you start: **only Rohit is transfer-probed, three times, every answer scoring
`signals_found=0`.** If your change moves that number, say so before merging.

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
