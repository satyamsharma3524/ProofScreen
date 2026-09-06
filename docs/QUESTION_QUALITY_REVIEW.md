# Forensic review — question quality on `Abhishek-Singh-Resume-New.pdf`

Companion to [RESUME_PIPELINE_TRACE.md](RESUME_PIPELINE_TRACE.md). Claims, question
text, probe levels, `source`, `attempts` and `violations_json` are taken from
that trace's persisted `questions` rows. Everything else here was **measured**,
not reasoned about: four ablations, 82 generated questions, real `gpt-4o`,
production `generate_question()` and production `validate()` throughout.

**Two hypotheses were tested and killed before the recommendation in §6.** They
are kept in §5 because each is the obvious fix and each measurably makes things
worse.

---

## 1. The claims and their first questions

### Claim 1 — `cl_c9523b`

| | |
|---|---|
| **Claim text** | Optimized platform performance by 40% through architecting the entire front-end using ReactJS and Redux resulting in improved user experience and scalability. |
| **Claim type** | `performance_work` — Performance and scale work (weight 20) |
| **Metric** | `40%` |
| **First question (Q1)** | *How many team members were involved in the ReactJS and Redux project?* |
| **Provenance** | `probe_level=VALIDATION`, `target_dimension=null`, `source=regenerated`, `attempts=2`, `violations=["no_claim_anchor"]` |

### Claim 2 — `cl_0ad1e1`

| | |
|---|---|
| **Claim text** | Boosted storefront businesses' customer base by 45% with a hyper-local SaaS platform, leading to enhanced customer satisfaction and long-term growth using loyalty, referral, and feedback modules for B2B clients. |
| **Claim type** | `delivery` — Delivery and migration (weight 15) |
| **Metric** | `45%` |
| **First question (Q2)** | *How long did it take to achieve the customer base increase?* |
| **Provenance** | `probe_level=VALIDATION`, `target_dimension=null`, `source=regenerated`, `attempts=2`, `violations=["answer_leakage"]` |

Both opening questions are **second attempts**. Neither is what the model first
wrote, and the rejected text is not recoverable — `questions.violations_json`
stores which rules fired, never the text that tripped them.

---

## 2. Scores

| | Q1 (`performance_work`) | Q2 (`delivery`) |
|---|---|---|
| Claim verification | **2** | **3** |
| Metric ownership | **1** | **2** |
| Authenticity detection | **2** | **2** |
| Information gain | **3** | **2** |

**Q1 — claim verification 2.** The claim asserts a 40% performance gain caused by
a front-end re-architecture. Team size is not a term in that assertion; no answer
to it can confirm or undermine the 40%.

**Q1 — metric ownership 1.** The question does not mention the metric, its
definition, its baseline or its measurement. `40%` appears nowhere.

**Q1 — authenticity 2.** "Four of us" costs a fabricator nothing and is
unfalsifiable over WhatsApp.

**Q1 — information gain 3**, the highest score in the table, and it is
accidental. `team_size` **is** a tracked fact key for `software_engineering` and
is marked `stable=True` (trace Stage 9), so the answer enters the consistency
engine and a later divergence would be caught. Real value, but not value about
this claim.

**Q2 — claim verification 3.** Marginally better than Q1: it names the claim's
subject ("customer base increase"). Elapsed time still does not test whether the
45% is real, or theirs.

**Q2 — information gain 2**, below Q1's. Project duration is not one of the 11
fact keys this family tracks; `tenure_months` is about a role, not a project. So
unlike Q1 the answer feeds nothing downstream.

### The structural reason both passed validation

`validate()` has **seven rules and not one of them is about probative value**.
`answer_leakage`, `duplicate_content`, `multiple_fact_targets`,
`hypothetical_misuse`, `unsupported_metric`, `scope_drift`, `no_claim_anchor` —
every one is a test of *form*. A question can be perfectly anchored, unique,
non-hypothetical, single-target and leak-free while testing nothing, and the
validator will accept it. Q1 is that question.

---

## 3. The best possible first question

Neither of these is authored here. Both were **produced by production
`generate_question()`** under the §6 change and copied verbatim.

**Claim 1:** *How did you measure the performance improvement, and what was it
before?*

**Claim 2:** *How did you measure the customer base increase and what was your
role in achieving it?*

Each names the metric's *subject* without its *value*, so it satisfies
`answer_leakage` while asking for exactly the thing `answer_leakage` exists to
protect: the number, produced by the candidate. Each also asks for a baseline or
an attribution, which is the half of a resume metric that is never written down
and the half a fabricator has not prepared.

---

## 4. Why the generated questions are weaker

**Q1.** It probes a dimension the claim does not assert. `performance_work`
carries `probe_focus=['CAUSAL_REASONING','METRIC_OWNERSHIP']` and `VALIDATION`
covers `(SPECIFICITY, METRIC_OWNERSHIP)`; the question reaches neither. It
survives `no_claim_anchor` only through the shared tokens "ReactJS" and "Redux",
which is anchoring to the claim's *technology* rather than to its *assertion*.
The 40% — the entire reason a recruiter would want this line verified — is never
mentioned.

**Q2.** It swaps the claimed quantity for an unclaimed one. The claim's number is
45%; the question asks for elapsed time, a figure that appears nowhere in the
resume. `unsupported_metric` does not catch this because that rule compares
*numerals*, and the question contains none. So the interview's opening move on
this claim collects a fact the resume never asserted, and leaves the one it did
assert unprobed.

Both are **the same failure**: the opening probe collects scope nouns instead of
testing the claimed figure.

---

## 5. Where the weakness comes from

Ranked by measured contribution. 42 samples in the production configuration
(`VALIDATION`, `target_dimension=None`, shipped prompt, shipped brief) gave
**81% first-attempt rejects and 29% fallbacks**.

### Primary — the question prompt, specifically `PROBE_BRIEFS[VALIDATION]`

[`api/engine/question.py:74-78`](../api/engine/question.py#L74-L78), injected as
`$probe_level_brief`:

> "VALIDATION — establish that they actually held this scope. Ask for the shape
> of it: **how many, how long, who else was involved**, what the numbers were."

Every weak question observed is a phrase from that list:

| Generated question | Phrase in the brief |
|---|---|
| How **many** team members were involved | "how many … who else was involved" |
| How **long** did it take | "how long" |
| How **many** storefront businesses | "how many" |

The model is not failing. It is complying. And the fourth item — "what the
numbers were" — is what walks it into `answer_leakage`.

### Contributing — the planner

`plan_next`'s breadth branch passes `target_dimension=None`
([`orchestrator.py:620-625`](../api/engine/orchestrator.py#L620-L625)), so
`gap_hint` is empty on the opening probe. This is the **only** question every
claim is guaranteed, and it is the one question with no dimension steering. The
depth branch's own comment states the invariant the breadth branch breaks: *"the
hint must always describe the question actually being asked."*

### Contributing — the validator, as a selection effect rather than a defect

`answer_leakage` caused **45 of 47** first-attempt rejects measured. It is not
miscalibrated — the model really is restating `40%`. But it removes the attempts
that reach for the metric, so the survivors are disproportionately the scope
questions. Withholding the figure from the model confirms the mechanism: **0/12
leaks, and all 12 were scope questions.** The rule selects against the good
question when the brief has pushed the model at the raw figure.

Also relevant: `answer_leakage` is the single most-fired rule and is **the one
validator rule the base prompt never states**. `duplicate_content`,
`hypothetical_misuse` and `multiple_fact_targets` all appear in `RULES`; the
model learns about `answer_leakage` only from `_retry_brief`, after it has
already failed.

### Contributing — fallback logic

At 29% of openings the fallback fires, and it renders
`On "<claim, 90 chars>" — Tell me more…`, which quotes **`Optimized platform
performance by 40% …`** verbatim. The system rejects a question twice for
containing `40`, then sends one containing the whole claim including `40%`.
CLAUDE.md already records *why* the fallback is unvalidated; what the trace adds
is the **rate**. In the real interview the two fallback questions (Q5, Q10)
produced `signals_found=2` each, against a 4–8 range for every model-authored
question — the lowest yield in the interview, though confounded by the canned
answers not responding to the question asked.

### Not a cause — `probe_focus`

Declared in the taxonomy for all six claim types, documented as steering the
policy, and **read by nothing in `api/`** (`grep` finds only its definition).
Inert, so it cannot have caused this. It is why the taxonomy's stated intent
never reaches the planner.

### Not a cause — taxonomy

`claim_type`, labels and weights are all correct for these two claims.

---

## 6. The one change

**Rewrite `PROBE_BRIEFS[ProbeLevel.VALIDATION]`** — one dict entry,
[`api/engine/question.py:74-78`](../api/engine/question.py#L74-L78).

```python
ProbeLevel.VALIDATION: (
    "VALIDATION — establish that the claim, and the number in it, are really "
    "theirs. Ask how that figure was arrived at: what was counted or measured, "
    "what it was before, over what period, and which part they did themselves. "
    "Do not state the figure — producing it is their job. This is the opening "
    "question about this claim."
),
```

### Measured, same two claims, nothing else changed

| | shipped brief | proposed brief |
|---|---|---|
| First-attempt rejects | 13/16 (81%) | 7/16 (44%) |
| **Fallbacks** | **5/16 (31%)** | **0/16 (0%)** |
| Questions asking how the figure was produced | 0/16 | **16/16** |

Before: *"How many team members were involved in the ReactJS and Redux project?"*
After: *"How did you measure the performance improvement and what was it before?"*
and *"How did you calculate the percentage increase in the customer base?"*

### Why this one

- It is the string that **authored** the weak questions. Fixing the component
  that caused the defect beats compensating for it downstream.
- It fixes all four contributing causes at once without touching any of them:
  fallbacks go to zero, so the fallback leak stops; rejects halve, so the
  validator's selection effect weakens; and the metric gets probed without the
  planner needing a `target_dimension`.
- **It is generator-side only.** `validate()` is untouched, so no `qpol_3` bump
  and no collision with counter-metric C7 (which forbids tuning
  `DUPLICATE_JACCARD` and the stopword lists during the Phase 3 study).
- One constant, one file, one owner (A). No `api/schemas.py` edit, no new module,
  no new abstraction.
- It is versioned automatically: `PROBE_BRIEFS` feeds `$probe_level_brief`, and
  D7 already stamps question-policy provenance on every evaluation.

### What it does not fix, and one cost

It does not fix `probe_focus` being inert, the planner's `target_dimension=None`
on the breadth phase, or the missing `answer_leakage` line in the base prompt.
That prompt line was measured separately and halves rejects on its own (88% →
44%) **without improving question content** — it is a good second change, not the
first one.

**The cost:** prompts are product, and Phase 3's study is mid-flight with 100
human-review items outstanding. Changing the generator changes the population
being measured, so M7h's 25.5% will not be comparable across this edit. C7
forbids tuning the *validator* to the test set; this changes the *generator* in
response to a validator rule that is public and unchanged, which is the intended
use of that measurement rather than a corruption of it. Worth stamping the
change against the outstanding sample either way — your call, not mine.

---

## Reproducing

```bash
# the trace these claims come from
DATABASE_URL="sqlite+aiosqlite:///./inspect.sqlite3" \
  python scripts/inspect_resume_pipeline.py \
    "resume_test/Abhishek-Singh-Resume-New.pdf" --fresh
```

The four ablations are scratchpad scripts, not repo files: `gap_hint_experiment.py`
(30 samples, probe_focus dimensions), `validation_dims.py` (24 samples,
VALIDATION-covered dimensions), `leak_source.py` (12 samples, figure withheld),
`brief_test.py` (32 samples, before/after on the brief). Each calls production
`generate_question()` and production `validate()` and changes exactly one input.

**Caveats.** One resume, two claims, one family, `n=16` per arm in the decisive
test. `temperature=0.4` and `cache=False`, so wording varies run to run — the
rates are stable across four runs, individual sentences are not. Both claims here
carry a bare percentage as their metric, which is the condition that makes
`answer_leakage` live; a claim whose metric is `50-member team` would behave
differently and was not tested.

---

# Addendum — extraction selection: prompt vs Python re-rank

Follow-up review of two proposed changes. Measured with production
`extract_claims()` and production `taxonomy`, only `PROMPT_DIR` moving; cache
cleared between every run. 30 extraction runs across four resumes and three
cohorts (`software_engineering`, `product`, `sales`).

**The extraction prompt changed on disk during this review** (hash `87100f0f6a67`
-> `9e19b40fca26`). Everything below treats the new one as current.

## 1. The premise: was extraction biased toward percentages?

Yes, under the old prompt — and it was also **unstable**. Three runs, old prompt:

| run | claims kept | includes the Twilio/API integration bullet? |
|---|---|---|
| 1 | 3 | no |
| 2 | 3 | yes, typed `delivery` (w 15) |
| 3 | 3 | yes, typed `delivery` (w 15) |

So the integration claim was not systematically excluded — it was surfaced
inconsistently, which is worse than either extreme because it cannot be
reasoned about.

## 2. The live prompt already fixes it

Same resume, prompt now on disk, three runs — **identical every time**:

```
[system_ownership  w=25] Integrated Twilio's SDK to enable SMS, voice and WhatsApp
                         communications, building a robust communication platform…
[performance_work  w=20] Optimized platform performance by 40% through architecting…
[delivery          w=15] Boosted storefront businesses' customer base by 45%…
```

The integration claim is now the **lead** claim at the family's heaviest type.
Stable 3/3, summed claim-type weight 60.

## 3. The proposed prompt measures worse than the one already shipped

| | live prompt | proposed prompt |
|---|---|---|
| Claims kept (3 runs) | 3, 3, 3 | 2, 2, 3 |
| Summed claim-type weight | 60, 60, 60 | 45, 45, 60 |
| Surfaced the Twilio claim | 3/3 | **0/3** |

The proposal names *"Integrated Twilio SDK for SMS, Voice and WhatsApp
communications"* as a worked example and then did not select that bullet in any
run. Its extra length appears to crowd the resume itself.

**The cohort-bias objection was not reproduced.** On a PM resume the proposed
prompt returned the same three claims as the live one — no drift toward the six
software-engineering examples. The concern stands only as recorded project
history (three templates once carried BPO-only examples and biased every other
cohort; A's contract forbids per-family examples for that reason), not as
anything measured here.

## 4. The Python re-rank cannot bite

`model_order -> classify_claim() -> weight_by_claim_type() -> sort -> dedup ->
truncate` is a **no-op on every run measured**, for two independent reasons.

### a. Nothing to truncate — extraction does not over-produce

| resume | `limit=3` | `limit=8` |
|---|---|---|
| Arshad (PM) | 3 returned | **3 returned** |
| Abhishek (SE) | 3 returned | **3 returned** |
| Astha (PM) | 3 returned | **2 returned** |

`$max_claims` does double duty — it is both *how many to propose* and *how many
to keep*. The model never proposed more than 3 even when asked for 8, so the
truncate step has nothing to discard and the sort has nothing to reorder.
Raising the ask does not raise the yield; Astha returned **fewer**.

### b. Nothing to reorder — model order is already weight-descending

Weights in model order across all six runs: `25,20,5` · `25,20,5` · `25,20,15` ·
`25,20,15` · `25,20,20` · `20,20`. **Descending in 6 of 6.**

### c. `classify_claim()` cannot carry the sort key

Run over all ten achievement bullets of the SE resume:

- **9 of 10** classify as `system_ownership`
- **5 of 10** match no taxonomy keyword at all, and `fallback_claim_type()`
  returns the family's **heaviest** type — so every unclassifiable claim sorts
  to the **top**
- the one bullet that is genuinely about API integration —
  *"Collaborated with backend teams and QA to integrate RESTful APIs"* — is
  typed `performance_work`, because the word `optimiz` appears in
  *"an optimized user experience"*

Sorting on this key gives a nine-way tie at 25.0 and actively demotes the
integration bullet. `normalise_claim_type()` (which keeps the model's label when
it is valid) is the only usable key — but then the model is still the selector,
and the sort is the no-op of (b).

### d. The proposed weight table needs a taxonomy expansion

| proposed | exists in `software_engineering`? |
|---|---|
| `system_ownership` 100 | yes, weight 25 |
| `performance_work` 80 | yes, weight 20 |
| `delivery` 75 | yes, weight 15 |
| `architecture` 95 | **no** |
| `integration_work` 90 | **no** |
| `leadership` 85 | **no** |
| `optimization` 70 | **no** |

Four of seven exist in no family. Adding them means editing
`data/claim_taxonomy.json` for nine families, re-tuning each to sum to 100, and
checking keyword collisions in both directions. `leadership` also overlaps the
existing `mentoring`.

And the taxonomy **already encodes the proposed tier order**:
`system_ownership 25 > performance_work 20 = reliability 20 > delivery 15 =
tech_depth 15 > mentoring 5`. A second weight table in Python would compete with
the one a PM is meant to retune in data without a deploy.

## 5. Where the diagnosis is right

The claim *"this means the model decides everything"* is correct, and one run
shows the cost. On the PM resume the model selected `stakeholder_alignment`
(**weight 5**) while `discovery` (20), `prioritisation` (15) and
`experimentation` (15) went unselected — the prompt asks it to honour importance
and it complied inconsistently. Two runs of the same resume also returned
different claim sets.

A sort cannot fix that: all three candidates were kept, so there was nothing to
sort away. **Deterministic selection requires over-production first** — the model
proposing every claim worth verifying and Python choosing among them. That is a
prompt change plus decoupling the two meanings of `$max_claims`, not a sort.

## 6. Recommendation

**Ship the prompt already on disk. Do not ship the Python re-rank.** It is a
no-op on 6 of 6 runs, its sort key is degenerate, and its weight table needs a
nine-family taxonomy edit to express an ordering the taxonomy already expresses.

If one more change is wanted before the demo, the binding constraint is not
ranking but **`MAX_CLAIMS=3` combined with dedup-by-type**: a ten-bullet resume
yields three claims and at most three claim types probed, which is why
`role_coverage` read **35** in the trace. Raising it is one environment variable
— but `MAX_QUESTIONS=12` is shared across claims, and five ladder levels × four
claims is 20, so depth per claim would be cut. That is a coverage-vs-depth
trade to make deliberately, not a bug to fix.
