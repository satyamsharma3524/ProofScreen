# Demo Mode Move Audit — 6-question interview lens only

Audit only, nothing implemented. Scoped exactly as asked: question
selection, competence coverage, seniority alignment, wording, dimension
targeting — extraction, scoring, ranking, graph logic, and evaluation are
out of scope throughout. Every finding is from the three real transcripts
already gathered this session: the **Infra log** (7 real turns, real
config `max_questions=12`/`transfer_probe=True`, the log pasted two turns
ago), the **Yogendra log** (6 turns, current Demo Mode config, this
session's own run), and the **original transcript** (15 turns, adversarial,
pre-Demo-Mode). Dimension names below are the new competence vocabulary
(`docs/UNIVERSAL_COMPETENCE_FRAMEWORK.md`), since that's the lens requested;
each is traced back to the specific old move that actually produces it
today.

---

## Per-Move Audit

Only the 8 moves currently active under Demo Mode (`EXCLUSION`/`PERTURB`
excluded already — see their own rows for why re-adding either wouldn't
change anything anyway).

| Move | Dimension targeted | Valuable in 6Q? | Junior-friendly? | Senior-friendly? | Real-log evidence yield | Keep enabled? |
|---|---|---|---|---|---|---|
| **OPERATING_CONTEXT** | EXECUTION | **Yes** — cheapest, fastest-populating dimension measured | **Yes** — "what did you actually do," assumes nothing about rank | Yes | **High** — populated 2 dimensions turn 1 in every real log (Infra Q2, Yogendra Q1, original Q1) | **Yes** — best-performing move, no change needed |
| **FAILURE** | PROBLEM_SOLVING | Yes, but unreliably delivered — see below | Conditional — a junior candidate may not have a "big" incident yet, risking a thin honest answer | Yes — richer incident history to draw from | **Medium, high variance** — Infra Q4 gave a full answer that still scored its own dimension (AUTHENTICITY) 0; Yogendra's ISSUE-shaped question (Enzyme snapshots) landed cleanly; original transcript's version got a garbled non-answer | **Yes** — only move for this dimension, but flag the wording gap (below) |
| **DEPENDENCY** | OWNERSHIP (secondary EXECUTION) | Yes | Yes — anyone can be blocked by something | Yes | **High** — Infra Q5 was the single richest answer in that log (7 signals, 4 of 6 dimensions) | **Yes** |
| **AUTHORITY** | OWNERSHIP | High variance, and specifically **the move most responsible for the "approval-heavy" impression** — see Planner Sequence Audit below | **Risky** — a genuinely junior candidate's honest answer ("not much was mine to decide") is thin for a reason that has nothing to do with competence, and reads identically to evasion | Yes — real decision-rights content to draw from | **Highest variance of any move measured**: Infra Q3 → 5 of 6 dimensions from one answer; original transcript's equivalent → "I did independently.", zero | **Conditional** — see recommendations |
| **OWNERSHIP_BOUNDARY** | OWNERSHIP | Yes | **More junior-friendly than AUTHORITY** — "where did your part end" has a complete honest answer at any seniority ("my part ended at implementation, my lead reviewed it"); AUTHORITY's "what could you decide independently" doesn't | Yes | **High** — Infra Q1, the very first question of that interview, scored 2 dimensions immediately | **Yes** |
| **COHERENCE** | *(cross-check, not a dimension move)* | **No** — never observed firing in any of the three real logs; its precondition (two established facts on one claim) is structurally hard to reach inside a 2-question-per-claim cap | N/A | N/A | **None measured** — zero real occurrences | **Moot** — effectively inert under the current cap regardless of its nominal setting |
| **PEOPLE** | OWNERSHIP (weak) | **No** — never fired in any real log either, and structurally can't: it sits at ladder position 4 for both archetypes it appears in (`OWNERSHIP`, `VOLUME`), already unreachable once a claim caps at 2 questions | N/A | N/A | **None measured** | **Moot, same reason as `COHERENCE`** — already dead under the cap; "disabling" it costs nothing because it's already never reached |
| **METRIC_DEFINITION** | KNOWLEDGE | Yes in principle — the *only* source of this dimension | Yes — explaining how a metric works assumes no authority | Yes | **Zero — never fired in any of the three real logs.** Structural: none of the 9 real claims selected across all three logs were `METRIC_MOVE` archetype, so this move was never once offered as a choice | **Yes, keep enabled** — nothing to lose — but see recommendations; it needs to actually be reachable to matter |

---

## Planner Sequence Audit

Dimension coverage per real interview, counted by which move actually fired:

| Dimension | Infra log (7 turns) | Yogendra log (6 turns, current Demo Mode) | Original transcript (15 turns) |
|---|---|---|---|
| EXECUTION | 2x (Q2, Q7/8-repair) | 1x (Q1) + 2 threaded follow-ups (API, library — both EXECUTION-shaped) | 2x (opener + a later repeat) |
| **OWNERSHIP** | **3x** (Q1 `OWNERSHIP_BOUNDARY`, Q3 `AUTHORITY`, Q5 `DEPENDENCY`) | 1x (Q3 `AUTHORITY`) | 1x (`AUTHORITY`-equivalent) |
| PROBLEM_SOLVING | 1x (Q4) | 1x (Q5) | 1x (Q4) |
| JUDGMENT | **0x** | **0x** | 1x (`EXCLUSION`, pre-Demo-Mode only) |
| ADAPTABILITY | 1x (Q6, `PERTURB` — pre-Demo-Mode config) | **0x** (disabled) | 3-4x (`PERTURB` fired repeatedly on stalled claims) |
| **KNOWLEDGE** | **0x** | **0x** | **0x** |

**Never received a question, in any of the three real logs: KNOWLEDGE.**
Structural, not incidental — see the `METRIC_DEFINITION` row above.

**Under current Demo Mode specifically (Yogendra log, the only one of the
three actually run under today's settings): JUDGMENT and ADAPTABILITY both
read zero** — JUDGMENT because its only source (`EXCLUSION`) is disabled,
ADAPTABILITY because `PERTURB` is disabled. Both were reachable and
producing real evidence in the pre-Demo-Mode logs (the original
transcript's `EXCLUSION` question, the Infra log's `PERTURB` question) —
disabling them for the demo didn't just remove noise, it also zeroed out
two dimensions entirely for the current configuration.

**Redundant coverage: OWNERSHIP, not any single move.** The per-move table
above shows each of `AUTHORITY`/`OWNERSHIP_BOUNDARY`/`DEPENDENCY`
individually performing well — the redundancy only shows up at the
dimension level, in the Infra log, where all three fired within one
7-question interview and jointly consumed 3 of 7 questions (43%) on the
same competence, while KNOWLEDGE got none. This is the concrete shape of
what "approval-heavy" actually looks like in this system: not one
overused move, but three different moves that all happen to converge on
the same competence.

---

## "If we only have 6 questions, what's the optimal dimension coverage strategy?"

Based purely on measured reliability, not aspiration: **spend the first
1-2 questions per claim on EXECUTION (`OPERATING_CONTEXT`/`DEPENDENCY`) —
it's the cheapest, fastest, least variance dimension in every log
gathered. Spend exactly one question, interview-wide, on OWNERSHIP — not
one per claim.** Three different moves already compete for that one
dimension; letting all three fire is how a 6-question budget ends up
redundant on OWNERSHIP and empty on KNOWLEDGE. PROBLEM_SOLVING deserves one
attempt per interview, accepting its yield is real but variable. Given the
current disabled state of `EXCLUSION`/`PERTURB`, JUDGMENT and ADAPTABILITY
are not realistically coverable within Demo Mode as configured today
without re-enabling one of them — an honest gap, not something a wording
tweak fixes.

---

## Smallest Possible Planner Changes

All of the following are config values, existing-mechanism extensions, or
move-brief wording — no new scoring, no new extraction, no new planner
architecture, and every change stays inside Demo Mode as already built.

**1. Remove approval/authority-heavy interviewing** — extend
`_rotate_session_fresh`'s *existing* session-wide skip-set
(`orchestrator.py:1795`, already tracks "has this exact move fired
anywhere this session") to treat `AUTHORITY` and `OWNERSHIP_BOUNDARY` as
one synonym group rather than two independent moves. Once either fires
once, the other is skipped session-wide, the same way the mechanism
already skips a literally-repeated move today. This is a same-shape
extension of a mechanism that already exists, not a new one — and per the
per-move table, `OWNERSHIP_BOUNDARY` is the stronger and more junior-safe
of the two, so it's the one worth keeping as the default if only one
should fire.

**2. Reduce incident/failure overuse** — not actually observed as a
frequency problem (`FAILURE` fired once per interview in every log, never
redundantly) — the real problem measured is *reliability*, not overuse.
Smallest fix: tighten `FAILURE`'s brief the same way `OWNERSHIP_BOUNDARY`'s
was tightened earlier this session — from "ask about one specific occasion
this did not go the way they expected" to something that explicitly rules
out a precaution/procedure answer as satisfying the ask (the Infra log's
actual failure mode: a real, substantive answer about a precaution taken,
not an incident recalled). Wording-only.

**3. Increase setup and implementation questions** — this is the flip
side of #1: capping `AUTHORITY`/`OWNERSHIP_BOUNDARY` to one combined slot
per interview mechanically frees remaining budget for `OPERATING_CONTEXT`/
`DEPENDENCY` follow-ups (already the highest-yield moves measured) without
adding anything new to select from.

**4. Make questioning seniority-aware** — a full seniority-branch is out
of scope (Part 5 of the prior audit found seniority is extracted and
deliberately never branched on — reversing that is a real design decision,
not a small patch). The smallest change that helps without doing that:
reword `AUTHORITY` to ask for **a specific decision or handoff moment**
rather than a general self-assessment of decision-making scope — the same
fix already applied to `OWNERSHIP_BOUNDARY` this session
("a specific call that was theirs alone to make" vs. "how much they
owned"). A specific-moment question has a complete, non-thin honest answer
at any seniority level; an abstract scope question doesn't.

**5. Maximize evidence collected per question** — `PEOPLE` and `COHERENCE`
are already unreachable under the 2-question-per-claim cap (per the
per-move table) — there is no budget currently being spent on them to
reclaim. The only real lever left, given the constraints, is #1: the
measured redundancy is 3 questions on one dimension in a 7-question
interview, and removing that redundancy is the single highest-leverage,
lowest-risk change available without touching scoring, extraction, or the
planner's actual selection architecture.

**Not recommended given the stated constraints:** de-gating
`METRIC_DEFINITION` from `anatomy.has_metric` would be the obvious fix for
KNOWLEDGE's zero coverage, but it requires touching
`question_engine.move_available()`'s precondition logic — a small change,
but a planner-behavior change, not a config value or a wording edit, so
it's named here as the one item this audit found but does not propose,
per the "no new planner architecture" boundary.
