# Answers: the exact prompt, the exact fallbacks, the exact validator rules

**Date:** 2026-09-06 · Artifacts and measurements. No code changed.

---

# Question 1 — the exact prompt sent to GPT

**Your suspicion is confirmed verbatim.** The brief literally contains
*"how many, how long, who else was involved, what the numbers were."*

## There is no question-generation system prompt

`api/llm.py:39` — one generic system message, **shared by all four prompts in
the repo** (`extract_claims`, `extract_signals`, `generate_question`,
`classify_role`):

```
You are a precise information-extraction service. You return only valid JSON
matching the requested schema. No prose, no explanation, no markdown fences.
```

The model is never told it is an interviewer, never told what the product is
for, and never told that authorship is the thing being tested. **Every piece of
interview framing lives in the user message.**

## There are no few-shot examples

Zero, anywhere in the question path. This is deliberate and documented at
`api/engine/question.py:675-683`: worked examples are a per-cohort authoring
cost and re-introduce family bias into code. Note the consequence — the model's
only guidance on *what a good question looks like* is the prose brief.

## The complete user message, rendered for a real claim

Claim: `Built REST APIs on Postgres and deployed to Kubernetes on AWS.`
Probe level: `VALIDATION`. Template: `api/prompts/generate_question.txt`.

```
You are interviewing a candidate about ONE claim from their resume. Write the
NEXT question. One question only.

THE CLAIM
---------
Built REST APIs on Postgres and deployed to Kubernetes on AWS.        ← $claim_text
Claim type: Technology depth                                          ← $claim_type_label
Measurable core: none stated                                          ← $claim_metric
Job family: Software Engineering                                      ← $family_label

THE PROBE LEVEL YOU MUST ASK AT: VALIDATION                           ← $probe_level

VALIDATION — establish that they actually held this scope. Ask for     ← $probe_level_brief
the shape of it: how many, how long, who else was involved, what the      ★★★
numbers were. This is the opening question about this claim.

ALREADY ASKED AND ANSWERED IN THIS SESSION
------------------------------------------
(nothing yet — this is the first question of the session)             ← $prior_qa

                                                                      ← $gap_hint (empty here)

RULES
  - Do not repeat anything already asked above.
  - ONE question. Under 32 words. It is read on WhatsApp on a phone.
  - Plain, direct language. No jargon the candidate did not use first. No
    corporate warm-up ("I'd love to understand..."). Just ask.
  - Ask about THEIR actual experience, and never a definition quiz ("what is
    the formula for that metric?"). We are testing whether they did the work,
    not whether they memorised definitions.
  - No hypotheticals — UNLESS the probe brief above explicitly asks for one.
    When it does, the hypothetical is the point: it is what a memorised resume
    cannot answer.
  - Never comment on their English, and never ask them to elaborate "more
    professionally". Score is on evidence, not presentation.
  - One answerable thing. No two questions joined by "and also".
                                                                      ← $violations (empty on attempt 1)

Return ONLY JSON, no prose, no markdown fences, matching this schema:

{"question": "string", "probe_level": "VALIDATION"}
```

The `★★★` line is the entire content specification for the question. Everything
below it is a constraint. **The model is doing exactly what it is told.**

## The other injected briefs, verbatim (`question.py:73`)

| level | brief |
|---|---|
| **VALIDATION** | "…Ask for the shape of it: **how many, how long, who else was involved, what the numbers were.** This is the opening question about this claim." |
| OPERATIONAL | "…Ask for the mechanics: the steps, the cadence, the systems they worked in, what they looked at each morning." |
| INCIDENT | "…Ask about a particular time it went wrong, or the hardest week. Real practitioners produce concrete detail here…" |
| DECISION | "…Ask what they decided, what they considered and rejected, and why they chose as they did." |
| OUTCOME | "…Ask what happened afterwards, how they knew it worked, which number moved, and what they would do differently." |
| TRANSFER | "…Ask only for the reasoning… Do NOT ask for numbers, tools or results — this did not happen, so there are none." |

And the second metadata instruction, `GAP_HINTS[SPECIFICITY]`
(`question.py:182`), appended when the planner targets that dimension:

> "The answers so far have been short on concrete figures. Word the question so
> **a number, a headcount or a timeframe is the natural answer.**"

**Measured consequence:** 93.5% of VALIDATION questions are metadata; metadata is
**0%** of every other probe level. The distribution is not model drift — it is
compliance.

---

# Question 2 — the fallback templates

**One correction to your premise, and it matters:
`How long did the REST API integration project take?` is not a fallback. No
fallback can produce that shape.**

Measured: of the 32 asked questions matching *"how long"* or *"how many
weeks/months"*, **19 came from `source=model` and 13 from
`source=regenerated`. Zero came from `source=fallback`.**

**Fallback questions containing "how long" or "how many": 0 of 33.**

## Where it lives

`api/engine/question.py:132` (`FALLBACK_QUESTIONS`), `:166`
(`TRANSFER_FALLBACKS`), `:611` (`fallback_question()`), `:638`
(`REPAIR_PROMPTS`).

## Does it bypass the LLM entirely?

**Yes, completely.** `fallback_question()` is pure Python — a dict lookup plus
string formatting. It is passed to `complete_json(..., fallback=lambda: ...)`,
so it is returned without any network call when the model fails, and it is
returned directly when both validation attempts fail. `REPAIR_PROMPTS` likewise
makes no model call. **No fallback path ever reaches GPT.**

## The literal templates

```python
FALLBACK_QUESTIONS = {                                    # question.py:132
  VALIDATION:  "Tell me more about this — what exactly was your scope, and what were the numbers?",
  OPERATIONAL: "How did this work day to day? Walk me through the steps and the systems you used.",
  INCIDENT:    "Tell me about one specific time this went wrong. What happened that week?",
  DECISION:    "What did you decide to do about it, and what did you consider but decide against?",
  OUTCOME:     "What happened afterwards? How did you know it worked, and which number moved?",
  TRANSFER:    "Suppose that had moved the number the wrong way instead. What would you check first, "
               "and what would rule a cause out?",
}
```

Rendered as `On "<claim, truncated to 90 chars>" — <base>`. A real one that
reached a candidate:

```
On "Carrying a quota of $1.2M ARR." — How did this work day to day? Walk me
through the steps and the systems you used.
```

`TRANSFER_FALLBACKS` (`:166`) are `string.Template`s filled from the planner's
`TransferSpec`; `REPAIR_PROMPTS` (`:638`) are six more fixed lines used when an
answer is classed a non-answer — **which fired 0 times in 68 interviews.**

## How often it activates

| source of the question actually asked | n | % |
|---|---:|---:|
| `model` — accepted first try | 304 | 77.0% |
| `regenerated` — accepted second try | 58 | 14.7% |
| **`fallback`** | **33** | **8.4%** |

By probe level: OPERATIONAL 9, OUTCOME 9, VALIDATION 5, INCIDENT 4, DECISION 3,
TRANSFER 3.

## Is the fallback producing metadata garbage?

**No — measured, and it slightly outperforms the model** (Tier B):

| | fallback (n=21) | model (n=244) | t |
|---|---:|---:|---:|
| signals/answer | 6.95 | 6.06 | 1.58 |
| answer score | 35.76 | 31.68 | 1.58 |
| dimensions/answer | 4.19 | 3.79 | 2.35 |

Two of three intervals cross zero at n=21, so the honest claim is **no evidence
of quality loss**, not "better". But the strongest single answer in the entire
corpus (14 signals, score 62) came from the VALIDATION fallback:

```
On "Owned attrition, engagement surveys and the onboarding programme." —
Tell me more about this — what exactly was your scope, and what were the numbers?
```

**The fallback is open-ended and the model's VALIDATION question is not.** The
fallbacks are not the problem you need to fix. `FALLBACK_QUESTIONS[VALIDATION]`
is arguably the best VALIDATION question in the system.

---

# Question 3 — the validator rules, and the Option A / B decision

## `answer_leakage` — the exact code

`question.py:493-502`

```python
claim_numerals   = _numerals(claim_text) | _numerals(claim_metric or "")
answer_numerals  = set()
for answer in prior_answers:
    answer_numerals |= _numerals(answer)
question_numerals = _numerals(text)

# 1 — answer leakage.
if question_numerals & claim_numerals:
    violations.append("answer_leakage")
```

`_NUMERAL = re.compile(r"(?<![A-Za-z0-9])\d+(?:[.,]\d+)?")` (`:334`)

**It is a set intersection over numerals. Nothing else.** It cannot see whether a
figure is the thing being asked for or merely the referent — it only sees that
the digits appear in both strings.

The critical asymmetry, and it is already in the code: **`answer_numerals` is
computed but is not used by rule 1** — it is used by rule 5
(`unsupported_metric`). The effect is that a figure the *candidate volunteered*
passes rule 1 and rule 5; a figure from the *resume* is blocked by rule 1.

## `no_claim_anchor` — the exact code

`question.py:564-601`

```python
subject        = _words(text,       _STOP_SUBJECT, stem=True)
claim_subject  = _words(claim_text, _STOP_SUBJECT, stem=True)
label_subject  = _words(claim_type_label(job_family, claim_type), _STOP_SUBJECT, stem=True)

anchors = claim_subject | label_subject
if prior_answers:
    anchors |= _words(prior_answers[-1], _STOP_SUBJECT, stem=True)   # last answer counts
if probe_level is ProbeLevel.TRANSFER and target_claim_text:
    anchors |= _words(target_claim_text, _STOP_SUBJECT, stem=True)

# 7 — no claim anchor.
if not (subject & anchors):
    violations.append("no_claim_anchor")
```

A **stemmed word-set intersection**. It already admits the last answer's
vocabulary, so it is partly conversation-aware. What it cannot do is resolve a
pronoun: *"that number"*, *"that project"*, *"it"* contribute nothing to
`subject` because `_STOP_SUBJECT` strips them and no anaphora resolution exists.

## Current health of both rules

| rule | fires (519 attempts) | human precision (post-4A) |
|---|---:|---:|
| **`answer_leakage`** | **55 → 51 today** | **86.4% — best of six** |
| `no_claim_anchor` | 14 | 28.6% |
| `duplicate_content` | 40 | 27.3% |
| `multiple_fact_targets` | 9 | 0% |
| `scope_drift` | 5 | 0% |
| `unsupported_metric` | 4 | (n=1) |

*(Re-running the 55 CSV fires through today's validator: **51 still fire**; 4 no
longer do — they were the `P1`/`p95` tokenisation bug, fixed in Phase 4A.
`_numerals("Owned resolution time for P1 issues.")` now returns `[]`.)*

## The answer to your question: neither A nor B — Option C

I tested the three rejected spec-conformant questions against the live
validator, then rewrote each to **name the metric instead of quoting the number**
and **name the subject instead of saying "that number"**. The forensic ask is
identical in every pair. Only the referring expression changed.

| verdict | question |
|---|---|
| **REJECT** `answer_leakage` | "You mentioned a 63% activation rate. How was that number calculated?" |
| **ACCEPT** | "You mentioned the activation rate. How was it calculated?" |
| **ACCEPT** | "How was activation counted — who was in the denominator?" |
| **REJECT** `answer_leakage` | "You mentioned growing activation from 41% to 63%. What changed that made activation go up?" |
| **ACCEPT** | "You mentioned rebuilding the first-run flow. What changed that made activation go up?" |
| **REJECT** `no_claim_anchor` | "Who looked at that number besides you?" |
| **ACCEPT** | "Who else looked at the activation number every week?" |
| **ACCEPT** | "Besides you, who watched activation each week?" |

**All three conflicts dissolve with no validator change.** The collision was
never between the specification's *intent* and the validator — it was between
the specification's *example phrasings* and the validator.

### What this means for the three options

| option | cost | verdict |
|---|---|---|
| **A — keep the validator unchanged** | The generator must name metrics and subjects rather than quote figures and use pronouns. One added generator constraint, zero validator risk. | **This is the recommendation.** |
| **B — relax `answer_leakage` for conversational references** | Puts the highest-precision rule in the validator (86.4%, 51 live fires) at risk to buy a phrasing style that Option A already provides for free. Phase 3 measured 19 of 24 sampled `answer_leakage` rejects as **correct**. | **Not justified by the measurements.** |
| **C — constrain the generator instead** | Add to the forensic spec: *cite the metric by name, never by value; name the subject, never "that number".* | **= Option A, stated as a rule.** |

### The one thing Option A costs you

Your MEASUREMENT family's canonical opener — *"You mentioned a 40% improvement.
How was that number calculated?"* — **has to be rephrased**, to
*"You mentioned the AHT improvement. How was that calculated?"* or
*"How was AHT counted — over which calls?"*.

That is a real constraint on the spec, and it happens to be defensible on its
own terms: quoting the figure back is the one thing that tells a copier which
number to be confident about. **Not quoting it is better forensics, not just
better rule compliance.**

### Two residual notes

- `no_claim_anchor` sits at **28.6% precision** and fires 14 times. It is a weak
  rule independent of this decision. Nothing in this analysis argues for
  changing it, and nothing argues it is healthy.
- If you later want genuine pronoun reference (*"that project"*, *"it"*),
  the change is **anaphora resolution in rule 7**, not relaxation of rule 1.
  Those are different rules with opposite precision profiles, and they should
  not be traded against each other.
