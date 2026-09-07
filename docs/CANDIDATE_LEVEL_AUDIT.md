# Candidate-Level Appropriateness Audit + Minimal Level-Awareness Proposal

Audit and design proposal only — nothing implemented. Builds on
`docs/QUESTION_SYSTEM_AUDIT.md` (same session, same real-log evidence base)
and extends it exactly where asked: a third ladder position, an explicit
Junior/Mid/Senior model, and a concrete minimal-change proposal for
level-aware selection, scoped strictly to selection per the stated
constraints.

---

## 1. First Three Questions Per Archetype, Today

**Caveat that has to come first:** under `demo_max_questions_per_claim=2`,
**no claim ever reaches a third real question today.** Position 3 in every
ladder below is real (it's the actual next entry `ClaimState.forensic_moves_left()`
would offer), but it is currently unreachable in production — shown here
because the audit asks for it, not because it fires.

| Archetype | Q1 | Q2 | Q3 *(unreachable under current cap)* |
|---|---|---|---|
| **BUILD** | `OPERATING_CONTEXT` | `DEPENDENCY` | `FAILURE` |
| **OWNERSHIP** | `OPERATING_CONTEXT` | `OWNERSHIP_BOUNDARY` | `FAILURE` |
| **PROCESS** | `OPERATING_CONTEXT` | `FAILURE` | `COHERENCE` |
| **METRIC_MOVE** | `METRIC_DEFINITION` | `FAILURE` | `COHERENCE` |
| **VOLUME** | `OPERATING_CONTEXT` | `FAILURE` | `PEOPLE` |

## 2. Per-Question Analysis

| Archetype | # | Move | Difficulty | Evidence yield | Junior | Mid | Senior |
|---|---|---|---|---|---|---|---|
| BUILD | 1 | OPERATING_CONTEXT | 1 | High | ✓ | ✓ | ✓ |
| BUILD | 2 | DEPENDENCY | 2 | High | ✓ | ✓ | ✓ |
| BUILD | 3 | FAILURE | 3 | Moderate | △ | ✓ | ✓ |
| OWNERSHIP | 1 | OPERATING_CONTEXT | 1 | High | ✓ | ✓ | ✓ |
| OWNERSHIP | 2 | OWNERSHIP_BOUNDARY | 2 | High | ✓ | ✓ | ✓ |
| OWNERSHIP | 3 | FAILURE | 3 | Moderate | △ | ✓ | ✓ |
| PROCESS | 1 | OPERATING_CONTEXT | 1 | High | ✓ | ✓ | ✓ |
| PROCESS | 2 | FAILURE | 3 | Moderate | △ | ✓ | ✓ |
| PROCESS | 3 | COHERENCE | 4-5 | Low (1 real example: candidate confusion) | ✗ | △ | ✓ |
| METRIC_MOVE | 1 | METRIC_DEFINITION | 3 | Unmeasured live (never fires in real logs) | △ | ✓ | ✓ |
| METRIC_MOVE | 2 | FAILURE | 3 | Moderate | △ | ✓ | ✓ |
| METRIC_MOVE | 3 | COHERENCE | 4-5 | Low | ✗ | △ | ✓ |
| VOLUME | 1 | OPERATING_CONTEXT | 1 | High | ✓ | ✓ | ✓ |
| VOLUME | 2 | FAILURE | 3 | Moderate | △ | ✓ | ✓ |
| VOLUME | 3 | PEOPLE | 1 *(too easy)* | Low (both real examples: bare name, zero signal) | ✓ | ✓ | ✓ |

---

## 3. Candidate-Level Interview Model

### Junior

- **Evidence to collect:** did they *personally* do the concrete work, and
  can they describe it in their own words. Execution and contribution
  (`OPERATING_CONTEXT`, `OWNERSHIP_BOUNDARY` in its reworded, contribution-
  framed form, `DEPENDENCY`) are exactly right — none of them assume prior
  authority, a war-chest of incidents, or ownership of measurement design.
- **Questions to ask:** the three Difficulty-1/2 moves above, in that
  order. A junior candidate's honest, complete answer to any of them is a
  real signal, not a thin one.
- **Never ask early:** `COHERENCE` (real evidence this session: it produced
  confusion, not evidence, from a candidate with no seniority markers) and
  `FAILURE`/`METRIC_DEFINITION` **as an opener** — not because a junior
  candidate can't eventually answer them, but because a junior role
  plausibly never included ownership of a "failure worth telling" or a
  metric's actual measurement design, and asking cold penalizes a true
  "I haven't been in that position yet" with the same thin score as an
  evasive answer would get.

### Mid

- **Evidence to collect:** everything Junior collects, plus early signs of
  judgment and problem-solving — `FAILURE` (real incident recall) and
  `METRIC_DEFINITION` (do they understand *how* something is measured, not
  just that a number moved) both become fair asks once there's reason to
  believe the candidate has owned enough to have answers.
- **Questions to ask:** all five moves in the table are fair game for Mid,
  in roughly the order shown — Difficulty 1-2 first, 3 second.
- **Never ask early:** `COHERENCE` still shouldn't open or sit in the
  middle — its precondition (two already-established facts to cross) makes
  it structurally a late question regardless of level, and the one real
  example available suggests it needs a confident, senior-level candidate
  to land at all.

### Senior

- **Evidence to collect:** everything above, plus judgment under ambiguity
  and the ability to reconcile multiple things they've said into one
  coherent picture — `COHERENCE` is a genuinely senior-shaped ask, and (if
  ever re-enabled) `AUTHORITY`/`PERTURB` are too: a senior candidate's
  honest answer to "what could you decide independently" or a grounded
  hypothetical is a real differentiator, where the same question penalizes
  a junior candidate for their level rather than their competence.
- **Questions to ask:** any move, any order — `OPERATING_CONTEXT` is still
  a reasonable universal opener (it costs nothing and warms up any
  candidate), but nothing needs to be withheld past that.
- **Never ask early:** nothing needs categorical protection at this level;
  the concern for Junior/Mid is candidates being asked something their
  role never gave them the material to answer, which is far less likely
  to be true for a senior candidate on their own claims.

---

## 4. Per-Move Table — Level Fit and Position

| Move | Difficulty | Evidence yield | Best level | Worst level | Recommended position |
|---|---|---|---|---|---|
| **OPERATING_CONTEXT** | 1 | High | All — no best/worst, universally safe | None | **Opener**, any level |
| **DEPENDENCY** | 2 | High | Junior, Mid (a relatable "what blocked you") | None particularly bad | **Opener or middle**, any level |
| **OWNERSHIP_BOUNDARY** | 2 | High *(post-rewording)* | Junior (this was the specific fix's intent) | None now | **Opener or middle**, any level |
| **FAILURE** | 3 | Moderate | Mid, Senior (richer incident history to draw from) | Junior (may not have a "big" one yet; honest thinness looks identical to evasion) | **Middle**, not an opener for Junior specifically |
| **METRIC_DEFINITION** | 3 | Unmeasured live | Mid, Senior (measurement ownership is a real differentiator at these levels) | Junior (may genuinely never have owned metric derivation) | **Middle/late** for Junior; **opener-eligible** for Senior on a metric-bearing claim |
| **PEOPLE** | 1 *(too easy)* | Low — both real examples measured zero signal | None confidently — Red regardless of level | All levels equally (produces a bare name from anyone) | **Late**, if kept at all — see the prior audit's quality finding |
| **COHERENCE** | 4-5 | Low (1 real example: confusion, not evidence) | Senior only, on current evidence | Junior | **Late only**, and only reachable once two facts already exist — already structurally late by its own precondition |

---

## 5. Smallest Possible Architecture Change

**The lever already exists and is already computed — it's just discarded.**
`api/engine/extract.py:413` (`classify_role`, LLM call #0) already extracts
`seniority` (junior/mid/senior, self-reported from the resume's own
framing) into a local `RoleClassification` object. Per its own docstring
(`extract.py:398-403`), it is deliberately never branched on — but it is
also, as a separate and purely mechanical fact, **never returned**:
`classify_role()`'s signature is `-> str` (line 413), and the only thing
that survives past the function body is the chosen family string
(`return chosen`, line 447). `result.seniority` is read once, for a log
line, then the whole object goes out of scope.

**This means the smallest change has almost nothing to do with candidate
*level* per se — it's a plumbing gap, not a missing capability.** Nothing
about extraction's *logic* needs to change; only what it *returns*.

### The four-part minimal path, in order

1. **Widen `classify_role`'s return** from `-> str` to a small tuple or
   NamedTuple carrying `(family, seniority)` — one line changed, the LLM
   call itself untouched. Its one caller, `extract_claims()` (`extract.py:491`),
   already destructures a similar shape and needs one more field threaded
   through its own return.
2. **One new optional column** — `Candidate.seniority: str | None`,
   defaulted `None` — following the exact `_REQUIRED_COLUMNS` pattern
   CLAUDE.md documents for adding a column under `create_all()`. This is
   the one piece that touches `api/schemas.py`, which is frozen and
   two-owner — an optional, defaulted field is "a conversation," per rule
   2, not a redesign; Phase 4 already added optional fields to `HealthOut`/
   `OutcomeOut` this same way.
3. **One new pure filter function**, the same shape as the `demo_mode`
   EXCLUSION/AUTHORITY filter already living in
   `ClaimState.forensic_moves_left()`:

   ```python
   # Illustrative only -- not proposing to add this now.
   LEVEL_RESTRICTED: dict[Move, frozenset[str]] = {
       Move.COHERENCE: frozenset({"senior"}),
       Move.FAILURE: frozenset({"mid", "senior"}),
       Move.METRIC_DEFINITION: frozenset({"mid", "senior"}),
   }

   def level_appropriate(move: Move, seniority: str | None) -> bool:
       if seniority is None:          # the common case -- self-reported,
           return True                 # often absent -- changes nothing
       restriction = LEVEL_RESTRICTED.get(move)
       return restriction is None or seniority in restriction
   ```

4. **One added condition** in `forensic_moves_left()`'s existing list
   comprehension — literally the same line shape the `demo_mode` filter
   already added this session, just one more `and` clause.

**Why this is the minimum, not just *a* minimum:** step 1 touches zero
lines of extraction *logic* (only its return signature); step 2 is one
optional column, not a new table or a new pipeline; step 3 is a
standalone, zero-dependency pure function; step 4 is one boolean clause in
a filter that already exists and already does exactly this kind of
gating for a different reason (`demo_mode`). Nothing above requires a new
planner, a new scoring pass, a new claim concept, or a new dimension —
matching every constraint given. And critically: **when `seniority` is
`None` — the realistic default, since it's self-reported and often
missing or unclear — every one of the four steps is a no-op**, so shipping
this incrementally never risks behavior for a candidate the system isn't
confident about, which is the same conservative posture CLAUDE.md's rule 1
already asks for everywhere else a model's self-report shows up.

Nothing here is proposed as ready to build — it's the shape the smallest
change would take if and when the level-awareness gap gets prioritized.
