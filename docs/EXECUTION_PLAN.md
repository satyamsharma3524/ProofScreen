# ProofScreen — Execution Plan (revised after pre-implementation review)

Supersedes the first cut of this file. Every task was re-examined against one
question: **does it help prove that a candidate can memorise a resume but cannot
fake real experience when forced to transfer knowledge into an unfamiliar
situation?**

Result: **12 tasks → 6.** Net code drops from ~+215/−33 to **~+80**, and the
frozen file is touched for exactly **one line**.

---

## The finding that nearly sank the demo

`seed.py:277-288` serves answers from a per-claim-type pool:

```python
answer = pool[min(cursor, len(pool) - 1)]     # runs out -> repeats the LAST answer
```

Each pool holds exactly five answers — one per existing probe level. **Add a
sixth probe level and every seeded candidate answers the transfer question with
their canned OUTCOME answer.**

The consequence is worse than a cosmetic bug. Priya's fifth answer is rich, so
she would score *well* on a transfer probe **without transferring anything**.
Rohit's is thin, so he would score badly. The contrast a judge sees would look
exactly like proof of the thesis while being an artefact of answer repetition.
Open the drill-down and the transfer question is answered with a non-sequitur
about attrition.

**Authoring genuine transfer answers is therefore not a footnote inside
"re-seed" — it is the task that proves the product claim.** It is now PS-004,
and it is must-ship.

## Two things that got smaller once checked

- `api/prompts/generate_question.txt` is **fully generic** — it interpolates
  `$probe_level`, `$probe_level_brief` and `$family_label`. A new probe level
  needs **no prompt-file edit**, only two dictionary entries. PS-002 shrank from
  two files to one.
- Because `family_label` already reaches the model, the separate
  "domain-specific scenarios" task was redundant with what the prompt already
  does. Cut; only the offline fallback text needed the domain flavour, which is
  now three lines inside PS-002.

---

## Rulings on every original task

| Task | Necessary? | Smaller version | Safer version | Reuse? | Avoid schema change? | Avoid frozen file? | P(breaks behaviour) | **Ruling** |
|---|---|---|---|---|---|---|---|---|
| PS-001 schemas (3 additions) | Only the enum | **Yes — 1 line, not 25** | Additive only | — | Enum: no. Other 2 fields: yes, by cutting them | Enum unavoidable (`ProbeLevel` lives there) | ~2% (nothing enumerates `ProbeLevel`) | **MUST SHIP (reduced to 1 line)** |
| PS-002 transfer wording | Yes — `PROBE_BRIEFS[...]` and `FALLBACK_QUESTIONS[...]` are bare dict lookups; without it TRANSFER raises `KeyError` in fixture mode | Yes — 2 dict entries, no prompt file | Ships inert before PS-003 | Existing brief/fallback pattern | Yes | Yes | ~1% | **MUST SHIP** |
| PS-003 activation + stall exemption | **Yes — this is the thesis.** Without the stall exemption the fabricator never gets the probe (`orchestrator.py:112-122`; the evasive candidate gets 9 questions, not 12) | Not meaningfully | **Yes — add a `TRANSFER_PROBE` env flag** so it can be disabled on stage without a git revert | Follows the existing `ADAPTIVE_PROBING` flag pattern | Yes | Yes | ~35% — it moves policy tests by design | **MUST SHIP** |
| PS-004 domain scenarios | No — `family_label` already reaches the prompt | Folds into PS-002 as 3 lines of fallback text | — | The prompt already does it | Yes | Yes | ~1% | **CUT (merged)** |
| **NEW — transfer answers in seed** | **Yes — without it the demo cannot show the contrast, and appears to prove the thesis while proving nothing** | No | Prose only, no code | Existing pool structure | Yes | Yes | ~5% (seeded numbers shift, which is the point) | **MUST SHIP** |
| PS-005 voice weight | Not for the thesis; protects a stated non-negotiable | **Yes — 1 config line, no scoring code**: at weight 0 the blend reduces to `content * 1.0` | Reversible by env var | — | Yes | Yes | ~5% | **NICE TO HAVE (ship — costs one line)** |
| PS-006 dead code removal | No | — | — | — | Yes | Yes | ~0% | **CUT — postpone** (cleanup, zero demo value) |
| PS-007 re-seed + verify | Yes — the gate | No | No | Existing scripts | Yes | Yes | n/a (it *detects* breakage) | **MUST SHIP** |
| PS-008 "why ranked" line | No — for *this* thesis. It serves ranking explainability, which the drill-down already demonstrates | Dashboard could compute it from existing graph data | — | `CandidateGraph` already carries the inputs | **Only by cutting it** | Only by cutting it | ~5% | **NICE TO HAVE** |
| PS-009 verification flags | No — it rolls up statements the graph already makes verbatim (`"capped at 55: no quantity given"`, `signal_count`, `contradiction_count`) | — | — | **Yes — already in the gate messages** | Only by cutting it | Only by cutting it | ~5% | **CUT** |
| PS-010 burst debounce | Only if a human types live on stage | — | — | Stride pattern | Yes | Yes | ~10% (new async path) | **NICE TO HAVE (conditional)** |
| PS-011 turn log line | No | — | — | — | Yes | Yes | ~2% | **CUT** |
| PS-012 dry run | Yes | No | No | — | Yes | Yes | n/a | **MUST SHIP** |

---

## The smallest plan that proves the thesis

Six tasks, ~80 lines, one engineering day.

# PS-001

**Name:** Add `ProbeLevel.TRANSFER`

**Goal:** Make a transfer probe a first-class, selectable, testable, *visible*
level — so the recruiter can see "this was a transfer question" in the
drill-down, and so it can be targeted deliberately rather than smuggled into a
DECISION probe.

**Files:** `api/schemas.py` *(one line)*

**Dependencies:** none · **LOC:** +1 · **Risk:** Low *(process-Medium: frozen, two owners)*

**Considered and rejected:** wording an existing level as a transfer question to
avoid the frozen file. It saves one line and costs everything else — no
targeting, no stall exemption, no test, and nothing tells the recruiter which
question was the transfer.

**Acceptance:** all 102 tests pass **unchanged**; `PROBE_ORDER` untouched, so no
selection behaviour changes yet.
**Test:** `pytest -q` · **Rollback:** revert; no consumer exists.

# PS-002

**Name:** TRANSFER brief and offline fallback question

**Goal:** Make the transfer question answerable in both live and fixture mode —
fixture mode is what runs if the model dies on stage.

**Files:** `api/engine/question.py` *(two dict entries; **no prompt file change** —
the template already interpolates `$probe_level_brief` and `$family_label`)*

**Dependencies:** PS-001 · **LOC:** +20 · **Risk:** Low

Per `TRANSFER_DESIGN_AUDIT.md`: the fallback is a `string.Template` with slots
filled from the candidate's **own** claims (`$their_method`, `$other_problem`),
not a fixed question — so the offline path is domain-agnostic too. The brief
instructs: pose a problem they have **not** solved, reusing their own reasoning
steps; never ask for numbers about a hypothetical.

**Acceptance:** `fallback_question(TRANSFER)` poses a situation the candidate has
**not** described; `generate_question(..., TRANSFER)` works with no API key.
**Test:** `test_transfer_question_poses_an_unseen_situation` · `pytest -q`
**Rollback:** revert; inert until PS-003.

# PS-003

**Name:** Activate TRANSFER and exempt stalled claims

**Goal:** **The thesis.** Ask the question a memorised resume cannot answer — and
ask it of the people who need asking. Today a stalling claim is dropped, which
is precisely why the evasive candidate gets a *shorter* interview.

**Files:** `api/engine/signals.py` *(B reviews this hunk)*, `api/engine/orchestrator.py`,
`api/config.py`, `tests/test_policy.py`

**Dependencies:** PS-001, PS-002 · **LOC:** +38/−5 · **Risk:** **Medium**

- `PROBE_ORDER` + `PROBE_LEVEL_DIMENSIONS[TRANSFER] = (CAUSAL_REASONING, PROCESS)`
- `exhausted` → `saturated or (stalled and transfer_used) or not levels_left`
- TRANSFER never opens a claim
- **`TRANSFER_PROBE=true|false` env flag** — an on-stage off switch that needs no
  git revert, matching the existing `ADAPTIVE_PROBING` pattern
- **`select_transfer(claim, evidence, other_claims) -> TransferSpec`, with no
  `job_family` parameter** so family branching is unrepresentable, not merely
  discouraged. Operators T1 (their method → their *other* claim's problem) and
  T3 (invert the outcome); see `TRANSFER_DESIGN_AUDIT.md`

**Acceptance:** a stalled claim gets exactly one transfer probe before being
dropped; a saturated claim gets none; never an opening probe; `plan_next` stays
pure and deterministic. **Family-invariance test:** identical evidence tagged
`bpo_operations` and `software_engineering` must select a byte-identical
operator and target — family may change wording, never the question.
**Test:** `pytest tests/test_policy.py -q` — 2–3 assertions will move; **review
each by hand, never edit one just to make it green** · full `pytest -q`
**Rollback:** `TRANSFER_PROBE=false`, or revert.

# PS-004

**Name:** Cohort-neutral demo vehicle *(replaces "author transfer answers in seed")*

**Goal:** Demonstrate the transfer contrast **without committing any job-family
data to the repo.** Seeded BPO personas anchor the product to one cohort before
its cohort-agnostic identity is settled, so no new seed prose is authored.

**Files:** `api/routers/dev.py` *(remove the BPO `PLACEHOLDER_ANSWERS`
fallback)*, demo script *(uncommitted)*

**Dependencies:** PS-003 · **LOC:** +5 / −20 · **Risk:** Low

`SimulateIn` already accepts `resume_text` **and** `answers` from the caller, so
`/api/dev/simulate` is a cohort-agnostic demo vehicle by construction: supply
any resume and any answers at request time. `PLACEHOLDER_ANSWERS` (six hardcoded
call-centre answers) is the only thing making it BPO-shaped — remove it and
require caller-supplied answers.

The demo then runs two contrasting candidates **in whatever cohort the audience
cares about**, authored in a scratch script that is never committed. Better
demo, zero repo-resident domain data, and it removes a Tier-1 finding from
`PLATFORM_ARCHITECTURE_REVIEW.md` for free.

**Acceptance:** `/api/dev/simulate` with caller-supplied answers produces a full
graph including a transfer probe; no BPO strings remain in `api/`.
**Test:** existing simulate tests, updated to pass answers explicitly · `pytest -q`
**Rollback:** revert.

**Open decision — `seed.py` and `fixtures/sample_graph.json` (see chat):**
nothing imports `seed.py`, so deleting it breaks **zero** tests; deleting the
committed fixture breaks **three** (`test_pipeline.py:527,534,551`). Default
taken: leave both in place, quarantined and unextended, until the cohort-neutral
product definition is settled.

Write deliberately: the strong candidates answer an unseen scenario with
sequenced actions, a named trade-off and a way of knowing it worked. The
fabricator answers with fluent generalities that produce **no countable
signals** — which is what the existing rubrics already punish, with no new
scoring code.

**Acceptance:** transfer answers are visibly *responses to the scenario*, not
restatements of a claim; the fabricator's produces ≈0 signals; the contrast is
legible in the drill-down side by side.
**Test:** `python seed.py --reset` then read all three transfer Q&A pairs in the
graph · `pytest -q`
**Rollback:** revert `seed.py`, re-seed.

# PS-005

**Name:** Re-seed, regenerate fixture, verify all three demo moments

**Goal:** The gate. Nothing ships past a failure here.

**Files:** `fixtures/sample_graph.json` *(regenerated, never hand-edited)*

**Dependencies:** PS-004 · **LOC:** 0 · **Risk:** Low *(blocking gate)*

**Acceptance:** ① the resume/competence inversion still holds ② two role
profiles still produce two different orders ③ **new** — the transfer contrast is
visible. All three candidates' numbers go in the PR description so later drift
shows in git history.
**Test:** `pytest tests/test_pipeline.py -q` · both `role_id` rankings via curl · `pytest -q`
**Rollback:** regenerate from the previous commit.

# PS-006

**Name:** Acceptance dry run

**Goal:** Prove it end to end before demo day, twice.

**Files:** none (may add one integration test) · **Dependencies:** PS-005 ·
**LOC:** +30 (test) · **Risk:** Low

**Acceptance:** resume → claims → adaptive questions **including a transfer
probe on the fabricator's stalled claim** → evidence → scoring → graph →
ranking → drill-down. Then, with only API responses on screen, answer aloud:
*"why is this candidate above that one?"* — and *"what did the transfer question
reveal that the resume did not?"*

---

## Dependency graph, critical path, parallelism

```
PS-001 ──▶ PS-002 ──▶ PS-003 ──▶ PS-004 ──▶ PS-005 (gate) ──▶ PS-006
                                    ▲
   (optional, any time) voice-weight ┘   ── independent: debounce, why-ranked
```

**Critical path is the whole plan** — six tasks, strictly sequential, ~6 hours.
That is the cost of cutting everything that was parallelisable-but-optional.

**Genuine parallelism** is now limited to the optional items: B can write the
draft transfer answers (PS-004 prose) while A builds PS-002/PS-003, so the
authoring is ready the moment activation lands. That is the one overlap worth
scheduling.

## Day 1

| Slot | Work |
|---|---|
| 09:00–09:30 | PS-001 together (one line, both owners) |
| 09:30–10:30 | A: PS-002 · B: **draft transfer answers in parallel** |
| 10:30–12:30 | A: PS-003 (+ env flag); B reviews the `signals.py` hunk |
| 13:30–14:30 | B: PS-004 (land the answers against the real policy) |
| 14:30–15:30 | B: PS-005 — the gate. Read all three candidates' numbers aloud |
| 15:30–EOD | PS-006 dry run · then the one-line voice-weight change if green |

**Stop rule — PS-003 and PS-004 are atomic.** Landing the probe without the
answers is *worse than not starting*: the seed's pool repeats its last answer,
so every candidate would answer the transfer question with a canned
non-sequitur, and the drill-down would show it. If PS-003 is not green by 12:30,
or PS-004 cannot land the same day, set `TRANSFER_PROBE=false` and demo the
untouched baseline — the existing evidence graph is already a good demo.

## Day 2 — optional only

Nothing here is required. In value order: "why ranked" line (~25 LOC) →
burst debounce, *only if a human types live on stage* (~40) → dead-code removal
(~−26). **If Day 1 slipped at all, Day 2 is rehearsal, not code.**

---

## What was cut, and the trigger to reinstate

| Cut | Trigger |
|---|---|
| Verification flags roll-up | A recruiter says the gate messages are too buried to read |
| Turn log line | Debugging a real failure, not a demo |
| Dead-code removal, codec dedup | Any day after the demo |
| Domain-specific scenario injection | The model writes an off-domain transfer question in practice |
| Everything in `IMPLEMENTATION_PLAN.md` | See `PLAN_REVIEW.md` for each item's trigger |

---

## Totals

| | Before review | After review |
|---|---|---|
| Tasks | 12 | **6** |
| Net LOC | +215 / −33 | **≈ +84 / −5** |
| Frozen-file lines | 25 | **1** |
| Medium-risk tasks | 2 | **1** |
| Schema fields added | 3 + a new model | **0** (one enum value) |
