# Forensic Question Generator — Specification

**Date:** 2026-09-06 · **Status: design specification. No code written.**
Optimisation target: **"Did this person actually do the work, or did they only
write it on a resume?"** — authorship verification, not interview quality, not
skill assessment, not rule compliance.

Evidence base: [PROBE_ARCHITECTURE_FACTUAL_AUDIT.md](docs/PROBE_ARCHITECTURE_FACTUAL_AUDIT.md),
[PROBE_LEVEL_FORENSIC_AUDIT.md](docs/PROBE_LEVEL_FORENSIC_AUDIT.md).
Converges with [QUESTIONING_PHILOSOPHY.md](docs/QUESTIONING_PHILOSOPHY.md).

---

## 1. The generator contract

### Standing instruction

> You are not an interviewer. You are a forensic examiner of a written claim.
>
> A resume claim is a statement made by an interested party about their own
> past. Knowledge is free — anything answerable from Google, ChatGPT, interview
> prep or general industry familiarity is **weak evidence**, because a stranger
> supplies it as well as the author.
>
> Strong evidence is **incidental detail**: facts that are cheap for the person
> who did the work to recall and expensive for anyone else to invent. What they
> had to leave out. Who they had to wait on. Which part didn't improve. What the
> number was measured against.
>
> Before returning any question, run this test: **two people answer — one did
> the work, one read the resume ten minutes ago. If the second answers nearly as
> well, the question is worthless. Discard it and ask something else.**

### Hard rules

| # | Rule |
|---|---|
| 1 | Anchor to one specific claim this candidate made. |
| 2 | Probe the periphery — exclusions, trade-offs, dependencies, failures, measurement, people, constraints, rejected alternatives. **Never the headline.** |
| 3 | Ask for recall, never for what they *would generally* do. |
| 4 | Never ask for a definition. |
| 5 | Never ask for an opinion. |
| 6 | Never ask a generic hypothetical. A hypothetical is permitted only when it is built from their own stated world with exactly one variable changed. |
| 7 | **Never ask how long, how many people, what the team size was, or what technologies were used** — unless that fact already emerged from a prior answer, in which case it may be referred to but not re-asked. |
| 8 | One question. One fact target. |
| 9 | Answerable out loud, on WhatsApp, in ninety seconds, from memory. |
| 10 | Natural spoken English. A sixteen-year-old understands every word. |

### Output

```json
{
  "question": "...",
  "reasoning": "why this separates an author from a copier",
  "family": "ESTABLISH | PERIPHERY | MEASUREMENT | SEAM | TRANSFER",
  "target_signal": "the incidental detail this is trying to surface"
}
```

`reasoning` is not shown to the candidate. It exists so the separation argument
is auditable — a question whose reasoning cannot name what a copier would fail
to produce has not been designed, only phrased.

---

## 2. The five families

| family | goal | may introduce new subject matter? | needs prior answers? |
|---|---|---|---|
| **ESTABLISH** | Prove they touched the work. Ask for the first move, not the result. | yes | no |
| **PERIPHERY** | Leave the rehearsed centre. Exclusions, dependencies, near-misses, people. | yes | no |
| **MEASUREMENT** | Own the metric before the result. Derivation, provenance, audience. | no | no |
| **SEAM** | Load two facts already stated and see if they hold together. | **no — never** | **yes** |
| **TRANSFER** | Their world, one variable changed. | no | yes |

**Why these five and not the current six.** Measured, from the corpus:

- **INCIDENT is the strongest probe in the current system** — 1.77 hard-to-invent
  signals/answer, 10.8% zero-yield, incident markers in 78.5% of answers against
  11.9–23.5% everywhere else. PERIPHERY generalises it.
- **DECISION leads no measurement in the corpus** and has the lowest answer score
  (26.8). Its useful half — the *rejected* option — is absorbed by PERIPHERY.
- **VALIDATION is the weakest probe** (0.82 dear, 39.7% zero-yield) and its
  metric-definition rate is **1.5% against OUTCOME's 42.4%**. ESTABLISH replaces
  the cardinality ask; MEASUREMENT takes the metric ask and moves it early.
- **SEAM has no analogue anywhere in the current architecture.**

---

## 3. Demonstration — real claims from the corpus

Left column is what the current system actually asked, with its measured
hard-to-invent yield. Right column is what this specification produces.

### 3.1 `Grew activation from 41% to 63% over two quarters by rebuilding the first-run flow`

| current system | dear |
|---|---:|
| "How many people were involved in rebuilding the first-run flow?" | 1 |
| "What specific actions did you take in the analytics dashboard each Monday?" | 1 |
| "What criteria did you use to decide which experiments to ship?" | 2 |
| "What specific change in the first-run flow had the biggest impact on activation?" | 2 |

```json
{"question": "You mentioned rebuilding the first-run flow. What was the first thing you looked at?",
 "reasoning": "The rebuild is the headline and is rehearsed. Where they started is not on the resume and is remembered by whoever did it. A copier names a generic artefact ('user research'); an author names a funnel step, a dashboard, or a complaint.",
 "family": "ESTABLISH", "target_signal": "the specific diagnostic entry point"}

{"question": "What part of the first-run flow did you leave alone?",
 "reasoning": "Every real rebuild has a piece nobody touched, and the reason is usually boring and specific — it was owned elsewhere, or it was risky. A copier has no basis to exclude anything and will either invent or generalise.",
 "family": "PERIPHERY", "target_signal": "an exclusion and its constraint"}

{"question": "How was activation counted — who was in the denominator?",
 "reasoning": "Activation has no standard definition. The author knows their own population and window; the copier knows the word. This is the one place the claim can be falsified rather than doubted.",
 "family": "MEASUREMENT", "target_signal": "metric derivation and population"}

{"question": "Besides you, who watched that number every week?",
 "reasoning": "Metric ownership has a social footprint — a standup, a review, a person who complained when it dipped. Cheap to recall, and a copier has no org to draw on.",
 "family": "MEASUREMENT", "target_signal": "the metric's audience"}
```

### 3.2 `Built REST APIs on Postgres and deployed to Kubernetes on AWS.` *(your worked example)*

| current system | dear |
|---|---:|
| "How many REST APIs did you build and deploy on AWS?" | **0** |
| "What factors led you to choose Kubernetes on AWS for deployment?" | 2 |
| "Describe a specific time when deploying an API to Kubernetes on AWS went wrong." | 2 |

```json
{"question": "When you first deployed to Kubernetes, what broke that you weren't expecting?",
 "reasoning": "First deployments always break, and how they break is specific to the setup — a health check timeout, a secret that wasn't mounted, an image that was too big. A copier produces a textbook failure; an author produces an annoying one.",
 "family": "PERIPHERY", "target_signal": "an unexpected operational failure"}

{"question": "Which part of that stack did you not pick yourself?",
 "reasoning": "Almost nobody chooses the whole stack. Naming the inherited piece requires knowing the org, and it quietly separates the person who joined the project from the person who designed it — without asking them to admit anything.",
 "family": "PERIPHERY", "target_signal": "an inherited constraint / scope boundary"}

{"question": "Who did you have to go to when a deploy needed something you couldn't change yourself?",
 "reasoning": "Dependencies are cheap to recall and impossible to invent convincingly — a platform team, a security review, one person with the AWS role. DEPENDENCY questions appear once in 395 in the current corpus.",
 "family": "PERIPHERY", "target_signal": "an external dependency"}
```

**Note what is absent:** no "how many APIs", no "why did you choose Kubernetes".
The first is rule 7 and measured at **0 hard-to-invent signals**. The second
supplies its own answer shape — the candidate need only agree fluently.

### 3.3 `Cut first response time from 9 hours to under 2.`

| current system | dear |
|---|---:|
| "How many team members were involved in reducing the response time?" | 1 |
| "How did you measure the improvement in response time after implementing changes?" | 2 |
| "Describe a specific incident when reducing response time didn't go as planned." | 2 |

```json
{"question": "When the clock started on a ticket, what actually started it?",
 "reasoning": "First response time is defined by when the timer starts — ticket creation, business hours, first human touch. Every support org argues about this. The author has a position; the copier has the phrase.",
 "family": "MEASUREMENT", "target_signal": "metric start condition"}

{"question": "Which kind of ticket never got faster?",
 "reasoning": "An average that moves hides a category that didn't. The author remembers the stubborn queue and usually why; a copier has no reason to believe any category resisted.",
 "family": "PERIPHERY", "target_signal": "the exclusion inside an aggregate"}
```

### 3.4 `Reviewed loan files for underwriting and cleared KYC exceptions before disbursement.`

| current system | dear |
|---|---:|
| "How many loan files did you review monthly and who else was involved?" | 3 |
| "Which system did you use to clear KYC exceptions and what steps did you take in it?" | **0** |
| "Describe a specific time you faced a challenging KYC exception and how you resolved it." | **0** |
| "What factors did you consider when deciding to clear a KYC exception?" | **0** |

```json
{"question": "What kind of exception could you clear yourself, and what kind had to go to someone else?",
 "reasoning": "Authority boundaries are precise, memorable and organisation-specific. It surfaces the real scope of the role without asking 'what was your scope', and a copier cannot guess where the line sat.",
 "family": "PERIPHERY", "target_signal": "authority boundary and escalation path"}

{"question": "You said you cleared exceptions before disbursement. What happened if one was still open when the disbursement date came?",
 "reasoning": "SEAM — it loads two things already stated (clearing exceptions, and the disbursement deadline) against each other. It cannot be answered by repeating either, and the real answer is a process everyone in that seat has lived through.",
 "family": "SEAM", "target_signal": "conflict resolution between two stated facts"}
```

Three of the four current questions on this claim produced **zero** hard-to-invent
evidence.

### 3.5 `Carrying a quota of $1.2M ARR.`

| current system | dear |
|---|---:|
| "How long did you carry this quota and who else was involved?" | 3 |
| "What was the final ARR achieved, and how did you track progress?" | 1 |
| "On 'Carrying a quota of $1.2M ARR.' — How did this work day to day? Walk me through the steps and the systems you used." *(fallback)* | **0** |

```json
{"question": "Was that quota just yours, or shared with someone?",
 "reasoning": "Quota structure is unglamorous and never on a resume, and it materially changes what the claim means. One sentence to answer honestly; nothing to draw on if you weren't carrying it.",
 "family": "ESTABLISH", "target_signal": "quota ownership structure"}

{"question": "Which deal in that number took the longest to close?",
 "reasoning": "Aims at one deal rather than the aggregate. The author reaches for a specific painful cycle; the copier has to invent a company, and invented deals are thin on the parts that made them slow.",
 "family": "PERIPHERY", "target_signal": "a specific deal with incidental friction"}
```

### 3.6 `Managed a team of 35 agents across 4 pods with 4 senior associates reporting to me`

| current system | dear |
|---|---:|
| "How long did you manage the team of agents?" *(regenerated from "…team of 35 agents?" by deleting the figure)* | 1 |
| "What criteria did you use to decide which senior associate handled specific issues?" | **0** |

```json
{"question": "When someone called in sick on a Monday, what did you actually do first?",
 "reasoning": "The most ordinary operational event in a 35-seat process. The author answers immediately and concretely — a roster tool, a specific person, an overtime call. A copier gives management theory.",
 "family": "PERIPHERY", "target_signal": "routine operational constraint handling"}

{"question": "Which of the four pods gave you the most trouble, and what was different about it?",
 "reasoning": "Uses a structural fact from their own claim to force a comparison they can only make from the inside. A copier has four identical pods because they have never met any of them.",
 "family": "SEAM", "target_signal": "differentiation within a stated structure"}
```

---

## 4. Integration findings — measured, not predicted

I ran ten specification-conformant questions through the **live**
`question.validate()` against a real corpus claim.

**Result: 3 of 10 rejected.** The failures are systematic, not incidental.

| spec question | verdict | rule |
|---|---|---|
| "You mentioned rebuilding the first-run flow. What was the first thing you investigated?" | ACCEPT | — |
| **"You mentioned growing activation from 41% to 63%. What changed that made activation go up?"** | **REJECT** | `answer_leakage` |
| **"You mentioned a 63% activation rate. How was that number calculated?"** | **REJECT** | `answer_leakage` |
| "Where did that activation number come from?" | ACCEPT | — |
| **"Who looked at that number besides you?"** | **REJECT** | `no_claim_anchor` |
| "What part of the first-run flow did you leave unchanged?" | ACCEPT | — |
| "What almost became a problem during the rebuild?" | ACCEPT | — |
| "Who did you need help from on the first-run flow?" | ACCEPT | — |
| "You said the first-run flow drove activation. How did you know it was that and not something else?" | ACCEPT | — |
| "You mentioned the first-run flow was the bottleneck. If signups doubled tomorrow, what would break first?" | ACCEPT | — |

### Finding 1 — `answer_leakage` forbids the specification's signature pattern

The spec's canonical MEASUREMENT example — *"You mentioned a 40% improvement. How
was that number calculated?"* — **cannot be generated.** Citing a claim figure to
establish the referent is indistinguishable, to rule 1, from handing over the
answer.

Further measured detail:

- The rejection holds **at turn 1 and mid-thread alike.** Conversational context
  does not rescue it.
- Removing the figure passes: *"How was the activation rate calculated, and who
  checked it?"* → ACCEPT.
- Citing a figure the **candidate** volunteered passes: *"You said 30% fell out at
  email verification. What did that number do after the rebuild?"* → ACCEPT,
  because `answer_numerals` covers it.

So the boundary is precisely: **the candidate's own spoken figures may be
cited; the resume's may not.**

**This changes a decision that was correct when it was made.**
`studies/phase3/validator_disagreements.md` Finding 5 identified exactly this —
*"the human accepts a figure used as a reference point and rejects one used as
the thing being asked for"* — and declined to fix it: *"At n=3, and against a
rule that is the only one working, the risk of breaking 19 good rejects to
rescue 3 is plainly bad odds."*

That arithmetic was right for the old design, where reference-point citation was
three edge cases. **Under this specification it is the opening move of two of the
five families.** The cost side of that trade has changed by an order of
magnitude; the decision should be re-taken rather than inherited.

`answer_leakage` is also the highest-precision rule in the validator (86.4%) and
43.3% of all violations. This is a contract collision between two sound
components, not a defective rule.

### Finding 2 — `no_claim_anchor` forbids short natural questions

*"Who looked at that number besides you?"* is rejected because "number" and
"besides" share no stem with the claim. Rule 7 requires lexical overlap with the
claim text; specification rule 10 requires natural spoken English, which reaches
back with pronouns. Mid-thread context does not help — the last answer's words
are added to the anchor set, but a question this short still misses.

Both findings share one cause: **the validator judges each question against the
claim in isolation; the specification assumes a conversation.**

### Finding 3 — the quality test relocates the judgement

The specification's core test — *"if a stranger could answer nearly as well,
reject and generate again"* — is a judgement, and `validate()` is pure Python
with no model call **by design**. Under this spec the impostor-parity check runs
**inside the model**, which inverts the standing invariant that the model
produces and Python decides.

That is a legitimate design choice, but it should be made deliberately, because:

- CLAUDE.md rule 1 (*the model never produces a score*) is **not** violated —
  `reasoning` is prose, not a rating, and nothing parses a number out of it.
- The measured hazard is different: §4b of the forensic audit found **11 of 58
  regenerations (19%)** satisfied the validator by deleting words and adding
  nothing. A self-assessed regeneration loop has no external check against the
  same failure.
- The invention-cost instrument built for these audits (incident markers, causal
  links, `how_measured` definitions vs bare quantities) **can measure impostor
  parity after the answer arrives**. It cannot gate a question before it is
  asked. Impostor parity is available as an outcome metric, not as a filter.

### Finding 4 — rule 7 is implementable as written

*"Never ask how long / how many people / team size / what technologies"* is
lexical, and would have caught the three worst-performing patterns in the corpus:
`how long did you` (0.62 dear, 62% zero-yield), `how many team members`
(0.25 dear, 75% zero-yield), `how long did the` (1.00 dear, 50% zero-yield).
The "unless it emerged from a prior answer" clause is also checkable — the same
`prior_answers` list rule 1 already receives.

---

## 5. What this specification does not resolve

Stated so they are not discovered later.

- **CAUSAL_REASONING has no owner and this spec does not give it one.** It is the
  lowest dimension corpus-wide (34.1), targeted by two probe levels that score
  30.0 and 27.6. SEAM is the closest fit, but the gap is in the rubric and the
  signal extractor, one layer below question generation.
- **TOOL_FAMILIARITY loses its only source.** OPERATIONAL is the sole level
  targeting it (69.4% tool-signal rate vs 9.2–20.3% elsewhere) and has no
  successor here. Either PERIPHERY absorbs it through dependency and constraint
  questions, or the dimension leaves the evidence graph. It is currently the
  lowest claim-level final in the graph (39.8).
- **AUTHENTICITY becomes redundant with the whole design.** Under authorship
  verification every family targets what AUTHENTICITY measures, which makes it
  either the master metric or a duplicate axis.
- **SEAM requires state the planner does not currently carry.** It must select
  two prior facts rather than one claim. `session_facts` exists (97 rows, 1.4 per
  interview) but was built for contradiction detection, and only 16 session/key
  pairs in the whole corpus repeat a key.
- **Contradiction detection is untested.** 1 fire in 68 interviews, and it is a
  false positive.
- **Nothing here has been measured against real candidates.** The corpus
  simulator never produced a weak answer in 305 turns, so no question in this
  document has been tested against a person who could not answer it.
