# Question Evaluation Harness + Candidate-Level Interview Model

Design-only audit and implementation proposal. Nothing implemented. Builds
on `docs/QUESTION_SYSTEM_AUDIT.md` and `docs/CANDIDATE_LEVEL_AUDIT.md`
(same session) — this document adds the two things those didn't have: an
independent, competence-blind question-quality harness, and a level model
whose move-mapping turns out to connect directly back to what this
session already disabled.

---

## Part A — Question Evaluation Harness

### A1. Current question generation pipeline (what already exists to build on)

`generate_forensic_question()` (`question.py:1479+`) already produces
exactly the raw material a quality harness needs, and **already persists
all of it** — no new instrumentation required to start:

- `Question.text` — the generated question, final form.
- `Question.move`, `Question.probe_level` — what it was targeting.
- `Question.source` — `model` / `regenerated` / `fallback` / `thread` /
  `repair` (this session's addition).
- `Question.attempts`, `Question.violations_json` — whether `validate()`'s
  7 rules passed first try, and which failed if not.
- The parent `Claim.text` is one join away.

This is precisely the same raw material `scripts/interview_study.py`
(Phase 3) already reads to measure `validate()`'s real-world reject rate —
**this harness is that same methodology, generalized to a richer rubric.**

### A2. Best insertion point

**Recommendation: offline only, reading already-persisted `Question` rows.
Not during generation, not synchronously after generation.**

Reasoning, not just a preference:

- **During generation** (as a live gate before sending) would mean a
  second LLM call in the hot path of every single candidate-facing
  question — direct latency cost against the same "+20% median-turn-
  latency" guardrail that already caps `validate()`'s regeneration at
  exactly one retry, and it doubles live-interview LLM cost for every
  turn, not just the ones worth checking.
- **Synchronously after generation** (scored before the send, but not
  gating it) still adds latency to the turn unless explicitly moved to a
  background task — and if it's a background task anyway, there's no
  reason it needs to run per-interview rather than in a periodic batch;
  the codebase already has a working precedent for exactly this
  decoupling (`SCORE_INLINE=false` moves signal extraction to a
  background task rather than the live turn).
- **Offline** costs nothing per candidate interaction, can be run against
  a sample instead of every question, can use a cheaper/faster judge model
  since nothing live is waiting on it, and — most importantly — keeps a
  second model's subjective 1-5 opinion **out of the live decision path**,
  consistent with the same "the model produces, Python decides" posture
  CLAUDE.md states for scoring generally. A live quality-gate would be a
  softer version of the exact anti-pattern that principle exists to avoid.

### A3. Cost implications

Offline, sampled: cost is incurred only when the harness is run, is fully
metered (run over yesterday's transcripts, or a random 10% sample, or only
the moves being actively iterated on), and can use a smaller/cheaper model
for the judge since nothing live depends on its latency. This is the same
cost shape Phase 3's study already had — `$3.67` for 519 questions,
`scripts/interview_study.py`'s own measured total.

### A4. Logging implications

None required for a v1 — the harness reads existing `questions`/`claims`
rows, unmodified. Its own *output* (the 7-axis scores + a short reasoning
string per question) should land in `studies/`, matching this repo's
existing convention (`studies/phase3/`), not in a live table — keeping it
symmetric with Phase 3's explicit acceptance criterion that the study
phase never modifies `api/`.

### A5. Minimal implementation path

1. One new prompt file (e.g. `api/prompts/question_quality_judge.txt`)
   taking `claim_text`, `move`/`target`, and the generated `question`, and
   returning the seven requested axes as structured JSON — a **new,
   local-to-the-script Pydantic model**, not an addition to the frozen
   `api/schemas.py`, mirroring the same "local to this module" pattern
   `RoleClassification` already uses for exactly this reason.
2. One new standalone script, `scripts/question_quality_harness.py`,
   modeled directly on `scripts/interview_study.py`: query `Question` rows
   (optionally filtered by date range, session, or move), join `Claim` for
   context, call the judge prompt once per row, write results to
   `studies/question_quality/`.
3. **Zero changes to `api/`.** Same acceptance criterion Phase 3 held
   itself to.
4. A follow-up question this design deliberately leaves open, since it's
   an implementation decision, not an audit finding: whether to run this
   as a one-time study (Phase-3-shaped) or a recurring scheduled job. Both
   are equally "offline" from the live path's perspective; the choice is
   about how continuously you want quality drift caught, not about
   architecture.

**What this harness is *for*, stated plainly:** it's a measurement tool
for catching the next `AUTHORITY`/`OWNERSHIP_BOUNDARY`-style wording defect
before a human has to notice it by reading logs, the way every fix this
session came from someone reading transcripts by hand. It is explicitly
not proposed as a live gate, and it does not touch competence scoring —
matching the instruction not to evaluate competence dimensions at all.

---

## Part B — Candidate-Level Interview Model

The requested ladders map cleanly onto real moves for two of three levels
— and reveal something worth stating plainly for the third: **the Senior
ladder (`tradeoffs → judgment → failure → ambiguity`) maps almost exactly
onto the three moves this session disabled for everyone.** `EXCLUSION`
("what did you deliberately not do") is a tradeoff question. `AUTHORITY`
("what could you decide independently") is a judgment question. `PERTURB`
("one variable changed, reason it through") is an ambiguity question.
Disabling them under Demo Mode wasn't "these questions are bad" — per this
session's own measurements, `AUTHORITY` produced the single richest real
answer of any move measured. It was "these questions are unfair as
*unconditional defaults* for a candidate whose level is unknown." That's
precisely the gap `docs/CANDIDATE_LEVEL_AUDIT.md`'s `LEVEL_RESTRICTED`
proposal exists to close — this document reuses it rather than designing
a second mechanism.

### Junior

- **Evidence to collect:** did they personally implement the work, what
  was their specific contribution, which tools they actually used and how.
- **Early questions:** `OPERATING_CONTEXT` (implementation), `OWNERSHIP_BOUNDARY`
  in its reworded, contribution-framed form (contribution), `DEPENDENCY`
  (the closest existing move to "tools" — it reliably surfaces
  `TOOL_FAMILIARITY` signal alongside its own dependency-moment target;
  there is no dedicated "tools" move today, `TOOL_FAMILIARITY` is a scored
  dimension, not a move — noted rather than papered over).
- **Late/never:** nothing from this ladder needs to be late for Junior —
  all three are Difficulty 1-2, per the prior audit's real-log evidence.
- **Disallowed moves:** `AUTHORITY`, `EXCLUSION`, `PERTURB`, `COHERENCE` —
  all four either assume authority a junior role may never have granted,
  or (per `COHERENCE`'s one real example) are dense enough to produce
  confusion rather than evidence regardless of level.

### Mid

- **Evidence to collect:** everything Junior collects, plus real decisions
  made and the boundary of what was theirs to own.
- **Early questions:** `OPERATING_CONTEXT` (implementation, same as
  Junior — a universal opener costs nothing).
- **Later questions:** **`decisions` has no clean home in the current live
  move set — a genuine gap, not one this document is going to paper over
  with a forced fit.** `EXCLUSION` ("what did you deliberately not
  change, and what constraint kept it that way") is the closest existing,
  already-built move — it's currently disabled entirely, for every
  candidate. Re-enabling it specifically for Mid+ is the proposal here,
  not inventing a new move. `OWNERSHIP_BOUNDARY` covers `ownership`
  directly, already live.
- **Disallowed moves:** `AUTHORITY` and `PERTURB` still — a Mid-level
  candidate's decision-rights are plausibly still narrow enough that
  "what could you decide independently" risks the same unfair-thinness
  problem as it does for Junior; `EXCLUSION` is the one disabled move
  this level model recommends opening up for Mid, not all three.

### Senior

- **Evidence to collect:** tradeoffs actually weighed, judgment exercised
  under ambiguity, a real failure recalled and reasoned through, and
  reasoning that extends past what literally happened.
- **Early/any-order questions:** all four are fair game at this level —
  `EXCLUSION` (tradeoffs), `AUTHORITY` (judgment), `FAILURE` (already
  live, no change needed), `PERTURB` or `COHERENCE` (ambiguity — `PERTURB`
  is the more direct match to "reasoning under a changed condition";
  `COHERENCE` is the closer match to "reconciling two things already
  said," which is a different but related kind of ambiguity-handling).
- **Disallowed moves:** none — a Senior candidate should be able to
  handle every move in the current set; `OPERATING_CONTEXT` remains a
  reasonable universal opener even here, not because it's required, but
  because it costs nothing and still warms up the exchange.

---

## Exact Move Mappings

| Level | Requested step | Mapped move | Status today |
|---|---|---|---|
| Junior | implementation | `OPERATING_CONTEXT` | Live |
| Junior | contribution | `OWNERSHIP_BOUNDARY` (reworded) | Live |
| Junior | tools | `DEPENDENCY` (closest proxy — no dedicated "tools" move exists) | Live |
| Mid | implementation | `OPERATING_CONTEXT` | Live |
| Mid | decisions | `EXCLUSION` | **Disabled — proposed re-enable, Mid+ only** |
| Mid | ownership | `OWNERSHIP_BOUNDARY` | Live |
| Senior | tradeoffs | `EXCLUSION` | **Disabled — proposed re-enable, Mid+ only** |
| Senior | judgment | `AUTHORITY` | **Disabled — proposed re-enable, Senior only** |
| Senior | failure | `FAILURE` | Live, no change |
| Senior | ambiguity | `PERTURB` (or `COHERENCE`) | **Disabled (`PERTURB`) / Live (`COHERENCE`) — proposed re-enable `PERTURB`, Senior only** |

## Exact Planner Changes

Everything here is additive to the `LEVEL_RESTRICTED` mechanism already
proposed in `docs/CANDIDATE_LEVEL_AUDIT.md` — no second mechanism, just
its allow-list populated further:

```python
# Illustrative only -- not proposing to add this now.
LEVEL_RESTRICTED: dict[Move, frozenset[str]] = {
    Move.COHERENCE:  frozenset({"senior"}),
    Move.FAILURE:    frozenset({"mid", "senior"}),
    Move.METRIC_DEFINITION: frozenset({"mid", "senior"}),
    Move.EXCLUSION:  frozenset({"mid", "senior"}),   # re-enabled, gated
    Move.AUTHORITY:  frozenset({"senior"}),           # re-enabled, gated
    Move.PERTURB:    frozenset({"senior"}),           # re-enabled, gated
}
```

Plus removing `Move.EXCLUSION` and `Move.AUTHORITY` from the unconditional
`demo_mode` disable list in `forensic_moves_left()` (they'd now be handled
by `LEVEL_RESTRICTED` instead — for `seniority=None`, `level_appropriate()`
already returns `True` unconditionally per the prior document's design,
so an **unknown-level candidate would suddenly see these moves again**
unless the disable list is *replaced* by the level gate rather than simply
supplemented by it. This is the one real subtlety in combining the two
documents' proposals, named here precisely because it's exactly the kind
of interaction that's cheap to get wrong: for unknown seniority, the
*old* demo_mode blanket disable should still apply; only a *confident*
`mid`/`senior` classification should unlock them. That means
`level_appropriate()` needs a `demo_mode`-aware default (disabled when
`seniority is None`) rather than the permissive default proposed for the
narrower `COHERENCE`/`FAILURE`/`METRIC_DEFINITION` case — worth flagging
as a design decision to make deliberately, not inherit by accident.

`settings.transfer_probe` would also need to move from a blanket
True/False into something `PERTURB`-specific rather than global, since
today it's the only thing gating `PERTURB`'s entire stall-branch — a
slightly bigger touch than the other three, and worth calling out as the
one part of this proposal that isn't a pure filter-table addition.

## Minimal Implementation Path

Same four-step plumbing already specified in `docs/CANDIDATE_LEVEL_AUDIT.md`
(widen `classify_role`'s return, one optional `Candidate.seniority` column,
the `level_appropriate()` filter, one added clause in
`forensic_moves_left()`), plus:

5. Populate `LEVEL_RESTRICTED` with the six-move table above instead of
   the narrower three-move version.
6. Resolve the default-direction subtlety above: `level_appropriate()`
   must know that `EXCLUSION`/`AUTHORITY`/`PERTURB` default to *disabled*
   when seniority is unknown (preserving today's Demo Mode behavior
   exactly), while `COHERENCE`/`FAILURE`/`METRIC_DEFINITION` keep their
   *permissive* unknown-default (they were never blanket-disabled, only
   level-preferenced).
7. Give `PERTURB` its own settings flag (or fold its stall-branch check
   into the same `level_appropriate()` call) rather than leaving it keyed
   to the global `transfer_probe`.

## Migration Sequence

1. Ship the seniority plumbing alone (steps 1-4 above) — zero behavior
   change, `seniority` simply becomes readable where it wasn't before.
2. Add `level_appropriate()` scoped to exactly today's Demo Mode set
   (`COHERENCE`/`FAILURE`/`METRIC_DEFINITION`) — still zero behavior
   change for any candidate, confirms the plumbing works before touching
   anything that's currently disabled.
3. Re-enable `EXCLUSION` for `{"mid", "senior"}` only — the smallest,
   lowest-risk of the three disabled moves to bring back (never measured
   as high-variance the way `AUTHORITY` was; simply never fired in any
   real log this session).
4. Validate against real Mid/Senior-classified candidates before doing
   anything else — the same discipline this session held every other
   change to.
5. Only after 3-4 are validated, re-enable `AUTHORITY` and `PERTURB` for
   `{"senior"}` only — these are the two moves with the most measured
   variance and risk, so they go last and narrowest.
6. Build the Question Evaluation Harness (Part A) around this same
   moment, specifically because `EXCLUSION`/`AUTHORITY`/`PERTURB` are
   exactly the moves this session's manual log-reading found the most
   wording problems in historically — an automated, continuous check is
   most valuable exactly where the riskiest moves are being reintroduced.

## Expected Effect on Real Interview Quality

- **Junior and unknown-seniority candidates: no change.** The entire
  design is built so the common case (seniority absent or unclear) is a
  no-op at every step.
- **Confidently-classified Mid/Senior candidates: richer, more
  differentiating evidence** on exactly the axes (`decisions`, `judgment`,
  `tradeoffs`, `ambiguity`) the current Demo Mode set structurally cannot
  reach at all — not more questions, since the per-claim cap and global
  6-question ceiling are untouched; a *harder pairing* within the same
  budget.
- **Named risk, not hidden:** seniority is self-reported and can be wrong
  or absent. A misclassified junior-as-mid candidate could still receive
  a question their real role never prepared them for. The conservative
  unknown-default limits the *blast radius* of that risk to
  confidently-classified candidates only — it does not eliminate it, and
  no version of this proposal can, since the underlying signal is a
  resume's own self-description, not a verified fact.
