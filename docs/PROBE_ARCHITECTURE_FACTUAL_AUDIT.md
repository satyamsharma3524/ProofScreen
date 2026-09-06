# Probe Architecture — Factual Audit

**Date:** 2026-09-06 · **Measurements only. No recommendations, no proposed
changes.**

**Corpus:** `studies/phase3/` — 68 interviews, 395 asked questions, 519
generation attempts, 395 answers, 1508 evidence rows, 92 finalised claim scores,
97 session facts, 1 contradiction.

### Read this before any number below

The corpus has **two tiers with different answer mechanics**, and only one can
support a question→answer measurement:

| tier | n turns | how the answer was produced | usable for causal measurement? |
|---|---:|---|---|
| **B** | **305** | LLM simulator conditioned on the question just asked | **Yes** |
| A | 90 | fixed pool indexed by `claim_type`, consumed in order — **independent of the question** | No |

Every per-question measurement below is **Tier B only** unless marked. **All 10
TRANSFER turns are Tier A**, so TRANSFER has no causal data in this corpus and is
reported as unmeasured rather than as a low score.

**Invention-cost instrument** (used for "hard-to-invent evidence"): each stored
signal is classed CHEAP (bare quantities, metric *names*, tool *names*), MID
(quantities tied to a metric, entities, process steps, described tool usage) or
**DEAR** (incident markers, causal links, metric definitions carrying
`how_measured`). The DEAR class is the count reported. The mapping is a
judgement, applied uniformly; a second independent instrument (novel-content
share) agrees with it on every ranking.

---

## Section A — current probe architecture

| level | n | avg answer score | avg hard-to-invent | avg answer len | % zero evidence | % contradiction | % metric definitions | % incident markers | % tool signals |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| VALIDATION | 68 | 32.5 | **0.82** | 272 | 0.0% | 0.0% | **1.5%** | 23.5% | 16.2% |
| OPERATIONAL | 62 | 33.2 | 0.90 | 385 | 0.0% | 0.0% | 4.8% | 14.5% | **69.4%** |
| INCIDENT | 65 | 34.1 | **1.77** | 408 | 0.0% | 0.0% | 0.0% | **78.5%** | 9.2% |
| DECISION | 51 | **26.8** | 1.06 | 395 | 0.0% | 0.0% | 3.9% | 13.7% | 17.6% |
| OUTCOME | 59 | **35.8** | 1.54 | 393 | 0.0% | 1.7% | **42.4%** | 11.9% | 20.3% |
| TRANSFER *(Tier A only)* | 10 | 0.7 | 0.00 | 46 | 100.0% | 0.0% | 0.0% | 0.0% | 0.0% |

Notes on specific cells:

- **"% zero evidence" is 0.0% everywhere in Tier B.** Every simulated answer
  produced at least one signal. The meaningful scarcity measure is
  **zero *hard-to-invent* evidence: 24.9% of all Tier-B answers** (per level:
  VALIDATION 39.7%, OPERATIONAL 37.1%, DECISION 21.6%, OUTCOME 13.6%,
  INCIDENT 10.8%).
- **TRANSFER's row is an artifact, not a result.** The Tier-A answer pool has no
  transfer entry, so all 10 turns collapsed to a fallback non-answer. It measures
  the study harness, not the probe.
- **Metric definitions: OUTCOME 42.4% vs VALIDATION 1.5% — a 28× gap** on the
  same targeted dimension.
- **Incident markers: INCIDENT 78.5% vs 11.9–23.5% elsewhere.**
- **Tool signals: OPERATIONAL 69.4% vs 9.2–20.3% elsewhere.**
- **DECISION leads on no column.** Lowest answer score (26.8) and no signal type
  where it is first.

### Rankings (Tier B; TRANSFER excluded — no causal data)

| rank | total evidence | hard-to-invent evidence | contradiction yield |
|---|---|---|---|
| 1 | OPERATIONAL (7.44) | **INCIDENT (1.77)** | OUTCOME (1 event) |
| 2 | OUTCOME (6.46) | OUTCOME (1.54) | VALIDATION (0) |
| 3 | INCIDENT (6.23) | DECISION (1.06) | OPERATIONAL (0) |
| 4 | VALIDATION (5.49) | OPERATIONAL (0.90) | INCIDENT (0) |
| 5 | DECISION (5.04) | **VALIDATION (0.82)** | DECISION (0) |

**Contradiction yield is not measurable in this corpus.** Total contradictions
across 68 interviews: **1**. Only **16 session/fact-key pairs** in the whole
corpus repeat a key at all, which is the precondition for detection. The single
fire is a **false positive**: `team_size` "5 m" vs "20 %", comparing *"teams of
up to 5 members"* against *"a 20% increase in engagement"* — the extractor keyed
an engagement metric as team size. **True-positive contradiction yield: 0.**

---

## Section B — interview flow

| measurement | value |
|---|---|
| interviews that started with a greeting response | **not measurable** |
| greetings incorrectly treated as answers | 0 (none present to mis-handle) |
| answers under 5 words | **0 / 395 (0.0%)** — Tier B: 0 |
| answers under 10 words | 8 / 395 (2.0%) — **Tier B: 0** |
| answers that are "I don't know" | 20 / 395 (5.1%) — **Tier B: 0** |
| answers sharing no content word with the question | 53 / 395 (13.4%) — Tier B: 3 |

**On greetings:** `scripts/interview_study.py` calls
`orchestrator.submit_answer()` directly. The opt-in / greeting flow in
`routers/whatsapp.py` is never exercised; all 68 sessions are `state=COMPLETE`,
`channel=simulated`. There are zero greeting turns in the corpus **to** count.
This is an absence of instrumentation, not a measurement of zero.

**On weak answers:** every short answer, every "I don't know", and 50 of 53
unrelated answers are **Tier A** — the fixed pool, where content is assigned by
position and not by the question. The simulator (Tier B, 305 turns) produced
**zero** answers under 10 words and **zero** "I don't know" responses, despite
its prompt instructing it to be vague when the resume does not support an answer.

### Time to first evidence

| milestone | mean turns | interviews reaching it |
|---|---:|---|
| first meaningful evidence (≥1 hard-to-invent signal) | **1.38** | 68 / 68 (100%) |
| first incident marker | 2.60 | 60 / 68 (88.2%) |
| first metric-ownership signal (`how_measured`) | **3.41** | **37 / 68 (54.4%)** |
| first contradiction | 1.00 | **1 / 68 (1.5%)** |

**45.6% of interviews never establish metric ownership at all**, and those that
do reach it at turn 3.4 of a ~5.8-turn interview.

---

## Section C — evidence graph

Restricted to cells where the probe level **targets** that dimension. A targeted
cell includes zeros; a non-targeted cell only exists when the score is >0, so it
is biased upward and is excluded from every comparison below.

| dimension | claim-level final | per-answer | gain/question | levels that target it | most | least |
|---|---:|---:|---:|---:|---|---|
| SPECIFICITY | 89.7 | 41.0 | 23.0 | 2 | VALIDATION 54.1 | INCIDENT 30.5 |
| PROCESS | 91.1 | 70.7 | 23.4 | 2 | OPERATIONAL 93.4 | DECISION 71.0 |
| METRIC_OWNERSHIP | **63.3** | 36.5 | 16.2 | 2 | OUTCOME 53.8 | VALIDATION 25.4 |
| CAUSAL_REASONING | 77.8 | 36.1 | 20.0 | 2 | DECISION 30.0 | OUTCOME 27.6 |
| AUTHENTICITY | **45.2** | 33.4 | **11.6** | **1** | INCIDENT 32.2 | — |
| TOOL_FAMILIARITY | **39.8** | 48.8 | **10.2** | **1** | OPERATIONAL 44.5 | — |

*gain/question = claim-level final ÷ 3.9 answered questions per claim.*

### Ownership verdicts

| dimension | verdict | evidence |
|---|---|---|
| SPECIFICITY | **clear owner: VALIDATION** | +23.7 over the only other targeting level |
| PROCESS | **clear owner: OPERATIONAL** | +22.4 |
| METRIC_OWNERSHIP | **clear owner: OUTCOME** | +28.4 |
| CAUSAL_REASONING | **NO EFFECTIVE OWNER** | DECISION 30.0 vs OUTCOME 27.6 — **spread 2.4**, both levels target it, neither produces it. Lowest per-answer of any dimension with 100% coverage. |
| AUTHENTICITY | **SINGLE POINT OF FAILURE** | targeted by INCIDENT alone. No redundancy. Second-lowest claim-level final (45.2). |
| TOOL_FAMILIARITY | **SINGLE POINT OF FAILURE** | targeted by OPERATIONAL alone. **Lowest claim-level final in the graph (39.8)** and lowest gain/question (10.2). |

**Dimensions with no effective owner: CAUSAL_REASONING.**
**Dimensions with exactly one owner and no redundancy: AUTHENTICITY,
TOOL_FAMILIARITY.**

---

## Section D — question quality

Ten-category classification over all 395 asked questions (earliest-cue-wins,
fixed precedence, 100% classified).

| category | n | % | Tier B n | total evidence | hard-to-invent | DEAR share | % zero hard-to-invent | answer len |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| METADATA | 84 | 21.3% | 67 | 5.45 | **0.82** | 15.1% | **40.3%** | 271 |
| WORKFLOW | 81 | 20.5% | 60 | **7.40** | 0.92 | **12.4%** | 35.0% | 384 |
| INCIDENT | 71 | 18.0% | 57 | 6.18 | **1.74** | 28.1% | 12.3% | 406 |
| MEASUREMENT | 70 | 17.7% | 61 | 6.52 | 1.52 | 23.4% | 14.8% | 392 |
| TRADEOFF | 60 | 15.2% | 50 | 5.04 | 1.04 | 20.6% | 22.0% | 394 |
| FAILURE | 16 | 4.1% | 9 | 6.89 | **1.78** | 25.8% | **11.1%** | 428 |
| TRANSFER | 10 | 2.5% | 0 | — | — | — | — | — |
| PEOPLE | **2** | 0.5% | 0 | — | — | — | — | — |
| DEPENDENCY | **1** | 0.3% | 1 | 4.00 | 2.00 | 50.0% | 0.0% | 385 |
| **EXCLUSION** | **0** | **0.0%** | 0 | — | — | — | — | — |

**Four of the ten categories are effectively absent: EXCLUSION (0),
DEPENDENCY (1), PEOPLE (2), TRANSFER (10, none causal).** Together they are
**3.3%** of the interview. The three highest-volume categories — METADATA,
WORKFLOW, INCIDENT — are **59.8%**.

### Rankings

| rank | total evidence | hard-to-invent evidence |
|---|---|---|
| 1 | WORKFLOW (7.40) | DEPENDENCY (2.00) *n=1* |
| 2 | FAILURE (6.89) | **FAILURE (1.78)** |
| 3 | MEASUREMENT (6.52) | **INCIDENT (1.74)** |
| 4 | INCIDENT (6.18) | MEASUREMENT (1.52) |
| 5 | METADATA (5.45) | TRADEOFF (1.04) |
| 6 | TRADEOFF (5.04) | **WORKFLOW (0.92)** |
| 7 | DEPENDENCY (4.00) *n=1* | **METADATA (0.82)** |

**WORKFLOW is 1st on total evidence and 6th of 7 on hard-to-invent evidence.**
It has the lowest DEAR share of any category (12.4%).

---

## Section E — authorship verification

**Question asked:** could a knowledgeable stranger who read only the resume
plausibly answer this without having done the work? **HIGH = yes, the stranger
can** (the question does not discriminate).

| category | rating | corpus justification |
|---|---|---|
| **METADATA** | **HIGH** | 0.82 dear, 15.1% DEAR share, **40.3% of answers carry no hard-to-invent signal at all**; shortest answers in the corpus (271 chars vs 384–428). Answers are one cardinal plus filler: *"around 150 employees"*, *"around 10 hours a week"*. |
| **WORKFLOW** | **HIGH** | Highest total evidence (7.40) but **lowest DEAR share (12.4%)** and 35.0% zero-dear. The volume is process steps and named tools; a generic daily routine is producible from the claim. |
| **TRADEOFF** | **MEDIUM** | 1.04 dear, 22.0% zero-dear. Splits by sub-pattern: *"what factors led you"* yields 1.44 dear / 0% zero, while *"what factors did you"* yields 0.68 / 42% zero — a 2.1× difference within one category. |
| **MEASUREMENT** | **LOW** | 1.52 dear, 14.8% zero-dear, and the only category that opens the METRIC_OWNERSHIP gate (42.4% at OUTCOME vs 1.5% at VALIDATION). Requires committing to a population, window and instrument. |
| **INCIDENT** | **LOW** | 1.74 dear, 28.1% DEAR share, 12.3% zero-dear, longest-but-one answers. Produces incident markers in **78.5%** of answers vs 11.9–23.5% at every other level. |
| **FAILURE** | **LOW** | Highest dear of any usable category (1.78), lowest zero-dear (11.1%), longest answers (428). **n=9 in Tier B** — directional. |
| DEPENDENCY | insufficient data | n=1 |
| PEOPLE | insufficient data | n=2, neither in Tier B |
| EXCLUSION | **no data** | **n=0. This category was never generated.** |
| TRANSFER | insufficient data | n=10, all Tier A, all collapsed to a pool non-answer |

### 10 strongest question patterns (Tier B, n≥4, ranked by hard-to-invent yield)

| pattern | n | dear | total sig | % zero-dear |
|---|---:|---:|---:|---:|
| "describe a specific week…" | 11 | **2.09** | 5.73 | **0%** |
| "tell me about a…" | 6 | 2.00 | 8.00 | 0% |
| "describe a specific incident…" | 8 | 1.88 | 6.75 | 0% |
| "describe a time when…" | 4 | 1.75 | 5.50 | 0% |
| "describe a specific time…" | 21 | 1.71 | 5.86 | 19% |
| "what factors led you…" | 9 | 1.44 | 4.44 | 0% |
| "how did you measure…" | 30 | 1.40 | 6.80 | 23% |
| "what specific actions did…" | 13 | 1.23 | 7.15 | 23% |
| "what steps did you…" | 7 | 1.14 | 8.00 | 0% |
| "what criteria did you…" | 18 | 1.11 | 5.28 | 17% |

### 10 weakest question patterns

| pattern | n | dear | total sig | % zero-dear |
|---|---:|---:|---:|---:|
| "how many people were…" | 6 | 1.00 | 5.17 | 17% |
| "what specific steps did…" | 6 | 1.00 | 7.50 | 33% |
| "how long did the…" | 4 | 1.00 | 6.75 | 50% |
| "which system did you…" | 8 | 0.75 | 7.00 | 38% |
| "what specific tasks did…" | 10 | 0.70 | **7.40** | **60%** |
| "what factors did you…" | 19 | 0.68 | 5.05 | 42% |
| "how long did it…" | 6 | 0.67 | 5.67 | 33% |
| "how long did you…" | 8 | **0.62** | 5.62 | **62%** |
| "describe a specific challenge…" | 5 | 0.60 | 4.80 | 40% |
| "how many team members…" | 4 | **0.25** | 4.00 | **75%** |

*20 patterns reach n≥4, covering 203 of 305 Tier-B turns.*

Two observations from the pattern table, stated as measurements:

- **"what specific tasks did"** produces 7.40 total signals — 4th highest of any
  pattern — with 0.70 dear and **60% of answers carrying no hard-to-invent
  signal**. Total-evidence rank and authorship rank are inverted within a single
  pattern.
- **Every "how long" / "how many" stem sits in the weakest ten.** The three
  worst-performing patterns in the corpus are all cardinality or duration frames.

---

## Confirmation status of the four stated discoveries

Reported as measurement outcomes only.

| # | claim | status | measurement |
|---|---|---|---|
| 1 | VALIDATION is weak, and the brief is the cause | **Confirmed** | Lowest hard-to-invent (0.82) and highest zero-dear (39.7%) of any level. Its brief enumerates *"how many, how long, who else"*; 93.5% of its questions are metadata and metadata is 0% at every other level. Metric definitions 1.5% vs OUTCOME 42.4%. |
| 2 | DECISION owns nothing | **Confirmed** | Leads no column in Section A. Lowest answer score (26.8) and lowest total evidence (5.04). On CAUSAL_REASONING it scores 30.0 against OUTCOME's 27.6 — spread 2.4, classified NO EFFECTIVE OWNER. On PROCESS it trails OPERATIONAL by 22.4. |
| 3 | OPERATIONAL yields much, but cheap | **Confirmed** | 1st on total evidence (7.44), 4th of 5 on hard-to-invent (0.90). Lowest DEAR share of any category (12.4%); 37.1% of its answers carry no hard-to-invent signal. |
| 4 | INCIDENT is the strongest authorship signal | **Confirmed** | 1st on hard-to-invent (1.77), lowest zero-dear (10.8%), incident markers in 78.5% of answers vs 11.9–23.5% elsewhere. Four of the five strongest question patterns are incident stems, all at 0% zero-dear. |

### Measured facts bearing on the proposed four-move model, without recommendation

- **EXCLUSION questions: 0 of 395.** The category the proposal names as PERIPHERY's
  core move has never been generated by the current system.
- **DEPENDENCY: 1. PEOPLE: 2.** Also PERIPHERY-adjacent, also effectively absent.
- **AUTHENTICITY and TOOL_FAMILIARITY each have exactly one targeting level**
  (INCIDENT and OPERATIONAL respectively) and are the two lowest claim-level
  finals in the graph (45.2 and 39.8).
- **CAUSAL_REASONING has no effective owner today** and is targeted by the two
  levels the proposal reassigns.
- **SEAM has no current analogue.** No probe level cross-references two prior
  answers; validator rule 3 (`multiple_fact_targets`) fires on questions naming
  two fact keys, 9 times in the corpus.
- **Contradiction detection is untested at this corpus size.** 16 repeat-key
  opportunities, 1 fire, 0 true positives.
