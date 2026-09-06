# Forensic Question Generation — Technical Design

**Status:** design for implementation. **Objective: authorship verification.**
Supersedes the probe-brief generator for question *selection and wording*. It
does not change scoring, evidence extraction, tenancy, evaluation or replay.

---

## 1. Objective and invariants

**The generator answers one question: did this person do the work described in
the claim?**

Operationally that means every question must be **cheap for the author and
expensive for the copier**. The architecture makes this mechanical rather than
aspirational by giving the planner a target that is a *specific incidental
detail*, not a rubric dimension.

### Invariants preserved without exception

| # | Invariant | How this design holds it |
|---|---|---|
| 1 | **The model never scores.** | The model receives an anchor, a move and a target and returns wording. Family, target and sequencing are chosen in Python. |
| 2 | **`api/schemas.py` is frozen.** | No new enum, field or type there. New types are engine-local NamedTuples, as `FamilyMatch` and `TransferSpec` already are. |
| 3 | **Quotes verified in Python.** | Unchanged. `enforce_verbatim()` is untouched. |
| 4 | **Every LLM call has a fallback.** | Every family has a Python-rendered fallback built from claim anatomy. |
| 5 | **Never score presentation.** | No family, precondition or selector reads fluency, grammar, register or length-as-quality. |
| 6 | **The validator is correct and unchanged.** | `validate()` is not modified. The generator is constrained so its output passes — see §13.3. |

### The one standing generator constraint

> **Name the metric, never quote its value. Name the subject, never say "that
> number".**

This is not a style preference. Quoting the figure back tells a copier which
number to be confident about, and it is the difference between a question that
passes `answer_leakage` and one that does not.

---

## 2. Architecture

```
                        ┌─────────────────────────────────────────┐
   resume ──► EXTRACT ──►│ Claim + ClaimAnatomy                   │  LLM #1
                        └──────────────┬──────────────────────────┘
                                       │
                        ┌──────────────▼──────────────────────────┐
                        │ CLAIM STATE MACHINE                     │  pure Python
                        │  UNTOUCHED → GROUNDED → DETAILED        │
                        │            → STALLED → CLOSED           │
                        └──────────────┬──────────────────────────┘
                                       │
                        ┌──────────────▼──────────────────────────┐
                        │ PLANNER                                 │  pure Python
                        │  eligible families  = f(state, anatomy, │
                        │                          ledger)        │
                        │  select family + TARGET                 │
                        └──────────────┬──────────────────────────┘
                                       │  QuestionBrief(family, anchor, target)
                        ┌──────────────▼──────────────────────────┐
                        │ WORDING                                 │  LLM #2
                        │  system prompt + one family prompt      │
                        │  ONE ask, ONE target                    │
                        └──────────────┬──────────────────────────┘
                                       │
                        ┌──────────────▼──────────────────────────┐
                        │ validate()  — UNCHANGED                 │  pure Python
                        └──────────────┬──────────────────────────┘
                       reject          │ accept
                        ┌──────────────▼──────────────────────────┐
                        │ RE-TARGET (not re-word) — one attempt   │
                        │ then TARGETED FALLBACK                  │
                        └──────────────┬──────────────────────────┘
                                       │
                                   candidate
                                       │  answer
                        ┌──────────────▼──────────────────────────┐
                        │ EVIDENCE EXTRACT  — UNCHANGED           │  LLM #3
                        └──────────────┬──────────────────────────┘
                                       │  signals
                        ┌──────────────▼──────────────────────────┐
                        │ FACT LEDGER  ◄── the missing feedback   │
                        │  indexes signals for planning           │
                        └──────────────┬──────────────────────────┘
                                       └──► back to the state machine
```

**Two structural changes carry the whole design:**

1. **Claim anatomy** — the claim is decomposed *before* it is probed, so the
   planner knows which forensic moves are even possible against it.
2. **The fact ledger** — the signals the evidence extractor already produces are
   fed back into planning. Today they flow only to scoring. This is a missing
   loop, not a new component.

---

## 3. Claim anatomy

Produced by LLM #1 alongside the claim itself. No new model call — it is an
extension of the existing extraction contract.

```
ClaimAnatomy
  mechanism      str        what they did.        "rebuilding the first-run flow"
  object         str        what it was done to.  "the first-run flow"
  metric         str|None   the quantity named.   "activation"        ← NAME, not value
  metric_value   str|None   the value claimed.    "41% -> 63%"        ← never sent to LLM #2
  population     str|None   who/what was affected."new signups"
  parts          [str]      named sub-parts.      ["email verification", "project creation"]
  scope          [str]      headcount/duration/volume markers, EXTRACTED AND NEVER ASKED ABOUT
  archetype      enum       see §7
```

**Why anatomy is required and not a convenience.** A periphery question needs to
know the claim has parts before it can ask what was left alone. A measurement
question needs a metric *name* to ask about without quoting its value. Without
anatomy the planner selects blind and the model papers over the gap with a
generic question — which is the failure mode this design exists to remove.

**`metric_value` is stored and deliberately withheld from the wording prompt.**
It is needed by scoring and by `validate()`; sending it to the generator is how
figures get quoted back.

**`scope` is extracted precisely so it can be excluded.** Headcount, duration and
volume are recorded for the evidence graph and are never a question target
unless the candidate raises them first (§10.3).

---

## 4. The fact ledger

A per-session index over the signals LLM #3 already returns.

```
LedgerFact
  kind        quantity | entity | tool | process_step | causal_link
              | incident_marker | metric_definition
  text        the extracted content
  quote       the candidate's verbatim words
  claim_id    which claim it arrived under
  answer_ix   which answer it arrived in
  cost        CHEAP | MID | DEAR
```

`cost` is assigned by kind and completeness:

| cost | kinds |
|---|---|
| CHEAP | bare quantity, metric named without `how_measured`, tool named without usage |
| MID | quantity bound to a named metric, entity, process step, tool with described usage |
| **DEAR** | **incident marker, causal link, metric definition carrying `how_measured`** |

**`cost` is the control signal for the entire state machine.** It is the
operational definition of "expensive for a copier to invent", and it is computed
in Python from stored structure — never asked of a model, never a judgement made
at runtime.

The ledger is the **only** source of subject matter for SEAM and TRANSFER. Those
families may not introduce anything the candidate has not already said, and that
constraint is enforced by construction: their prompts receive ledger facts and
nothing else.

---

## 5. Question families

Nine moves in five families. **One family, one ask, one target — always.**

| family | move | target it hunts | precondition |
|---|---|---|---|
| **ESTABLISH** | `FIRST_MOVE` | the diagnostic entry point | always |
| | `MECHANISM` | how the work actually flowed | always |
| **MEASUREMENT** | `DERIVATION` | how the number was computed | `anatomy.metric` |
| | `PROVENANCE` | where the number came from, who else read it | `anatomy.metric` |
| **PERIPHERY** | `EXCLUSION` | what was deliberately left out | `parts` or aggregate metric |
| | `DEPENDENCY` | who/what they had to wait on | always |
| | `AUTHORITY` | where their decision rights ended | archetype ∈ {OWNERSHIP, PROCESS, VOLUME} |
| | `FAILURE` | the specific thing that broke | always |
| | `PEOPLE` | the named human in the loop | always |
| **SEAM** | `COHERENCE` | whether two stated facts hold together | ≥2 ledger facts, ≥2 answers |
| **TRANSFER** | `PERTURB` | reasoning under one changed variable | ≥1 MID/DEAR mechanism fact |

### Family contracts

**ESTABLISH.** Never asks the headline. Asks for the move *before* the result —
what they looked at first, how the thing actually worked end to end. May
introduce subject matter.

**MEASUREMENT.** Owns the metric before the result. Asks derivation
(*"how was activation counted — who was in the denominator?"*), provenance
(*"where did that number come from?"*), or audience (*"besides you, who watched
it each week?"*). **May name the metric. May never state its value.**

**PERIPHERY.** The highest-yield family. Every move aims off-centre: the part
untouched, the person waited on, the decision that needed someone else, the
thing that broke, the human who complained. May introduce subject matter, but
only subject matter grounded in `anatomy.object` or `anatomy.parts`.

**SEAM.** Loads two facts the candidate has already stated against each other.
**Introduces no new subject matter, ever.** Cannot be answered by repeating
either fact.

**TRANSFER.** Their world, exactly one variable changed, sourced from the
ledger. Never a generic hypothetical, never a role-play.

---

## 6. Family → evidence dimension mapping

The family declares which dimensions its answer is expected to carry. This
replaces `PROBE_LEVEL_DIMENSIONS` as the *scoring* key.

| family / move | dimensions marked probed |
|---|---|
| ESTABLISH·FIRST_MOVE | PROCESS, SPECIFICITY |
| ESTABLISH·MECHANISM | PROCESS, TOOL_FAMILIARITY |
| MEASUREMENT·DERIVATION | METRIC_OWNERSHIP |
| MEASUREMENT·PROVENANCE | METRIC_OWNERSHIP, SPECIFICITY |
| PERIPHERY·EXCLUSION | CAUSAL_REASONING, PROCESS |
| PERIPHERY·DEPENDENCY | TOOL_FAMILIARITY, PROCESS |
| PERIPHERY·AUTHORITY | PROCESS, SPECIFICITY |
| PERIPHERY·FAILURE | AUTHENTICITY, SPECIFICITY |
| PERIPHERY·PEOPLE | SPECIFICITY, AUTHENTICITY |
| SEAM·COHERENCE | CAUSAL_REASONING |
| TRANSFER·PERTURB | CAUSAL_REASONING, PROCESS |

**This is the critical decoupling.** Today a question's *probe level* decides
both what is asked and which dimensions are marked probed, so a level that
targets two dimensions and serves one reports coverage it did not earn. Here the
family owns the question and declares its own coverage honestly. A stored
`probe_level` is still written for replay and backward compatibility, derived
from the family, but **it is no longer the scoring key.**

`TOOL_FAMILIARITY` retains two sources (ESTABLISH·MECHANISM,
PERIPHERY·DEPENDENCY) rather than one. `CAUSAL_REASONING` gains a dedicated
owner in SEAM.

---

## 7. Claim → question mapping

Five archetypes, assigned during anatomy. Each defines an **opening move** and a
**preferred ladder**. The planner walks the ladder; the state machine gates it.

| archetype | shape | opening move | ladder |
|---|---|---|---|
| **METRIC_MOVE** | "reduced X from A to B by doing Y" | MEASUREMENT·DERIVATION | → PERIPHERY·EXCLUSION → PERIPHERY·FAILURE → SEAM → TRANSFER |
| **OWNERSHIP** | "owned / managed / led X" | ESTABLISH·FIRST_MOVE | → PERIPHERY·AUTHORITY → PERIPHERY·PEOPLE → PERIPHERY·FAILURE → SEAM |
| **BUILD** | "built / deployed / migrated X with Y" | ESTABLISH·MECHANISM | → PERIPHERY·DEPENDENCY → PERIPHERY·FAILURE → PERIPHERY·EXCLUSION → TRANSFER |
| **PROCESS** | "ran / reviewed / handled X" | ESTABLISH·MECHANISM | → PERIPHERY·AUTHORITY → PERIPHERY·EXCLUSION → PERIPHERY·FAILURE → SEAM |
| **VOLUME** | "handled N of X" | PERIPHERY·AUTHORITY | → ESTABLISH·MECHANISM → PERIPHERY·FAILURE → PERIPHERY·PEOPLE |

**METRIC_MOVE opens on MEASUREMENT, not ESTABLISH.** A quantified claim earns its
measurement question first: the metric is the falsifiable part, and everything
downstream is worth less if the number is undefined.

**VOLUME opens on AUTHORITY** because the volume itself — the N — is exactly what
must not be asked about. The forensic content of a volume claim is the boundary
of what the person was allowed to decide.

---

## 8. Claim state machine

State is per claim, recomputed after every answer from the ledger. **Transitions
are driven by evidence gained, never by question count.**

```
                    ┌────────────┐
                    │ UNTOUCHED  │   no answer yet
                    └─────┬──────┘
        first answer with │ ≥1 MID fact
                    ┌─────▼──────┐
                    │  GROUNDED  │   they have described it in their own words
                    └─────┬──────┘
              ledger has  │ ≥2 DEAR facts on this claim, from ≥2 answers
                    ┌─────▼──────┐
                    │  DETAILED  │   SEAM becomes available
                    └─────┬──────┘
                          │
     2 consecutive answers│ adding 0 DEAR facts
                    ┌─────▼──────┐
                    │  STALLED   │   one TRANSFER, then close
                    └─────┬──────┘
                          │
                    ┌─────▼──────┐
                    │   CLOSED   │   saturated, transferred, or out of budget
                    └────────────┘
```

### Eligible families by state

| state | eligible |
|---|---|
| UNTOUCHED | the archetype's opening move only |
| GROUNDED | ESTABLISH, MEASUREMENT, PERIPHERY (any move whose precondition holds) |
| DETAILED | as GROUNDED, **plus SEAM**; SEAM preferred while unused |
| STALLED | TRANSFER once, then CLOSED |
| CLOSED | none |

A claim may re-enter GROUNDED from STALLED if a TRANSFER answer yields a DEAR
fact. It never re-enters UNTOUCHED.

---

## 9. Planner

Pure function. No model call, no randomness — the same session always produces
the same interview.

```
plan_next(claims, ledger, budget) -> QuestionBrief | None
```

**Selection order, first match wins:**

1. **Breadth.** Any claim in UNTOUCHED → its archetype's opening move. Claims are
   ordered heaviest-first by role weight, as today.
2. **Seam.** Any claim in DETAILED with SEAM unused → SEAM·COHERENCE. Preferred
   over further depth: a coherence test on two established facts is worth more
   than a third independent fact.
3. **Depth.** Heaviest non-CLOSED claim → next unused move on its ladder whose
   precondition holds.
4. **Transfer.** Any STALLED claim → TRANSFER·PERTURB, once.
5. Otherwise `None` — the interview is complete.

### The brief handed to wording

```
QuestionBrief
  claim_id     str
  family       enum
  move         enum
  anchor       str          the phrase the question must name (from anatomy)
  target       str          the incidental detail being hunted
  ledger_facts [LedgerFact] SEAM and TRANSFER only; empty otherwise
  forbidden    [str]        scope markers and metric values that must not appear
  reason       str          why this move on this claim — log and dashboard only
```

`forbidden` is the mechanism that enforces the standing constraint. It carries
`anatomy.metric_value` and `anatomy.scope` verbatim, and the wording prompt is
instructed not to reproduce any of it. `reason` is never sent to the model.

---

## 10. Prompt architecture

### 10.1 System prompt — new, and the largest single gap being closed

Today all four prompts share a generic *"You are a precise information-extraction
service."* The generator is never told what it is for. The new system prompt is
specific to question generation:

> You are a forensic examiner of a written claim, not an interviewer.
>
> A resume claim is a statement made by an interested party about their own
> past. Knowledge is free: anything answerable from search, from a model, or
> from general familiarity with the field is worthless here, because a stranger
> supplies it as well as the author.
>
> What separates them is **incidental detail** — facts that are cheap to recall
> if you were there and expensive to invent if you were not. What had to be left
> out. Who had to be waited on. Which part did not improve. What the number was
> measured against.
>
> You will be given one claim, one forensic move, and one target. Produce one
> question that hunts that target. You choose only the wording.
>
> Before answering, test it: two people reply — one did the work, one read the
> resume ten minutes ago. If the second answers nearly as well, the question is
> wrong. Choose different wording that they could not.
>
> Return only valid JSON. No prose, no markdown fences.

### 10.2 One prompt file per family

Not one template with a switch. Nine move-specific templates under
`api/prompts/forensic/`, each carrying exactly one ask. A multi-ask brief
degenerates to whichever ask is cheapest to satisfy; one ask per file removes the
choice.

Shared skeleton:

```
THE CLAIM
  <claim text>
  What they did:      $mechanism
  What they did it to: $object
  Metric named:        $metric            ← NAME ONLY. Never its value.

YOUR MOVE: <move name>
  <the single ask, three lines, family-specific>

WHAT YOU ARE HUNTING
  $target

ALREADY ESTABLISHED IN THIS INTERVIEW
  $ledger_summary                          ← so it is not re-asked

DO NOT
  - Do not state any of: $forbidden
  - Do not ask how long, how many, team size, or which technologies,
    unless it appears in ALREADY ESTABLISHED above.
  - Do not ask for a definition, an opinion, or what they would generally do.
  - Do not ask two things.

  One question. Under 32 words. Spoken English a sixteen-year-old
  understands, read on a phone. Name the metric, never its value.
  Name the subject, never "that number".

Return: {"question": "...", "target_signal": "...", "reasoning": "..."}
```

`reasoning` and `target_signal` are stored, never shown to the candidate, and
never parsed for a number. They exist so a question's separation argument is
auditable: a question whose reasoning cannot name what a copier would fail to
produce has been phrased, not designed.

### 10.3 Rule 7 as a prompt constraint plus a data constraint

*"Never ask how long / how many people / team size / which technologies"* is
enforced twice: the `DO NOT` block states it, and `forbidden` carries the
extracted `scope` markers so the model cannot reach for them. The exception —
"unless it emerged from a prior answer" — is expressed by `ledger_summary`: a
fact in the ledger may be referred to, because the candidate raised it.

---

## 11. Follow-up generation logic

A follow-up is not a special case. It is the next planner selection against an
updated ledger. What makes it a follow-up is that `ledger_summary` now contains
the previous answer's facts, so the model is structurally unable to re-ask them.

**Three rules govern depth on one claim:**

1. **Never re-target.** A move whose target has produced a DEAR fact is retired
   for that claim.
2. **Escalate cost.** If the last answer yielded only CHEAP facts, the next move
   is chosen from those whose dimensions are not yet covered — preferring
   PERIPHERY, which carries the highest DEAR rate.
3. **Two cheap answers close the claim.** Two consecutive answers adding no DEAR
   fact move the claim to STALLED. Continuing to probe a claim that is not
   producing expensive detail spends budget that another claim would convert.

---

## 12. Cross-question (SEAM) generation logic

SEAM is the only family that reasons over two facts, and the pairing is chosen in
Python.

### Pair selection

Eligible pairs are drawn from the ledger for one claim, subject to:

- the two facts come from **different answers** (a pair inside one answer tests
  nothing — the candidate already reconciled them as they spoke)
- both are MID or DEAR (two CHEAP facts have nothing to hold together)
- they **share a referent** — the same metric, object, tool or named entity

Preferred pair shapes, in order:

| # | shape | example seam |
|---|---|---|
| 1 | causal_link + metric_definition | "You said the script rewrite brought handle time down. How did you know it was that and not the volume drop?" |
| 2 | two metric_definitions expected to co-move | "You said handle time fell. What happened to repeat contacts over the same weeks?" |
| 3 | incident_marker + causal_link | "You said the deploy broke on health checks. How did that square with the rollout finishing on time?" |
| 4 | entity/tool + process_step | "You said the roster tool assigned pods. Who moved someone when it got it wrong?" |

Shape 2 is the highest-value seam and the hardest to fake: real systems have
counter-moving metrics, and a candidate who reports that everything improved in
every dimension has told us the number is decoration.

### Constraints

- The prompt receives **only the two facts and their verbatim quotes**. It cannot
  introduce new subject matter because it has not been given any.
- The question must be unanswerable by repeating either fact. The prompt states
  this; the pair-selection rule (different answers, shared referent) makes it
  achievable.
- **One seam per claim per interview.** A second is a rephrase of the first.

---

## 13. Transfer generation logic

Retains the operator model, re-sourced from the ledger rather than from sibling
claims.

```
TransferSpec
  operator      SUBSTITUTE | INVERT | SCALE
  their_method  str          from a MID/DEAR process_step or causal_link
  variable      str          the ONE thing changed
  basis         str          why this operator and variable — log only
```

| operator | change | source of the variable |
|---|---|---|
| `SUBSTITUTE` | their method, a different subject | another claim's `object` |
| `INVERT` | the number moved against them | their own stated metric name |
| `SCALE` | their world, one quantity multiplied | a ledger quantity (volume, headcount, traffic) |

`SCALE` is new and is the strongest of the three: it changes exactly one variable
inside a world the candidate has just described in their own words, which is what
makes it unanswerable from a resume.

**Constraints.** The variable must come from the ledger — never invented, never
from the resume alone. Asks for reasoning only: where they would start, what they
would check, what would rule a cause out. Never for numbers, tools or results,
because none exist for something that did not happen.

---

## 14. Generation loop

### 14.1 Attempt

Planner → `QuestionBrief` → family prompt → LLM #2 → `validate()`.

### 14.2 Re-target, not re-word

**If validation rejects, the second attempt changes the target, not the
wording.** The planner supplies the next eligible move on the ladder, and the
prompt is rendered fresh. The rejected draft is not shown to the model.

This is deliberate and structural. A retry that says *"you tripped
`answer_leakage`, fix it"* invites the model to satisfy the rule by deleting the
offending token, producing a question that is compliant and no better. Handing
the model a **different target** makes that impossible: the second attempt is a
different question, not a patched one.

There is no third attempt. Two explicit calls, not a loop.

### 14.3 Targeted fallback

Every move has a Python-rendered fallback built from anatomy, not a generic
per-level sentence:

| move | fallback template |
|---|---|
| ESTABLISH·FIRST_MOVE | "You mentioned $mechanism. What was the first thing you looked at?" |
| ESTABLISH·MECHANISM | "Walk me through how $object actually worked, start to finish." |
| MEASUREMENT·DERIVATION | "How was $metric counted — who or what was included?" |
| MEASUREMENT·PROVENANCE | "Besides you, who looked at $metric regularly?" |
| PERIPHERY·EXCLUSION | "Which part of $object did you leave alone?" |
| PERIPHERY·DEPENDENCY | "Who did you have to go to when $object needed something you couldn't change?" |
| PERIPHERY·AUTHORITY | "What could you decide yourself on $object, and what had to go to someone else?" |
| PERIPHERY·FAILURE | "Tell me about a time $object didn't go the way you expected. What happened?" |
| PERIPHERY·PEOPLE | "Who else was in the room when $object went wrong?" |
| SEAM·COHERENCE | "You said $fact_a and $fact_b. How did those fit together?" |
| TRANSFER·PERTURB | "Suppose $variable had changed. What would you check first?" |

**These are real forensic questions, not degraded ones.** They interpolate only
`mechanism`, `object`, `metric` name and ledger quotes — never `metric_value`,
never `scope` — so they satisfy the standing constraint by construction and pass
`validate()` without needing an exemption.

The fallback is still never validated (rule 5 requires a guaranteed path), but it
no longer *needs* the exemption the current generic fallback depends on.

---

## 15. Integration

### 15.1 Where the change lands

| component | change |
|---|---|
| `engine/extract.py` | emits `ClaimAnatomy` alongside each claim; assigns archetype |
| `engine/question.py` | `PROBE_BRIEFS` / `GAP_HINTS` replaced by the family catalogue, per-family prompts, targeted fallbacks |
| `engine/orchestrator.py` | `plan_next` rewritten against state machine + ledger; `select_transfer` re-sourced from the ledger |
| `engine/signals.py` | `FAMILY_DIMENSIONS` added beside `PROBE_LEVEL_DIMENSIONS`; the latter remains for replay |
| `engine/evidence.py` | `_nodes_from` marks probed dimensions from the family, not the probe level |
| `api/prompts/forensic/*` | nine new templates plus the system prompt |
| `api/schemas.py` | **untouched** |
| `engine/question.validate` | **untouched** |
| `engine/scoring.py`, `graph.py`, `consistency.py`, `evaluation.py`, `replay.py` | **untouched** |

### 15.2 Persistence

`questions` gains `family`, `move`, `target_signal` and `reasoning`. Under the
no-Alembic rule this means adding them to `db._REQUIRED_COLUMNS` and re-seeding
with `docker compose down -v`. `probe_level` is retained and written, derived
from the family, so stored history and replay stay readable.

### 15.3 Provenance

`QUESTION_POLICY_VERSION` moves to `qpol_3`. The family catalogue and the
archetype ladders are content that changes which questions get asked, so both
are hashed into the question-policy component of `evaluation_version` exactly as
the validator already is.

### 15.4 The one validator interaction

SEAM names two facts by design and will trip `multiple_fact_targets` when both
are metrics. Rule 3 is **already** not evaluated on TRANSFER, for precisely this
reason — a probe that spans two subjects by construction. SEAM extends that
existing exemption to a second family. No rule is added, modified, or retuned.

### 15.5 Ownership

Every file above is A's under `DEVELOPER_A_CONTRACT.md`. `signals.py` follows the
standing arrangement: A edits, B reviews the hunk. No B-owned file is touched and
`api/schemas.py` needs zero edits.

---

## 16. What this design does not do

Stated so it is not assumed.

- **It does not change scoring.** Rubrics, gates, weights, consistency and the
  graph are untouched. The same answers produce the same numbers.
- **It does not give `CAUSAL_REASONING` a rubric fix.** SEAM gives it a dedicated
  question owner, which is the most a generator can do; whether the extractor
  recognises causal chains is a separate layer.
- **It does not add an impostor-parity gate.** That test is a judgement and runs
  inside the model at generation time. The Python-side control is the DEAR-cost
  ledger, which measures the *answer* and drives the state machine — after the
  fact, not before.
- **It does not change the interview budget.** `MAX_QUESTIONS` and `MAX_CLAIMS`
  keep their meaning; only the allocation across families changes.
