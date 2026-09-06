# Question Generation Audit — evidence before change

**Date:** 2026-09-06 · **Scope:** read-only. No code, prompt, threshold or
corpus entry was modified.
**Data:** `studies/phase3/real_question_dataset.csv` (519 generation attempts,
395 questions actually asked, 68 interviews, 9 families) joined to
`studies/phase3/study.sqlite3` (395 responses, 1508 evidence rows, 92 claims).
**Method:** every question classified by an auditable regex cue set
(earliest-cue-wins, 99.2% coverage), then joined question → answer → per-dimension
evidence score.

This document does not restate `studies/phase3/validator_disagreements.md` or
`confusion_matrix.md`. Those hold the human-labelled validator finding and are
cited where they answer a question. What is new here is the **question-type
taxonomy**, the **type → evidence-yield correlation**, and the **prompt-level
root cause**.

---

## Verdict up front

The quality problem is **not** diffuse. Ranked by evidence:

| # | Candidate source | Verdict |
|---|---|---|
| 2 | **Probe-level definitions** | **PRIMARY.** One brief, `VALIDATION`, explicitly instructs metadata questions. |
| 1 | Prompt design | **Secondary, same root.** The prompt file is sound; the injected brief and one gap hint are what steer. |
| 3 | Validator rules | **Real but separate.** 54.3% precision, already measured and documented. Not the metadata cause. |
| 4 | Fallback templates | **Not a defect.** Measured no worse than generated questions — mildly better. |
| 5 | Question-selection logic | **Not a defect** on this data, but un-measurable (see D3). |
| 6 | Claim extraction / classification | **Not a defect.** Ruled out with numbers (B4). |
| 7 | Transfer strategy | **Under-exercised, n=10.** One specific validator interaction found. |

**The single highest-value finding:** asking *how big a metric was* yields
**25.3** mean METRIC_OWNERSHIP; asking *how the metric was measured* yields
**53.6** — a 2.1× difference, t=7.13, 95% CI [20.5, 36.1], on the same dimension
with identical 100% coverage. The `VALIDATION` probe brief is the instruction
that produces the 25.3 arm, and `VALIDATION` is the largest probe level in the
corpus.

---

## A. Prompt analysis

### A1. Where the prompts are

There is exactly **one** question-generation prompt file:
[api/prompts/generate_question.txt](api/prompts/generate_question.txt). Probe-specific
content is not in the file — it is injected at `$probe_level_brief` from
`PROBE_BRIEFS` in [api/engine/question.py:73-107](api/engine/question.py#L73-L107).

Four other things reach the model or shape the output:

| Element | Location | Role |
|---|---|---|
| `PROBE_BRIEFS` | [question.py:73](api/engine/question.py#L73) | what to ask at this depth |
| `TRANSFER_INSTRUCTIONS` | [question.py:112](api/engine/question.py#L112) | T1/T3 slot substitution |
| `GAP_HINTS` | [question.py:181](api/engine/question.py#L181) | nudge toward an under-probed dimension |
| `_RETRY_HINTS` | [question.py:694](api/engine/question.py#L694) | one-line rule names on regeneration |

**There is no system prompt, no examples and no few-shot samples anywhere.**
That is deliberate and documented at [question.py:675-683](api/engine/question.py#L675-L683):
worked examples are a per-cohort authoring cost and re-introduce the bias the
taxonomy exists to keep out of code. This audit found no reason to overturn it —
see F2.

### A2. What behaviour is rewarded

From the prompt body: ask at the assigned probe level; one question; under 32
words; plain language; their actual experience not a definition quiz; no
hypotheticals unless the brief asks; never comment on presentation; one
answerable thing.

Those are all **constraints**. The only instruction that says *what to ask about*
is the injected probe brief. So the probe brief is, functionally, the entire
content specification — and it is where the defect lives.

### A3. Are we accidentally encouraging metadata questions?

**Not accidentally. Explicitly, in two places.**

`PROBE_BRIEFS[VALIDATION]`, [question.py:75-77](api/engine/question.py#L75-L77):

> "VALIDATION — establish that they actually held this scope. Ask for the shape
> of it: **how many, how long, who else was involved, what the numbers were.**
> This is the opening question about this claim."

That is a literal enumeration of metadata interrogatives. `GAP_HINTS[SPECIFICITY]`,
[question.py:182-185](api/engine/question.py#L182-L185), reinforces it:

> "Word the question so **a number, a headcount or a timeframe** is the natural
> answer."

The model complies. In the corpus, **86 of 92 VALIDATION questions (93.5%) are
metadata**, and metadata is **0%** of every other probe level (see B2). This is
not model drift — it is instruction-following.

### A4. Are we encouraging evidence questions?

Yes, at the other four levels, and the briefs are well written:

| Level | Brief asks for | Corpus result |
|---|---|---|
| OPERATIONAL | "the steps, the cadence, the systems they worked in" | 78/82 process (95.1%) |
| INCIDENT | "a particular time it went wrong, or the hardest week" | 85/85 failure (100%) |
| DECISION | "what they decided, what they considered and rejected, and why" | 58/63 decision (92.1%) |
| OUTCOME | "how they knew it worked, which number moved" | 63/63 metrics (100%) |
| TRANSFER | "only the reasoning… do NOT ask for numbers, tools or results" | 10/10 transfer (100%) |

**Every brief is being followed with 92–100% fidelity.** The prompt layer is
working exactly as designed. The design is what needs review, in one place.

### A5. Worked examples of the defect

Model output under the VALIDATION brief, with the evidence it produced
(Tier B, simulator conditioned on the question):

```
Q  How many employees were in the contact centre you managed?       sig=2  score=12
Q  How many team members attended the daily stand-ups you ran?      sig=2  score=15
Q  How many pricing approvals did you handle monthly?               sig=3  score=20
Q  How many disbursement checks did you handle monthly?             sig=3  score=21
```

These are **7 of the 8 weakest answers in the entire simulated corpus.** The
answer to "how many X" is one cardinal number plus social filler; there is
nothing else for the signal extractor to count.

Against the hand-written VALIDATION fallback, which is open:

```
Q  On "Owned attrition, engagement surveys and the onboarding programme." —
   Tell me more about this — what exactly was your scope, and what were
   the numbers?                                                     sig=14 score=62
```

That is the **single strongest answer in the simulated corpus**, and the question
was never generated by a model or seen by the validator.

---

## B. Phase 3 corpus classification

### B1. Counts and percentages

**Questions actually asked (n = 395, `is_final=True`):**

| Category | n | % | Example |
|---|---:|---:|---|
| Failure / Incident | 88 | 22.3% | *"Describe a specific week when process optimization efforts failed to improve AHT."* |
| **Metadata** | **86** | **21.8%** | *"How many escalations did you handle weekly?"* |
| Process | 83 | 21.0% | *"What specific steps did you take daily to optimize backend processes?"* |
| Metrics | 67 | 17.0% | *"How did you measure the success of the calibration sessions?"* |
| Decision | 58 | 14.7% | *"What factors led you to choose Tableau over Power BI for a specific dashboard?"* |
| Transfer | 10 | 2.5% | *"How would you manage AHT improvements using your team huddle approach?"* |
| unclassified | 3 | 0.8% | — |

**All generation attempts including rejected drafts (n = 519):**

| Category | n | % |
|---|---:|---:|
| Metadata | 118 | 22.7% |
| Process | 109 | 21.0% |
| Failure / Incident | 102 | 19.7% |
| Metrics | 100 | 19.3% |
| Decision | 65 | 12.5% |
| Transfer | 17 | 3.3% |
| unclassified | 8 | 1.5% |

Only 1.0% of questions matched more than one category cue, so the taxonomy
partitions this corpus cleanly.

### B2. The cross-tab that carries the finding

**Question category × probe level (n = 395):**

| probe | metadata | process | decision | failure | metrics | transfer | other | n |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| VALIDATION | **86** | 3 | 0 | 0 | 3 | 0 | 0 | 92 |
| OPERATIONAL | 0 | 78 | 0 | 2 | 1 | 0 | 1 | 82 |
| INCIDENT | 0 | 0 | 0 | 85 | 0 | 0 | 0 | 85 |
| DECISION | 0 | 2 | 58 | 1 | 0 | 0 | 2 | 63 |
| OUTCOME | 0 | 0 | 0 | 0 | 63 | 0 | 0 | 63 |
| TRANSFER | 0 | 0 | 0 | 0 | 0 | 10 | 0 | 10 |

**Question type and probe level are the same variable in this corpus.** The
matrix is near-diagonal. Two consequences:

1. The metadata problem is **entirely** a VALIDATION problem. Fixing one brief
   addresses 100% of it. No other level leaks metadata at all.
2. Section D **cannot separate "question type" from "probe level"** as causes.
   Every correlation below is a joint effect. Stated again where it matters.

### B3. Volume balance

23% of the interview budget is spent on the question type that yields the least
evidence, and 2.5% on transfer. DECISION — the level whose brief best matches
"pick competence" — gets 16% of questions.

### B4. Claim extraction ruled out

40.2% of claims (37/92) carry no metric, which looks like an extraction gap. It
is not: the metric-less claims are legitimate (*"Ran the deal desk."*, *"Owned
resolution time for P1 issues."*), and
[api/prompts/extract_claims.txt](api/prompts/extract_claims.txt) explicitly
instructs `null` there — *"A claim with no number is still a claim — never drop
one for lacking a metric."*

Measured impact on downstream evidence (Tier B):

| | no-metric claim | metric claim | diff | t |
|---|---:|---:|---:|---:|
| signals/answer | 6.01 (n=166) | 6.32 (n=139) | −0.31 | −1.33 |
| answer_score | 31.35 | 34.22 | −2.87 | −2.53 |
| dims/answer | 3.79 | 3.95 | −0.16 | −1.66 |

Small and only marginally significant. **Claim extraction is not a source of the
quality problem.** Leave it alone.

---

## C. Real interview analysis — this section cannot be answered, and that is the finding

The request was to identify questions that produced weak answers, confusion,
"I don't know" and "I don't understand". **The corpus contains no such data**,
for a structural reason worth recording.

The 68 interviews split into two tiers with fundamentally different answer
mechanics ([scripts/interview_study.py:593-600](scripts/interview_study.py#L593-L600)):

- **Tier A (132 rows, 4 authored personas).** Answers come from a **fixed pool
  indexed by `claim_type` and consumed in order**. The answer is a function of
  position, *not of the question asked.* Correlating question type with answer
  quality here measures nothing.
- **Tier B (387 rows, 64 generated personas).** An LLM simulator conditioned on
  the question. This is the only tier where a question can cause an answer.

Measured over answers:

| | Tier B (n=305, causal) | Tier A (n=90, not causal) |
|---|---:|---:|
| Hedged / vague answers | **0 (0.0%)** | 22 (24.4%) |
| Explicit "I don't know / don't remember" | **0 (0.0%)** | 20 (22.2%) |
| Confusion / "I don't understand" / clarify | **0** | 0 |
| Zero-signal answers | **0** | 26 |

**The simulator never once produced a weak answer in 305 attempts**, despite
`_SIMULATOR_PROMPT` instructing it to: *"If the resume does not really support an
answer to this question, be vague and move on, the way a real person does."*
Hedge rate is 0.0% in every one of the five question categories.

This supersedes the diagnosis in CLAUDE.md that the repair turn fired zero times
because `is_non_answer()` is too strict. That is true but downstream of a larger
fact: **there was never a non-answer for it to catch.** No question in the causal
tier produced confusion, so the study cannot say which questions confuse people.

Nobody has been misled — Phase 3's own plan reports the repair-turn result as a
failure rather than fixing it. But the fix belongs in the *simulator*, not in
`is_non_answer()`.

### What the corpus *can* say about weak answers

Within Tier B, ranking by signals found, the weakest answers cluster hard:

**7 of the 8 weakest answers are closed-cardinality VALIDATION/metadata
questions** (sig 2–3, answer_score 12–21). The strongest are INCIDENT/failure and
OPERATIONAL/process (sig 11–13), plus the open VALIDATION fallback (sig 14).

```
WEAK   "How many employees were in the contact centre you managed?"
       → "…we had around 150 employees working across both sites. It was a
          challenging but rewarding experience…"              sig=2

STRONG "Tell me about the hardest week you had running the deal desk."
       → "…during a critical quarter-end. We had multiple high-stakes deals…
          One deal had a requested discount way above our standard…"   sig=11
```

That is a genuine signal about question *strength*. It says nothing about
confusion, and it should not be reported as if it did.

---

## D. Correlation analysis

### D1. The methodological constraint that governs every number here

An evidence row is written only when the dimension was **targeted by the probe
level** or the candidate scored >0 on it anyway
([evidence.py:286-306](api/engine/evidence.py#L286-L306),
`signals.PROBE_LEVEL_DIMENSIONS`). So:

- Where a dimension is **targeted**, the mean **includes zeros** — honest.
- Where it is **not targeted**, the mean is conditional on score>0 — **biased
  upward** and not comparable.

Comparisons below are restricted to cells where both sides are targeted. This
invalidates one comparison I initially drew (failure vs decision on causal
reasoning) — the failure arm sits at 72% coverage and is inflated. It is dropped.

### D2. Unbiased evidence matrix (Tier B, n = 305)

`·` = not targeted at that level, so not comparable.

| dimension | metadata | process | decision | failure | metrics |
|---|---:|---:|---:|---:|---:|
| SPECIFICITY | **54.3** | · | · | 30.4 | · |
| PROCESS | · | **93.6** | 70.7 | · | · |
| CAUSAL_REASONING | · | · | 29.2 | · | 28.0 |
| METRIC_OWNERSHIP | 25.3 | · | · | · | **53.6** |
| TOOL_FAMILIARITY | · | 43.0 | · | · | · |
| AUTHENTICITY | · | · | · | 32.2 | · |

**Valid head-to-head tests:**

| dimension | winner | loser | diff | t | 95% CI | n |
|---|---|---|---:|---:|---|---|
| METRIC_OWNERSHIP | metrics **53.6** | metadata 25.3 | +28.3 | 7.13 | [20.5, 36.1] | 60/67 |
| SPECIFICITY | metadata **54.3** | failure 30.4 | +23.9 | 6.64 | [16.8, 30.9] | 67/67 |
| PROCESS | process **93.6** | decision 70.7 | +22.9 | 5.10 | [14.1, 31.7] | 60/49 |
| CAUSAL_REASONING | metrics 28.0 | decision 29.2 | −1.2 | −0.25 | [−10.5, 8.1] | 60/49 |

**Overall evidence yield, by category (Tier B):**

| category | signals/answer | sd | dims/answer | answer chars |
|---|---:|---:|---:|---:|
| process | **7.42** | 1.71 | 3.70 | 385 |
| metrics | 6.53 | 1.78 | **4.27** | 393 |
| failure | 6.24 | 2.03 | 4.21 | 409 |
| metadata | 5.45 | 2.15 | 3.85 | **271** |
| decision | **5.04** | 1.54 | **3.18** | 394 |

### D3. What this actually shows

1. **Metadata questions are the best source of SPECIFICITY (54.3) and the worst
   source of METRIC_OWNERSHIP (25.3).** They are not useless — they are
   *narrow*. They buy one dimension and starve the rest: lowest signals/answer
   of any non-decision category and by far the shortest answers (271 chars vs
   385–409).

2. **Metric ownership is bought by asking how, not how much.** 25.3 → 53.6 for
   the same dimension at the same 100% coverage. This is the best-powered result
   in the audit (t=7.13, n=127) and the clearest lever available.

3. **Causal reasoning is uniformly broken and no question type fixes it.**
   28.0 vs 29.2 with a CI straddling zero, and it is the lowest-scoring dimension
   corpus-wide (34.1 mean across all 273 rows). Both the DECISION and OUTCOME
   briefs target it directly and neither moves it. **This points at the rubric or
   the signal extractor, not at question generation** — and it should not be
   chased with a prompt change.

4. **Decision questions produce the least evidence of any category** (5.04
   signals, 3.18 dims/answer) — while being the type that most directly serves
   "pick competence". Confounded with probe level and not separable here, but it
   is the most interesting thing to measure next.

5. **Question type is confounded with probe level** (B2), so every row above is
   really "the effect of the probe level and its question style jointly". No
   claim in this document separates them, because this corpus cannot.

6. **The gap-hint (`target_dimension`) mechanism cannot be evaluated on this
   data.** The policy targets a dimension *because* it is weak, so the raw
   comparison is a selection effect, not an efficacy measure — CAUSAL_REASONING
   reads 32.0 when targeted vs 37.6 when not, which is regression to the mean,
   not a hint that backfires. Measuring this needs a hint-on/hint-off A/B that
   was never run. **Do not read the negative numbers as evidence the hints hurt.**

### D4. Two structural rules tested and found neutral

| test | result |
|---|---|
| Compound ("and") vs single-ask model questions | signals 5.94 vs 6.09, t=−0.48. **No effect.** The prompt's "one answerable thing" rule is a UX/WhatsApp rule, not an evidence rule. |
| Longer (>11w) vs shorter model questions | 6.26 vs 5.67, t=2.15. Weak, marginal. Not actionable. |

---

## E. Fallback and validator analysis

### E1. How often each path fires (n = 395 asked)

| source | n | % |
|---|---:|---:|
| `model` (accepted first try) | 304 | 77.0% |
| `regenerated` (accepted second try) | 58 | 14.7% |
| `fallback` (both attempts rejected, or model failed) | 33 | 8.4% |

Attempt-1 reject rate **23.0%** (91/395). Attempt-2 reject rate **36.3%**
(33/91) — so **regeneration rescues 63.7%** of rejected questions, and the
remaining third fall through to the fallback.

### E2. Rejection reasons (all 519 attempts, 127 violations)

| rule | fires | % | attempt 1 | attempt 2 |
|---|---:|---:|---:|---:|
| `answer_leakage` | 55 | 43.3% | 45 | 10 |
| `duplicate_content` | 40 | 31.5% | 25 | 15 |
| `no_claim_anchor` | 14 | 11.0% | 10 | 4 |
| `multiple_fact_targets` | 9 | 7.1% | 8 | 1 |
| `scope_drift` | 5 | 3.9% | 3 | 2 |
| `unsupported_metric` | 4 | 3.1% | 2 | 2 |
| `hypothetical_misuse` | **0** | 0% | 0 | 0 |

`duplicate_content` **gets relatively worse under regeneration** — 6.3% of
attempt-1 drafts vs 16.5% of attempt-2 drafts. The retry hint *"this repeats an
earlier question; ask something new"* is the least effective of the seven.

**Reject rate by probe level (attempt 1):**

| probe | rejected | % |
|---|---|---:|
| TRANSFER | 4/10 | 40.0% |
| OUTCOME | 23/63 | 36.5% |
| VALIDATION | 31/92 | 33.7% |
| OPERATIONAL | 18/82 | 22.0% |
| INCIDENT | 11/85 | 12.9% |
| DECISION | 4/63 | 6.3% |

VALIDATION and OUTCOME both ask about the claim's own figure, so they collide
with `answer_leakage` (29 and 13 fires) by construction.

### E3. Is the fallback worse than a generated question?

**No. Measured, and the point estimates run the other way** (Tier B):

| | fallback (n=21) | model (n=244) | diff | t | 95% CI |
|---|---:|---:|---:|---:|---|
| signals/answer | 6.95 | 6.06 | +0.90 | 1.58 | [−0.21, +2.00] |
| answer_score | 35.76 | 31.68 | +4.08 | 1.58 | [−0.97, +9.13] |
| dims/answer | 4.19 | 3.79 | +0.40 | 2.35 | [+0.07, +0.74] |

Read this carefully. Two of the three intervals cross zero and n=21, so the
correct statement is **not** "the fallback is better". It is:

> **There is no evidence that falling back costs quality.** The 8.4% fallback
> rate is not a quality leak, and the assumption that it is should not drive
> any change.

The strongest single answer in the corpus came from the VALIDATION fallback
(A5). The mechanism is plausible: the fallbacks are open and two-part
(*"what exactly was your scope, and what were the numbers?"*), where the model,
following the brief, asks a closed cardinal question.

Supporting detail, per probe level (Tier B, small n on the fallback arm):

| probe | model signals | fallback signals |
|---|---:|---:|
| VALIDATION | 5.16 (n=51) | 10.00 (n=3) |
| OPERATIONAL | 7.35 (n=52) | 9.25 (n=4) |
| INCIDENT | 6.26 (n=57) | 6.67 (n=3) |
| DECISION | 5.06 (n=47) | 4.67 (n=3) |
| OUTCOME | 6.43 (n=37) | 5.62 (n=8) |

### E4. Open vs closed VALIDATION — the mechanism, at low power

Within the VALIDATION level, splitting on closed-cardinality phrasing
("how many / how much / how long / how often"):

| | closed (n=64) | open (n=4) | diff | t |
|---|---:|---:|---:|---:|
| signals/answer | 5.2 | 9.5 | −4.3 | −2.71 |
| answer_score | 31.3 | 51.5 | −20.2 | −4.48 |
| METRIC_OWNERSHIP | 23.8 | 50.0 | −26.2 | −2.44 |
| answer chars | 264 | 400 | −136 | −3.49 |

**The open arm is n=4, and 3 of the 4 are the same fallback sentence.** This is
one hand-written question measured four times, not a result. It is included
because it points the same direction as the well-powered D2 finding
(25.3 vs 53.6, n=127), not because it stands alone. **Do not cite E4 as
evidence on its own.**

### E5. Validator quality — already measured, cited not restated

`studies/phase3/confusion_matrix.md` and `validator_disagreements.md` carry the
human-labelled result. The headline, post-Phase-4A rescore
(`phase4_insample_rescore.json`, **in-sample, direction only**):

| | pre-4A | post-4A |
|---|---:|---:|
| Reject rate | 25.5% | 22.6% |
| Precision | 54.0% | 54.3% |
| Recall | 50.7% | 46.9% |
| `answer_leakage` precision | 79.2% | **86.4%** |
| `duplicate_content` precision | 38.5% | **27.3%** |

The Phase 4A changes helped the rule that was working and hurt the rule that was
not. `duplicate_content` now fires 27 times at 27.3% precision — **the worst
cost/benefit ratio in the validator**, and it is the second-highest-volume rule.

### E6. One new validator finding this audit adds

`unsupported_metric` fires **exactly 4 times in 519 rows, and all 4 are TRANSFER
probes on the same claim**:

```
claim:  "Managed a team of 45 agents and consistently exceeded all CSAT targets"
Q:      "How would you apply a focus on quality to achieve a 30% CSAT
         improvement across the whole process?"            → unsupported_metric
```

The `30%` is not invented. It comes from the **planner's own chosen target
claim** — *"Drove a 30% improvement in CSAT scores across the entire process"* —
selected by `select_transfer()` as the T1 substitution.

In [question.py:493](api/engine/question.py#L493), `validate()` builds
`claim_numerals` from `claim_text` and `claim_metric` only. Rules 6 and 7 both
receive and use `target_claim_text`; **rules 1 and 5 do not.** So the validator
rejects the transfer question for containing the figure the planner told the
model to put in it.

This is structurally the same defect class as the documented rule-2/rule-7
conflict fixed in Phase 4A: two rules disagreeing about what the question is
allowed to name.

**Caveat that keeps this honest:** the human review sampled one of these four and
*agreed* with the validator (`unsupported_metric` 1/1). At n=4, with 1 human
label pointing the other way, this is a **code-visible mechanism with
insufficient outcome data**, not a proven false-positive class. It is also why
TRANSFER shows a 40% reject rate — on n=10.

---

## F. Recommendations

### F1. What should remain unchanged

| Item | Why |
|---|---|
| **`api/prompts/generate_question.txt` body** | Every constraint in it is being followed at 92–100% fidelity. It is not the problem. |
| **No few-shot examples** | The stated reason (per-cohort authoring cost, bias re-entry) still holds, and nothing measured argues against it. |
| **The fallback templates** | E3: no measured quality cost. Changing them optimises a non-problem and risks the one path that must never fail. |
| **The one-regeneration cap** | Regeneration rescues 63.7%; a third attempt would buy less against the +20% latency guardrail. |
| **`hypothetical_misuse`** | 0 fires. Already ruled on in the Phase 3 plan §11 — it costs nothing and guards a regression. Do not delete. |
| **`DUPLICATE_JACCARD = 0.37`** | Counter-metric C7. Its precision problem is structural, not a threshold. |
| **Claim extraction and classification** | B4: measured, marginal, correctly specified. |
| **The `is_non_answer()` / repair-turn behaviour** | C: the corpus never produced a non-answer. Tuning it against zero observations is fitting to nothing. |
| **`OUTCOME` and `INCIDENT` and `OPERATIONAL` briefs** | The three highest evidence yields in the corpus come from these. |

### F2. Prompt changes justified by data

**P1 — Rewrite `PROBE_BRIEFS[VALIDATION]`. This is the one change the data
actually supports.**

Evidence: 93.5% of VALIDATION questions are metadata (B2); the brief literally
enumerates "how many, how long" (A3); metadata is the lowest-yield category on
four of five measures (D2); VALIDATION's METRIC_OWNERSHIP is 25.3 against
OUTCOME's 53.6 at t=7.13 (D3); 7 of the 8 weakest answers in the corpus are
VALIDATION metadata (C); and VALIDATION carries 33.7% of the reject rate through
`answer_leakage` collisions (E2).

Direction — ask for **scope as a described shape** rather than as a cardinal
count, which is what the fallback already does and what the brief's own first
sentence ("establish that they actually held this scope") already says. The
enumerated interrogatives contradict the sentence above them.

**Do not** move metadata to another level or delete it: metadata is the best
source of SPECIFICITY in the corpus (54.3, t=6.64). The goal is to stop it
crowding out METRIC_OWNERSHIP at the level that also targets it.

**P2 — Reconsider `GAP_HINTS[SPECIFICITY]`.** It is the second metadata
instruction (A3). Lower confidence: its efficacy is unmeasurable on this data
(D3.6), so this is a consistency argument, not a measured one. Change it only
alongside P1, and measure both together.

**Not justified:** anything aimed at causal reasoning. It is the worst dimension
corpus-wide and neither of the two briefs that target it moves it (D3.3). That
is a rubric/extractor question and a prompt change would be aimed at the wrong
layer.

### F3. Validator changes justified by data

**V1 — Pass `target_claim_text` numerals into rules 1 and 5.** (E6)
Smallest, most contained, and the mechanism is visible in code rather than
inferred from labels. Caveat: n=4, one contrary human label. Treat as a
correctness fix to a rule that is inconsistent with rules 6 and 7, not as a
precision win — and do not expect it to move any aggregate metric.

**V2 — `duplicate_content` needs a decision, not a tweak.** 27 fires at 27.3%
precision post-4A, worse than pre-4A. The two obvious fixes are both already
disqualified: threshold tuning is C7, and claim-id gating was measured to change
**zero** verdicts across all 519 rows ([question.py:504-521](api/engine/question.py#L504-L521)).
This audit adds no new mechanism, so the honest position is **it is unresolved
and should not be touched on a guess.**

**V3 — `multiple_fact_targets` and `scope_drift` remain 0-for-5.** Unchanged
from `validator_disagreements.md` Finding 6, and this audit adds no evidence
either way (9 and 5 fires). n is still not a verdict. Leave them.

### F4. Defer until after the hackathon

| Deferred | Why | Trigger |
|---|---|---|
| **`unsupported_premise` (8th rule)** | Largest defect class (9/32 false accepts), but the human's own labels split 6/7 on it. Cannot be specified crisply enough to code. | `validator_disagreements.md` Finding 4 — 15 min of re-labelling plus a 20-item κ. |
| **Fixing the simulator so it can hedge** | The single largest gap in the measurement apparatus (C). Blocks any future work on confusion, repair turns and non-answers. | Before any Phase 5 study. Cheap: the instruction exists and is ignored; it needs to be enforced, not written. |
| **Rebalancing the probe budget** | DECISION gets 16% of questions and yields the least evidence (5.04); TRANSFER gets 2.5%. Real, but confounded with question type (D3.5) and unresolvable on this corpus. | A study that varies probe level and question style independently. |
| **Causal-reasoning rubric investigation** | Lowest dimension corpus-wide (34.1), immune to both briefs that target it. Different layer, different owner. | Post-hackathon. Owner A (`signals.py` / `evidence.py`). |
| **P1/P2 efficacy measurement** | The gap-hint mechanism has never been A/B'd (D3.6). | Alongside the P1 rewrite. |

### F5. If only one thing is done

Rewrite `PROBE_BRIEFS[VALIDATION]` (F2-P1), and measure it by re-running the
Phase 3 harness on **new** interviews — never by re-scoring these 519 rows, which
is C7. The expected movement is VALIDATION's METRIC_OWNERSHIP off 25.3 and the
VALIDATION reject rate off 33.7%. If neither moves, the hypothesis was wrong and
should be recorded as such rather than patched.

---

## Appendix — reproducing this

```bash
cd studies/phase3
python3 analyze.py           # joins CSV -> sqlite -> recs.json (395 rows, 0 unmatched)
# classify.py holds the cue sets; classification is deterministic
```

`classify.py`, `analyze.py` and `recs.json` are audit scratch, written into
`studies/phase3/` alongside the data they read. They are **not** part of `api/`
and nothing in the service imports them. Delete them if they are unwanted —
every number above is reproducible from the CSV and the sqlite file.

**Counter-metrics respected:** no corpus entry added (C6); no threshold tuned
against the study sample (C7); `api/` unmodified (Phase 3 acceptance criterion 1).
