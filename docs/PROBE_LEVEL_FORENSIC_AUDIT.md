# Probe-Level Forensic Audit — authorship vs skill

**Date:** 2026-09-06 · **Scope:** analysis only. No code, no prompts, no
sequencing.
**Data:** 305 Tier-B interview turns (simulator conditioned on the question —
the only tier where a question can cause an answer), with the full stored
`signals_json` for each, plus all 519 generation attempts.
**Companion documents:** [QUESTION_GENERATION_AUDIT.md](docs/QUESTION_GENERATION_AUDIT.md)
(measurement), [QUESTION_GENERATION_DESIGN_AUDIT.md](docs/QUESTION_GENERATION_DESIGN_AUDIT.md)
(stage responsibilities), [QUESTIONING_PHILOSOPHY.md](docs/QUESTIONING_PHILOSOPHY.md)
(first-principles interview design).

---

## 0. The instrument

Impostor parity cannot be asserted; this audit measures a proxy for it.

Every signal the extractor stores is scored by **invention cost** — how hard is
it for an articulate stranger who has read only the resume to produce this
signal convincingly?

| cost | signal types | why |
|---|---|---|
| **CHEAP** | bare quantities, metric *names*, tool *names* | "about three months", "we used Zendesk" — guessable from the claim |
| **MID** | quantities tied to a named metric, entities, process steps, described tool usage | commits to a specific, but a plausible generic version exists |
| **DEAR** | **incident markers, causal links, metric definitions with `how_measured`** | requires having been there; a wrong answer is visibly wrong |

A second, independent instrument cross-checks it: **novel-content share** — the
fraction of an answer's content words absent from *both* the claim and the
question. A question that fails impostor parity gets an answer that mostly
restates what the question already supplied.

Neither instrument depends on the other. They agree on every ranking below.

---

## 1. Per probe level

### VALIDATION

| | |
|---|---|
| **Signal it targets** | That the candidate held the scope they claim. |
| **Dimensions it should improve** | SPECIFICITY, METRIC_OWNERSHIP |
| **What it actually harvests** | quantities **1.65** (highest of any level) · metric_definitions **0.07** (lowest by 16×) |
| **Does the brief produce that evidence?** | **Half.** SPECIFICITY 54.3 — the best cell in the system. METRIC_OWNERSHIP 25.3, with **98.5% of answers capped by the "metric never defined" gate.** |
| **Forensic yield** | hard-to-invent **0.82** — worst of five. **39.7% of its answers contain no hard-to-invent signal at all.** Novel content **78.7% / 18.3 words** — 40% less new information than any other level. |

The brief asks *"how many, how long, who else was involved, what the numbers
were."* It harvests exactly what it asks for, and what it asks for is the
cheapest signal class in the taxonomy.

### OPERATIONAL — the biggest surprise in this audit

| | |
|---|---|
| **Signal it targets** | How the work ran day to day. |
| **Dimensions it should improve** | PROCESS, TOOL_FAMILIARITY |
| **What it actually harvests** | process_steps **4.00** (2× any other level) · tools **0.95** (highest) · quantities **0.02** |
| **Does the brief produce that evidence?** | **Yes, emphatically.** PROCESS 93.6, the highest score anywhere in the system. |
| **Forensic yield** | hard-to-invent **0.90** — **second worst**, and only 12.1% of its signal mass. **37.1% of its answers contain no hard-to-invent signal.** |

**This level is #1 on total evidence and #4 on forensic evidence.** It produces
the most signals of any probe (7.44/answer) and almost none of them are
expensive to invent. A generic daily workflow — *"every morning I pulled the
report, went through exceptions, handed the summary up"* — is exactly what a
stranger writes. The level is excellent under a skill lens and weak under an
authorship lens.

### INCIDENT — the best level in the system

| | |
|---|---|
| **Signal it targets** | One specific episode. |
| **Dimensions it should improve** | AUTHENTICITY, SPECIFICITY |
| **What it actually harvests** | incident_markers **0.97 — 6× any other level**, and the only level that meaningfully produces them |
| **Does the brief produce that evidence?** | **Yes.** 100% of INCIDENT questions are failure/episode-shaped. |
| **Forensic yield** | hard-to-invent **1.77 — best of five**, 28.4% of signal mass. Only **10.8%** zero-yield. Novel content **89.2%**, highest. |

The brief — *"a particular time it went wrong, or the hardest week"* — is the
only one in the system already written as a forensic move. **It should be the
template, not the exception.**

### DECISION — no distinctive harvest

| | |
|---|---|
| **Signal it targets** | The judgement they exercised. |
| **Dimensions it should improve** | CAUSAL_REASONING, PROCESS |
| **What it actually harvests** | process_steps 2.41 · causal_links 0.86 — **it leads on nothing** |
| **Does the brief produce that evidence?** | **No.** CAUSAL_REASONING 29.2 vs OUTCOME's 28.0 — statistically indistinguishable (t=−0.25). PROCESS 70.7 vs OPERATIONAL's 93.6. |
| **Forensic yield** | hard-to-invent 1.06, 21.6% zero-yield. Fewest total signals of any level (5.04) and fewest dimensions per answer (3.18). |

**DECISION is dominated on both of its own targeted dimensions** — by OPERATIONAL
on PROCESS and by nobody on CAUSAL_REASONING, because nothing produces causal
reasoning (see §4). As briefed, it is a weaker OPERATIONAL.

The brief asks *"what they decided, what they considered and rejected, and
why."* The corpus shows the model reliably asking the first and third clauses
(*"What factors led you to choose Tableau over Power BI?"*) and rarely the
second — **the rejected option, which is the forensically valuable half**, is the
part that gets dropped.

### OUTCOME

| | |
|---|---|
| **Signal it targets** | Closing the loop on the result. |
| **Dimensions it should improve** | METRIC_OWNERSHIP, CAUSAL_REASONING |
| **What it actually harvests** | metric_definitions **1.14 — 10× any other level** · quantities 1.41 |
| **Does the brief produce that evidence?** | **On one dimension, excellently.** METRIC_OWNERSHIP 53.8 — the highest in the system, and the gate is open in 42% of answers vs 1.5% at VALIDATION. **On CAUSAL_REASONING, no: 28.0.** |
| **Forensic yield** | hard-to-invent **1.54**, second best. 13.6% zero-yield. |

OUTCOME is where metric ownership actually happens, and it happens *last* — after
the interview has already spent its opening question on the magnitude of a
number nobody has defined.

### TRANSFER

| | |
|---|---|
| **Signal it targets** | Reasoning that a memorised resume cannot supply. |
| **Dimensions it should improve** | CAUSAL_REASONING, PROCESS |
| **Does the brief produce that evidence?** | **Unmeasurable.** n=10, all from one persona's three claims, all Tier A — the fixed-pool tier, where the answer is independent of the question. 3 of 10 were fallbacks. |
| **Forensic yield** | **No data.** The Tier-A pool has no transfer entry, so those turns collapsed to *"I don't remember the details."* — a study artifact, **not** evidence that transfer questions fail. |

40% attempt-1 reject rate, driven entirely by rules 1 and 5 firing on the
figure the planner itself injected. **The one probe level designed as a
forensic move is the one the corpus cannot evaluate.**

### Summary table

| level | targets | actually harvests | hard-to-invent | zero-yield | verdict |
|---|---|---|---:|---:|---|
| VALIDATION | SPEC, METRIC | quantities | **0.82** | **39.7%** | half-working; cheapest signal class |
| OPERATIONAL | PROCESS, TOOL | process_steps, tools | 0.90 | 37.1% | high volume, low forensic value |
| INCIDENT | AUTH, SPEC | **incident_markers (6×)** | **1.77** | **10.8%** | **working as designed** |
| DECISION | CAUSAL, PROCESS | *nothing distinctive* | 1.06 | 21.6% | redundant as briefed |
| OUTCOME | METRIC, CAUSAL | **metric_definitions (10×)** | 1.54 | 13.6% | half-working; right ask, wrong position |
| TRANSFER | CAUSAL, PROCESS | — | — | — | unmeasured |

---

## 2. The ranking flip

The same corpus ranks the probe levels differently depending on which product
you think you are building:

| level | total signals | rank | hard-to-invent | rank |
|---|---:|---:|---:|---:|
| OPERATIONAL | 7.44 | **1** | 0.90 | **4** |
| OUTCOME | 6.46 | 2 | 1.54 | 2 |
| INCIDENT | 6.23 | 3 | **1.77** | **1** |
| VALIDATION | 5.49 | 4 | 0.82 | 5 |
| DECISION | 5.04 | 5 | 1.06 | 3 |

> **skill lens:** OPERATIONAL > OUTCOME > INCIDENT > VALIDATION > DECISION
> **authorship lens:** INCIDENT > OUTCOME > DECISION > OPERATIONAL > VALIDATION

**The two best levels under one goal are 3rd and 4th under the other.** This is
the whole question you are asking, and the corpus answers it with a reordering
rather than a rescaling. Choosing authorship verification is not a matter of
degree — it changes which probe levels are worth the budget.

**24.9% of all answers contain zero hard-to-invent evidence.** One turn in four
is currently producing nothing a copier could not have fabricated.

---

## 3. Ten real corpus examples

All verbatim from `real_question_dataset.csv` / `study.sqlite3`.

| # | question (real) | level | signals | class |
|---|---|---|---|---|
| 1 | *"Tell me about the hardest week you had running the deal desk."* | INCIDENT | 11 sig, **4 dear** | **Strong evidence.** Answer surfaced a quarter-end margin conflict on a named deal. A stranger produces "it was busy". |
| 2 | *"What impact did freezing the client's account have on your compliance metrics?"* | OUTCOME | 9 sig, **5 dear** | **Strong evidence.** Highest forensic yield in the corpus — the answer commits to a mechanism that can be wrong. |
| 3 | *"Describe a specific time when a project delivery went wrong. What happened?"* | INCIDENT | 6 sig, 4 dear | **Strong evidence.** Periphery, not headline. |
| 4 | *"How did you measure the success of your onboarding process?"* | OUTCOME | 8 sig, 4 dear | **Strong evidence.** Opens the METRIC_OWNERSHIP gate — definition, not value. |
| 5 | *"How many employees were in the contact centre you managed?"* | VALIDATION | 2 sig, **0 dear** | **Metadata + impostor-parity failure.** Answer: *"around 150."* Weakest class in the corpus; passed every rule. |
| 6 | *"How many hours per week did you spend coaching the reps?"* | VALIDATION | 3 sig, 0 dear | **Metadata + impostor-parity failure.** *"Around 10 hours a week."* Identical to your REST-API case. |
| 7 | *"How long did you manage the team of 35 agents?"* → **rejected**, regenerated to *"How long did you manage the team of agents?"* → **accepted** | VALIDATION | — | **Impostor-parity failure, made worse by the pipeline.** See §5. |
| 8 | *"What specific tasks did you perform daily in the system to track deliverables?"* | OPERATIONAL | — | **Weak evidence.** High signal count, generic workflow. A stranger writes this answer. |
| 9 | *"What factors led you to prioritize updating project management tools over other tasks?"* | DECISION | — | **Weak evidence.** Asks for a justification, which is free to generate. The forensically valuable half — *what was rejected* — is absent. |
| 10 | *"What specific process changes led to the 30% AHT improvement?"* → **rejected** → *"What specific process changes led to the AHT improvement?"* → accepted | OUTCOME | — | **Weak evidence.** The regeneration removed the figure and changed nothing about what the question can learn. |

### The Knowledge-question class is empty — and that is a result

**Zero definition-quiz questions in 519 attempts.** No *"what is AHT"*, no
*"explain the difference between"*, no *"what's the formula for"*. The prompt's
rule — *"never a definition quiz… We are testing whether they did the work, not
whether they memorised definitions"* — works perfectly.

**This is the one thing in the question layer that is already doing exactly what
authorship verification requires. Do not touch it.**

---

## 4. Two findings that change what "fix the prompt" means

### 4a. The validator has no rule for discriminative power — your REST-API case, at scale

*"How long did the REST API integration project take?"* passes all seven rules
because all seven test **structural validity**: does it echo a figure, repeat a
prior question, name two metrics, pose a hypothetical, invent a number, drift
scope, or fail to anchor. **None asks whether the answer is worth having.**

In the corpus this shape is **55 of 519 attempts — 10.6%.**

### 4b. Regeneration by deletion — the pipeline actively degrading questions

**11 of 58 regenerations (19%) were "fixed" by deleting words and adding
nothing.**

```
BEFORE (rejected: answer_leakage)   How long did you manage the team of 35 agents?
AFTER  (accepted)                   How long did you manage the team of agents?

BEFORE (rejected: answer_leakage)   How long did you manage the 12-member support team?
AFTER  (accepted)                   How long did you manage the support team?

BEFORE (rejected: answer_leakage)   What steps did you take each morning to manage your 60 accounts?
AFTER  (accepted)                   What steps did you take each morning to manage your accounts?
```

The first pair is not merely no better — it is **ungrammatical and strictly less
informative**, and the validator accepted it.

> **The regeneration loop optimises for rule compliance, and compliance is
> orthogonal to evidence.** A filter that can only subtract will, when pushed,
> be satisfied by subtraction.

This is the strongest single piece of evidence for your thesis, and it is not an
argument for a better rule. It is an argument that **question value has to be
caused at generation and cannot be recovered at validation.**

### 4c. Causal reasoning has no owner

CAUSAL_REASONING is the lowest dimension corpus-wide (34.1). DECISION targets it
(29.2), OUTCOME targets it (28.0), and the difference between them is zero. No
question type in the corpus produces causal reasoning. **This is a rubric or
extractor problem one layer below question generation** and no re-brief will
reach it. Flagged so it is not mistaken for a prompt failure.

---

## 5. If the goal is authorship verification, what should each level become?

### The organising principle the data supports

> **Spend no question on the headline. Every probe should aim at something
> cheap for the author to recall and expensive for a copier to invent.**

INCIDENT already does this and is the best level in the system by every measure.
The recommendation is to make the other levels resemble it.

### Per level

| level | becomes | why the data says so |
|---|---|---|
| **VALIDATION → ESTABLISH** | Ask **what the number is and how it was captured**, never its magnitude. Which population, which window, counted by whom, against what baseline. | Its METRIC_OWNERSHIP gate is shut in 98.5% of answers; OUTCOME's identical ask opens it in 42%. The ask exists and works — it is simply in the wrong position. Converges with PHILOSOPHY Principle 5. |
| **OPERATIONAL → narrowed, not deleted** | Keep the tool harvest; drop "walk me through your day". Ask for **exclusions and dependencies** — what could *not* be automated, who you had to wait on, what the system would not let you do. | 37.1% zero-yield and the lowest dear-share (12.1%) despite the highest signal count. A generic workflow is what a stranger writes; an exclusion list is argued about and remembered. |
| **INCIDENT → PERIPHERY, unchanged** | Already correct. | incident_markers 6× any other level; 10.8% zero-yield, best in system. |
| **DECISION → folded into PERIPHERY** | Stop asking *why you chose*; ask **what you rejected and what made it not viable**. | It leads on no signal type, is dominated on both its own dimensions, and produces the fewest signals of any level. The rejected option is the half the brief already names and the model already drops. Converges with PHILOSOPHY Principle 8 — *"why did you choose Redis"* supplies its own answer shape. |
| **OUTCOME → SEAM** | Once measurement moves to ESTABLISH, OUTCOME's ask is free. It should become the **coherence test**: put load on two things already said and see whether they hold — p95 against p99, quota against deal count, AHT against repeat contacts. | This is PHILOSOPHY Principle 9, which currently has no home anywhere in the architecture. It is also the only move that cannot be answered by repeating an earlier answer. |
| **TRANSFER → unchanged in intent** | Keep it. Fix the measurement, not the design. | n=10 on the fixed-pool tier is not evidence of anything. Its 40% reject rate is a validator contract bug, not a question-quality result. |

### On your four-move model — where the data agrees, and one consequence

`ESTABLISH · PERIPHERY · SEAM · TRANSFER` maps cleanly onto the harvests above,
and it is a better vocabulary than the current one for the reason your framing
implies: **the current names describe positions on a ladder, the new names
describe forensic moves.** The mapping falls out of the data without forcing.

**One consequence to accept deliberately:** a four-move model has no home for
OPERATIONAL, and **OPERATIONAL is the only level that targets TOOL_FAMILIARITY**
(it harvests 0.95 tools/answer against 0.09–0.29 everywhere else). Collapsing to
four moves orphans that dimension entirely. Either a fifth move owns tools, or
PERIPHERY absorbs the tool question via dependencies and exclusions, or
TOOL_FAMILIARITY leaves the evidence graph. **That is a real choice, not an
oversight to be discovered later.**

### On your forensic-interviewer prompt

The direction is right and it lands in the correct stage — **generation**, which
is where value must be caused (§4b). Three observations:

1. **Its central test cannot become a validator rule.** *"Could a smart stranger
   answer this as well?"* is a judgement, and `validate()` is pure Python with no
   model call by design. Impostor parity can be a **generation instruction** and
   an **outcome metric** (§0's instrument, computed after the answer arrives),
   but it cannot be a gate.
2. **One part of it can.** The kill list is lexical: `how long`, `how many`,
   `what is`, `how do you generally`. A rule banning the duration/cardinality
   frame **is** implementable in Python and would have caught the 55 questions in
   §4a. That is the one new validator rule this corpus supports — and note it is
   a rule that removes a *shape*, not one that judges quality.
3. **"Prefer tradeoffs, exclusions, failures, measurement methods, dependencies,
   people involved"** is six asks in one instruction. That is the four-ask OUTCOME
   brief pattern that collapsed to one ask in 519 attempts. **One move, one ask** —
   the list should be distributed across the moves, not handed to the model as a
   menu.

### What must not be read into this

- **Do not conclude OPERATIONAL is bad.** It is the best level for PROCESS (93.6)
  and the only source of TOOL_FAMILIARITY. It is weak *for authorship*, which is
  a statement about the goal, not the level.
- **Do not conclude TRANSFER underperforms.** It was never measured.
- **Do not expect any of this to move CAUSAL_REASONING** (§4c).
- **The invention-cost mapping in §0 is a judgement**, applied consistently. The
  novel-content instrument agrees with it on every ranking, which is the reason
  to trust the direction — not the absolute values.
