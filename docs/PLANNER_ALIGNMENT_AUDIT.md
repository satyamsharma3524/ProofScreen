# Planner Alignment Audit — is the interview planner suited to a 6-question interview?

Audit only. Nothing in this document was implemented and nothing here
recommends an architecture rewrite. Every claim is backed by a file:line
citation, a rubric read directly from `signals.py`, or a real transcript.
Three real transcripts are used throughout, all cited explicitly by name:

- **Infra log** — the log pasted into this task (2026-09-07 06:29-06:41,
  DevOps/on-prem candidate: Proxmox, Kubernetes, Prometheus/Grafana, AWS).
- **Yogendra log** — this session's own real run against `Yogendra.pdf`
  with a strong, engaged candidate (React Native / mobile).
- **Original transcript** — the earlier adversarial run pasted into this
  conversation (2026-09-06, "I don't know" candidate).

**A caveat that matters for everything below citing the Infra log:** it
shows `remaining_budget=12` at turn 1 and PERTURB firing at Q6 ("stalled
after 2 answers — one perturbation"). That is `max_questions=12` and
`transfer_probe=True` — **not** the Demo Mode configuration implemented
earlier today (`max_questions=6`, `transfer_probe=False`). Either the
running container wasn't rebuilt after that change, or `.env`/the
deployment overrides those settings. Where this matters to a conclusion,
it's called out explicitly rather than silently treated as current
behavior.

---

## Part 1 — Lifecycle Trace

### Stage 1: Resume → text

**Files:** `api/ingest/parse.py`. **Function:** `extract_text(filename, data)`.
**Input:** uploaded bytes + filename. **Output:** plain text string.
**Decision rule:** dispatches on file extension (`_from_pdf`, `_from_docx`,
else treated as plain text); `pymupdf` with a `fitz` fallback for PDFs (a
documented gotcha — the module renamed itself).

### Stage 2: Claim Extraction

**Files:** `api/engine/extract.py`. **Function:** `extract_claims(resume_text,
job_family, limit)` (LLM call #1). **Inputs:** resume text, an optional
requisition `job_family`. **Outputs:** `(job_family, list[ExtractedClaim])`
— each claim carries `text`, `claim_type`, `metric`, `verifiable`.

**Decision rules, in order (`extract.py:463-491`):**
1. Requisition's `job_family`, if the caller supplied a real one — absolute,
   never overridden by inference.
2. `classify_role()` (LLM #0) — routes on the resume's own header/title.
3. `detect_family()` — deterministic keyword scoring over the whole resume.
4. `GENERAL`.

Every extracted claim's `claim_type` is independently validated in Python
(`normalise_claim_type`) — a model-invented type is silently reclassified by
keyword (CLAUDE.md rule: never trust the model's own classification of
itself). `classify_role()` also extracts `confidence` and `seniority`
(`extract.py:406-408`) — see Part 5; both are logged and **never branched
on**, by explicit design.

### Stage 3: Claim Ranking

**Files:** `api/engine/extract.py:653-704`. **Inputs:** the classified claim
pool, `default_claim_weights(family)` (from `taxonomy.py`). **Outputs:** up
to `max_claims` (3) claims, plus a `rejected` list with a human-readable
reason each.

**Decision rule** — two passes:
1. **One-per-type cap**, ordered by `(-weight, not metric, document
   position)` (`extract.py:666-668`) — the strongest, then metric-bearing,
   then earliest-in-resume claim of each type survives; every other claim of
   that type is rejected as `"one-per-type cap: X already kept"`.
2. **`max_claims` cutoff**, sorted by weight alone
   (`extract.py:698`) — the top 3 remaining types survive; the rest are
   rejected as `"max_claims limit, ranked by claim_type weight"`.

Both passes are visible verbatim in every real log this session collected
(`claim ranking: N claim(s) not selected: [...]`).

### Stage 4: Planner Selection

**Files:** `api/engine/orchestrator.py`. **Function:** `plan_next_forensic
(states, index)` (the live default; `plan_next_evidence` and `plan_next` are
the v2 and pre-forensic alternatives, both off by default) — plus, ahead of
it, `_thread_plan(states, session, prior_qa)` when `demo_mode` is on.
**Inputs:** `list[ClaimState]` (claim, weight, moves already used, answer
signals so far, derived `anatomy`/`ledger`/`archetype`), the current
question index. **Output:** a `Plan` — which claim, which `Move`, the
`ProbeLevel` it maps to, `alt_moves` for a rejected first draft, a `reason`
string.

**Decision rule**, first match wins (`orchestrator.py:1778-1865`):
0. (Demo Mode only) **Answer thread** — if the last answer on the current
   claim named a keyword-list entity and the claim hasn't hit its 2-question
   cap, force a canned follow-up on that same claim (no model call).
1. **Breadth** — every claim gets its ladder's opening move before any
   claim gets a second, heaviest-weight claim first.
2. **Seam** — a claim with two crossable facts earns `COHERENCE` ahead of a
   third independent fact.
3. **Depth** — heaviest still-open claim, next move on its
   `ARCHETYPE_LADDER` entry.
4. **Transfer** — a claim that has stopped producing hard-to-invent detail
   ("`dear_stalled`") earns one `PERTURB`, gated on `settings.transfer_probe`.

Which move a claim's ladder offers depends on its `Archetype`
(`anatomy._archetype()`, `anatomy.py:294-305`), derived purely from **verb
keywords in the claim's own text** — see Part 5 for why this matters for
seniority. `_rotate_session_fresh` (`orchestrator.py:1681`) additionally
skips a move already spent by ANY claim this session, to stop two
same-archetype claims opening on identical wording — see Part 3's finding
that this can push a claim onto an abstract move it wasn't supposed to open
on.

### Stage 5: Question Generation

**Files:** `api/engine/question.py`. **Function:** `generate_forensic_question
(claim_text, move, anatomy, ledger, alt_moves, ...)` (LLM call #2) — renders
`api/prompts/forensic_question.txt` with the move's `MOVE_BRIEFS` entry.
**Inputs:** claim text decomposed into `mechanism`/`object`/`metric_name`
(`ClaimAnatomy`), the ledger of already-established facts, forbidden
figures. **Output:** `QuestionAttempt` (question text, `source`
model/regenerated/fallback/thread/repair, `attempts`, `violations`).

**Decision rule:** one model call; if `validate()` (pure Python, 7 rules —
answer leakage, duplicate content, multiple fact targets, hypothetical
misuse, unsupported metric, scope drift, no claim anchor) rejects it, a
**second** call targets a **different move** from `alt_moves` (never a
reworded retry of the same move); if that also fails, a deterministic,
unvalidated fallback line renders (`On "<claim>" — <canned line>`).

### Stage 6: Answer Scoring

**Files:** `api/engine/evidence.py` (LLM call #3, `extract_signals.txt` →
`AnswerSignals`), `api/engine/signals.py` (`score_answer`, pure Python, no
model). **Inputs:** the candidate's raw answer text. **Outputs:** counted,
quoted signals (`quantities`, `process_steps`, `causal_links`,
`metric_definitions`, `incident_markers`, `entities`, `tools`), then six
`DimensionScore`s. **Decision rule:** every signal's `quote` must appear
**verbatim** in the answer (`enforce_verbatim`) or it's dropped before
scoring ever sees it — the model reports, Python decides (Part 2 has the
rubric-by-rubric detail).

### Stage 7: Claim Recompute

**Files:** `api/engine/signals.py` (`score_claim`), `api/engine/scoring.py`
(`claim_score`). **Inputs:** the **union** of every answer's signals for
that claim so far (not best-of-answer), plus which dimensions were actually
`probed` (from the move/probe-level asked, `MOVE_DIMENSIONS` /
`PROBE_LEVEL_DIMENSIONS`). **Output:** one `claim_score` (0-100), a weighted
sum over all six dimensions where **an un-probed dimension contributes 0**
(`scoring.py:127-131` — a deliberate confidence-score design, not a bug).

### Stage 8: Final Evaluation

**Files:** `api/engine/evaluation.py`, `api/engine/graph.py`. **Inputs:**
every claim's score + weight, a session-level consistency multiplier
(`consistency.py`), role weight profile. **Outputs:** `competence_score`,
`role_coverage`, `dimension_breakdown` (session-wide, not per-claim),
`badge` (unverified/partial/verified). Visible verbatim in every log's
`final scoring` / `INTERVIEW SUMMARY` lines.

---

## Part 2 — Current Evidence Dimensions

All six defined in `signals.py:101-283`. `TARGET` is the weighted-signal-
count that saturates the dimension at 100; `GATE` is the ceiling applied
when a necessary ingredient is missing, regardless of raw count.

| Dimension | Purpose | Increases score | Decreases / caps score | Moves that feed it (`MOVE_DIMENSIONS`) | Hackathon value |
|---|---|---|---|---|---|
| **SPECIFICITY** | Concrete numbers and named things, not generalities | Each `quantity` + each named `entity` (target 5.0) | **Gated at 55** if zero quantities exist, however many entities are named (`signals.py:181`) | `OWNERSHIP_BOUNDARY` | **High** — cheap to populate (any technical answer names a tool/system), and the gate is real: log evidence, Infra Q1, 3 entities named, capped at 55 for lacking a number |
| **PROCESS** | Do they know *how* the work happened, step by step | Each `process_step` + domain-vocabulary hits (capped contribution 1.5, `MAX_VOCAB_CREDIT`) | **Gated at 50** with zero process steps, however much domain vocabulary appears (`signals.py:207`) | `OPERATING_CONTEXT`, `DEPENDENCY` | **High** — fastest-populating dimension across all three real logs; a real practitioner narrates steps involuntarily |
| **METRIC_OWNERSHIP** | Can they *define* a metric they claimed, not just repeat its name | A metric with `how_measured` filled (full credit); named-only metric (0.4 credit); a quantity tied to something (0.3, capped at 1.0) | **Gated at 45** unless at least one metric is fully defined (`signals.py:232`) | `METRIC_DEFINITION` only | **Low in a 6-question interview** — see Part 6: scored **zero across the entire 7-question Infra log**, because none of its 3 selected claims were `METRIC_MOVE` archetype, so `METRIC_DEFINITION` was never once offered |
| **CAUSAL_REASONING** | Problem → action → result, a complete chain | Complete `causal_link` (full credit); partial chain, missing outcome (0.4 credit) | **Gated at 50** with zero complete chains (`signals.py:251`) — "the dimension fabrication fails hardest on" (its own docstring) | `EXCLUSION`(disabled)`, AUTHORITY, COHERENCE, PERTURB`(disabled) | **Medium, at real risk under Demo Mode** — its only two *active* feeders are `AUTHORITY` and `COHERENCE`, and `COHERENCE` needs two already-established facts, unlikely inside a 2-question-per-claim budget. See Part 4 |
| **AUTHENTICITY** | A specific remembered incident, not a polished generality | Each `incident_marker` (target 3.0) | **Gated at 40** with zero incident markers (`signals.py:263`) | `FAILURE`, `PEOPLE` | **Low-Medium in practice** — the move that's supposed to feed it (`FAILURE`) doesn't guarantee it: Infra log Q4 used `FAILURE` and still scored `AUTHENTICITY: 0` ("no specific incident recalled") because the candidate answered descriptively, not narratively |
| **TOOL_FAMILIARITY** | Usage, not just naming a tool | A tool with `usage` described (full credit); named-only (0.3 credit) | **Gated at 40** with zero *used* tools (`signals.py:283`) | `OPERATING_CONTEXT`, `DEPENDENCY` | **High** — populates almost as fast as SPECIFICITY; every real log shows it hitting 50-100 within the first 1-2 answers on a claim |

Family dimension weights (`taxonomy.dimension_weights`, renormalised to
1.0) for `software_engineering`: SPECIFICITY 0.190, PROCESS 0.190,
AUTHENTICITY 0.143, CAUSAL_REASONING 0.190, METRIC_OWNERSHIP 0.143,
TOOL_FAMILIARITY 0.143. Note METRIC_OWNERSHIP still carries real weight
(14.3%) despite being the hardest dimension to ever populate — this is a
direct tension Part 6 returns to.

---

## Part 3 — Question Move Audit

Currently active under Demo Mode (per your confirmed choice): `METRIC_DEFINITION`,
`OWNERSHIP_BOUNDARY`, `OPERATING_CONTEXT`, `FAILURE`, `DEPENDENCY`, `PEOPLE`,
`AUTHORITY`, `COHERENCE`. Disabled: `EXCLUSION`, `PERTURB`.

| Move | Evidence it targets | Dimension(s) fed | Usually produces signal? | Junior | Mid | Senior |
|---|---|---|---|---|---|---|
| **OPERATING_CONTEXT** | What they were looking at day-to-day; the first concrete artefact/report/queue | PROCESS, TOOL_FAMILIARITY | **Yes, reliably** — every real log's opener scored 2+ dimensions on the first answer | Good — it's a "what did you actually do" question, no seniority assumed | Good | Good |
| **FAILURE** | One specific incident that didn't go as planned | AUTHENTICITY | **Inconsistent** — Infra log Q4 ("Can you describe a specific time...didn't go as planned?") got a real, substantive answer that STILL scored `AUTHENTICITY: 0`, because the candidate explained a precaution taken ("we were doing it at night... on non-production servers") rather than recounting a specific failure | Good in principle (memory of one bad day, no seniority needed) — but see the note above: candidates who over-explain "how we avoided a problem" rather than "what actually went wrong" starve this dimension regardless of level | Good | Good |
| **DEPENDENCY** | One specific moment a dependency blocked or changed the work | PROCESS, TOOL_FAMILIARITY (via `MOVE_DIMENSIONS`) | **Yes** — Infra Q5 ("Describe a moment when you were blocked...") produced the single richest answer in that log (7 signals, 4 of 6 dimensions moved) | Good — most candidates, junior included, have been blocked by *something* | Good | Good |
| **AUTHORITY** | What they could decide alone vs. what needed escalation | CAUSAL_REASONING | **High variance** — Infra Q3 got a rich 5-dimension answer; the original transcript's equivalent got "I did independently." (near-zero). See Part 4 in full | **Risky** — a junior candidate genuinely may have had almost no independent decision rights, and the honest answer ("everything needed approval") is thin through no fault of the candidate's |
| **OWNERSHIP_BOUNDARY** | Where their remit ended, told as a decision made or not made (reworded this session — used to invite "who reviewed your work") | SPECIFICITY | **Yes** — Infra Q1 scored SPECIFICITY:55, TOOL_FAMILIARITY:100 on the first answer | Same risk as AUTHORITY, milder — asks for an edge of remit rather than a decision right, so a junior candidate can usually answer with "this part was mine, that part wasn't" | Good | Good |
| **DEPENDENCY** *(listed once above)* | — | — | — | — | — | — |
| **PEOPLE** | A specific role in the loop and what they did | AUTHENTICITY, SPECIFICITY | Not observed firing in any of the three real logs this session collected — no direct evidence either way | Presumed fine — "who noticed first" doesn't assume rank | — | — |
| **METRIC_DEFINITION** | How a named metric was actually computed | METRIC_OWNERSHIP | Not observed firing in any of the three real logs — none of the 9 selected claims across them were `METRIC_MOVE` archetype. This is itself a finding: **the move most needed for the weakest-covered dimension never got exercised in any real transcript gathered this session** | Presumed fine for any level that named a metric | — | — |
| **COHERENCE** | Cross two already-established facts | CAUSAL_REASONING | Not observed firing in any of the three real logs — its precondition (two established facts on one claim) is hard to reach inside a 2-question cap; see Part 6 | Neutral by design — it's a memory-consistency check, not a difficulty question | — | — |
| *(disabled)* EXCLUSION | Deliberate omission and the constraint behind it | CAUSAL_REASONING | Fired in the Infra-style original transcript era; not reachable under current settings | — | — | — |
| *(disabled)* PERTURB | One hypothetical variable changed | CAUSAL_REASONING, PROCESS | Fired in the Infra log itself (Q6, pre-Demo-Mode config) — produced a genuinely strong answer here (PROCESS 56→100, CAUSAL_REASONING 20→70), in contrast to the original transcript where the same move on a stalled claim got "I don't know." **High variance, same shape as AUTHORITY**: rewards an engaged candidate, penalizes/wastes a turn on a disengaged one | — | — | — |

**Cross-cutting finding, not specific to one move:** `_rotate_session_fresh`
(existing mechanism, pre-dates Demo Mode) can push a claim onto a move
*other than* its archetype's designated opener when a sibling claim already
used it this session — confirmed live in the Yogendra log, where a
`PROCESS`-archetype claim's **first-ever question** was `AUTHORITY`
("what decisions could you make on your own, and what needed approval from
others?") instead of `OPERATING_CONTEXT`, purely because an earlier claim
had already spent `OPERATING_CONTEXT`. This connects directly to Part 4.

---

## Part 4 — Authority / Approval Audit

**Where these questions come from, precisely:** two distinct moves produce
approval/authority-flavored questions — `AUTHORITY` (`MOVE_BRIEFS[AUTHORITY]`,
`question.py:1037-1042`: *"Ask what they could decide on their own here and
what had to go somewhere else"*) and `OWNERSHIP_BOUNDARY` (`question.py:1000-1007`:
*"Ask where their ownership of this ENDED"*). Both are grouped under
`Family.PERIPHERY` (`MOVE_FAMILY`, `question.py:932-943`) — the family whose
stated purpose (per the section header, `question.py:882-898`) is to
**"leave the headline"**: ask about something the resume's own rehearsed
language doesn't cover, on the theory that a fabricated resume line has no
prepared answer for it. That's the origin: these moves exist specifically
*because* they're not answerable from the resume text alone — the same
"incidental detail is expensive to invent" philosophy this whole system was
built on.

**Scoring dimension supported:** `AUTHORITY` → `CAUSAL_REASONING` only.
`OWNERSHIP_BOUNDARY` → `SPECIFICITY` only (`MOVE_DIMENSIONS`,
`question.py:977-988`).

**What evidence it actually produces — measured, not assumed, across three
real transcripts:**

| Transcript | Question (paraphrased) | Answer | Dimensions moved |
|---|---|---|---|
| Infra log Q3 | "What decisions could you make independently and what needed approval?" | Rich: explained a Kubernetes air-gap decision, the client requirement behind it, and a connectivity issue faced | SPECIFICITY 20, PROCESS 31, **CAUSAL_REASONING 50**, AUTHENTICITY 33, TOOL_FAMILIARITY 50 — 5 of 6 dimensions from one answer |
| Yogendra log Q3 | "What decisions could you make on your own, and what needed approval from others?" | Rich: cold-start monitoring via Xcode Instruments | Real signal, though this run's exact per-dimension breakdown wasn't captured in the same detail |
| Original transcript Q2 | "What decisions could you make independently, and which required approval from others?" | **"I did independently."** | **Zero.** `answer_score=4`, no dimension moved |

**Is that evidence materially improving interview quality?** Mixed, and the
mix is the finding — not uniformly low value as suspected, but **high
variance**: it produces some of the richest single-answer evidence in the
whole corpus (Infra Q3) when a candidate happens to elaborate, and some of
the thinnest (original transcript) when they reach for the cheap "I did
independently" / "Mostly me" escape hatch this session's earlier audit
already named. The move doesn't discriminate a good answer from a bad one
by design — it just has a wide-open door for both.

**Answering your direct question — remove AUTHORITY entirely, what's lost:**
`CAUSAL_REASONING` (14-19% of a claim's score weight, every family) would
lose its **only reliable active feeder**. Its other three listed feeders are
`EXCLUSION` (disabled) and `PERTURB` (disabled) — both off under Demo
Mode — and `COHERENCE`, whose precondition (two already-established facts on
the same claim) is structurally hard to reach inside a 2-question-per-claim
budget (never observed firing in any of the three real transcripts
gathered this session). Concretely: **remove `AUTHORITY` and
`CAUSAL_REASONING` becomes a dimension with real scoring weight and no
practical way to ever populate it in a 6-question interview.** That is a
scoring-shape consequence worth knowing before deciding to cut it, not a
recommendation either way.

---

## Part 5 — Junior vs Senior Alignment

**Conclusion: the current system is NOT level-aware, and this appears to be
a deliberate design choice, not an oversight.**

**Evidence:**

1. **Seniority is extracted and explicitly never used.** `classify_role()`'s
   response model comment, verbatim (`extract.py:398-403`): *"`confidence`
   and `seniority` are RECORDED AND NEVER BRANCHED ON. CLAUDE.md rule 1
   forbids parsing a rating or a confidence out of a model response and
   acting on it, and there is no exemption for routing."* The field exists,
   is logged (`role classifier: ... seniority=%s ...`), and is read by
   nothing downstream — confirmed by grep: `seniority` appears in exactly
   one file, `extract.py`, and only in the definition and the log line.

2. **Move/archetype selection reads only the claim's own verbs**, never
   title, tenure, or years of experience. `anatomy._archetype()`
   (`anatomy.py:294-305`) pattern-matches `built/deployed/migrated/...` →
   `BUILD`, `owned/managed/led/...` → `OWNERSHIP`, else falls to `VOLUME` or
   `PROCESS`. Nothing in this function, or anywhere that calls it, reads
   candidate seniority, resume tenure, or job title.

3. **Claim weights are per job FAMILY, not per level**
   (`taxonomy.default_claim_weights(family)`) — a `system_ownership` claim
   is weighted 25 for every `software_engineering` candidate regardless of
   whether they're two years or twenty years in.

4. **A junior candidate can and does receive the identical question shape
   as a senior one.** Direct evidence: Infra log's candidate — infra/DevOps
   work, no seniority markers in the visible resume snippets — received
   `AUTHORITY` ("what decisions could you make independently and what
   needed approval from others?") on their very first delivery-type claim,
   the same move and wording the Yogendra and original-transcript
   candidates received regardless of their own apparent level. There is no
   code path that would have asked any of them a different-difficulty
   question based on who they are.

**Why this is probably deliberate, not just unfinished:** it's the same
principle CLAUDE.md states for scoring generally (rule 1: no LLM-produced
score gets acted on) extended to a field that is *itself* a kind of
self-reported confidence score ("I am senior"). Treating it as untrustworthy
input rather than a routing signal is consistent with the rest of the
system's philosophy, even though the practical effect is exactly what Part
4 flagged: an `AUTHORITY` question can land on a candidate with genuinely
little decision authority (because they're junior) and produce a thin,
honest answer that the system cannot distinguish from a fabricator's thin,
evasive one.

---

## Part 6 — Six-Question Budget Audit

Using the Infra log's real per-claim trajectories (the most complete real
data collected this session — 3 claims, 7 real answered turns):

| Dimension | Questions until first signal (observed) | Notes |
|---|---|---|
| SPECIFICITY | **1** | Populated on the very first answer for all 3 claims, every time — any technical answer names a system or a number |
| TOOL_FAMILIARITY | **1** | Same — populated turn 1 for all 3 claims |
| PROCESS | **1** (2 of 3 claims), **2** (1 claim) | Nearly as fast; a technical answer almost always describes at least one step |
| CAUSAL_REASONING | **1** (1 of 3 claims, via `AUTHORITY`), never for another claim across 3 real answers | Needs the right move *and* an answer shaped like "because X, we did Y" |
| AUTHENTICITY | **1** (1 of 3 claims, incidentally, via a broad `AUTHORITY` answer — not even from the `FAILURE` move meant to target it) | The dedicated `FAILURE` question on a different claim (Q4) scored **zero** here |
| METRIC_OWNERSHIP | **Never — 0 across all 7 real answered turns, final `dimension_breakdown` reads `METRIC_OWNERSHIP: 0`** | Structural: none of the 3 selected claims were `METRIC_MOVE` archetype, so `METRIC_DEFINITION` was never offered as a move at all |

**Cheapest (deserve budget first):** SPECIFICITY, TOOL_FAMILIARITY, PROCESS
— all three reliably return signal from a claim's *opening* question,
regardless of which move it happens to be.

**Expensive (consuming budget without reliable signal):**
- **AUTHENTICITY** — the move built for it (`FAILURE`) is not sufficient by
  itself; whether it scores depends on the candidate narrating an incident
  rather than describing a precaution, a distinction the question wording
  can't fully control.
- **METRIC_OWNERSHIP** — the most expensive by a wide margin. It requires
  (a) a claim that happens to be `METRIC_MOVE` archetype (~21% of real
  claims, measured earlier this session across 19 real claims from 10
  resumes) **and** (b) `METRIC_DEFINITION` actually being the move selected
  for it. Under a 3-claim, 2-question cap, a resume with zero or one
  metric-bearing claim among its top 3 selected ones will finish the entire
  interview with this dimension untouched — exactly what happened in the
  Infra log, a real 7-question interview.

**Rarely contributes to final scoring:** the same two, for the same
reasons — not because the *dimension* is unimportant (METRIC_OWNERSHIP
still carries 14.3% weight in `software_engineering`), but because the
current claim-selection and move-selection mechanics don't guarantee it
ever gets a turn.

**Direct answer to the question asked:** SPECIFICITY, PROCESS, and
TOOL_FAMILIARITY deserve first claim on a 6-question budget — they pay off
in the very first exchange on a claim, every time, in every real log
gathered. CAUSAL_REASONING is worth one dedicated attempt per claim (it's
genuinely differentiating when it lands) but shouldn't be counted on.
AUTHENTICITY and METRIC_OWNERSHIP are the two dimensions a 6-question
interview should expect to under-cover — not because the moves targeting
them are wrong, but because AUTHENTICITY depends on an answer shape the
question can't force, and METRIC_OWNERSHIP depends on a claim precondition
most claims don't meet.

---

## Part 7 — Recent Log Analysis

Analyzing the Infra log, question by question. Reminder: this log's
`max_questions=12`/`transfer_probe=True` — the Q6 PERTURB question would not
exist under current (Demo Mode) settings; noted inline.

| Q# | Move | Dimension goal | Evidence obtained | Value |
|---|---|---|---|---|
| Q1 | OWNERSHIP_BOUNDARY | SPECIFICITY | 3 entities, no quantity → SPECIFICITY 55 (gated), TOOL_FAMILIARITY 100 | **High** |
| Q2 | OPERATING_CONTEXT | PROCESS, TOOL_FAMILIARITY | 1 process step, 1 tool → PROCESS 31, TOOL_FAMILIARITY 50 | **Medium** — real but thin ("Garfana" transcription noise, single step) |
| Q3 | AUTHORITY | CAUSAL_REASONING | Rich: 5 of 6 dimensions moved from one answer | **High** — the standout question of the whole log |
| Q4 | FAILURE | AUTHENTICITY | PROCESS 56, CAUSAL_REASONING 20 (partial) — **AUTHENTICITY stayed 0**, the one dimension this move exists for | **Medium** — real evidence gained, but not the evidence this move was chosen to get |
| Q5 | DEPENDENCY | PROCESS, TOOL_FAMILIARITY | 7 signals, 4 of 6 dimensions moved (SPECIFICITY 40, PROCESS 88, CAUSAL_REASONING 50, TOOL_FAMILIARITY 100) | **High** — richest single answer in the log |
| Q6 | PERTURB *(unreachable under current settings)* | CAUSAL_REASONING, PROCESS | PROCESS 56→100, CAUSAL_REASONING 20→70 — genuinely strong | **High in this instance**, but see Part 3: the same move stalled a candidate to "I don't know" in the original transcript. High-variance, not reliably high-value |
| Q7 | OPERATING_CONTEXT | PROCESS, TOOL_FAMILIARITY | Empty answer (".") → 0 signal, repair fired | **Wasted** — but the repair mechanism caught it correctly |
| Q8 *(repair, off-budget)* | OPERATING_CONTEXT | PROCESS, TOOL_FAMILIARITY | 4 process steps → PROCESS 100, SPECIFICITY 40, TOOL_FAMILIARITY 100 | **High** — the repair recovered real value |

**Wasted questions:** Q7 (empty transcript) — recovered by its repair, so
not a net loss, but it is one of eight total exchanges that produced
literally nothing on the first attempt.

**Redundant questions:** none, strictly — every question targeted a
distinct move/claim combination. The closest to redundant is Q1 and Q4 on
the same claim (`OWNERSHIP_BOUNDARY` then `FAILURE`), which is the ladder
working as designed, not redundancy.

**Overly senior questions:** Q3 and Q6 both assume a candidate who made
independent infrastructure decisions and can reason about a hypothetical
swap — reasonable for this candidate (who clearly had the seniority to
answer richly), but per Part 5, nothing selected them *because* of that; a
junior candidate on an identical claim shape gets the identical question.

**Approval/authority questions:** Q3 only in this log — see Part 4 for the
full accounting; it was this log's single best question.

**Incident questions that could have been operational instead:** Q4
(`FAILURE`) is the clear case — the candidate answered with a precaution
taken ("we were doing it at night... on non-production servers"), which is
genuinely `PROCESS`/operational content dressed as an incident answer, and
scored accordingly (PROCESS 56, AUTHENTICITY 0). An `OPERATING_CONTEXT` or
`DEPENDENCY` question aimed at the same claim likely would have scored
similarly well *and* matched what the candidate was actually inclined to
describe.

---

## Part 8 — Final Recommendations

No architecture changes proposed, per instruction. Ranked observations only.

1. **Highest-signal moves, measured:** `DEPENDENCY` and `OPERATING_CONTEXT`
   — reliably multi-dimensional, fast, and not high-variance the way
   `AUTHORITY`/`PERTURB` are. `OWNERSHIP_BOUNDARY` close behind.
2. **Moves consuming budget without matching payoff:** `FAILURE` — real
   evidence came back in every observed case, but rarely the AUTHENTICITY
   signal it exists to collect; the log shows it scoring PROCESS instead
   more often than not.
3. **Dimensions producing useful differentiation:** SPECIFICITY, PROCESS,
   TOOL_FAMILIARITY — populate reliably and vary meaningfully between a
   rich and a thin answer (55-100 vs. 0, observed both ways in these logs).
4. **Dimensions that appear weak:** METRIC_OWNERSHIP (structurally
   unreachable for ~4 in 5 claims, confirmed at literal zero across a real
   7-question interview) and AUTHENTICITY (the move meant to feed it
   doesn't reliably do so).
5. **Should approval/authority questions remain:** the evidence doesn't
   support a clean yes/no. They produced this session's single richest
   answer (Infra Q3) and this session's single emptiest one (original
   transcript). What the evidence does support: removing `AUTHORITY`
   leaves `CAUSAL_REASONING` — a dimension with real scoring weight in
   every family — with no practically-reachable active source left. That's
   the concrete tradeoff to weigh, not a verdict either way.
6. **Is the system too senior-heavy for junior resumes:** not by design
   intent (Part 5 — nothing selects for seniority at all), but in effect,
   yes, situationally: a junior candidate with genuinely little decision
   authority gets the same `AUTHORITY` question as a senior one and their
   honest, thin answer is indistinguishable in the log from an evasive
   candidate's thin answer.
7. **Top 5 things worth a closer look, ranked by impact / risk / effort**
   (observations, not proposals to build):

   | # | Observation | Impact | Risk to verify further | Effort to even investigate further |
   |---|---|---|---|---|
   | 1 | `CAUSAL_REASONING` has one practical active feeder (`AUTHORITY`) under Demo Mode | High — a scored dimension with no reliable path to a score | Low | Low (already measured here) |
   | 2 | `METRIC_OWNERSHIP` scores zero whenever no selected claim is `METRIC_MOVE` archetype | High — same shape as #1, worse in this log | Low | Low |
   | 3 | `FAILURE` doesn't reliably produce `AUTHENTICITY` even when it produces a real answer | Medium | Low | Low |
   | 4 | `_rotate_session_fresh` can push a claim onto an abstract move it wasn't meant to open on | Medium | Low — reproduced live, once | Low |
   | 5 | Seniority is extracted, logged, and never used anywhere | Low-Medium (by design) — mostly relevant if junior-resume complaints keep surfacing | None — confirmed by grep, not inference | Already answered here |
