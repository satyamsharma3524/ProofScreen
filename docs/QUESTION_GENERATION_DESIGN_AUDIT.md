# Question Generation — Design Audit

**Date:** 2026-09-06 · **Scope:** architecture only. No code, no implementation,
no sequencing. Evidence is cited from
[docs/QUESTION_GENERATION_AUDIT.md](docs/QUESTION_GENERATION_AUDIT.md) and
`studies/phase3/`, not re-derived.

---

## 0. Verdict

The pipeline has seven stages and **six of them are correct**. There is one
structural defect, and it is not in any single stage — it is in **what the stages
pass to each other**.

> **The pipeline carries a *scoring* vocabulary where it needs an *interview*
> vocabulary.** `probe_level` is a partition of the rubric. `target_dimension` is
> an axis of the rubric. Neither describes what a question should *ask*. The
> probe brief is the only place that translation happens, and it is keyed on
> `probe_level` alone — so one brief must serve two rubric dimensions with one
> instruction, and it serves whichever one the signal extractor counts most
> cheaply.

Everything in section 3A follows from that one sentence. And the fix in section 5
requires **no new stage, no new module and no new abstraction** — the information
needed is already computed and already carried; it is simply not used as a key.

---

## 1. The flow as built

What actually moves between stages, which is where the defects are:

```
CLAIM                     text, claim_type, metric, family        extract.py
  │
  ▼
PROBE SELECTION           Plan(claim, probe_level, target_dimension,
  │                            reason, transfer?)                 orchestrator.plan_next
  │                       ── target_dimension computed here …
  ▼
PROBE BRIEF               PROBE_BRIEFS[probe_level]               question.py
  │                       + GAP_HINTS[target_dimension]  ← appended separately
  │                       + TRANSFER_INSTRUCTIONS[operator]
  │                       ── … but the brief is keyed on probe_level ONLY
  ▼
QUESTION GENERATION       one prompt file, $probe_level_brief slot LLM #2
  │
  ▼
VALIDATION                7 pure-Python rules, all evaluated      question.validate
  │
  ▼
REGENERATION              rule names as one-line hints, one retry
  │
  ▼
FALLBACK                  hand-written per level, NEVER validated
```

Two things to notice before the stage table:

- `target_dimension` is computed by the planner, then **demoted to a hint**
  rather than used as a selector. For the opening probe on every claim it is
  `None`, so the brief runs unqualified.
- The fallback is the only stage exempt from validation, and it is where the
  best-performing VALIDATION question in the entire corpus lives.

---

## 2. Stage-by-stage: owns / should own / leaking

### Stage 1 — Claim

| | |
|---|---|
| **Owns** | Extracting falsifiable statements, typing them against the taxonomy, compressing a metric. |
| **Should own** | The same, plus **an honest signal about how testable the claim actually is**. |
| **Leaking** | Nothing outward. But it **absorbs** a responsibility nobody else takes: an under-specified claim (*"Optimized performance by 40%"* — performance of *what*?) is passed downstream at full weight with no marker, and every later stage treats it as if it were precise. |

The extraction prompt is right to keep metric-less claims (measured: no
meaningful downstream cost). The gap is different — **nothing distinguishes a
claim that is vague from one that is merely unquantified**, and the planner
weights them identically.

### Stage 2 — Probe Selection

| | |
|---|---|
| **Owns** | Which claim, how deep, and which evidence gap to close. Correctly a pure function with no model call. |
| **Should own** | Exactly that. This stage is **well designed and should not change** except in one respect below. |
| **Leaking** | It computes the single most useful piece of routing information in the pipeline — `target_dimension` — and then **hands it downstream as an optional nudge instead of a selector**. |

Two structural facts amplify this:

- `level_for_dimension()` walks the ladder and returns the **first** level
  covering a dimension. VALIDATION is first and covers SPECIFICITY *and*
  METRIC_OWNERSHIP, so gaps in two of six dimensions route to VALIDATION.
- The breadth phase gives **every claim** a VALIDATION probe first, with
  `target_dimension = None`.

VALIDATION is therefore doubly privileged — mandatory opener *and* default
destination for a third of the dimension space. It is 23% of all questions asked.
That is a defensible policy. The problem is what happens to it in stage 3.

### Stage 3 — Probe Brief  ◀ **the defect lives here**

| | |
|---|---|
| **Owns** | Translating a rubric coordinate into an interview instruction. In practice: the *entire* content specification of the question, since the prompt file contains only constraints. |
| **Should own** | Exactly one ask per invocation, selected by **both** the level and the dimension the planner chose. |
| **Leaking** | Three ways, below. |

**Leak 3a — it bundles multiple asks and lets the model pick.**
`PROBE_BRIEFS[OUTCOME]` contains four asks. Measured across 519 attempts:

| brief's ask | fires |
|---|---:|
| "how they knew it worked" | 77 / 95 |
| "which number moved" | 14 / 95 |
| "what happened afterwards" | 13 / 95 |
| **"what they would do differently"** | **0 / 95** |

A four-ask brief collapses to one ask. **Which one is decided by the model and
the validator, not by the design.**

**Leak 3b — it inherits the extractor's counting units as its question
vocabulary.** `PROBE_LEVEL_DIMENSIONS` lives in `signals.py` — the *scoring*
module — and its own comment says it is read two ways: scoring uses it to mark
what was probed, and the policy uses it to pick a level. The brief is then
authored to elicit those dimensions. `score_specificity()` counts quantities and
entities. So the VALIDATION brief asks *"how many, how long, what the numbers
were."* **The question was designed backwards from what the counter counts.**

**Leak 3c — `GAP_HINTS` is a second, additive instruction rather than part of the
brief.** The model receives the level's generic ask *and* a dimension nudge that
may point elsewhere. The planner already guards the worst case (it drops the
target dimension when no remaining level covers the gap, with a comment saying a
mismatched hint produces "a confused, hybrid question") — which is an
acknowledgement, inside the code, that **two instructions in one prompt is a
known hazard being managed rather than removed.**

### Stage 4 — Question Generation

| | |
|---|---|
| **Owns** | Wording only. Correct, and the invariant is real — planner decides *what*, model decides *how*. |
| **Should own** | The same. |
| **Leaking** | Nothing. The measured brief-compliance is 92–100% at every level. **This stage is doing its job and is not the problem.** |

The prompt file contains constraints and no content specification. That is a
sound division. It also means every content complaint is a complaint about
stage 3.

### Stage 5 — Validation

| | |
|---|---|
| **Owns** | Rejecting questions that are structurally defective. Pure, deterministic, no model call — the right pattern, and the same one `enforce_verbatim()` uses. |
| **Should own** | **Validity only.** A filter that answers "is this question broken?" |
| **Leaking** | It is also, silently, **arbitrating question policy** — deciding which of the brief's asks are permitted to exist. |

**Leak 5a — the validator vetoes the brief, invisibly.** `PROBE_BRIEFS[OUTCOME]`
instructs "what they would do differently". That is a counterfactual, and rule 4
(`hypothetical_misuse`) forbids hypotheticals at every level except TRANSFER.
Result: **0 fires in 519 attempts.**

The invisibility is the architectural point. `hypothetical_misuse` also shows **0
rejections** — because the prompt's own no-hypotheticals rule suppresses the
question upstream, so the validator never gets to reject it and no metric ever
records the veto. **A stage is overriding another stage's instruction with no
observable trace.** Phase 3 read the zero as "gpt-4o does not make that mistake";
it is at least as consistent with "the pipeline forbids it twice."

**Leak 5b — the same contradiction exists on TRANSFER.** The planner selects a
target claim and instructs the model to substitute its subject in; rules 6 and 7
are told about `target_claim_text`, rules 1 and 5 are not, so the figure the
planner supplied reads as invented. All 4 `unsupported_metric` fires in the
corpus are this.

**Leak 5c — a validity rule is doing scope policy.** Rule 7 (`no_claim_anchor`)
requires lexical overlap with the claim. That is defensible on WhatsApp — the
candidate has three resume lines and needs to know which one. But it means the
bare universal question (*"What broke?"*) is **structurally unable to exist**, and
that constraint is expressed nowhere in the brief that authors questions. The
brief and the validator hold different theories of what a question is.
(See §6 — `QUESTIONING_PHILOSOPHY.md` Principle 1 endorses the anchoring
constraint itself, so the real gap is that it is stated only in the validator
and nowhere in the brief that authors questions.)

### Stage 6 — Regeneration

| | |
|---|---|
| **Owns** | One more attempt, told which rules it tripped by name. The one-retry cap and its "two explicit calls, not a loop" framing are sound. |
| **Should own** | The same. |
| **Leaking** | Mild. `_RETRY_HINTS` are **rule names**, i.e. *scoring* vocabulary again — *"this repeats an earlier question; ask something new"* gives no direction. It is the least effective hint: `duplicate_content` is 6.3% of attempt-1 drafts and **16.5%** of attempt-2 drafts. |

The stage is architecturally right. Its input vocabulary is inherited from the
same confusion as stage 3.

### Stage 7 — Fallback

| | |
|---|---|
| **Owns** | Guaranteeing an anchored, cohort-neutral question exists when everything else fails. Correctly exempt from validation — a validator able to reject it would leave no path at all. |
| **Should own** | The same. |
| **Leaking** | **Inward, and this is the tell.** The fallback holds question design that stage 3 should own. |

`FALLBACK_QUESTIONS[VALIDATION]` — *"what exactly was your scope, and what were
the numbers?"* — is open, two-part, and is **the only open scope question written
down anywhere in the system**. It produced the single strongest answer in the
corpus (14 signals vs a VALIDATION model-question mean of 5.16), and fallback
questions overall show no measured quality cost against generated ones.

**The emergency path out-performs the designed path at the level where the design
is wrong.** That is not a fallback problem. It is stage 3's specification leaking
into the one place nobody validated.

---

## 3A. Why VALIDATION questions become metadata questions

Four mechanisms, compounding. Only the first is a wording problem.

**1. The brief says so, literally.**

> "Ask for the shape of it: **how many, how long, who else was involved, what the
> numbers were.**"

93.5% of VALIDATION questions are metadata. Metadata is **0%** of every other
level. This is instruction-following, not drift.

**2. The brief was derived from the rubric, and the rubric counts quantities.**
VALIDATION targets `(SPECIFICITY, METRIC_OWNERSHIP)`. `score_specificity()` is a
count of quantities plus entities, gated on *"no quantity given"*. The shortest
path from that gate to a score is to ask for a number. The brief takes it.

**3. The brief serves one of its two dimensions and starves the other.**
This is the mechanism, and it is measurable:

| | SPECIFICITY | METRIC_OWNERSHIP |
|---|---:|---:|
| gate opens on | any quantity present | a metric the candidate *defines* |
| does the VALIDATION brief ask for it? | **yes, explicitly** | **no, never** |
| observed mean at VALIDATION | **54.3** (best cell in the matrix) | **25.3** (worst cell) |
| **share of answers capped by the gate** | — | **98.5% (67/68)** |
| observed mean at OUTCOME, which asks *how* | — | **53.8** (57.6% gated) |

**One question, one level, two targeted dimensions: one is the best-served in the
system and the other is gated shut 98.5% of the time.** The brief cannot open the
METRIC_OWNERSHIP gate because opening it requires asking *how a number was
captured*, and the brief asks *what the number was*.

**4. The planner sends more traffic here than anywhere else, unqualified.**
VALIDATION is the mandatory opener for every claim (with `target_dimension =
None`, so even the GAP_HINTS nudge is absent) **and** the default destination for
SPECIFICITY and METRIC_OWNERSHIP gaps via `level_for_dimension()`. 23% of the
interview budget arrives at the one brief that cannot serve half its own mandate.

**In one line:** VALIDATION produces metadata because a single brief is asked to
cover two rubric dimensions with one instruction, and it optimises for the
dimension whose gate is cheapest to open.

---

## 3B. Where should "What was the hardest part?" live?

**Answer: the probe brief. And three of your four examples already live there and
already ship.**

| your example | brief that already contains it | does it reach the candidate? |
|---|---|---|
| "What was the hardest part?" | INCIDENT — *"a particular time it went wrong, or the hardest week"* | **Yes.** INCIDENT → 100% failure-type questions. *"Tell me about the hardest week you had running the deal desk."* is a real corpus question, and the strongest INCIDENT answer. |
| "What broke?" | INCIDENT — same brief | **Yes**, in anchored form. |
| "How did you know?" | OUTCOME — *"how they knew it worked"* | **Yes** — 77 of 95 OUTCOME questions. |
| **"What would you do differently?"** | OUTCOME — *"what they would do differently"* | **No. 0 of 519.** Vetoed by validator rule 4. |

So the correct architectural reading of your question is not *"where should this
new behaviour go"*. It is:

> **The behaviour is already specified in the right stage. It is being crowded
> out by a four-ask brief collapsing to one ask, and in one case vetoed by a
> downstream filter.**

### Ruling out the other candidate stages

| stage | can it own this? | why not |
|---|---|---|
| **Probe selector** | No | It should own *which claim, how deep, which gap* — evidence routing. It has no business knowing the words "hardest" or "broke". Putting question intent here couples policy to phrasing and makes every new question style a planner edit. |
| **Prompt** | No | The prompt file is level-agnostic by design and is rendered once per call. Per-level asks placed here become a conditional pile inside a template, and the template is shared with TRANSFER. |
| **Validator** | **Never, structurally** | **A filter cannot create behaviour.** It is subtractive — it can only remove questions that already exist. Nothing you want to see *more* of can be caused here. This is the single most important boundary in the whole pipeline and it is currently being crossed in the other direction (leak 5a). |
| **Planner (as distinct from selector)** | No | There is no separate planner. `select_transfer()` deliberately lives beside the policy; adding a phrasing planner would be a new layer for something the brief table already expresses. |
| **Probe brief** | **Yes** | It is already the translation point from rubric coordinate to interview instruction. It is the only stage whose job is "what should this question ask". |

### What has to change about the brief for those four to ship reliably

1. **One ask per brief.** A brief with four asks is not a specification; it is a
   menu, and the model orders the cheapest item. "What would you do differently"
   loses to "how did you measure" every time.
2. **The validator must stop vetoing it.** Rule 4 and the OUTCOME brief hold
   contradictory positions on counterfactuals. That contradiction must be
   resolved in one direction or the other — it cannot be left to the model to
   discover silently.

---

## 4. Worked example — *"Optimized performance by 40%"*

Claim as extracted: `text = "Optimized performance by 40%"`, `metric = "40%"`,
family `software_engineering`.

Note what no stage remarks on: **"performance" is undefined.** Latency?
throughput? build time? page load? 40% of an unnamed quantity is not a
falsifiable claim, and nothing between extraction and questioning says so.

### Current pipeline output

Trace projected from the observed corpus. Every step has a direct real analogue,
cited.

```
PLAN      claim untouched → VALIDATION, target_dimension = None
BRIEF     "Ask for the shape of it: how many, how long, who else was
           involved, what the numbers were."
DRAFT 1   "How many services did you optimize to hit the 40% improvement?"
VALIDATE  numerals{40} ∩ claim numerals{40}  →  answer_leakage  →  REJECT
          ⤷ real analogue: "How many queues did you manage to maintain
            the 97% SLA?"  and  "How many weeks did it take to reduce AHT
            from 480 to 430 seconds?"  — both rejected, same rule
RETRY     hint: "do not state any figure the claim already gives — ask for it"
DRAFT 2   "How many services did you optimize?"
VALIDATE  accept
ASKED     "How many services did you optimize?"
```

Candidate answer, and what it scores:

```
A  "Around 12 services, mostly in the checkout path, over about two months."

   quantities: 12, two months      entities: checkout path
   metric_definitions: none

   SPECIFICITY        ~60   gate OPEN  (quantities present)
   METRIC_OWNERSHIP   ~25   gate SHUT  — "metric never defined", capped at 45
```

**After the opening question we know there were twelve services. We still do not
know what "performance" means, what it was before, or how it was measured.** The
claim is exactly as unfalsifiable as it was on the resume. The corpus means for
this cell are 54.3 / 25.3 — this trace is the median case, not the bad case.

### Desired pipeline output

```
PLAN      claim untouched → VALIDATION, target_dimension = METRIC_OWNERSHIP
          (the planner already computes dimension gaps; it simply does not
           supply one for the opener today)
BRIEF     one ask, selected by the pair:
          "Establish WHICH number this is and how it was captured, before
           asking what it did. Do not accept the metric's name as its
           definition."
DRAFT     "What was the performance number before you started, and how was
           it being measured?"
VALIDATE  no claim numeral echoed → passes rule 1
          asks one thing → passes rule 3
          shares "performance" with the claim → passes rule 7
ASKED     "What was the performance number before you started, and how was
           it being measured?"
```

```
A  "p95 checkout latency — 1.8 seconds, measured in Datadog RUM on real
    user sessions, not synthetic. That's the number the 40% is against."

   quantities: 1.8s, 40%           entities: Datadog RUM, checkout
   metric_definitions: p95 checkout latency, how_measured = "Datadog RUM
                       on real user sessions"

   SPECIFICITY        ~60   gate OPEN
   METRIC_OWNERSHIP   ~60   gate OPEN  ← the 45 cap is lifted
```

**The desired question serves both of VALIDATION's targeted dimensions. The
current one serves one and gates the other at 45.** That is the whole difference,
and it is worth roughly +35 points on a dimension that is currently capped in
98.5% of cases.

It also repairs the claim: *"performance"* is now *"p95 checkout latency"*, and
every subsequent probe on this claim inherits a falsifiable subject.

### The rest of the ladder, for contrast

| level × dimension | current (projected) | desired |
|---|---|---|
| OPERATIONAL × PROCESS | *"What specific tasks did you perform in the system daily?"* | *"How did you find the slow paths — what were you looking at?"* |
| INCIDENT × AUTHENTICITY | *"Describe a specific time when an optimization didn't work as planned."* ✅ already good | unchanged |
| DECISION × CAUSAL | *"What factors led you to prioritize those services?"* | *"What did you try that didn't move it, and how did you rule it out?"* |
| OUTCOME × CAUSAL | *"How did you measure the 40% improvement?"* (duplicates the fixed VALIDATION) | *"What would you do differently now?"* — **today: impossible, rule 4** |

Note the second-order effect in the last row. Once VALIDATION properly owns
"how was it measured", OUTCOME is freed to ask the retrospective — which is
exactly the question in your 3B list that never ships.

---

## 5. Minimum architectural change

### The change

> **Key the probe brief on the pair `(probe_level, target_dimension)` instead of
> `probe_level` alone, and require the selector to always supply a target
> dimension — including for the opening probe.**

That is the whole recommendation. One table is re-keyed; one planner branch stops
passing `None`.

### Why this is the minimum

Everything it fixes, it fixes as a consequence rather than as a separate change:

| symptom | why it resolves |
|---|---|
| VALIDATION → metadata (3A) | `VALIDATION × METRIC_OWNERSHIP` becomes a brief that asks *how the number was captured*. The metadata brief survives as `VALIDATION × SPECIFICITY`, where it is the best-performing cell in the system and should be kept. |
| Four-ask briefs collapsing (leak 3a) | A brief keyed on a dimension has one job, so it carries one ask. The collapse has nowhere to happen. |
| `GAP_HINTS` as a second instruction (leak 3c) | Dissolves. The hint *is* the brief; there is no longer a generic instruction for it to contradict, and the planner's defensive "drop the hint when levels mismatch" branch becomes unnecessary. |
| Retry hints in scoring vocabulary (stage 6) | Unchanged, but less load-bearing — fewer rejections to recover from once the brief stops steering into `answer_leakage`. |
| Fallback out-performing the model (stage 7) | The open scope question moves from the emergency path into the brief where it belongs. The fallback stays exactly as it is. |

### Why it is architecturally legitimate

- **No new stage.** The flow diagram in §1 is unchanged.
- **No new module, layer or abstraction.** `EXECUTION_STANDARD.md` §1's
  prohibition is not engaged — this is a re-parameterisation of `PROBE_BRIEFS`.
- **No new information.** `Plan` already carries both fields to the brief today.
  The pair is already the key everywhere else in the system:
  `PROBE_LEVEL_DIMENSIONS` defines exactly which pairs are reachable — 12 of 36,
  and TRANSFER's two are already special-cased.
- **No schema change**, no frozen-file edit, no `FamilyMatch` change.
- The planner/wording invariant is **strengthened**: the planner's decision now
  *selects* the instruction instead of decorating it.

### The precondition, which is not optional

**The brief and the validator must stop holding contradictory positions.** Two
are known:

1. `PROBE_BRIEFS[OUTCOME]` instructs a counterfactual; rule 4 forbids
   counterfactuals outside TRANSFER. Score: 0/519.
2. The TRANSFER planner injects a target claim's figure; rules 1 and 5 do not
   know that claim exists. All 4 `unsupported_metric` fires.

These are not tuning questions. They are two stages disagreeing about what a
valid question is, and **the validator currently wins in silence** — no counter
records the veto, which is why (1) survived a full 68-interview study
undetected. Whichever way each is resolved, the resolution belongs in the
design, not in the model's discovery.

### What this change explicitly does not do

- It does not touch the selector's routing logic. That stage is sound.
- It does not touch the prompt file. That stage is sound.
- It does not add rules, remove rules, or move a threshold.
- It does not address **causal reasoning**, the worst dimension corpus-wide
  (34.1) and immune to both briefs that target it. That is a rubric/extractor
  question one layer down and a brief cannot reach it. Do not expect this change
  to move it.
- It does not address **claim under-specification** (stage 1). *"Optimized
  performance by 40%"* still enters the pipeline unmarked; the desired
  VALIDATION question repairs it as a side effect rather than by design.

### Two things NOT to do, on the evidence

- **Do not add a question-intent taxonomy as a new abstraction.** The
  `(level, dimension)` pair already is one, it is already computed, and it is
  already the key the scoring side uses. A parallel vocabulary would be a second
  source of truth about what a question is for.
- **Do not push any of this into the validator.** A filter cannot create
  behaviour. Every request of the form "I want more questions like X" must be
  satisfied upstream of stage 5, or not at all.

---

## 6. Reconciliation with `docs/QUESTIONING_PHILOSOPHY.md`

That document appeared in the working tree during this audit (untracked — a
parallel session; CLAUDE.md warns to check `git log` before assuming a
baseline). It designs questions **from first principles, deliberately ignoring
how they are currently generated**. This document works the opposite direction —
from the built pipeline and its measured output. They should be read together,
and where they agree the agreement is worth more than either alone.

### Where they converge independently

| Philosophy principle | This audit's finding | Note |
|---|---|---|
| **5 — "Every quantified claim earns one question about definition and measurement, not value."** | §3A: VALIDATION asks *what the number was*, never *how it was captured*; the METRIC_OWNERSHIP gate is shut in **98.5%** of VALIDATION answers. | **The strongest result in either document.** One reached it by reasoning about fabrication; the other by counting gate closures. Same conclusion, no shared method. |
| **4 — "The headline of a claim is the rehearsed part; spend no questions on it."** | §2 stage 2: VALIDATION is the mandatory opener on every claim and 23% of the budget, and it asks about the headline. | A direct first-principles argument against the current opener. |
| **7 — "One question asks for one thing."** | Leak 3a: a four-ask OUTCOME brief collapses to one ask, chosen by the model. | Independent endorsement of the one-ask-per-brief half of §5. |
| **1 — "Anchor to a claim, never to a field."** | Leak 5c: rule 7 (`no_claim_anchor`) makes the bare universal question structurally impossible. | **The philosophy doc endorses the constraint.** So leak 5c is milder than I framed it: the policy is right, it is simply expressed only in the validator and nowhere in the brief that authors questions. The fix is to state it in both, not to relax the rule. |

### Where they conflict — and the philosophy doc probably wins

§3B treats *"What would you do differently?"* as desired behaviour blocked by
validator rule 4. Philosophy **Principle 3** ("ask for recall, not opinion —
never *how would you, what's your approach*") and the kill list would likely
reject it too, as an invitation to a free, infinitely generable opinion.

So the §5 precondition stands — the OUTCOME brief and rule 4 cannot both be
right — but the direction now has an argument: **resolve it by dropping the
counterfactual from the OUTCOME brief, not by carving an exception into rule 4.**
The measured fact is unchanged either way: a brief is instructing something the
system forbids, and nothing recorded it for 519 attempts.

### Where the philosophy doc requires MORE than the minimum change in §5

Two of its principles have no home in the current architecture, and neither is
reachable by re-keying `PROBE_BRIEFS`:

- **Principle 9 — the cross question.** "Put load on two things the candidate has
  already said and see whether they hold together: p95 against p99, quota
  against deal count." This is neither a ladder level nor TRANSFER. It needs the
  planner to select **two prior facts** rather than one claim, which is a new
  plan shape — genuinely new architecture, and outside the minimum change. Note
  it also sits in tension with validator rule 3 (`multiple_fact_targets`), which
  exists to forbid exactly two fact targets; the philosophy doc licenses it as
  "the one exception" in Principle 7. Same class of stage-contradiction as §5's
  precondition, one layer earlier.
- **Principle 8 — "never supply the answer inside the question."** *"Why did you
  choose Redis?"* hands over the decision and its frame. `answer_leakage` catches
  only numerals; this is its non-numeric sibling, and it is the same gap already
  recorded as `unsupported_premise` in `studies/phase3/validator_disagreements.md`
  Finding 1 — the largest defect class in the human review, and the one the human
  labelled inconsistently 6/7. Still not specifiable as a crisp rule.

### What this means for §5

Nothing in the philosophy document changes the minimum architectural
recommendation, and one principle (5) independently converges on the precise cell
this audit identified as broken. But it is a **larger target than the minimum
change reaches**: re-keying the brief on `(level, dimension)` delivers principles
4, 5 and 7. Principles 8, 9 and 10 need work in stages this recommendation
deliberately does not touch.
