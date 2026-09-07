# Competence Framework Audit — current architecture vs. the Universal Competence Framework

Audit and migration-planning only. Nothing implemented, nothing wired.
Builds directly on `docs/UNIVERSAL_COMPETENCE_FRAMEWORK.md` (the framework
design) and `docs/PLANNER_ALIGNMENT_AUDIT.md` (the current-system audit) —
cross-referenced rather than re-derived where the two already established a
fact.

---

## Part A — Per-Dimension Evidence Audit

For each new dimension: which existing extracted signals already
contribute, which current moves collect them, and a support verdict.

### KNOWLEDGE

- **Existing signals that contribute:** `metric_definitions.how_measured`
  (explaining how a metric is computed is a form of conceptual
  understanding); `tools[].usage` weakly (describes use, not the concept
  behind it).
- **Moves that currently collect it:** `METRIC_DEFINITION` (closest
  existing analogue to an EXPLAIN-style question, but gated entirely behind
  a claim having a metric); `OPERATING_CONTEXT` incidentally, when an
  answer happens to include a conceptual aside.
- **Verdict: Partially supported.** The extractor captures *whether* a
  metric or tool was explained, never a general "why does this concept,
  policy or process work this way" signal, and no active move is designed
  to ask for one outside the metric-specific case. **Needs new extraction**
  (Part D).

### EXECUTION

- **Existing signals:** `process_steps` (direct), `tools[].usage` (direct),
  `entities` (weak support).
- **Moves that collect it:** `OPERATING_CONTEXT` (primary, purpose-built),
  `DEPENDENCY` (secondary — a "what blocked you" answer often incidentally
  describes steps).
- **Verdict: Fully supported today.** This is exactly what `PROCESS` +
  `TOOL_FAMILIARITY` already measure, and real logs confirm it —
  `OPERATING_CONTEXT` reliably produced both within the first answer on a
  claim in every real transcript gathered this session.

### PROBLEM_SOLVING

- **Existing signals:** `incident_markers` (direct), `causal_links`
  (partial — a complete chain often co-occurs with a real incident).
- **Moves that collect it:** `FAILURE` (primary, purpose-built).
- **Verdict: Partially supported.** Signal type and move both exist and are
  well-matched in *intent*, but the prior audit's real-log evidence
  (Infra log Q4) showed `FAILURE` producing a full, substantive answer that
  still scored `AUTHENTICITY: 0`, because the candidate described a
  precaution/procedure rather than a specific incident. The gap isn't
  missing extraction or a missing move — it's that one move doesn't
  reliably produce an incident-shaped answer even when it produces a real
  one.

### JUDGMENT

- **Existing signals:** `causal_links` only as a weak proxy — a chain gives
  a reason, not a considered *alternative*. Nothing in the **live**
  extractor captures "what else did you consider."
- **Already-specified, unwired:** `api/prompts/v2_extract_signals.txt`'s
  `decisions` field — *"A choice they made AND why... skip the whole item
  if the answer names a choice with no stated reason"* — is exactly this
  signal, written this session, never connected to the live extractor (per
  the earlier wiring audit).
- **Moves that collect it today:** none reliably. `AUTHORITY` sometimes
  elicits a decision-plus-reason incidentally, but it's designed to probe a
  boundary, not an alternative weighed.
- **Verdict: Partially supported — mostly a wiring gap, not a design gap.**
  The right signal is already fully specified; it just isn't connected, and
  no current move is built to ask for it directly.

### OWNERSHIP

- **Existing signals:** none directly. `entities` tagged as a team/role is
  the only incidental proxy, and it isn't structured as a boundary.
- **Moves that collect it:** `AUTHORITY` and `OWNERSHIP_BOUNDARY` **already
  ask exactly this question** ("what was yours to decide, what needed
  approval") — the move-asking side is not the gap.
- **Verdict: Partially supported, asymmetrically.** The *question* already
  exists (two moves, in fact); the *scoring* doesn't — today's credit for
  an `AUTHORITY` answer comes from whatever `entities`/`causal_links`
  happen to appear in it (feeding `SPECIFICITY`/`CAUSAL_REASONING`), not
  from whether a boundary was actually named. **Needs new extraction** — a
  structured "boundary named" signal — even though the move that would
  trigger it is already shipping.

### ADAPTABILITY

- **Existing signals:** `causal_links`, `process_steps` — the same signals
  `EXECUTION`/`PROBLEM_SOLVING` use, just scored from a hypothetical-but-
  grounded answer.
- **Moves that collect it:** `PERTURB` — purpose-built, already mapped to
  exactly these two signal types in `MOVE_DIMENSIONS`.
- **Verdict: Fully supported in design, currently disabled.** Real
  evidence: the Infra log's `PERTURB` question (fired under the pre-Demo-
  Mode config that log reflects) produced PROCESS 56→100, CAUSAL_REASONING
  20→70 — genuinely strong. This is an activation question
  (`settings.transfer_probe`), not a capability gap.

**Summary:** EXECUTION is fully supported. ADAPTABILITY is fully supported
in design but switched off. KNOWLEDGE, PROBLEM_SOLVING, JUDGMENT and
OWNERSHIP are all partially supported, for four *different* reasons —
missing extraction (KNOWLEDGE, OWNERSHIP), a move that doesn't reliably
produce its intended answer shape (PROBLEM_SOLVING), and a wiring gap with
the design already written (JUDGMENT). None of the four is a "start from
zero" gap.

---

## Part B — Current Dimension → New Dimension Migration Map

| Current dimension | Primary new dimension | Secondary | Why |
|---|---|---|---|
| **SPECIFICITY** (quantities + named entities, gated on a quantity existing) | EXECUTION | OWNERSHIP (weakly — naming specific people/systems inside a boundary answer) | Concrete detail is what makes an EXECUTION answer credible; it's incidental, not causal, to an OWNERSHIP answer |
| **PROCESS** (process steps + domain vocabulary) | EXECUTION | PROBLEM_SOLVING, ADAPTABILITY | A described step is EXECUTION by default; it becomes PROBLEM_SOLVING or ADAPTABILITY evidence only in context (an EXCEPTION or ADAPTATION answer that happens to include steps) |
| **METRIC_OWNERSHIP** (metric defined vs. named only) | KNOWLEDGE | JUDGMENT (weakly — choosing which metric matters) | Explaining how a metric is computed is understanding a concept, which is exactly KNOWLEDGE's definition |
| **CAUSAL_REASONING** (complete cause→action→outcome chain) | JUDGMENT | PROBLEM_SOLVING, ADAPTABILITY | **The one old dimension with real fan-out.** A "because X, I did Y" chain is compatible with a reasoned choice (JUDGMENT), a diagnosis (PROBLEM_SOLVING), or a hypothetical extension (ADAPTABILITY) — the old scoring never distinguished which, which is exactly why `AUTHORITY` (feeding this dimension) produced this session's richest *and* emptiest real answers: it wasn't measuring judgment specifically, it was measuring "any coherent reasoning, about anything" |
| **AUTHENTICITY** (incident markers) | PROBLEM_SOLVING | — | Cleanest, closest to 1:1 mapping of any old dimension |
| **TOOL_FAMILIARITY** (tool usage described vs. named only) | EXECUTION | KNOWLEDGE (weakly — understanding what a tool is *for*, distinct from having used it) | Same reasoning as SPECIFICITY: using a tool is EXECUTION; explaining *why* that tool fits is a different, currently uncaptured claim |

**The load-bearing finding in this table:** `CAUSAL_REASONING` is the old
system's most overloaded dimension — it's the only one that fans out to
three of the six new dimensions rather than one or two. That overload is
the direct mechanism behind Part 4 of the prior audit's finding that
removing `AUTHORITY` would leave `CAUSAL_REASONING` with no reliable active
feeder: the old dimension was never really measuring one thing.

---

## Part C — Current Move → New Move Mapping (minimum set)

| Current move | Maps to | Notes |
|---|---|---|
| `OPERATING_CONTEXT` | **WALKTHROUGH** | Direct retarget, no reframing needed |
| `FAILURE` | **EXCEPTION** | Direct retarget; the reliability gap (Part A) is a wording problem to solve *inside* this move, not a reason to split it |
| `DEPENDENCY` | **RESPONSIBILITY** (primary), WALKTHROUGH (secondary) | "What blocked you" is already halfway to "what wasn't yours to control" |
| `AUTHORITY` | **RESPONSIBILITY** | Reframe the definition of a *good* answer: boundary clarity, not amount of authority held (Part A, OWNERSHIP) |
| `OWNERSHIP_BOUNDARY` | **RESPONSIBILITY** | Consolidates with `AUTHORITY` — two moves asking the same competence question today, feeding two different old dimensions that don't actually distinguish it |
| `PEOPLE` | **RESPONSIBILITY** (weak) | Retirement candidate — never observed firing in any real log gathered this session; RESPONSIBILITY already covers "who was in the loop" |
| `COHERENCE` | *(not a move)* | Demotes to a cross-check over whatever RESPONSIBILITY/CHOICE/etc. already collected — it generates no new evidence itself, it tests consistency between two already-collected facts |
| `METRIC_DEFINITION` | **EXPLAIN** | Retarget and de-gate: keep the "how was this measured" question, stop requiring KNOWLEDGE-style questions to only exist for metric-bearing claims |
| `PERTURB` | **ADAPTATION** | Direct 1:1 — already scores CAUSAL_REASONING + PROCESS exactly as ADAPTATION would; this is a re-enable + rename, not a redesign |

**Minimum set: 6 moves** (EXPLAIN, WALKTHROUGH, EXCEPTION, CHOICE,
RESPONSIBILITY, ADAPTATION), down from 9 listed here (7 active +
`COHERENCE` demoted + `PERTURB` currently disabled). **CHOICE is the one
genuinely new move** — nothing in the current active set is designed to
ask for a weighed alternative; `AUTHORITY` is the nearest neighbor and it
targets a boundary, not a tradeoff. Its evidence signal (`decisions`) is
already written, just unwired (Part A, JUDGMENT).

### Example questions — six families, proving the moves are role-agnostic

| Move | Software Engineering | IT Support | BPO | Banking Operations | Sales | Customer Support |
|---|---|---|---|---|---|---|
| **EXPLAIN** | "You mentioned using a message queue — why does that fit here better than calling the service directly?" | "You mentioned resetting user permissions — what actually determines who should have admin access?" | "You mentioned following the escalation matrix — what actually decides which tier a call goes to?" | "You mentioned KYC checks — what is that check actually trying to catch?" | "You mentioned qualifying leads — what actually separates a qualified lead from one that isn't?" | "You mentioned handling refunds — what actually qualifies something for a refund versus not?" |
| **WALKTHROUGH** | "You mentioned deploying the service — walk me through what you actually did to get it live." | "You mentioned resolving a ticket — walk me through what you did from when it came in to when it closed." | "You mentioned handling that call — walk me through what you did from pickup to wrap-up." | "You mentioned processing that loan application — walk me through intake to approval." | "You mentioned closing that account — walk me through the first call to the signature." | "You mentioned resolving that escalation — walk me through what you actually did." |
| **EXCEPTION** | "You mentioned the integration — describe a time it broke or didn't behave as expected." | "You mentioned that fix — describe a time the standard fix didn't work, and what you tried next." | "You mentioned handling calls — describe one that didn't fit any of your normal scripts." | "You mentioned reconciliation — describe a time the numbers didn't match, and what you did." | "You mentioned your pipeline — describe a deal that fell apart unexpectedly." | "You mentioned handling complaints — describe one that didn't resolve the way you expected." |
| **CHOICE** | "You mentioned choosing that framework — what else did you consider, and what made you pick it?" | "You mentioned that troubleshooting step — what made you try that first instead of something else?" | "You mentioned de-escalating that caller — what made you choose that over just following the script?" | "You mentioned flagging that transaction — what made you decide it needed escalation rather than clearing it?" | "You mentioned discounting to close — what made you choose that over holding the price?" | "You mentioned offering that resolution — what made you pick that over the standard policy option?" |
| **RESPONSIBILITY** | "You mentioned the migration — what part was entirely yours to decide, and what needed sign-off?" | "You mentioned that access change — what could you approve yourself, and what needed someone else?" | "You mentioned that call — at what point does something stop being yours to handle and go to a supervisor?" | "You mentioned the loan file — what could you approve yourself, and what had to go to underwriting?" | "You mentioned the account — what could you offer on your own, and what needed manager approval?" | "You mentioned resolving tickets — at what point does something stop being yours to fix?" |
| **ADAPTATION** | "You said you optimized that query — if a different table had ten times the rows, what would you check first?" | "You said you fixed that issue — if the same symptom showed up on a different OS, would your approach change?" | "You said you handle billing complaints — if the same complaint came from a first-time caller, what would you do differently?" | "You said you flagged that transaction pattern — if it came from a long-standing customer instead, would your response change?" | "You said you closed that deal with a discount — if the buyer had a smaller budget, what would you try first?" | "You said you de-escalated that call — if the customer had already been transferred twice, would you handle it differently?" |

Every question in this table follows the same underlying shape regardless
of family — name the claim, ask for the mechanism/reason/boundary/
transfer, never the domain jargon. That's the evidence the moves are
universal: nothing above required inventing a different question *type*
for a different industry, only a different noun.

---

## Part D — Three-Horizon Proposal

### 1. Minimum change for the hackathon demo

**Change nothing in extraction, scoring, or the planner.** The demo timeline
doesn't support validating new rubrics or new extraction fields safely
(Section on risk below). The actual minimum-risk move that gets most of the
narrative value: **relabel at the presentation layer only.** Part B's
mapping table is a pure, static lookup — a claim's existing dimension
scores can be *displayed* to a recruiter grouped under the six new
competence names (`EXECUTION` shown from `PROCESS`+`TOOL_FAMILIARITY`,
`PROBLEM_SOLVING` from `AUTHENTICITY`, etc.) without touching a single
extraction, scoring, or planner file. This is a dashboard/serialization
change, not an `api/engine` change — zero risk to anything this session
validated (Demo Mode, the wiring audits), and it's honest: it labels what
the system already measures in the vocabulary the framework proposes,
rather than claiming to measure something it doesn't yet.

### 2. Medium-term migration

Small, additive, flag-gated — the same pattern every existing planner
change in this codebase already follows:

- Wire `v2_extract_signals.txt`'s `decisions` field into a real extraction
  call (JUDGMENT's missing half, already written).
- Consolidate `AUTHORITY` + `OWNERSHIP_BOUNDARY` into one move behind a
  flag, reusing the existing `alt_moves` retarget mechanism rather than new
  control flow.
- Re-enable `PERTURB` (flip `settings.transfer_probe`) under its
  `ADAPTATION` framing — no new code, a config flip plus a rename.
- Retarget `METRIC_DEFINITION` to fire on any claim, not only
  metric-bearing ones, closing KNOWLEDGE's biggest reachability gap without
  new extraction.

None of this requires the two genuinely new extraction fields (KNOWLEDGE's
concept-explanation signal, OWNERSHIP's boundary signal) — it's entirely
reuse and reactivation of what already exists or is already written.

### 3. Long-term architecture

- New extraction fields for KNOWLEDGE (`concept_explanations`) and
  OWNERSHIP (`boundaries`) — the two dimensions Part A found need actual
  new design, not reuse.
- A parallel rubric module (`competence_signals.py`-shaped, alongside
  `signals.py`, not replacing it).
- A new planner behind a new flag implementing the claim-to-dimension-pair
  coverage rule from the framework design doc's Section 5 — including
  resolving its two open design questions (which claim gets which
  dimension pair; what happens when a claim can't sustain two dimensions
  of evidence) before this phase is built, not during it.
- Cross-family validation (all ten listed families, real interviews, not
  fixture mode) before any default flips — the same gate Demo Mode and
  every prior planner change in this codebase were held to.

This mirrors `docs/UNIVERSAL_COMPETENCE_FRAMEWORK.md`'s Phase 0-5 plan
exactly; this section restates it as three horizons because that's the
shape asked for here, not because the substance changed.
