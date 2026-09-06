# Architectural Deletions and Simplifications

What the forensic architecture removes. Verified against the code, not inferred.

---

## 1. Modules and components that become unnecessary

### 1.1 Deleted outright — `engine/question.py`

| component | lines | why it goes |
|---|---|---|
| `PROBE_BRIEFS` | 73–107 | Replaced by the family catalogue. The brief was keyed on probe level; briefs are now keyed on `(family, move)`. |
| `GAP_HINTS` | 181–204 | Dissolves into the family prompt. There is no longer a generic instruction for a hint to contradict. |
| `_RETRY_HINTS` | 694–702 | The retry no longer tells the model which rule it tripped. |
| `_retry_brief()` | 673–692 | Same. Its whole purpose was rendering violation names into the prompt. |
| `$violations` slot | prompt template | Nothing is fed back into a retry. |
| `api/prompts/generate_question.txt` | whole file | Replaced by one system prompt plus nine move templates. |

`_RETRY_HINTS` and `_retry_brief()` are the load-bearing deletion. **The
re-target rule makes them unimplementable**: the second attempt is a different
question against a different target, so there is no previous draft to repair and
no violation to report. This is what structurally eliminates the
regeneration-by-deletion path.

### 1.2 Deleted outright — `engine/orchestrator.py`

| component | why it goes |
|---|---|
| `ClaimState.weakest_dimension()` (166) | Dimension-gap routing is replaced by state + ledger cost. Only other consumer is a diagnostic script. |
| `ClaimState.levels_left` (126) | There is no ladder of levels to have a remainder of. |
| the gap-routing block in `plan_next` (658–700) | ~45 lines: preferred-level lookup, the "any remaining level that touches the gap" fallthrough, and the defensive branch that drops the target dimension when no level covers the gap. All three exist to reconcile a rubric axis with a probe ladder. Neither survives. |
| the fixed-sweep branch (620–628) | See §5.3. |

### 1.3 Deleted outright — `engine/signals.py`

| component | why it goes |
|---|---|
| `level_for_dimension()` (315–325) | Its only runtime caller is the `plan_next` block above. |
| `LADDER_ORDER` (90) | Exists to give `level_for_dimension` and the fixed sweep something to walk. |
| `PROBE_ORDER` (72) | Exists only to define `LADDER_ORDER` and to gate selectability. Selectability is now a family precondition. |
| `PROBE_LEVEL_DIMENSIONS` (53) | **Conditionally** — see §1.5. |

### 1.4 Dead code, deletable now and independent of this migration

`scoring.py:84 merge_dimension_scores()` is marked *"DEPRECATED — kept only so
nothing silently breaks"* and has **zero callers anywhere in the repo, including
tests**. It is the only thing importing `PROBE_LEVEL_DIMENSIONS` into
`scoring.py`.

### 1.5 `PROBE_LEVEL_DIMENSIONS` — deletable, in this order

Three consumers, all resolvable:

1. `scoring.py:97` — inside the dead function above. Delete the function.
2. `orchestrator.py` (3 sites) — all inside the `plan_next` block being replaced.
3. `evidence.py:291` — `_nodes_from` uses it as the probed-dimension key.
   Replaced by `FAMILY_DIMENSIONS`.

Once all three move, the table has no runtime consumer. **Replay does not read
it** — `replay.py` never references it, and `probed_dimensions` is a stored
column on `claim_scores`, so historical evaluations reproduce from stored values
rather than by re-deriving the mapping.

**Correction to the design document:** it stated `scoring.py` was untouched.
`scoring.py:97` does consume this table, and deleting the dead function around it
is a prerequisite. The change is a deletion, not a rewrite, but it is not zero.

### 1.6 Components that shrink rather than disappear

| component | before | after |
|---|---|---|
| `generate_question()` | two model calls, violation feedback, three exit paths | two model calls, no feedback, target swap between them |
| `FALLBACK_QUESTIONS` | 6 generic per-level sentences | 11 per-move templates interpolating claim anatomy |
| `select_transfer()` | scans sibling claims | reads the ledger |
| `Plan` | carries `target_dimension` (a rubric axis) | carries `target` (an incidental detail) |

---

## 2. Probe levels that disappear

**No `ProbeLevel` enum value can be deleted.** `api/schemas.py` is frozen,
`questions.probe_level` and `evidence.probe_level` are `NOT NULL`, and stored
history must stay readable. All six values survive as **derived labels written
for replay**.

What disappears is their **behavioural role**:

| level | status after migration |
|---|---|
| VALIDATION | **Disappears as a concept.** Its brief is deleted, its opening-probe privilege is replaced by archetype-specific openings, and its two mandates split between ESTABLISH and MEASUREMENT. |
| DECISION | **Disappears entirely.** Nothing in the planner reasons about it; nothing selects it. Its one useful half — the rejected option — becomes PERIPHERY·EXCLUSION. |
| OPERATIONAL | Survives as a label for two moves (ESTABLISH·MECHANISM, PERIPHERY·DEPENDENCY). Its "walk me through your day" brief is deleted. |
| INCIDENT | Survives as a label. Its brief is the only one whose content carries forward, into PERIPHERY·FAILURE. |
| OUTCOME | Survives as a label for MEASUREMENT and SEAM. Its four-ask brief is deleted; three of the four asks survive as separate moves and the counterfactual ask is dropped. |
| TRANSFER | Survives as both label and family. |

**The concept of a probe *ladder* is deleted.** There is no ordered sequence of
levels, no "levels used", no "levels remaining". A claim has a state and an
archetype ladder of moves; levels are a reporting artifact.

---

## 3. Dimensions that lose ownership

**None. Every dimension gains owners.** `TOOL_FAMILIARITY` goes from one source
to two; `CAUSAL_REASONING` goes from two levels that produce nothing to a
dedicated owner in SEAM.

Two dimensions change character, and both are simplification opportunities:

### 3.1 `AUTHENTICITY` becomes structurally redundant

Under authorship verification, **every family targets what AUTHENTICITY
measures**. It stops being one axis among six and becomes the objective
function. Keeping it as a weighted dimension double-counts the thing the whole
score is now for.

Two coherent resolutions, both simplifications:

- **Delete it as a dimension** and let the composite score be the authenticity
  signal. Costs a `Dimension` enum value — frozen file, not a solo decision.
- **Keep it, set its weight to zero**, and report it as a diagnostic. No schema
  change; the dimension survives as an observation rather than a contributor.

### 3.2 `SPECIFICITY`'s gate becomes a defect the migration introduces

`score_specificity()` gates on `bool(quantities)` — *"no quantity given"* caps
the score at 55 — and carries the highest saturation target of any dimension
(`TARGETS[SPECIFICITY] = 5.0` against 2.0–4.0 elsewhere).

The new architecture **deliberately stops asking for quantities** (rule 7,
`forbidden` scope markers). So SPECIFICITY will be fed only by numbers the
candidate volunteers, while still penalising them for not producing numbers we
chose not to request.

**This must be resolved as part of the migration, not after it.** Either the gate
is removed, or SPECIFICITY becomes an unweighted observation. Leaving both the
gate and the new question policy in place produces a systematically depressed
score with no defect visible anywhere in the question path.

---

## 4. Validator rules that become redundant

`validate()` is not modified. This section is about which rules stop having work
to do.

### 4.1 `duplicate_content` — the one rule with a genuine deletion argument

Its failure mode is eliminated at the source, not merely reduced:

- **Same-claim duplication is structurally impossible.** A move is retired for a
  claim once used, and once its target yields a DEAR fact. The planner cannot
  select the same move twice on the same claim.
- **Cross-claim frame reuse is not a defect.** Re-using *"how was X counted?"* on
  three different claims is house style. It is what the rule mostly fires on, and
  those fires were measured as incorrect.
- `ledger_summary` in every prompt shows what is already established, so the
  model is not reaching for a repeat in the first place.

The argument for deletion here is **not** "its precision is low" — that argument
was correctly rejected before. It is that **the structure it guards against no
longer exists**. It is the only rule where that is true.

If retained, expect it to fire almost exclusively on cross-claim frame reuse,
which is the case it gets wrong.

### 4.2 Rules that become backstops — near-zero fires, keep

| rule | why it stops firing |
|---|---|
| `answer_leakage` | `forbidden` carries `metric_value` and the prompt is instructed not to reproduce it. The violation is prevented upstream. |
| `no_claim_anchor` | The anchor is *supplied* by `QuestionBrief.anchor` and the prompt requires naming it. Anchoring is caused, not checked. |
| `unsupported_metric` | Its only observed failure mode was TRANSFER citing the planner's target-claim figure. TRANSFER now sources variables from the ledger — the candidate's own words — which rule 5 already permits. |

All three keep earning their place as regression guards. None should be deleted:
a rule that fires zero times because the generator is correct is doing its job.

### 4.3 `multiple_fact_targets` — exemption list grows, rule unchanged

SEAM names two facts by construction. Rule 3 is already not evaluated on
TRANSFER for the same reason; SEAM joins that exemption. **No new rule, no
retuning** — one more level added to an existing carve-out.

### 4.4 Nothing else

`hypothetical_misuse` and `scope_drift` are unaffected. Neither becomes
redundant.

---

## 5. Orchestration simplifications

### 5.1 `plan_next` loses its reconciliation layer

The current function performs four jobs: choose a claim, choose a level, choose a
dimension, and **reconcile the last two when they disagree**. The fourth job is
~45 lines and exists only because a rubric axis and a probe ladder are different
coordinate systems.

After: choose a claim by state and weight, choose the next eligible move from the
archetype ladder. **One coordinate system, no reconciliation.**

### 5.2 Stall detection becomes a measurement instead of a heuristic

`transfer_available` currently triggers on an answer count. It becomes: two
consecutive answers adding zero DEAR facts. Same branch, real signal.

### 5.3 `ADAPTIVE_PROBING=false` and the fixed-sweep branch

The strict `VALIDATION→OUTCOME` sweep has no meaning once the ladder is deleted.
Removing it deletes the branch, the flag, and the ability to reproduce the
Phase 1 interview. **That reproduction path is the actual cost** — decide whether
it is still wanted before deleting rather than after.

### 5.4 Diagnostic surface

`scripts/inspect_resume_pipeline.py` prints `PROBE_ORDER`, `LADDER_ORDER`,
`level_for_dimension` and `weakest_dimension` (lines 420–449, 488, 612, 631). All
four disappear. The script needs a corresponding section on families, anatomy and
the ledger, or those blocks are simply removed.

### 5.5 Test surface

`tests/test_policy.py` pins the ladder directly — `PROBE_ORDER`,
`LADDER_ORDER`, `dimensions_for_level`, and the invariant that TRANSFER is
selectable but never walked to (lines 236–248, 306, 315). Those assertions
describe a structure that will not exist. `tests/test_pipeline.py:52–53`
documents the same invariant in prose.

---

## 6. What must not be deleted

Short, because each is a mistake that would otherwise look like a simplification.

| candidate | why it stays |
|---|---|
| **The repair turn** (`REPAIR_PROMPTS`, `repair_question`, `is_non_answer`, `REPAIR_TURN`) | Fired zero times, but the corpus never produced a non-answer to catch. The state machine handles a *thin* answer by closing the claim; it does not handle *"ok"*. Different failure modes. Deleting it converts a mis-sent message into a burned claim. |
| **`hypothetical_misuse`** | Zero fires because the prompt already forbids hypotheticals. It guards against prompt regression, and the new architecture adds eight more prompts that could regress. |
| **`scope_drift`, `multiple_fact_targets`** | Low precision at n≤5 is not a verdict, and neither rule's failure mode is removed by this design. |
| **`ProbeLevel` enum and stored `probe_level` columns** | Frozen schema; stored history and replay depend on them. |
| **`PROBE_LEVEL_DIMENSIONS`, until all three consumers move** | Deleting it before `evidence.py` switches key silently zeroes `probed_dimensions`, which is a confidence input with no visible failure. |

---

## 7. Net effect

| | removed | added |
|---|---|---|
| **Concepts** | probe ladder, dimension-gap routing, violation feedback, level ordering | claim anatomy, fact ledger, family catalogue, claim state machine |
| **Prompt files** | 1 | 10 (1 system + 9 moves) |
| **Config tables** | `PROBE_BRIEFS`, `GAP_HINTS`, `_RETRY_HINTS`, `PROBE_LEVEL_DIMENSIONS`, `LADDER_ORDER`, `PROBE_ORDER` | `FAMILY_DIMENSIONS`, family catalogue, archetype ladders, fallback templates |
| **Functions** | `level_for_dimension`, `weakest_dimension`, `levels_left`, `_retry_brief`, `merge_dimension_scores` | anatomy decomposition, ledger indexing, state transition, pair selection |
| **Validator rules** | 0 modified; 1 (`duplicate_content`) becomes deletable | 0 |
| **Frozen-file edits** | 0 | 0 |

**This is not a net reduction in code.** It is a reduction in *coordinate
systems* — from two (rubric axes and probe ladder, permanently reconciling) to
one (forensic moves, with dimensions declared as output). The deletions above are
the reconciliation layer, and they are the reason the design is worth doing.
