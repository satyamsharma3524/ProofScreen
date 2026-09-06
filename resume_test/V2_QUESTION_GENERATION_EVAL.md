# v2 Question Generation — Wiring Verification + Question-Only Evaluation

Scope: exactly the three tasks assigned. No planner logic, scoring, or
evidence-extraction code was modified. `generate_v2_questions.py`
(harness) and its raw output live outside the repo, in the session
scratchpad, since this file is the only artifact meant to persist.

---

## 1. Is `v2_forensic_question.txt` fully wired into the live interview path?

**No — it is wired, but off, and one of its ten targets is permanently
unreachable even when on.**

- The render path is real: `orchestrator.plan_next_evidence()` →
  `evidence_planner.plan_next()` → `question.generate_evidence_question()` →
  `load_prompt("v2_forensic_question", ...)` (`api/engine/question.py:1685`).
  This is not a stub.
- It is selected only when `settings.evidence_planner_v2` is `True`
  (`api/engine/orchestrator.py:1016`). The field defaults to `False`
  (`api/config.py:87`), and neither `.env` nor `.env.example` sets
  `EVIDENCE_PLANNER_V2`. **The live default path today is the Move-based
  `forensic_question.txt`** (`forensic_questions=True`, `api/config.py:78`),
  not this one. Every finding below describes a system a candidate does not
  currently see in production.
- **`CROSS_CLAIM_LINK` — one of the ten target categories the prompt itself
  documents (`v2_forensic_question.txt:56`) — can never be selected.**
  `plan_next_evidence()` always calls `evidence_planner.plan_next(..., graph_edges=())`
  with an empty edge tuple (`api/engine/orchestrator.py:957-962`, comment
  admits this: "CROSS_CLAIM_LINK is simply never offered"), because nothing
  in the codebase ever calls `claim_graph.txt` — confirmed by grep, zero
  `load_prompt("claim_graph", ...)` call sites anywhere in `api/`. The file
  is a complete, well-specified prompt (typed edges, a "sentence test") that
  is dead code today, not a wired-but-idle feature.

## 2. Is `v2_extract_signals.txt` wired and updating evidence state?

**No. It has zero call sites.** `grep -rn 'load_prompt("v2_extract_signals'
api/` returns nothing. The live extractor (`api/engine/evidence.py:329`)
still loads the original `extract_signals.txt`, whose output validates
against the frozen `AnswerSignals` model (`api/schemas.py:237-248`) —
which has **no `decisions` and no `constraints` field**.

`evidence_planner.coverage_from_signals()` (`api/engine/v2_evidence_planner.py:356`)
*is* live-called every turn, from `orchestrator.py:223` — so coverage state
does update in production — but it reads `raw.get("decisions")` and
`raw.get("constraints")`, and those keys never exist in what the live
extractor actually returns. Both always evaluate to `0`. Combined with
`OWNERSHIP`, which the same function's own docstring already documents as
unmapped (`v2_evidence_planner.py:372-376`), **three of the ten evidence
categories — OWNERSHIP, DECISION, CONSTRAINT — are structurally incapable
of reaching `ESTABLISHED` in production today**, not occasionally, always.
`v2_extract_signals.txt` is a fully-written fix for two of those three
(it adds exactly `decisions` and `constraints`, matching the planner's
expectations field-for-field) that was never connected to anything.

**One consequence worth flagging on its own:** `sufficiently_covered()`
(`v2_evidence_planner.py:210`) requires `OWNERSHIP` to reach `ESTABLISHED`
before a claim can stop being probed on that path. Since `OWNERSHIP` can
never reach `ESTABLISHED`, **a claim can never satisfy this stop condition
in production, ever** — this is not about your six-question sample, it
holds for an unbounded real interview too. The only things that actually
end a claim's questioning today are `EXHAUST_AFTER` (per-category give-up)
and the global `MAX_QUESTIONS`/index cap in `plan_next_evidence`, never the
"we have enough" condition the design intends.

---

## 3. Question-generation-only evaluation

### Method actually run

Real, unedited resumes from `resume_test/` — 7 distinct candidates plus 3
role-targeted variants of one candidate (Deloitte/Nykaa/Nike), chosen for
family diversity: engineering, product, sales, ops. `extract_claims()` (LLM
#1, real call) → up to 3 claims per resume → 6 questions per resume via
`v2_evidence_planner.plan_next()` + `question.generate_evidence_question()`
(both real calls, `evidence_planner_v2` forced on for the harness only).
`gpt-4o`, temp 0.4, matching the live config.

**No answer was simulated or fabricated**, per instruction. Between
questions the harness calls `update_coverage(state, observed={}, targeted=category)`
— pure turn/attempt bookkeeping, the same no-signal-this-turn case a real
extractor legitimately returning empty lists would produce. **This is not a
free methodological choice — it is what "do not simulate answers" makes
unavoidable, and it produced a finding in its own right:**

> **Every one of the 59 questions generated targets one of only 3 of the
> 10 evidence categories — PROCESS, ARTIFACT, OWNERSHIP.** No DECISION,
> DEPENDENCY, INCIDENT, CONSTRAINT, METRIC_DEFINITION, CAUSAL_CHAIN, or
> CROSS_CLAIM_LINK question was generated across 10 resumes.

This is not sampling noise. `PRIORITY_ORDER` + the escalation gate
(`_unlocked_level`, `ESCALATION_LEVEL`) only unlock level-2/3/4 categories
once a level-1 category (`OWNERSHIP`/`PROCESS`/`ARTIFACT`) reaches
`ESTABLISHED`, which requires a real observed count — which requires a real
answer. **Six questions with no answers is not an edge case of this
harness; it is what the opening of every real interview looks like too,
until a candidate's first two or three answers actually land.** So this run
is not a weak sample of the deep categories — it is a complete, accurate
picture of what escalation level 1 alone produces, which is exactly what
every interview spends its first several turns on. 10 resumes × 6
questions = 60 attempted; one resume (Ankush, banca sales, one thin claim)
exhausted after 5. **n = 59.**

### Per-category statistics

Each question scored 0–2 on five dimensions (2 = good): **A** one-word-exit
resistance, **B** procedural-recall requirement, **C** candidate-centricity,
**D** impostor resistance, **E** escapes template convergence. Scoring
method and per-question breakdown: `/tmp/scored_v2.json` (session
scratchpad).

| Category | n | source: model / regenerated / fallback | A | B | C | D | E | mean total /10 |
|---|---|---|---|---|---|---|---|---|
| PROCESS | 29 | 22 / 7 / — (fallback for process never occurred as the *target*; 6 fallbacks landed here via retarget) | 2.00 | 1.86 | 1.93 | 1.86 | 0.55 | **8.21** |
| ARTIFACT | 20 | 13 / — / 7 | 1.75 | 0.65 | 1.65 | 0.65 | 1.05 | **5.75** |
| OWNERSHIP | 10 | 7 / — / 3 | 0.60 | 0.00 | 1.90 | 0.40 | 0.80 | **3.70** |

Overall source mix: **42/59 (71%) model, 10/59 (17%) fallback, 7/59 (12%)
regenerated.** A 17% fallback rate means roughly one in six questions a
real candidate would see today is the unvalidated, by-design-generic
`On "<claim>" — tell me more about the <category> involved.` line —
CLAUDE.md rule 5 requires this path to exist and forbids validating it, so
this is not a defect to fix, but it is a real, measured fraction of live
question quality that the other two tasks' methodology can't see if they
only score `validate()`-accepted output.

PROCESS is the clear strongest category (matches every prior audit's
verdict for this category under its old name) — but **21 of its 29
questions (72%) share one dominant frame**, `"What were the steps
(you followed/took) to X?"` — verbatim-converged, not just
object-varied.

### Named escape-hatch styles — what the task asked to check for

| Named style | Category it maps to | Reachable in 6 turns? | Found? |
|---|---|---|---|
| "manager" | OWNERSHIP ("who reviewed your work") | Yes | **5/10 (50%)** — reproduces verbatim |
| "backend team" / "customers" | ARTIFACT ("...who else used it?") tail | Yes | **8/20 (40%)** — reproduces verbatim |
| "approval" | AUTHORITY-adjacent / DECISION | **No** | Untestable — category never fires within the escalation gate before an answer exists |
| "budget" | CONSTRAINT | **No** | Untestable — same reason, *and* CONSTRAINT's coverage is structurally dead per §2 even if it did fire |
| "nothing" (stonewall) | INCIDENT | **No** | Untestable — same reason |

Three of the five named risks are not merely absent from this sample —
they are **structurally unreachable** in the window this task specified.
That is itself the honest answer to "are these still a problem": nobody
can currently tell, including this evaluation, because no live interview
today gets past PROCESS/ARTIFACT/OWNERSHIP before a candidate has actually
answered several questions.

### Top 20 questions (highest scored)

```
10  What did the final component library look like, and who else used it?             [process, retargeted from artifact]
10  What document or report did you create for the DROGYNA launch?                     [process, retargeted]
10  What form did the final multi-agent shopping assistant take, and who used it?       [process, retargeted]
10  What were the first three steps you took to optimize the app's performance?         [process]
10  What were the specific steps you followed to build the dbt transformation pipelines?[process]
10  How did you implement the capping logic to prevent single-session depletion?        [process]
10  What form did the measurement infrastructure take, and who else used it?            [process, retargeted]
10  What document or report did you create to track the time-to-market reduction?       [process, retargeted]
 8  What were the steps you followed to integrate APIs into the component libraries?    [process]
 8  What were the steps you followed to implement the hyper-local SaaS platform...      [process]
 8  What were the steps you followed to manage and grow the portfolio?                  [process]
 8  What specific report or document did your work on the portfolio produce?            [artifact]
 8  What steps did you follow to manage the CR portfolio daily?                         [process]
 8  What were the steps you took to integrate Groq APIs with LangChain?                  [process]
 8  What were the key steps you took to optimize hybrid search with FastEmbed?           [process]
 8  What were the steps you followed when processing a Banca Sales Insurance application?[process]
 8  What document or report did you create for Banca Sales Insurance?                    [artifact]
 8  What steps did you follow to complete a banca sales insurance task?                  [artifact, retargeted]
 8  What were the steps you followed to integrate Java applications with the Ikasan...   [process]
 8  What specific artifact did your integration work produce using the Ikasan framework? [artifact]
```

Note the top 8: six of them are labeled `process` **only because they were
retargeted there after an artifact draft was rejected** — the text still
reads exactly like an artifact question ("what did it look like... who
used it"). The retarget mechanism (`question.py:1783-1799`) genuinely
switches which category's prompt is asked next, but the model does not
reliably shift its wording to match — a real, separate defect: **category
labels in `questions.move`/evidence-graph storage are not a reliable
signal of what was actually asked**, worth a note for whoever eventually
reads `probed_dimensions` off this data.

### Worst 20 questions (lowest scored)

```
 6  What specific app feature did your work produce, and who used it?                   [artifact]
 6  What specific features or modules were you personally responsible for in the RN apps?[ownership]
 6  What artifact did your work on dbt transformation pipelines produce, and who used it?[artifact]
 6  What specific decisions did you make that the absence of a CPO or CTO affected?      [ownership]
 6  What artifact did you create for the measurement infrastructure and who used it?     [artifact]
 3  On "Led frontend architecture with scalable component libraries..." — tell me more about the artifact involved.   [fallback]
 3  On "Responsible for 55 CR portfolio management and growth strategies" — tell me more about the artifact involved. [fallback]
 3  On "Responsible for 55 CR portfolio management and growth strategies" — tell me more about the ownership involved.[fallback]
 3  On "Built a multi-agent shopping assistant using LangChain..." — tell me more about the artifact involved.        [fallback]
 3  On "1 Year Experience in Reliance General Insurance..." — tell me more about the process involved.                [fallback]
 3  On "Responsible for integrating java applications using Ikasan framework." — tell me more about the process involved.[fallback]
 3  On "Engineered end-to-end data infrastructure..." — tell me more about the artifact involved.                     [fallback]
 3  On "Scaled platform to 10,000 DAU in 6 months..." — tell me more about the artifact involved.                     [fallback]
 3  On "Sole product, design, and strategy authority – no CPO or CTO..." — tell me more about the artifact involved.  [fallback]
 3  On "Architected measurement infrastructure processing 500M+..." — tell me more about the artifact involved.       [fallback]
 2  Who reviewed your frontend architecture work and what feedback did they give?        [ownership]
 2  Who reviewed your integration work with the Ikasan framework?                        [ownership]
 2  Who reviewed your dbt transformation pipelines and what feedback did they give?      [ownership]
 2  What part of the platform's scaling were you personally responsible for, and who reviewed your work? [ownership]
 2  Who reviewed your work on the measurement infrastructure?                            [ownership]
```

---

## 4. Comparison against previous audits — has question quality materially improved?

Six prior documents exist. Five (`docs/QUESTION_GENERATION_AUDIT.md`,
`PROBE_LEVEL_FORENSIC_AUDIT.md`, `PROBE_ARCHITECTURE_FACTUAL_AUDIT.md`,
`QUESTION_GENERATION_DESIGN_AUDIT.md`, `LIVE_INTERVIEW_QUALITY_AUDIT.md`)
audit **two different, earlier systems** — the original 6-probe-level path
(`generate_question.txt`) and the intermediate Move-enum forensic path
(`forensic_question.txt`) — neither is the v2 EvidenceCategory planner this
task is about. None of their fixes were code changes; all five are
"observation only, nothing implemented" by their own text. They're useful
priors for *which failure shapes to watch for* (metadata/cardinal escape
hatches, template convergence, cheap-exit authority questions), not for
what v2 specifically has fixed.

**`resume_test/QUESTION_QUALITY_AUDIT.md` is the one prior audit of this
exact system**, from a smaller sample (90 questions from a CSV covering 3
resumes, plus a 5-turn live sim). Comparing its findings to this run,
category by category, for the two categories both samples actually
reached:

| Category | Prior audit finding | This run | Changed? |
|---|---|---|---|
| OWNERSHIP one-word-exit | 5/10 (50%) default to "who reviewed your work" → "my manager"/"QA" | 5/10 (50%) — **identical rate**, same phrase | **No** |
| ARTIFACT "who else used it" leak | 3/10 (30%) soft-fail on this tail | 8/20 (40%) | **No** — same or slightly worse |
| PROCESS quality | HIGH, best-performing, ~5/10 share a dominant frame | HIGH, best-performing, 21/29 (72%) share a dominant frame | **No** — repetition is worse by this measure, though content quality holds |
| CAUSAL_CHAIN | Confirmed already fixed mid-prior-session (two-part trigger+change form) | Not reached — escalation-gated out of a 6-turn no-answer window | Cannot confirm regression or improvement; code inspection (§1 of this doc's prior turn) shows the fixed wording is still in the prompt |
| DECISION / DEPENDENCY / CONSTRAINT / METRIC_DEFINITION / INCIDENT / CROSS_CLAIM_LINK | Various ratings given | Not reached at all | Cannot compare |

**Answer: has question quality materially improved since the prior v2
audit? No, for the two categories both audits can actually see.** The
recommended fixes for OWNERSHIP and ARTIFACT in that prior audit's §8 were
not applied — the current `v2_forensic_question.txt` text (read this
session) still instructs *"who reviewed their work"* for OWNERSHIP
(line 25) and *"who else used it"* for ARTIFACT (line 55), unchanged — and
the failure rates measured fresh, on entirely new resumes and claims, land
at the same order of magnitude. For the other seven categories, "improved"
isn't the right question yet — the honest status is **untested**, and per
§2 above, three of them (OWNERSHIP itself, DECISION, CONSTRAINT) cannot
be meaningfully tested by a live interview at all until `v2_extract_signals.txt`
is wired.

---

## 5. Exact prompt instructions causing the failures, and wording-only fixes

All in `api/prompts/v2_forensic_question.txt`. No planner, scoring, or
extraction change implied or needed.

**OWNERSHIP (line 24-26)** — current:
> *"Ask what they personally were responsible for, who reviewed their
> work, or what depended on them. Not "did you own this" — find the edge
> of their authority."*

Measured failure: 5/10 (50%) of generations reach for "who reviewed your
work on X?" — answerable "my manager" or "QA," verbatim the escape hatch
this evaluation was asked to check for. This confirms the prior audit's
diagnosis exactly, with a fresh sample. Fix (same one proposed before,
restated because it was never applied): **delete "who reviewed their
work" as a suggested angle.** Replace with an instruction to ask for a
decision made unilaterally, or the edge of authority directly — the
line already gestures at this ("find the edge of their authority") but
undercuts itself by listing the escape hatch as an equally-valid option
one sentence earlier.

**ARTIFACT (line 54-55)** — current:
> *"Ask about the concrete thing their work produced — what it was, what
> shape it took, who else used it."*

Measured failure: 8/20 (40%) carry a "...who used/else used it?" tail
answerable in one generic word. Fix (also previously proposed, also never
applied): replace "who else used it" with something that forces a
specific, non-generic recall — e.g. *"what surprised them about how
someone else ended up using it, or what they had to change about it once
it left their hands."* Same target (downstream use), closes the one-word
half.

**PROCESS (line 27-28)** — no prior fix was proposed for this category
(it was rated the strongest), but this run's larger sample shows 72%
template convergence on *"What were the steps you followed/took to X?"*
— higher than the 50% seen in the smaller prior sample. Since content
quality holds regardless of frame (matches prior finding), this is
lower-priority than the two above, but if it's addressed: append an
instruction to vary the opening verb/shape across turns — *sometimes ask
what surprised them mid-process, sometimes what they'd change about the
order, sometimes which step took longest — never let "what were the
steps" be the only shape this category produces* — mirroring the fix
already proposed and un-applied for DECISION in the prior audit, which
has the identical repetition shape.

**Not addressed here, and shouldn't be, by wording alone:** the 17%
fallback rate, the DECISION/CONSTRAINT/OWNERSHIP dead-signal gap, and
CROSS_CLAIM_LINK's unreachability. All three are wiring/schema problems
(§1, §2), not prompt-wording problems — a wording fix to
`v2_forensic_question.txt` cannot make `AnswerSignals` carry a `decisions`
field, and per CLAUDE.md rule 5 the fallback must stay unvalidated by
design. Flagged, not fixed, per this task's scope.
