# Minimal-Change Migration — Forensic Planner to Competence Framework

Design only, nothing implemented. Builds on `docs/UNIVERSAL_COMPETENCE_FRAMEWORK.md`
and `docs/COMPETENCE_FRAMEWORK_AUDIT.md` — this document adds the two things
those didn't have: per-dimension **effort estimates**, and a concrete,
buildable **coverage-planner mechanism**. Extraction, graph scoring, and
claim ranking are treated as fixed throughout, per instruction — every
proposal below reuses `api/engine/evidence.py`, `api/engine/signals.py`'s
existing rubric shape, `api/engine/graph.py`, and `api/engine/extract.py`
unmodified.

---

## Per-Dimension: Signals, Gaps, Effort, Scoring Reuse

| Dimension | Existing signals that support it | Missing signals | Effort | Can scoring be reused? |
|---|---|---|---|---|
| **EXECUTION** | `process_steps`, `tools[].usage`, `entities` | None | **None** — cosmetic move rename only (`OPERATING_CONTEXT`→`WALKTHROUGH`) | **Yes, fully** — thin wrapper summing `score_process()` + `score_tool_familiarity()`, both unchanged |
| **PROBLEM_SOLVING** | `incident_markers`, `causal_links` (complete) | None structurally — the gap is *reliability*, not missing data (`FAILURE` sometimes produces a full answer that scores zero `AUTHENTICITY` anyway, per the prior audit) | **Small** — wording iteration on the `ISSUE` move's brief, same shape and same validation loop as this session's earlier `OWNERSHIP`/`ARTIFACT` prompt fixes (a few hours, empirically checked against real answers, no schema touch) | **Yes, fully** — `score_authenticity()` unchanged, optionally blended with `score_causal_reasoning()`'s complete-chain credit |
| **ADAPTABILITY / TRANSFER** | `causal_links`, `process_steps` (from a `PERTURB`-shaped answer) | None | **Trivial** — flip `settings.transfer_probe` back on, rename `PERTURB`→`TRANSFER` in display/logging only (the `ProbeLevel.TRANSFER` name this move maps to **already exists** in the codebase; nothing to rename at that layer) | **Yes, fully** — `MOVE_DIMENSIONS[PERTURB]` already credits exactly `(CAUSAL_REASONING, PROCESS)`, unchanged |
| **JUDGMENT / CHOICE** | `causal_links` only, weakly (a reason, not a weighed alternative) | `decisions` (`choice`, `reason`, `quote`) — **already fully specified** in `api/prompts/v2_extract_signals.txt`, never wired to the live extractor | **Medium** — wiring the already-written field into the live `extract_signals.txt`/`AnswerSignals`, a new `score_judgment()` rubric (same shape as the five existing rubrics — count + target + gate), a new `CHOICE` move brief. **Process cost, not just engineering cost:** `AnswerSignals` lives in `api/schemas.py`, which CLAUDE.md marks as frozen and two-owner ("adding an optional field is a conversation") — the field itself is small, but it isn't a unilateral change | Partially — reasoning credit reuses `score_causal_reasoning()`'s shape; the alternative-weighed credit is new, small code following the identical pattern |
| **OWNERSHIP / RESPONSIBILITY** | None directly — only incidental `entities` | A structured "boundary named" signal (e.g. `scope_held` / `scope_handed_off`) — **not specified anywhere yet**, unlike JUDGMENT | **Highest of the six** — new signal design from scratch (no prior draft to build from), a new `schemas.py` field (same two-owner conversation as above), a new rubric, and it's the least validated proposal here — the *move* already exists and works (`AUTHORITY`/`OWNERSHIP_BOUNDARY` already ask this question), only the *scoring* is genuinely new | No — new rubric over a new signal |
| **KNOWLEDGE / EXPLAIN** | `metric_definitions.how_measured` only, and only for metric-bearing claims | A general concept-explanation signal (e.g. `concept_explanations`: `concept`, `reasoning`, `quote`) — not specified anywhere | **Medium-High** — new signal design, new `schemas.py` field (two-owner conversation), new rubric, **and** de-gating `EXPLAIN`'s availability from `anatomy.has_metric` (a small but real touch to `question_engine.move_available()`, since today's nearest-equivalent move, `METRIC_DEFINITION`, is only offered to claims with a metric) | No — new rubric over a new signal |

**Read straight down the Effort column:** three of six dimensions are
free-or-nearly-free (EXECUTION, ADAPTABILITY, PROBLEM_SOLVING) because they
reuse existing signals and existing rubrics exactly as they are. JUDGMENT
is Medium because its signal is already designed, just unconnected.
KNOWLEDGE and OWNERSHIP are the two genuine build items, and they're build
items for the same reason: no prior draft of their signal exists anywhere
in this codebase, unlike every other dimension here.

---

## Universal Interview Moves

| Move | Target dimension | Evidence expected |
|---|---|---|
| **EXPLAIN** | KNOWLEDGE | A concept/tool/policy explained in the candidate's own words, including *why*, not just *what* |
| **WALKTHROUGH** | EXECUTION | First-person sequence of what they actually did |
| **ISSUE** | PROBLEM_SOLVING | A specific moment something didn't go as expected, and the response |
| **CHOICE** | JUDGMENT | A real decision, the alternative considered, and the criteria used |
| **RESPONSIBILITY** | OWNERSHIP | A named boundary, handoff, or accountable outcome |
| **TRANSFER** | ADAPTABILITY | Reasoning carried from an established answer into a new, related situation |

### Examples across six families

| Move | Software Engineering | IT Support | Banking | BPO | Customer Support | Sales |
|---|---|---|---|---|---|---|
| **EXPLAIN** | "You mentioned using a message queue — why does that fit here better than calling the service directly?" | "You mentioned resetting permissions — what actually determines who should have admin access?" | "You mentioned KYC checks — what is that check actually trying to catch?" | "You mentioned the escalation matrix — what actually decides which tier a call goes to?" | "You mentioned handling refunds — what actually qualifies something for a refund versus not?" | "You mentioned qualifying leads — what actually separates a qualified lead from one that isn't?" |
| **WALKTHROUGH** | "You mentioned deploying the service — walk me through what you actually did to get it live." | "You mentioned resolving a ticket — walk me through what you did from intake to close." | "You mentioned processing that loan application — walk me through intake to approval." | "You mentioned handling that call — walk me through pickup to wrap-up." | "You mentioned resolving that escalation — walk me through what you actually did." | "You mentioned closing that account — walk me through the first call to the signature." |
| **ISSUE** | "You mentioned the integration — describe a time it broke or didn't behave as expected." | "You mentioned that fix — describe a time it didn't work, and what you tried next." | "You mentioned reconciliation — describe a time the numbers didn't match." | "You mentioned handling calls — describe one that didn't fit any of your normal scripts." | "You mentioned handling complaints — describe one that didn't resolve as expected." | "You mentioned your pipeline — describe a deal that fell apart unexpectedly." |
| **CHOICE** | "You mentioned choosing that framework — what else did you consider, and what made you pick it?" | "You mentioned that troubleshooting step — what made you try that first?" | "You mentioned flagging that transaction — what made you decide it needed escalation?" | "You mentioned de-escalating that caller — what made you choose that over the script?" | "You mentioned offering that resolution — what made you pick that over standard policy?" | "You mentioned discounting to close — what made you choose that over holding the price?" |
| **RESPONSIBILITY** | "You mentioned the migration — what was entirely yours to decide, and what needed sign-off?" | "You mentioned that access change — what could you approve yourself?" | "You mentioned the loan file — what could you approve, and what went to underwriting?" | "You mentioned that call — at what point does it stop being yours and go to a supervisor?" | "You mentioned resolving tickets — at what point does something stop being yours to fix?" | "You mentioned the account — what could you offer on your own, and what needed approval?" |
| **TRANSFER** | "You said you optimized that query — if a different table had ten times the rows, what would you check first?" | "You said you fixed that issue — if the same symptom showed up on a different OS, would your approach change?" | "You said you flagged that pattern — if it came from a long-standing customer instead, would your response change?" | "You said you handle billing complaints — if it came from a first-time caller instead, what would you do differently?" | "You said you de-escalated that call — if the customer had already been transferred twice, would you handle it differently?" | "You said you closed that deal with a discount — if the buyer had a smaller budget, what would you try first?" |

---

## Coverage-Planner Design

**The current planner's unit of optimization is the claim** — `plan_next_forensic`
walks one claim's `ARCHETYPE_LADDER` at a time, and nothing in it asks "has
every *dimension* been touched this interview." That's exactly why the
prior audit measured `METRIC_OWNERSHIP` scoring zero across a real
7-question interview: no selected claim happened to route to the one move
that feeds it. The minimal fix is not a new planner from scratch — it's one
new priority step ahead of the existing one, the same shape as the answer-
threading extension already shipped this session.

**New state, derived not persisted** (same pattern as `ClaimState.moves_used`
today — no schema change): `dimensions_covered = {DIMENSION_OF[mv] for mv in
session_used}`, where `session_used` is the *exact line already in
`plan_next_forensic`* (`orchestrator.py:1795`: `set().union(*(s.moves_used
for s in states))`) and `DIMENSION_OF` is a six-entry dict, the direct
analogue of today's `MOVE_DIMENSIONS`.

**Selection rule — one new step, "step 0", ahead of today's breadth/seam/
depth/transfer:**

```
COVERAGE_ORDER = (EXECUTION, PROBLEM_SOLVING, ADAPTABILITY,   # cheap, fast, reliable
                  JUDGMENT, RESPONSIBILITY, KNOWLEDGE)         # harder / gated / newer

def plan_next_competence(states, index):
    if index >= settings.max_questions or not states:
        return None
    session_used = set().union(*(s.moves_used for s in states))
    covered = {DIMENSION_OF[mv] for mv in session_used if mv in DIMENSION_OF}
    for dimension in COVERAGE_ORDER:
        if dimension in covered:
            continue
        move = MOVE_OF[dimension]
        for state in states:                      # heaviest-first, same order as today
            if move.value in state.moves_used:
                continue
            if not move_available(move, state.anatomy, state.ledger):
                continue                            # e.g. EXPLAIN still needs a metric, for now
            return brief(state, move, f"covering {dimension.value} — not yet touched this session")
    return plan_next_forensic(states, index)         # coverage complete; existing logic, unmodified
```

This is structurally identical to `_thread_plan()`'s relationship to
`plan_next_forensic` (checked first, falls through unchanged when it has
nothing to do) — not a new architecture, the same extension pattern applied
a second time.

**The one honest tension this creates, stated rather than hidden:** coverage
completeness can conflict with "max 2 questions per claim." If `EXPLAIN`
needs a metric and only one of the three selected claims has one, that
claim may need to carry `EXPLAIN` *and* whatever its own opener was,
pushing it to 2 questions while a sibling claim gets only 1 in the worst
case. The design choice this document recommends: **prefer coverage
completeness over strict per-claim symmetry** — the entire point of this
migration is "no dimension goes unmeasured," so an occasional lopsided
claim is the correct trade, not a bug to engineer away. Whether to relax
`EXPLAIN`'s metric-gate (Effort table, KNOWLEDGE row) is the real lever if
this tension bites in practice.

---

## Output

### 1. Old dimension → new dimension

| Old | New (primary) | New (secondary) |
|---|---|---|
| SPECIFICITY | EXECUTION | OWNERSHIP (weak) |
| PROCESS | EXECUTION | PROBLEM_SOLVING, ADAPTABILITY |
| METRIC_OWNERSHIP | KNOWLEDGE | JUDGMENT (weak) |
| CAUSAL_REASONING | JUDGMENT | PROBLEM_SOLVING, ADAPTABILITY *(most overloaded old dimension — see prior audit)* |
| AUTHENTICITY | PROBLEM_SOLVING | — *(cleanest 1:1)* |
| TOOL_FAMILIARITY | EXECUTION | KNOWLEDGE (weak) |

### 2. Old move → new move

| Old | New | Change required |
|---|---|---|
| OPERATING_CONTEXT | WALKTHROUGH | Rename only |
| FAILURE | ISSUE | Rename + wording iteration |
| DEPENDENCY | RESPONSIBILITY (primary) | Retarget |
| AUTHORITY | RESPONSIBILITY | Retarget, redefine "good answer" as boundary clarity |
| OWNERSHIP_BOUNDARY | RESPONSIBILITY | Consolidate with AUTHORITY |
| PEOPLE | RESPONSIBILITY (weak) | Retire — never fired in any real log this session |
| COHERENCE | *(cross-check, not a move)* | Demote out of the move set entirely |
| METRIC_DEFINITION | EXPLAIN | Retarget, de-gate from metric-only |
| PERTURB | TRANSFER | Re-enable (`transfer_probe=True`) + rename |

### 3. Coverage strategy

One new "step 0" ahead of the existing planner (above): track which of the
six new dimensions have been targeted this session (derived from the same
`moves_used` bookkeeping already in place), and route each turn to the
highest-priority uncovered dimension, cheapest/most-reliable first
(EXECUTION → PROBLEM_SOLVING → ADAPTABILITY → JUDGMENT → RESPONSIBILITY →
KNOWLEDGE), until all six are covered, then fall through to today's
breadth/seam/depth logic unmodified for any remaining budget.

### 4. Minimal code changes required

- `question.py`: six new move briefs (mostly renamed/retargeted existing
  text), one new `CHOICE` brief, `DIMENSION_OF`/`MOVE_OF` dicts (direct
  analogues of `MOVE_DIMENSIONS`).
- `orchestrator.py`: one new function, `plan_next_competence`, following
  the exact shape above; one new branch in `ask_next`'s planner-selection
  chain (`plan_next_competence if settings.competence_framework else
  plan_next_forensic ...`) — the same three-line pattern already used to
  add `plan_next_evidence` and `_thread_plan`.
- `signals.py`: one new rubric (`score_judgment`), reusing the existing
  five rubrics' exact shape (`_score()`, `TARGETS`, `GATES` entries added
  for `JUDGMENT`); `KNOWLEDGE`/`OWNERSHIP` rubrics deferred (see below).
- `schemas.py`: one new field (`decisions`) to unlock JUDGMENT — the one
  schema touch this phase actually needs, and it needs the two-owner
  conversation CLAUDE.md requires for that file, not just an engineering
  ticket.
- `config.py`: one new flag, `competence_framework: bool = False`, same
  pattern as every other planner flag already in this file.

No changes to `extract.py`, `graph.py`, claim ranking, or the existing
`Move`/`plan_next_forensic` code path — all remain reachable, unmodified,
exactly as Demo Mode left `forensic_question.txt` reachable behind its own
flag.

### 5. Recommended migration sequence

1. Ship the move renames + retargets (WALKTHROUGH, ISSUE, RESPONSIBILITY,
   TRANSFER re-enable, EXPLAIN un-gated) — zero new signals, all reuse
   existing scoring, lowest risk.
2. Build the coverage planner (`plan_next_competence`) against those six
   moves, behind its own flag, validated the same way Demo Mode was — real
   interviews, not fixture mode, across a representative claim from
   several of the ten target families.
3. Only once 1-2 are validated, take the `decisions` field to the two-owner
   conversation and wire JUDGMENT — it's ready to build, but it's the first
   thing in this plan that touches the frozen schema.
4. KNOWLEDGE's and OWNERSHIP's new signals last — they have no prior draft,
   need real design work, and should not block anything above.

### 6. What can be reused unchanged

`extract.py` (claim extraction and ranking), `graph.py` (role coverage,
final scoring assembly), `evidence.py`'s existing extraction call and
`enforce_verbatim()`, `signals.py`'s five existing rubrics
(`score_specificity`, `score_process`, `score_metric_ownership`,
`score_causal_reasoning`, `score_tool_familiarity`), `validate()`'s seven
rules, the fallback/repair mechanisms, and the orientation-reminder /
recruiter-voice prompt work already shipped this session — none of it is
competence-framework-specific, all of it is reused as-is.

### 7. What should be deferred until after the hackathon

The two new signal types (KNOWLEDGE's `concept_explanations`, OWNERSHIP's
`boundaries`) and their rubrics — the only two build items in this entire
plan without a prior draft to work from, and the only two that require the
`schemas.py` two-owner conversation *and* new extraction-prompt design *and*
new rubric design simultaneously. Everything else in this document is
buildable and validatable before then.
