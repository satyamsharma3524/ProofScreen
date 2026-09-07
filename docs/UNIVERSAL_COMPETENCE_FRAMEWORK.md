# Universal Competence Framework — design + migration plan (not implemented)

Design and migration-planning only, per instruction. Nothing in this
document is wired to anything; no code changes accompany it. Where the
design draws on how the current system actually works, it's cited to the
same files this session's other audits already traced
(`docs/PLANNER_ALIGNMENT_AUDIT.md`), so the migration plan is grounded in
real mechanics rather than a clean-slate proposal.

**Framing, stated once so it isn't re-litigated per section:** the current
system's dimensions (SPECIFICITY, PROCESS, METRIC_OWNERSHIP,
CAUSAL_REASONING, AUTHENTICITY, TOOL_FAMILIARITY) are *signal-shaped* — each
one names a kind of evidence a Python rubric can count (a quantity, a named
tool, a causal chain). The six dimensions below are *competence-shaped* —
each one names a kind of capability the evidence should support. That's a
real, non-cosmetic shift: it changes what a rubric has to reason about, not
just what it's called, and Section 4 is explicit about which old signals
transfer directly and which don't exist yet.

---

## 1. The Six Universal Dimensions

### KNOWLEDGE — understanding, not recall

- **Counts:** an explanation of a concept, process, tool, product, or policy
  in the candidate's own words, that includes *why* it works the way it
  does or *why* it applies here — not just naming it. Distinguishing it
  from something similar ("why not X instead"). Correct domain terminology
  used naturally in an explanation, not recited standalone.
- **Does not count:** a textbook definition that could be looked up
  verbatim ("REST is representational state transfer"); repeating a resume
  buzzword with no elaboration; a correct one-word or one-phrase answer
  with no reasoning attached.
- **Why it predicts competence:** you cannot apply what you don't
  understand. It's the weakest predictor of the six in isolation — it's
  memorizable — which is exactly why it should never be the *only*
  dimension a claim is scored on, and why EXECUTION exists as its pair.

### EXECUTION — evidence of personally having done it

- **Counts:** first-person description of the actual mechanics — sequence,
  specific tools/systems, what changed hands — detailed enough that a
  stranger reading only the resume line could not invent it.
- **Does not count:** team-level description with no personal action ("we
  did X"); the claim restated with no elaboration; the textbook/"how it
  should be done" version rather than what they actually did.
- **Why:** distinguishes the person who did the work from someone who
  watched it happen or wrote the resume line about someone else's work. A
  resume claim is trivially copyable; personal execution detail is not —
  this is the one dimension every prior version of this system already
  leaned on (`PROCESS`, `TOOL_FAMILIARITY`), because it's the hardest to
  fabricate cheaply.

### PROBLEM_SOLVING — evidence of handling the exception

- **Counts:** a real, specific moment something didn't go as expected —
  broke, surprised them, didn't fit the normal case — and what they did
  about it.
- **Does not count:** "we always follow the process" with no actual
  exception named; a hypothetical "I would do X" with no evidence they've
  faced it; a success-only narrative with no friction anywhere in it.
- **Why:** most work is routine; competence is revealed at the edges of the
  routine. This maps almost exactly to the current system's `AUTHENTICITY`
  + `FAILURE` pairing, and Part 3 of the prior audit already showed that
  pairing doesn't reliably connect — worth designing around explicitly this
  time (Section 4).

### JUDGMENT — evidence of reasoned choice under constraint

- **Counts:** a real decision point, the alternative(s) actually
  considered, and the criteria used to pick between them — tradeoffs named
  (cost vs. speed, risk vs. reward, one customer's need vs. policy).
- **Does not count:** a decision stated with no alternative or reasoning
  ("I decided to do X," full stop); a generic best-practices answer
  disconnected from their actual situation; a purely after-the-fact
  rationalization with no sign they reasoned about it at the time.
- **Why:** this is what separates "did the job" from "made good calls while
  doing the job" — the dimension most directly relevant to whether someone
  can be trusted with ambiguity, which is most of what a real job actually
  is above the most junior levels.

### OWNERSHIP — evidence of understood scope and accountability

- **Counts:** a clearly named boundary (what was theirs to decide vs. not),
  a specific handoff/escalation/approval moment, or accountability for an
  outcome — including a failure they own without deflecting it.
- **Does not count:** "I owned everything" with no boundary named; a
  supervisor's name with nothing about the boundary itself; total
  deflection ("that wasn't my call") with no account of what *was*.
- **Why:** predicts whether someone understands the actual scope of a role,
  at every seniority level — a junior candidate who names their boundary
  clearly and honestly is a *good* signal here, not a weak one. This is a
  deliberate correction on the current system's `AUTHORITY` move, which
  Part 5 of the prior audit found implicitly rewards *having more*
  decision rights rather than *understanding* the boundary that exists —
  the new dimension is defined around clarity of understanding, not amount
  of authority held.

### ADAPTABILITY — evidence of transferring knowledge to something new

- **Counts:** reasoning transferred from a situation they've already
  described to a different, related one — what changes, what doesn't, and
  why — built on something they already established, not invented from
  nothing.
- **Does not count:** a purely hypothetical answer disconnected from any
  real experience; the same fact restated for a new scenario without any
  reasoning about the difference; "I'd just look it up" style non-answers.
- **Why:** the resume describes the past; the job is the future. This is
  the one dimension that's inherently a little hypothetical — closest in
  spirit to the current (disabled) `PERTURB` move — but it's grounded here
  by requiring the hypothetical to build on the candidate's *own prior
  answer*, not a cold "what if" with no anchor.

---

## 2. Planner Moves

| Move | Target dimension | Evidence expected |
|---|---|---|
| **EXPLAIN** | KNOWLEDGE | The candidate explains a concept/tool/policy/process in their own words, including the *why* |
| **WALKTHROUGH** | EXECUTION | First-person sequence of what they actually did |
| **EXCEPTION** | PROBLEM_SOLVING | A specific moment something didn't go as expected, and the response |
| **CHOICE** | JUDGMENT | A real decision, the alternative considered, and the criteria used |
| **RESPONSIBILITY** | OWNERSHIP | A named boundary, handoff, or accountable outcome |
| **ADAPTATION** | ADAPTABILITY | Reasoning transferred from an established answer to a new, related situation |

### Example questions across four families

| Move | Software Engineering | Customer Support | Sales | Banking Operations |
|---|---|---|---|---|
| **EXPLAIN** | "You mentioned using Redis for caching — why fit that here instead of just querying the database directly?" | "You mentioned handling refunds — what actually qualifies something for a refund versus not?" | "You mentioned enterprise accounts — what actually separates an enterprise deal from a mid-market one, in how you'd approach it?" | "You mentioned KYC checks — what is that check actually trying to catch?" |
| **WALKTHROUGH** | "You mentioned deploying the service — walk me through what you actually did to get it live." | "You mentioned resolving escalations — walk me through what you actually did on the last one." | "You mentioned closing that account — walk me through what you actually did between the first call and the signature." | "You mentioned processing loan applications — walk me through what you actually did from intake to approval." |
| **EXCEPTION** | "You mentioned the API integration — describe a time it broke or didn't behave as expected." | "You mentioned handling calls — describe a time a customer's issue didn't fit any of your normal scripts." | "You mentioned your pipeline — describe a deal that fell apart unexpectedly, and what happened." | "You mentioned account reconciliation — describe a time the numbers didn't match, and what you did." |
| **CHOICE** | "You mentioned choosing React Native — what else did you consider, and what made you pick it?" | "You mentioned de-escalating a customer — what made you choose that approach over just following the script?" | "You mentioned discounting to close — what made you choose that over holding the price?" | "You mentioned flagging that transaction — what made you decide it needed escalation rather than clearing it?" |
| **RESPONSIBILITY** | "You mentioned the migration — what part was entirely yours to decide, and what needed someone else's sign-off?" | "You mentioned resolving tickets — at what point does something stop being yours to fix and go to someone else?" | "You mentioned the account — what could you offer on your own, and what needed manager approval?" | "You mentioned the loan file — what could you approve yourself, and what had to go to underwriting?" |
| **ADAPTATION** | "You said you optimized that query — if a different table had ten times the rows, what would you check first?" | "You said you handle billing complaints — if the same complaint came from a first-time customer instead of a repeat one, what would you do differently?" | "You said you closed that deal with a discount — if the buyer had a smaller budget than that account, what would you try first?" | "You said you flagged that transaction pattern — if it came from a long-standing customer instead of a new one, would your response change?" |

Every example follows the orientation-reminder pattern already shipped
today ("You mentioned X...") — that piece of the current design transfers
unchanged; it's about candidate comprehension, not about which dimension is
being measured, so there's no reason to redesign it.

---

## 3. Reuse / Retire — mapping the current move set onto the new one

| Current move | Maps to | Verdict |
|---|---|---|
| `OPERATING_CONTEXT` | WALKTHROUGH (mostly), some EXPLAIN | **Reuse, retarget.** Already asks "what did you actually do day to day" — closest thing today has to WALKTHROUGH. |
| `FAILURE` | EXCEPTION | **Reuse, direct 1:1.** Cleanest mapping of any current move — the concept is identical, only the scoring pairing changes (Section 4). |
| `DEPENDENCY` | RESPONSIBILITY (mostly), some EXECUTION | **Reuse, retarget.** "What blocked you" is already halfway to "what wasn't yours to control." |
| `AUTHORITY` | RESPONSIBILITY | **Reuse, reframe.** Keep the move, change what a *good* answer looks like — clarity of boundary, not amount of authority (Section 1). |
| `OWNERSHIP_BOUNDARY` | RESPONSIBILITY | **Retire — merges into `AUTHORITY`/RESPONSIBILITY.** Under the current system these are two separate moves feeding two different dimensions (`SPECIFICITY` vs. `CAUSAL_REASONING`); under the new framework they're the same competence question asked twice. Consolidating removes a real redundancy. |
| `METRIC_DEFINITION` | EXPLAIN (mostly), some EXECUTION | **Reuse, retarget.** "How was this actually measured" is a KNOWLEDGE question already; keep it, feed it into EXPLAIN instead of a metric-only dimension. |
| `PEOPLE` | Weak fit — RESPONSIBILITY-adjacent | **Retire.** Never observed firing in any real log gathered this session (per the prior audit); no evidence it's pulling its weight, and RESPONSIBILITY already covers "who was in the loop" better. |
| `COHERENCE` | Not a move — a cross-check | **Retire as a competence-collecting move, keep as a validator.** It doesn't generate new evidence, it tests consistency between two already-collected facts. That's a real and useful thing, but it's a different kind of tool than the other five — it belongs alongside `enforce_verbatim()`/`validate()` as a Python-side consistency check over whatever ADAPTATION/CHOICE/etc. already collected, not as a seventh move competing for one of the six question slots. |
| `EXCLUSION` *(disabled)* | CHOICE-adjacent | **Candidate for revival under CHOICE**, reframed as "what did you deliberately not do, and why" — a real judgment question, just currently retired for demo-scope reasons unrelated to this redesign. |
| `PERTURB` *(disabled)* | ADAPTATION | **Direct 1:1, essentially unchanged in spirit.** The current brief already says "change exactly one thing... do not invent, build on what they said" — that's ADAPTATION's definition almost verbatim. Re-enable under the new name once ADAPTATION is real. |

**Net move count: six new moves, versus today's eight active + two
disabled.** Two retirements (`OWNERSHIP_BOUNDARY`, `PEOPLE`), one demoted
from move to validator (`COHERENCE`), one revival candidate (`EXCLUSION` →
folded into CHOICE), one already-disabled move restored under its new name
(`PERTURB` → ADAPTATION).

---

## 4. Scoring Migration

The current extractor's raw signal vocabulary (`AnswerSignals`:
`quantities`, `process_steps`, `causal_links`, `metric_definitions`,
`incident_markers`, `entities`, `tools`) is largely **family-agnostic
already** — nothing about a `process_step` or an `incident_marker` is
software-engineering-specific. That's the good news: most of the migration
is re-aggregating existing signal types into new dimensions, not building a
new extractor from zero.

| New dimension | Built from | Status |
|---|---|---|
| **EXECUTION** | `process_steps` + `tools` (usage described) + `entities` | **Direct reuse** — nearly identical to today's `PROCESS` + `TOOL_FAMILIARITY` combined |
| **PROBLEM_SOLVING** | `incident_markers` + `causal_links` (complete) | **Direct reuse** — today's `AUTHENTICITY` + `CAUSAL_REASONING` combined |
| **ADAPTABILITY** | `causal_links` + `process_steps` from the ADAPTATION answer specifically | **Direct reuse** — this is exactly how `PERTURB` is credited today (`MOVE_DIMENSIONS[PERTURB] = (CAUSAL_REASONING, PROCESS)`) |
| **JUDGMENT** | `decisions` (choice + reason) | **Half-built already, unwired.** `api/prompts/v2_extract_signals.txt` (written this session, never connected to the live extractor per the earlier wiring audit) already specifies exactly this field: *"A choice they made AND why... `choice` = what they picked... `reason` = why."* This is JUDGMENT's raw material, sitting unused. |
| **KNOWLEDGE** | *(no current field)* | **Real gap.** Nothing in the current schema captures "explained why a concept/tool/process works," only "named a tool" (`entities`/`tools`) or "defined a metric's measurement" (`metric_definitions`). Needs one new extraction field — something like a `concept_explanations` list (`concept`, `reasoning`, `quote`) — genuinely new extraction work, not re-aggregation. |
| **OWNERSHIP** | *(no current field)* | **Real gap.** Nothing today captures "a named boundary between what was theirs and what wasn't" as a structured signal — the current `SPECIFICITY`/`CAUSAL_REASONING` credit an `AUTHORITY` answer incidentally (via whatever entities/causal chains happen to appear in it), not because a boundary was actually named. Needs a new field — something like `boundaries` (`scope_held`, `scope_handed_off`, `quote`). |

**So: four of six new dimensions map cleanly onto existing or
already-specified extraction. Two (KNOWLEDGE, OWNERSHIP) need genuinely new
signal types before they can be scored as anything more than a proxy.**
That's the single most important fact for sequencing the migration
(Section 6) — it's not "redefine six rubrics," it's "redefine four rubrics,
finish one that's already written, and design one from scratch."

---

## 5. Can Six Questions Cover All Six Dimensions?

**Yes — but only with a coverage-complete assignment rule, which is not how
either the current or the demo-mode planner is built.**

The arithmetic is clean: 3 claims (`max_claims`) × 2 questions per claim
(`demo_max_questions_per_claim`) = 6 questions = 6 dimensions. If each claim
is assigned **two distinct dimensions with no repeats across claims** — say
claim 1 gets KNOWLEDGE + EXECUTION, claim 2 gets PROBLEM_SOLVING + JUDGMENT,
claim 3 gets OWNERSHIP + ADAPTABILITY — a 6-question interview covers every
dimension exactly once, guaranteed.

That is a **materially different guarantee than today's system offers**.
The prior audit's Part 6 measured a real 7-question interview where
`METRIC_OWNERSHIP` scored zero, structurally, because claim archetype
(derived from claim verbs, independent of any coverage goal) never happened
to route a `METRIC_DEFINITION` move to any of the three selected claims.
The current archetype-ladder approach optimizes each *claim* for depth on
its own most-relevant moves; it has no mechanism that asks "have all six
dimensions been touched *anywhere* this interview" — that question isn't
representable in the current design at all.

Two open design questions this creates, deliberately left open rather than
resolved here (per "do not implement"):

1. **Which claim gets which dimension pair?** Assigning by claim
   *archetype* (as today) risks repeating the same gap in a new shape — a
   claim with genuinely no judgment-relevant content forced through CHOICE
   produces the same thin, forced answer the current system already
   struggles with for `AUTHORITY` (per the prior audit's Part 4 finding).
   Assigning by claim *strength* (richest claim gets the hardest
   dimensions) is the more promising direction but is itself a ranking
   change, out of scope for a design-only document.
2. **What if a claim is too thin to support two distinct dimensions of
   evidence?** The current system already has this failure mode (a
   generic "team player" line rejected outright at extraction); the new
   framework would need an explicit answer for "a claim survives ranking
   but can't sustain a JUDGMENT question" that doesn't currently exist.

---

## 6. Migration Plan

The codebase already has a proven pattern for exactly this situation:
**three planners coexist today, chosen by settings flag**
(`plan_next` → `plan_next_forensic` → `plan_next_evidence`, gated by
`forensic_questions` / `evidence_planner_v2`), and `v2_forensic_question.txt`
already sat fully written and unwired before it was ever turned on. The
migration plan below is "add a fourth planner behind a fourth flag," not
"replace what exists" — consistent with how every prior version of this
system was actually introduced.

**Phase 0 — Vocabulary only, zero wiring.** Write the six move definitions,
the six dimension rubric *specs* (not code), and one prompt file per move
family (or one parameterized template, following `v2_forensic_question.txt`'s
pattern of a single template with a `$target_evidence` slot). Nothing
imports it. Zero risk, matches how every prior prompt in this repo started.

**Phase 1 — Finish the one dimension that's half-built.** Wire
`v2_extract_signals.txt`'s `decisions` field (already written, per the
earlier wiring audit) into a real extraction call, and add `concept_explanations`
and `boundaries` as two new fields on the same schema, for KNOWLEDGE and
OWNERSHIP respectively. This is the one piece of *actual new extraction
design* the whole migration needs — everything else in Section 4 is
re-aggregation of what's already extracted today.

**Phase 2 — New rubrics, parallel module.** A new `competence_signals.py`
(name illustrative), parallel to today's `signals.py`, computing the six new
`DimensionScore`s from the Phase 1 schema. Doesn't touch `signals.py` —
the same "the old path stays reachable" principle every settings flag in
this codebase already follows.

**Phase 3 — New planner, new flag.** A `competence_framework` (or similar)
setting, defaulting False, selecting a new `plan_next_competence()` — the
claim-to-dimension-pair assignment from Section 5 lives here. This is where
the two open design questions in Section 5 need real answers before this
phase can be built, not before Phase 0-2.

**Phase 4 — Validate across families before touching a default.** Run real
interviews (not fixture-mode) across a representative resume from each of
the ten listed families, specifically checking: does every dimension
receive at least one genuine attempt per interview (the Section 5 promise),
and does EXPLAIN/CHOICE/RESPONSIBILITY produce meaningfully different
question text for, say, Banking Operations versus Software Engineering, or
does the template genericize toward the same wording regardless of family
(a failure mode the current system already has evidence of — the prior
audit's Part 3 found several moves converging on one dominant sentence
frame across unrelated claims).

**Phase 5 — Only after Phase 4, consider a default flip.** Exactly the same
gate every other planner change in this codebase has waited for (v2 is
still off by default after being fully built; Demo Mode was validated
end-to-end before being trusted). Nothing here should default on before
that validation exists, and this document takes no position on whether it
ever should — that's the sign-off Section 5 explicitly leaves open.

No step above requires removing or rewriting `plan_next_forensic`,
`signals.py`, or the existing Move enum — every one of them keeps running,
unmodified, for as long as their own flags stay on. That's the same
non-negotiable this session's other design work (Demo Mode) was built
under, carried forward here by construction rather than by promise.
