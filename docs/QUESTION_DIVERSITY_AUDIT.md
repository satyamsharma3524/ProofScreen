# Question Generation Diversity — Audit + Design (no implementation)

Audit only, per instruction. Nothing in this document has been implemented.
Scope is deliberately narrow: **how questions are phrased**, not what evidence
they target. Planner logic, move selection, `engine/scoring.py`,
`engine/evidence.py`, `engine/graph.py` and the eval harnesses are untouched
by everything proposed here — every change below is confined to the
generation layer (`api/engine/question.py` and its two prompt files).

## 1. Audit — where the repetition actually comes from

Three independent sources, not one. All three currently produce the exact
"What happened / What did you do / Can you walk me through" pattern you
flagged, for three different reasons.

### 1a. A single shared instruction line, duplicated in both live prompts

`api/prompts/forensic_question.txt:64-65` and
`api/prompts/v2_forensic_question.txt:137-138` — **byte-identical text in
both files**:

> "Never ask for a definition, an opinion, or what they would generally do.
> Ask what happened, what they did, what they chose, what broke."

This is the direct textual source of the narrow vocabulary. It's a real,
necessary constraint (don't ask for opinions or definitions) written as a
closed list of FOUR sanctioned openers. Every model call for every move goes
through this same instruction, so the model has been told, explicitly and
repeatedly, that these four phrasings are the safe ones. This is the
highest-leverage fix in this audit: one line, present in both prompts,
shapes phrasing for 100% of model-generated questions regardless of move.

### 1b. Deterministic fallback templates — one fixed string per move, forever

`api/engine/question.py:1433` — `MOVE_FALLBACKS: dict[Move, Template]`. Each
move maps to exactly ONE template, used every time the model is unavailable
or rejects twice (CLAUDE.md rule 5 — this is production code, not a stub, and
in fixture mode it is the ONLY path, so every fixture-mode interview asks the
literal same sentence per move, always):

| Move | Fallback (verbatim, every time) |
|---|---|
| `OPERATING_CONTEXT` | "When you were working on $object, what did you look at first?" |
| `FAILURE` | "Tell me about a time $object did not go the way you expected. **What happened?**" |
| `DEPENDENCY` | "Who or what did you have to rely on most while working on $object?" |
| `AUTHORITY` | "On $object, what could you decide yourself and what had to go to someone else?" |
| `EXCLUSION` | "Which part of $object did you leave alone, and what made you leave it?" |

These are what actually showed up verbatim in this session's own smoke-test
logs and in the real production log you shared earlier — this table is not
hypothetical, it's what the system produces today. `FALLBACK_QUESTIONS`
(`question.py`, probe-level generator, dormant while `forensic_questions=True`)
and `_evidence_fallback` (`question.py:1806`, v2 generator, dormant while
`evidence_planner_v2=False`) have the identical structural problem — one
fixed template each, `_evidence_fallback` worse (ONE generic template shared
across ALL nine v2 categories: `'On "$claim" — tell me more about the $topic
involved.'`).

### 1c. `validate()`'s `duplicate_content` rule is scoped to ONE interview

`question.py:560-562` checks Jaccard similarity against `prior_questions`,
which `ask_next()` populates from **this session's own prior turns only**.
It cannot see, and was never designed to see, that FAILURE has asked "what
happened?" in 400 other interviews this week. The repetition you're
describing is invisible to the validator by construction — it is not a bug
in `duplicate_content`, it is a rule solving a different problem (don't ask
the same candidate the same thing twice), and no existing mechanism solves
the one you're raising (don't sound like a form letter across candidates).

### One deliberate exception, called out so it isn't "fixed" by accident

`REPAIR_PROMPTS` (`question.py:652`) is ALSO one fixed string per probe level
("Could you give me the steps? What did you actually do, in what order?"),
and it is fixed **on purpose**, with its own comment saying so: *"NO MODEL
CALL. There is nothing to word creatively... a fixed line is easier to defend
on stage than a generated one."* This is a repair turn, off-budget, meant to
be the plainest possible restatement after a non-answer — diversifying it
trades a small amount of "sounds mechanical" against CLAUDE.md's own stated
demo-safety reasoning for keeping it invariant. Flagged as a decision for
you, not folded into the plan below.

## 2. Exact files/prompts to change

| File | What changes |
|---|---|
| `api/prompts/forensic_question.txt` | Replace the closed 4-opener line (§1a) with an instruction to vary phrasing, plus one new `$style_hint` slot |
| `api/prompts/v2_forensic_question.txt` | Same replacement (kept in sync — it's currently a literal duplicate of the same line) |
| `api/engine/question.py` — `MOVE_FALLBACKS` | Widen from `dict[Move, Template]` to `dict[Move, tuple[Template, ...]]`, 3-4 phrasings per move |
| `api/engine/question.py` — `_evidence_fallback` | Same widening, per `EvidenceCategory` (currently the single worst offender — one template for nine categories) |
| `api/engine/question.py` — new `QuestionStyle` enum + selector | New, additive. Not a modification to `Move`, `Archetype`, `ARCHETYPE_LADDER`, or anything the planner reads |
| `api/engine/question.py` — `generate_forensic_question` / `_forensic_prompt` (and the v2 counterpart) | Thread the chosen style into the existing prompt-render call as one more template variable — no new function signature the orchestrator has to know about beyond what's already passed through `plan` |

Nothing in `api/engine/orchestrator.py` needs to change. The style is a
phrasing choice made **inside** question generation, from data the generator
already receives (`claim`, `move`, `anatomy`) — it does not need move
selection, session state, or a new field on `Plan`/`ClaimState`.

## 3. Minimal implementation plan (not yet built)

1. **`QuestionStyle` enum** — `chronological`, `decision_focused`,
   `incident_focused`, `artifact_focused`, `observation_focused`,
   `reconstruction`, `retrospective`, matching your list.
2. **A small, per-move allow-list**, same shape as `MOVE_DIMENSIONS` already
   in this file: not every style fits every move (`decision_focused` on a
   `FAILURE` move doesn't make sense; `incident_focused` on `AUTHORITY`
   doesn't either). A `dict[Move, tuple[QuestionStyle, ...]]` constant, same
   pattern already established for `MOVE_DIMENSIONS`/`MOVE_PROBE_LEVEL`.
3. **Deterministic selection, not random.** `random.choice` would reintroduce
   the exact class of bug this repo already found and fixed once — recall
   CLAUDE.md's note that the generated fixture "is not a pure function of the
   seed data" turned out to depend on machine-id length, and that non-determinism
   was treated as a real defect, not a shrug. The style should be selected by
   something already stable and available — e.g. a hash of `(claim.id, move)`
   — so the same claim+move always renders the same style in fixture mode and
   in tests, and reseeding produces byte-identical fixtures.
4. **One new prompt slot, `$style_hint`**, a single short line inserted into
   both `forensic_question.txt` and `v2_forensic_question.txt` (e.g. "Frame
   this using a CHRONOLOGICAL angle: ask about the sequence of events, not
   just the outcome.") — the model still writes the actual sentence; this
   only steers register, same mechanism `$move_brief` already uses.
5. **Fallback variants selected the same deterministic way** — `MOVE_FALLBACKS`
   becomes `tuple[Template, ...]` per move, indexed by the same
   `hash(claim.id) % len(variants)` so a given claim's fallback phrasing is
   stable across a rerun (important for `dump_fixture.py`'s reproducibility
   requirement).
6. **Replace the closed-list line in both prompts** with something like:
   "Ask what happened, what they did, what they chose, or what broke — but
   vary HOW you ask it. Don't default to the same sentence shape every time;
   the style hint above is a starting point, not a script to copy verbatim."
   This keeps the actual constraint (no opinions, no definitions, no
   generalities) and removes only the four-phrase closed vocabulary.
7. **No change to `validate()`.** Rules 1-7 stay exactly as they are —
   `duplicate_content` still checks within-session repetition, which is a
   real and separate concern from cross-session sameness. Adding a
   cross-session diversity CHECK (as opposed to a diversity nudge at
   generation time) is a bigger, separate proposal (would need a corpus of
   recent phrasings to check against) and is out of scope here by your own
   instruction not to touch validation.

Rough cost: 1-2 hours once approved — mostly the enum, the allow-list table,
and widening two dicts from single `Template` to `tuple[Template, ...]`. The
two prompt edits are a few lines each.

## 4. Before / after, by move (this repo's actual vocabulary)

Mapped to this codebase's real `Move` enum rather than the generic category
names in the request — `OPERATING_CONTEXT` is this system's PROCESS-equivalent
opener, `FAILURE` is INCIDENT, `DEPENDENCY` matches directly,
`AUTHORITY`/`EXCLUSION` together cover DECISION-shaped ground.

### OPERATING_CONTEXT (today's PROCESS-equivalent)

**Before (the only fallback, every time):**
> "When you were working on $object, what did you look at first?"

**After — same move, five styles:**
- *chronological:* "What was the very first thing you did once this started?"
- *reconstruction:* "If I watched you do this again, what would I actually see you do first?"
- *observation_focused:* "What was on your screen, or in front of you, in the first hour of this?"
- *retrospective:* "Looking back, where did the real work begin — not the plan, the actual start?"
- *artifact_focused:* "What's the first thing you'd have pulled up to start on $object?"

### FAILURE (today's INCIDENT-equivalent)

**Before:**
> "Tell me about a time $object did not go the way you expected. What happened?"

**After:**
- *incident_focused:* "Was there a point where $object stopped going to plan?"
- *observation_focused:* "What's something about $object that surprised you at the time?"
- *reconstruction:* "Walk me through one specific moment $object broke or nearly did."
- *retrospective:* "Looking back at $object, what's the one thing that didn't go the way you expected?"
- *chronological:* "Between starting $object and finishing it, was there a moment things went sideways?"

### DEPENDENCY

**Before:**
> "Who or what did you have to rely on most while working on $object?"

**After:**
- *observation_focused:* "What were you stuck waiting on before you could keep moving on $object?"
- *reconstruction:* "What had to happen before you could actually get going on $object?"
- *incident_focused:* "Was there a point $object stalled because of something outside your control?"
- *retrospective:* "What got easier on $object once whatever you were waiting on came through?"
- *chronological:* "Early on in $object, what was blocking you from moving forward?"

### AUTHORITY / EXCLUSION (today's closest DECISION-shaped moves)

**AUTHORITY before:**
> "On $object, what could you decide yourself and what had to go to someone else?"

**AUTHORITY after:**
- *decision_focused:* "On $object, where did your own call end and someone else's begin?"
- *reconstruction:* "If something on $object needed a decision, whose call was it — yours, or did it go up?"
- *retrospective:* "Looking back at $object, what's one thing you decided without checking with anyone?"

**EXCLUSION before:**
> "Which part of $object did you leave alone, and what made you leave it?"

**EXCLUSION after:**
- *decision_focused:* "What did you deliberately choose not to touch on $object, and why?"
- *retrospective:* "Is there a part of $object you knew needed work but left as-is? What kept it that way?"
- *observation_focused:* "What's the one corner of $object that never got the attention the rest did?"

### COHERENCE and PERTURB — deliberately NOT in this plan

Both already interpolate the candidate's OWN prior answers (`$fact_a`/
`$fact_b`, `$other_subject`) rather than a fixed generic phrase, so they
don't exhibit the "same sentence every time" problem the same way — their
wording already varies by construction, per-candidate. Adding a style layer
on top would add complexity without addressing a measured problem; left out
of the plan for that reason, not an oversight.

## 5. On the harness — status, not a decision I'm making for you

Agreed that a fourth scoring tool would be the wrong move right now — three
overlapping tools (`question_quality_harness.py`, `question_eval_harness.py`,
the live `log_question_quality` background task) is already one too many to
have not run any of for real. None has been run against real data yet; all
three are built and smoke-tested only. If you want, I can kick off
`question_eval_harness.py` against whatever's currently in the (shared,
recently-reset) dev DB right now — say the word and how many questions
you're comfortable spending on (its own smoke test suggests a few dollars for
100-200, same order as Phase 3's $3.67/519).
