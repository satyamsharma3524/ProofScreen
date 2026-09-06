# Implementation readiness — four questions answered from the code

---

## 1. Where the planner chooses the probe level today

**`api/engine/orchestrator.py:610` — `plan_next(states, index)`.** One pure
function, no model call, no randomness. It is the only place a probe level is
chosen. `ask_next:830` is its only caller.

Five exit points, in evaluation order:

| line | branch | what it returns | fires when |
|---|---|---|---|
| 616 | budget guard | `None` | `index >= max_questions` or no claims |
| 619–626 | fixed sweep | `Plan(claim, level, None, "fixed sweep")` | `ADAPTIVE_PROBING=false` only |
| **630–639** | **breadth** | **`Plan(claim, ProbeLevel.VALIDATION, None, …)`** | any claim with `levels_used == ∅` |
| 645–664 | stall / transfer | `Plan(claim, TRANSFER, gap, …, transfer=select_transfer(...))` | `state.transfer_available` |
| 667–704 | depth / gap routing | `Plan(claim, chosen, gap, …)` | otherwise |

### The single line that produces the metadata problem

**Line 634: `ProbeLevel.VALIDATION` is a hardcoded literal in the breadth
branch**, with `target_dimension=None`. Every claim's opening question is
VALIDATION, unconditionally, with no dimension qualifier. That branch is where
~23% of the interview is decided, and it is one enum reference.

### The depth branch, which is the reconciliation layer

```
667  remaining = state.levels_left                    # LADDER_ORDER minus levels_used
668  gap      = state.weakest_dimension()             # lowest-scoring rubric axis
672  preferred = level_for_dimension(gap)             # first ladder level covering it
     ...if preferred not in remaining: any remaining level touching the gap
691  chosen = remaining[0]                            # else: next unused level,
                                                      #       and DROP the gap
704  return Plan(state.claim, chosen, gap, reason)
```

Three attempts to reconcile a rubric axis with a ladder position. This is the
block §1.2 of the deletion audit removes.

### What feeds it

**`build_claim_states` (line 307)** — one pass over the session. It reads the
`questions` and `responses` rows and produces, per claim: `levels_used`,
`answer_signals`, `dimensions`, `score`, `answers`, `last_answer_signals`,
`weight`, `claim_family`.

---

## 2. Inputs available at question generation time

### What `generate_question()` actually receives

| parameter | type | source |
|---|---|---|
| `claim_text` | `str` | `plan.claim.text` |
| `probe_level` | `ProbeLevel` | `plan.probe_level` |
| `claim_type` | `str` | `plan.claim.claim_type` |
| `claim_metric` | `str \| None` | `plan.claim.metric` — **the value, e.g. `"41% -> 63%"`** |
| `job_family` | `str` | `session.job_family` |
| `prior_qa` | `list[(str, str)]` | **raw question and answer text**, last 5 rendered |
| `target_dimension` | `Dimension \| None` | `plan.target_dimension` |
| `transfer` | `TransferSpec \| None` | `plan.transfer` |
| `other_claims` | `list[str]` | sibling claim texts |
| `target_claim_text` | `str \| None` | the transfer target's text |

### What `ask_next` holds and does not pass

This is the important half.

At line 829 `ask_next` has **`states: list[ClaimState]`** in scope and uses it
only for `other_claims`. It therefore already holds, and discards:

- **`state.answer_signals: list[AnswerSignals]`** — every signal from every
  answer on this claim, **already parsed into typed objects with verbatim
  quotes**
- `state.dimensions`, `state.score`, `state.answers`, `state.last_answer_signals`
- `state.weight`, `state.levels_used`
- `plan.reason`

**The generator today sees raw answer prose (`prior_qa`) and nothing structured.**
The structure exists one stack frame up and is thrown away.

---

## 3. Is there enough structured claim anatomy?

**No. This is the real gap, and it is the only one that needs new extraction.**

### What extraction produces today

`ExtractedClaim` (`schemas.py:116`) has exactly four fields:

```
text        str          "Grew activation from 41% to 63% ... rebuilding the first-run flow"
claim_type  str | None   "outcome_ownership"
metric      str | None   "41% -> 63%"
verifiable  bool
```

The `Claim` DB row stores `text`, `claim_type`, `metric`, `order_index`.

### Mapped against what each family needs

| anatomy field | available? | consequence |
|---|---|---|
| `archetype` | **derivable** | `claim_type` (~30 taxonomy values) plus `metric is not None` maps onto the five archetypes without new extraction. |
| `mechanism` | **no** | Present in `text`, not separated. ESTABLISH can work from raw text; the fallback templates cannot interpolate it. |
| `object` | **no** | Blocks PERIPHERY·EXCLUSION and every fallback that says `$object`. |
| `parts` | **no** | Blocks PERIPHERY·EXCLUSION's precondition. Without it the planner cannot tell whether "what did you leave alone?" is even askable. |
| `metric` **name** | **no — critical** | `metric` holds the *value* (`"41% -> 63%"`). The name (`"activation"`) exists only inside `text` and is never extracted. |
| `metric_value` | **yes** | It is the `metric` field, mis-named for this purpose. |
| `population` | **no** | Weakens MEASUREMENT·DERIVATION. Not blocking. |
| `scope` markers | **no** | Blocks the `forbidden` list, so rule 7 cannot be enforced by data — only by prompt text. |

### Family-by-family readiness on today's data

| family | ready? | blocker |
|---|---|---|
| ESTABLISH | **partially** — raw `text` is enough for the model, not for the fallback | `mechanism`, `object` |
| MEASUREMENT | **no** | **The metric name.** The Option A constraint is *name the metric, never its value* — and today the system stores only the value. This family cannot be built correctly without extracting the name. |
| PERIPHERY·FAILURE / ·PEOPLE / ·DEPENDENCY | **yes** | none — these need only the claim and the ledger |
| PERIPHERY·EXCLUSION | **no** | `parts` / `object` |
| PERIPHERY·AUTHORITY | **yes** — archetype is derivable | none |
| SEAM | **yes** | none — needs the ledger, not anatomy |
| TRANSFER | **yes** | none — needs the ledger, not anatomy |

**Summary: five of nine moves are buildable on today's data. The four that are
not all block on the same thing — the claim has never been decomposed.** The
single highest-value field is the **metric name**, because it gates the family
that owns METRIC_OWNERSHIP and it is what makes the standing generator
constraint satisfiable.

### Cost of closing it

`ExtractedClaim` is a Pydantic model in the **frozen** `api/schemas.py`. Two
options that avoid editing it:

- Return anatomy as an **engine-local NamedTuple** from `extract.py`, exactly as
  `FamilyMatch` and `TransferSpec` already sidestep the frozen file, and persist
  it on the `claims` row as new columns.
- Or derive `mechanism` / `object` / metric-name **deterministically in Python**
  from `claim.text` and `claim.metric` — no new LLM output at all. The claim
  text is one sentence; the metric value is already isolated, so the metric
  *name* is recoverable as the noun phrase adjacent to it. Weaker than
  extraction, but zero prompt change and zero new model output.

Neither requires a schema edit. Both require new columns on `claims`, which
under the no-Alembic rule means `db._REQUIRED_COLUMNS` plus a re-seed.

---

## 4. Can ledger facts be injected without schema changes?

**Yes — and it is close to free. Nothing needs to be built; something needs to be
passed.**

### Everything is already in place

| piece | status | location |
|---|---|---|
| storage | **exists** | `responses.signals_json`, a `TEXT` column, already populated on every answer |
| typed model | **exists** | `AnswerSignals` — seven signal types, each carrying `quote` |
| parser | **exists** | `evidence_engine.signals_of(response.signals_json)` |
| per-claim grouping | **exists** | `build_claim_states:~330` already calls the parser and appends to `ClaimState.answer_signals` |
| in the planner | **exists** | `plan_next` receives `states`; the transfer branch already calls `signal_rubrics.merge_signals(state.answer_signals)` at line 662 |
| in `ask_next` | **exists** | `states` is in scope at line 829, used only for `other_claims` |

**The ledger is already extracted, already parsed, already typed, already grouped
by claim, and already in the planner's hand. The only missing step is forwarding
it into `generate_question()` and rendering it into the prompt.**

Cost: one new keyword argument, one prompt slot, one renderer.

### What comes for free with it

| requirement | satisfied by |
|---|---|
| every fact carries verbatim words | `quote` on all seven signal types |
| "different answers" for SEAM pairing | `answer_signals` is an ordered list — index = answer position |
| CHEAP / MID / DEAR cost | pure function of structure: `metric_definitions[].how_measured`, `tools[].usage`, `causal_links[].is_complete`, `quantities[].refers_to` are all already modelled |
| shared-referent pairing | `quantities[].refers_to`, `metric_definitions[].metric`, `entities[].entity`, `tools[].tool` |
| TRANSFER variable sourcing | `quantities`, `entities`, `process_steps` |
| rule 7's "unless it emerged from a prior answer" | membership test against the ledger |

**No schema change. No new column. No new LLM call. No frozen-file edit.**

### Two limitations to know

- **`ClaimState.answer_signals` is grouped per claim.** A cross-claim seam needs
  session-level signals — the same rows, not grouped. That is a query shape, not
  a schema change.
- **`AnswerSignals` carries no answer index.** Position in the list supplies it,
  which is sufficient for "two facts from different answers" but is lost if
  anything ever reorders the list.

---

## Summary

| question | answer |
|---|---|
| Where is the level chosen? | `orchestrator.py:610 plan_next`, five branches. **Line 634 hardcodes `VALIDATION` for every claim's opening probe.** |
| What does the generator get? | Claim text, type, **metric value**, family, raw prior Q&A prose, target dimension, transfer spec, sibling claim texts. **No structured signals** — though `ask_next` holds them. |
| Enough claim anatomy? | **No.** Five of nine moves are buildable today. MEASUREMENT and PERIPHERY·EXCLUSION are blocked, both on claim decomposition. The critical missing field is **the metric name**, since only the value is stored. |
| Ledger without schema change? | **Yes.** Extracted, parsed, typed and grouped already. One argument and one prompt slot away. |

**The order this implies: the ledger is nearly free and unblocks SEAM and
TRANSFER immediately. Claim anatomy is the real work, and the metric name is the
single field that unblocks the most.**
