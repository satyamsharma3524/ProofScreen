# Live Interview Quality Audit — 6 Sep 2026

Two real WhatsApp interviews, run against live `gpt-4o` and live Meta Cloud API
on 6 Sep 2026 between 15:14 and 15:20. Both candidates sent real resumes and
answered by **voice note**. This is the first quality read on the forensic
question generator (`api/engine/anatomy.py` + `forensic_question.txt`, both
uncommitted at time of writing) against real humans rather than personas.

**Status: observation, not conclusion.** n = 2 interviews, 7 generated
questions, 6 answers, of which **4 are clean** (two transcriptions failed). The
central hypothesis below is supported by 4 data points. It is written down so
the next batch can confirm or kill it, per the standard in
`PHASE_3_VALIDATION_STUDY.md` §11 — a pattern that survives a second
independent batch is a finding; one that does not is an anecdote.

This document does **not** modify `api/`. It is an audit, not a change.

> **Batch 2 has since run — see §7.** It **confirms F2** (worse than recorded
> here) and **refutes F3 as stated**. Sections 1–6 are preserved as written
> before batch 2, deliberately: the decision rule in §6 only means anything if
> it is not edited after seeing the result.

---

## 1. Transcripts

### Session A — `s_3ece46f312`, candidate `c_7af16c` (Senior Frontend Developer)

Resume: 4 yrs frontend, React/Redux/Tailwind/TS/Next. Routed
`software_engineering` (title `Senior Frontend Developer`, seniority `senior`,
self-reported 0.9).

Six candidate claims classified, three kept after the one-per-type cap:

| # | Type | Weight | Claim |
|---|---|---|---|
| 1 | `system_ownership` | 25.0 | Led frontend architecture with scalable component libraries and API integrations. |
| 2 | `performance_work` | 20.0 | Optimized platform performance by 40% through architecting the entire front-end using ReactJS and Redux. *(metric 40%)* |
| 3 | `delivery` | 15.0 | Integrated Rest APIs resulting in an improved user experience. |

Dropped by the cap: *"Boosted storefront businesses' customer base by 45%…"*,
*"Designed customizable dashboards, analytics tools, reward systems…"*,
*"Developed a seamless integration with Google, Facebook, WhatsApp, and Twilio's
APIs…"* — all three as `delivery already kept`.

| Turn | Move / level | Question (source) | Answer (voice) | Yield |
|---|---|---|---|---|
| Q1 | `OWNERSHIP_BOUNDARY` | **Who managed the backend systems you integrated with?** *(model, 1 attempt)* | "There were two of the developers who managed those systems." | claim score 9 — SPEC 20, PROC 12, METRIC 15 |
| Q2 | `METRIC_DEFINITION` / OUTCOME | **How was platform performance measured and compared to before?** *(model, 1 attempt)* | "Number of users and the latency." *(4.3s, 6 words, effort 12)* | **1 signal**, answer_score 11 — METRIC_OWNERSHIP 50 ("1 metric defined"), CAUSAL 0 |
| Q3 | `OPERATING_CONTEXT` / OPERATIONAL | **What was the first thing you looked at to see if the API needed fixing?** *(model, 1 attempt)* | `पहले मॉड्यूल का टेक्स्ट है न तो वही पहले मॉड्यूल का टेक्स्ट है न तो वही` *(11.7s, 16 words, effort 33)* | **0 signals**, answer_score 5 — PROC 12 from "2 domain terms" |
| Q4 | `AUTHORITY` / DECISION | **What decisions could you make alone about the component libraries?** *(model, 1 attempt)* | "NOTHING" *(1.8s, 1 word, effort 4)* | **0 signals**, answer_score 0 |
| repair | — | `On "Led frontend architecture with scalable component libraries and API integrations." — What was the call you made, and what did you turn down to make it?` | *(not answered)* | — |

Competence trajectory: `4 → 7 → 9 → 7`.

### Session B — `s_209ef549b2`, candidate `c_20a8fc` (Senior ML / Agentic AI)

Resume: 4.5 yrs ML, MoE / AIOps / CrewAI / dbt / Airflow. Routed
`software_engineering` (title `Senior Software Engineer - ML and Agentic AI`,
seniority `senior`, self-reported 0.95).

| # | Type | Weight | Claim |
|---|---|---|---|
| 1 | `system_ownership` | 25.0 | Engineered end-to-end data infrastructure supporting AI operations, developing dbt transformation pipelines and Airflow DAGs… across Snowflake and production databases. |
| 2 | `delivery` | 15.0 | Architected and deployed production-scale AI agent systems for DocuSign's sales outreach teams, implementing CrewAI-based multi-agent workflows… |
| 3 | `tech_depth` | 15.0 | Engineered and deployed production-grade Mixture of Experts (MoE) models, developing novel modular framework to convert standard LLMs into specialized MoE architectures. |

Dropped by the cap: *"Built and deployed PII anonymization microservices…"*,
**"Architected and led implementation of large-scale AIOps platform providing
enhanced Assurance capabilities across ThousandEyes, Meraki, Catalyst Center"**,
*"Spearheaded development of Network Root Cause Analysis (RCA) solution…"*.

| Turn | Move / level | Question (source) | Answer (voice) | Yield |
|---|---|---|---|---|
| Q1 | `OPERATING_CONTEXT` / OPERATIONAL | **What was the first thing you checked to ensure the dbt pipeline was running correctly?** *(model, 1 attempt)* | "**This is such a dumb question** but yes first I did a compilation of the dbt pipeline and then again I did a test run so sort of like smoke test on the test server." *(15.5s, 35 words, effort 55)* | **4 signals**, answer_score 22 — SPEC 40 (2 named entities), PROC 56 (2 process steps) |
| Q2 | `DEPENDENCY` / OPERATIONAL | attempt 1 `What was the first thing you checked on the screen each day?` → **rejected** `duplicate_content`; attempt 2 re-targeted `OPERATING_CONTEXT → DEPENDENCY`: **Who approved the use of CrewAI for your project?** *(regenerated, 2 attempts)* | `यह नहीं आगा नहीं। मेनेजर अप्रूब्ड और करता रहे है। सुरे लगकाई को पर?` *(6.2s, 14 words, effort 22)* | **0 signals**, answer_score 2 |
| Q3 | `DEPENDENCY` / OPERATIONAL | attempt 1 `What was the first thing you checked on your screen each day?` → **rejected** `duplicate_content`, `no_claim_anchor`; attempt 2 re-targeted `OPERATING_CONTEXT → DEPENDENCY`: **Who approved the deployment of the MoE models?** *(regenerated, 2 attempts)* | *(not answered)* | — |

Competence trajectory: `— → 10 → 11`, while SPECIFICITY fell `40 → 25` and
PROCESS `56 → 35`.

---

## 2. Findings

### F1 — A failed transcription silently lowers the candidate's score

Two of six answers came back as garbled Hindi from Whisper. Both were scored as
if they were the candidate's words:

- Session A Q3 → 0 signals, `answer_score 5`, competence dimension deltas
  `SPECIFICITY 11→8`, `PROCESS 15→14`, `METRIC_OWNERSHIP 31→23`.
- Session B Q2 → 0 signals, `answer_score 2`, `SPECIFICITY 40→25`,
  `PROCESS 56→35`.

There is no transcription-confidence gate between `proofscreen.stt` and
`engine/evidence`. A candidate whose accent or language Whisper handles badly
loses score for a **delivery failure in our own pipeline**.

Nothing in the code scores accent directly, so CLAUDE.md rule 6 is not violated
in letter. In effect it is: the observable outcome is *speak English Whisper
likes, or score lower*. For an India-first BPO/tech product this is the single
most consequential defect in this log.

### F2 — The remedy for a duplicate question produces another duplicate

`duplicate_content` fired twice, correctly, on near-identical
`OPERATING_CONTEXT` drafts:

```
attempt 1 (Q2): "What was the first thing you checked on the screen each day?"
attempt 1 (Q3): "What was the first thing you checked on your screen each day?"
```

Both regenerations re-targeted to the **same** move, `DEPENDENCY`, and both
produced the **same sentence frame**:

```
Q2 (passed): "Who approved the use of CrewAI for your project?"
Q3 (passed): "Who approved the deployment of the MoE models?"
```

Back-to-back in one interview, and `validate()` accepted both. It cannot see
them: [`question.py:560`](../api/engine/question.py#L560) compares Jaccard
overlap **discounting the claim's own words**, so the residual content sets are
`{approved, use, project}` and `{approved, deployment}` — far under
`DUPLICATE_JACCARD = 0.37`.

The repetition here is **structural** (same move, same interrogative frame), and
rule 2 is **lexical**. The validator is not wrong; it is measuring a different
thing. Lowering the threshold would not fix this and is forbidden during the
study (`PHASE_3_VALIDATION_STUDY.md` C7).

Aggravating factor: across two unrelated resumes, three of seven first drafts
opened `What was the first thing you checked/looked at…`. The generator has a
favourite sentence.

### F3 — Sequence questions produce evidence; authority questions do not

Ranked by signals yielded, over the **four clean (non-garbled) answers**:

| Move | Question shape | Answer length | Signals | answer_score |
|---|---|---|---|---|
| `OPERATING_CONTEXT` | "what was the first thing you **did**" | 35 words | **4** | 22 |
| `METRIC_DEFINITION` | "how was X **measured**" | 6 words | 1 | 11 |
| `OWNERSHIP_BOUNDARY` | "**who** managed X" | 10 words | — | claim 9 |
| `AUTHORITY` | "what could you decide **alone**" | 1 word | 0 | 0 |

The one question that asked for an ordered sequence of actions produced the only
rich answer in either interview — and produced verbatim-verifiable quotes
(`"first I did a compilation of the dbt pipeline"`,
`"did a test run so sort of like smoke test on the test server"`). The questions
that asked *who* / *what were you allowed to do* produced 1 and 10 words.

Forensic argument for why this should be expected: **"who approved it?" is
equally cheap for the person who did the work and the person who did not.** It
has no recall cost. The 5-level protocol's value comes from questions whose
answers are expensive to fabricate; naming an approver is not one.

### F4 — The one-per-type cap keeps the first claim of a type, not the best

Session B dropped *"Architected and led implementation of large-scale AIOps
platform… (ThousandEyes, Meraki, Catalyst Center)"* — the achievement the
candidate's own summary leads with — because the dbt/Airflow line appeared
earlier in the PDF and had already filled `system_ownership`. Session A dropped
the only claim carrying a customer-facing metric (45% customer base) for the
same reason.

The interview verifies whichever qualifying line the resume happens to list
first. From a recruiter's seat this is the largest loss of value in these two
runs — more than any wording defect.

### F5 — A question aimed at the neighbouring team

Session A Q1 anchors to a claim about **frontend** architecture and asks who
managed the **backend**. The candidate answered accurately about two other
people and produced no evidence about himself. `OWNERSHIP_BOUNDARY` is a sound
move; pointed outward it collects facts about staffing rather than about the
candidate.

### F6 — Candidate rated the question in-band

`"This is such a dumb question but yes…"` — then answered it well, with the best
answer in either session. Both halves matter: the move worked forensically and
still read as beneath a senior engineer. Pitch and yield are separable, and we
currently measure only yield.

### F7 — The repair turn fired, on a real answer

`"NOTHING"` is 7 characters, under `is_non_answer()`'s 12-char floor, so the
off-budget repair fired and rendered
`On "Led frontend architecture…" — What was the call you made…`.

This is the first observed repair. `PHASE_3_VALIDATION_STUDY.md` records **zero
in 68 interviews**, reported there as a failed acceptance criterion. One real
firing does not overturn that; it does mean the mechanism works when the floor
is actually crossed. **It is not a reason to loosen `is_non_answer()`** — the
candidate was declining to answer, which is exactly what the repair is for.

---

## 3. Severity ranking

| # | Finding | Severity | Why this rank |
|---|---|---|---|
| 1 | **F1** transcription failure lowers score | **Critical** | Produces the discriminatory outcome rule 6 exists to prevent, on the product's primary market. Silent — nothing in the recruiter view says "we could not hear this answer". |
| 2 | **F4** claim selection is document-order | **High** | Wrong thing verified. Every downstream score is about a second-choice claim. Recruiter-visible, and no code path reports it. |
| 3 | **F2** duplicate remedy repeats itself | **High** | Candidate-visible as "the bot asks the same question twice". Wastes 2 of 5–6 screening turns. Validator cannot detect it by construction. |
| 4 | **F3** authority questions yield ~0 | **Medium-High** | Direct waste of scarce turns — but n = 4 and confounded with voice quality. **Needs the second batch before acting.** |
| 5 | **F5** question aimed at another team | **Medium** | One occurrence; may be prompt-level, may be chance. |
| 6 | **F6** register too junior for seniors | **Low-Medium** | Costs goodwill, not evidence. Real, and cheap to address in the prompt. |
| 7 | **F7** repair fired | **Not a defect** | Recorded because it contradicts a documented zero. |

---

## 4. Proposed fixes

Nothing below is implemented. Ownership is A (`question.py`, `extract.py`,
`anatomy.py`, `orchestrator.py`).

**P1 — gate scoring on transcription quality (F1).** A voice answer whose
transcript is unusable must not reach `engine/evidence` as if it were the
candidate's words. Options, cheapest first: (a) language mismatch check against
an expected set, (b) Whisper `avg_logprob` / `no_speech_prob` threshold from the
verbose response, (c) re-ask once, off-budget, as the repair turn already does
for non-answers. Whatever the mechanism, an unscoreable answer must be recorded
as **unscored**, never as zero-signal — the two are different facts, the same
way `role_coverage` distinguishes "evidenced badly" from "never claimed".

**P2 — rank claims before the one-per-type cap (F4).** Order candidates for the
cap by weight, then presence of a metric, then recency — not document position.
This is a sort key in `extract.py`, not new architecture.

**P3 — make re-targeting rotate, and make repetition visible (F2).** Two parts:
(a) the re-target must not always land on `DEPENDENCY`; (b) `questions.move` —
the column added for exactly this — should be read when planning, so a move
already spent on a session is not re-spent. Optionally add a **move-repetition**
check alongside the lexical one; that is a new rule and needs approval, so
prefer (a) + (b) first.

**P4 — hold F3 until the second batch.** See §6.

**P5 — register instruction in the prompt (F6).** One line in
`forensic_question.txt`: sound like a curious senior engineer, not an assessor.
No per-family examples (A's contract forbids them).

**P6 — constrain `OWNERSHIP_BOUNDARY` to the claim's own system (F5).** The
boundary of interest is the edge of *the candidate's* ownership, not the roster
of the team on the other side.

---

## 5. Open questions

1. **Is F3 real, or is it seniority + voice fatigue?** Both weak answers came
   late in their sessions; the strong one came first. Answer-quality decay over
   turns is an equally good explanation of the same four data points.
2. **Can a simulator test F3 at all?** A `gpt-4o-mini` persona will write a
   paragraph in reply to "who approved it?" — it has no model of effort, and
   effort is the whole phenomenon. What a simulator *can* test is whether the
   move yields **countable signals** even when answered fully; if a complete,
   cooperative answer to `DEPENDENCY` still extracts 0 signals, that is a
   structural property of the question class and does not depend on candidate
   psychology.
3. **Why did competence rise 10 → 11 while SPECIFICITY fell 40 → 25 and PROCESS
   56 → 35?** Consistent with un-probed dimensions contributing 0 across a
   widening claim set, but it will read as broken on a recruiter's screen and
   deserves an explicit answer.
4. **Should a garbled answer consume budget?** If P1 re-asks, it must be
   off-budget or a bad line costs the candidate a turn.
5. **Does `OPERATING_CONTEXT` have a single favourite sentence?** Three of seven
   drafts opened identically. Prompt-level, temperature, or genuine convergence
   on the best form of the move — unknown.
6. **Is the 5–6 question screening flow the right budget** if two turns can be
   lost to one repeated move? `MAX_QUESTIONS` is 12 here; the screening flow the
   product sells is shorter, which makes F2 and F3 proportionally worse.

---

## 6. What would settle F3

The decision rule, agreed before the data was collected:

> Run a further batch of real interviews. If sequence-shaped moves
> (`OPERATING_CONTEXT`, `INCIDENT`, process/step questions) again out-yield
> authority-shaped moves (`AUTHORITY`, `DEPENDENCY`, `OWNERSHIP_BOUNDARY`) in
> signals per question, change the planner's move priorities for the short
> screening flow.

Two conditions on that, both of which follow from §5:

- **Real candidates, not personas**, for the effort claim. Simulator runs
  measure generation-side behaviour (move distribution, reject rate, the F2
  pile-up) and the structural-yield question in §5.2 — not whether a human
  bothers to answer.
- **Control for audio.** Batch two should include text answers, or transcripts
  verified before scoring, or F1 will keep contaminating the yield table.


---

## 7. Batch 2 — controlled re-run, 6 Sep 2026

### Method

Four interviews, six turns each, **24 answered questions**, driven through
`/api/candidates/text` → `/api/dev/sessions/{id}/start` → `/api/dev/sessions/{id}/answer`.
That is the **real production pipeline** — live `gpt-4o` extraction, the live
forensic generator, live `validate()`, live signal extraction. `api/` was not
modified; the driver lives in the session scratchpad, not in the repo.

Sessions: `s_f78cd41d70`, `s_1c9f029689`, `s_3ffdafbce9`, `s_b7dd4b5d90` —
the **same two real resumes** as batch 1, twice each.

Two deliberate departures from batch 1, both required by §6:

- **Text answers, not voice.** Removes the F1 transcription confound entirely.
- **Effort held constant.** A `gpt-4o-mini` simulator answers as the candidate,
  instructed to always reply in 2–4 sentences regardless of the question. It
  worked: mean answer length was **507 chars for authority-shaped questions and
  504 for sequence-shaped** — a 0.6% difference. Effort is therefore excluded as
  an explanation of any yield gap.

This design tests **open question §5.2** — structural yield — and cannot test
candidate effort. That limit was stated before the run, not after.

Generation health: `source` was `model` or `regenerated` for all 24; **zero
fallbacks**, so no question in this batch came from the unvalidated path.

### Result — F3 is refuted as stated

Mean `answer_score` by question shape, effort held constant:

| Shape | Moves | n | Mean answer_score | Mean answer chars |
|---|---|---|---|---|
| **Authority-shaped** | `AUTHORITY`, `DEPENDENCY`, `OWNERSHIP_BOUNDARY`, `PEOPLE` | 8 | **37.8** | 507 |
| **Sequence-shaped / other** | `OPERATING_CONTEXT`, `FAILURE`, `METRIC_DEFINITION`, `COHERENCE`, `EXCLUSION` | 16 | **38.8** | 504 |

By individual move:

| Move | n | Mean answer_score |
|---|---|---|
| `METRIC_DEFINITION` | 2 | 47.5 |
| `DEPENDENCY` (as re-target) | 2 | 41.5 |
| `FAILURE` | 4 | 41.0 |
| `OWNERSHIP_BOUNDARY` | 2 | 39.5 |
| `OPERATING_CONTEXT` | 5 | 39.0 |
| `COHERENCE` | 4 | 36.5 |
| `AUTHORITY` | 3 | 33.7 |
| `EXCLUSION` | 1 | 20.0 |

**A one-point gap on n = 24 is nothing.** When the answer is complete, authority
questions produce countable signals at the same rate as sequence questions.

The cleanest single data point is an accident of the generator repeating itself:
the question

> *"What decisions could you make alone about the component libraries?"*

was generated **verbatim in both batches**, on the same claim.

- Batch 1, real human, voice: **"NOTHING"** → 0 signals, answer_score **0**.
- Batch 2, constant-effort simulator: full answer → answer_score **29**, with
  extracted `process_steps` and a `quantities` signal.

Identical question, identical claim. The variable is the person, not the
question.

### What F3 actually is

Not *"authority moves cannot produce evidence"* — they demonstrably can.

**Authority questions have a cheap exit and sequence questions do not.**
"Who approved it?" can be truthfully answered in two words; "what did you check
first?" cannot be answered at all without walking a sequence. Batch 1 shows real
candidates take the exit when offered. Batch 2 shows that if they don't, the
move is fine.

The intervention that follows is therefore **not** reprioritising moves. It is
**removing the one-word exit from the authority moves' phrasing** — a prompt
constraint requiring the question to demand a decision *and its circumstances*,
so the shortest true answer is still a sentence. `EXCLUSION` at 20.0 (n = 1) is
worth watching for the same reason.

### F2 is confirmed, and it is worse than §2 recorded

Move sequences per session (`>` = next turn):

```
s_f78cd41d70  OPERATING_CONTEXT > OPERATING_CONTEXT > OPERATING_CONTEXT > AUTHORITY > COHERENCE > FAILURE
s_3ffdafbce9  OPCTX,AUTHORITY   > OPCTX,DEPENDENCY  > OPCTX,DEPENDENCY  > FAILURE   > COHERENCE > EXCLUSION
s_1c9f029689  OWNERSHIP_BOUNDARY > METRIC_DEFINITION > OPERATING_CONTEXT > AUTHORITY > COHERENCE > FAILURE
s_b7dd4b5d90  OWNERSHIP_BOUNDARY > METRIC_DEFINITION > OPERATING_CONTEXT > AUTHORITY > FAILURE   > COHERENCE
```

**Two of four sessions opened with the same move three times running.**

`s_f78cd41d70`, three consecutive `OPERATING_CONTEXT`, every one accepted by
`validate()` at attempt 1:

```
Q1  What was the first thing you checked when a data workflow failed?
Q2  What report did you first check to see if the AI agent systems needed adjustment?
Q3  What was the first error message or alert you checked when something went wrong?
```

`s_3ffdafbce9`, three consecutive `regenerated` questions, each rejected at
attempt 1 for `no_claim_anchor` and each re-targeted away from
`OPERATING_CONTEXT` — twice onto `DEPENDENCY`, reproducing the batch-1
pile-up exactly:

```
Q2  Who did you need approval from to deploy the AI systems?
Q3  Who had to approve the deployment of the Mixture of Experts models?
```

So the pile-up is **not** peculiar to the `DEPENDENCY` re-target path. The
planner repeats a move across consecutive turns on different claims, and
`duplicate_content` cannot see it, because the near-duplicate wording sits in
the claim vocabulary that rule 2 discounts by design.

In a 6-turn screening flow, **half the interview** went to one move in two of
four sessions. That is the finding with the strongest evidence in this document:
n = 2 batches, 3 of 6 sessions, both generator paths.

### Revised severity

| # | Finding | Was | Now | Note |
|---|---|---|---|---|
| 1 | F1 transcription lowers score | Critical | **Critical** | Untested in batch 2 by design (text answers). Unchanged. |
| 2 | F2 move repetition | High | **Critical** | Reproduced at higher rate; burns half a screening flow. Now the top *code* defect. |
| 3 | F4 claim selection by document order | High | **High** | Reproduced — both resumes lost the same headline claims again. |
| 4 | F3 authority yield | Medium-High | **Refuted as stated → Medium** | Re-scoped to "cheap exit", a phrasing problem, not a planner-priority problem. |
| 5 | F5 outward-aimed ownership question | Medium | **Medium** | Recurred: *"Who handled backend integrations for these API projects?"* (`s_1c9f029689` Q1). |
| 6 | F6 register | Low-Med | **Low-Med** | Untestable with a simulator. |

### Revised recommendation on the planner

The pre-registered rule in §6 was: *if sequence out-yields authority again,
change the planner's move priorities.* **It did not.** Under the one condition
that isolates the question from the candidate, the two classes are within one
point. Reprioritising moves on this evidence would be fitting the planner to a
single voice interview.

What the batch does support, in priority order:

1. **P3 (move rotation) is now the top change.** Not a tie-break — a hard
   constraint that the same move cannot open three consecutive turns. The
   `questions.move` column exists and is populated; nothing reads it back yet.
2. **Re-scope P4** from "reprioritise moves" to "remove the one-word exit from
   authority phrasing" — a `forensic_question.txt` constraint.
3. **P1, P2 unchanged** and still ahead of any of this in severity.

### Residual doubts

- **n = 24, two resumes, one family** (`software_engineering`). The move-yield
  table has n ≤ 5 per move; only the grouped comparison is worth anything.
- **`answer_score` is the proxy**, not signal counts, which are not stored as a
  scalar. It is the number scoring actually consumes, so it is the right proxy,
  but it compresses.
- **The simulator invents specifics.** It cannot be caught lying, so
  `AUTHENTICITY` and consistency are untested here.
- **`/api/dev/llm` reported 4 `failures` with 0 `fallbacks`** during the run.
  Unexplained — worth a look, though no question in the batch came from the
  fallback path.
- **The container lost TLS to `api.openai.com` mid-session** (self-signed
  certificate in chain — a corporate proxy). The simulator was moved to the host
  as a result. If the app itself starts failing this way, every question becomes
  a fallback and F1-style silent degradation gets much worse.
