# ProofScreen — Evaluation Architecture Principles

System-level constraints for the evaluation engine. Not implementation details.
These exist to keep the platform extensible across job families, explainable to
customers, and resilient as cohorts are added.

**Two rules in the source draft are already violated by the code, silently.**
Both are documented in Part III with evidence.

---

# Core Philosophy

ProofScreen is not a resume parser.

ProofScreen is an evidence verification engine.

The objective is not:

    "What does this person claim?"

The objective is:

    "Can this person provide evidence for what they claim?"

Everything in the architecture reinforces that principle.

---

# Part I — Inviolable

These five are not trade-offs. They were absent from the draft, and they
outrank everything in Part II: a principles document that ranks "optimize for
re-ranking" above "the model never produces a score" has inverted the product's
own priorities. Each is already enforced in code, most by structural tests.

## Rule 0: The model never produces a score

The LLM returns **countable signals**, quoted verbatim. Python turns counts into
numbers. If you find yourself parsing a rating, confidence or percentage out of
a model response, stop.

Enforced by `test_scoring_modules_never_import_the_llm` and
`test_answer_signals_carries_no_score_field` — structurally, not by convention.

This is the answer to *"isn't the score just the AI's opinion?"*, and it is the
reason the product is defensible at all.

## Rule 1: Quotes are verified in Python, never requested in a prompt

`evidence.enforce_verbatim()` drops any signal whose quote is not literally
present in the answer. A paraphrase is exactly the hallucination this product
exists to eliminate. Asking the model to "only quote verbatim" is not a control;
checking is.

## Rule 2: Never score presentation

No accent, fluency, grammar, vocabulary sophistication, speaking speed,
polish, or perceived confidence — anywhere, ever. In India these track region,
first language and schooling far more than competence.

This is a product decision, not an oversight, and it is load-bearing for the
product's credibility. A candidate answering in simple English, Hindi or
Hinglish must be able to score at the top.

## Rule 3: Every model call has a deterministic fallback

`complete_json(..., fallback=...)` is always given one. The heuristic paths
(`extract.heuristic_claims`, `question.FALLBACK_QUESTIONS`,
`evidence.heuristic_signals`) are **production code, not stubs** — they are what
runs when the model is down.

They are deliberately more conservative than real extraction. **If a fallback
ever looks better than the model path, the fallback has become the product.**

## Rule 4: Un-probed is not the same as zero-earned

A dimension nobody asked about contributes 0 **and reports `probed: false`**.
This is a confidence score: thin questioning must show as low confidence, not as
a low candidate. `role_coverage` stays separate from the score for the same
reason — *"evidenced it badly"* and *"never claimed it"* are different facts and
a recruiter needs both.

---

# Part II — Architectural

## Rule 5: Deterministic components first

LLMs are reserved for tasks requiring semantic reasoning. Everything else is
deterministic.

    Family Detection      → Deterministic      ⚠ violated, see V2
    Taxonomy Resolution   → Deterministic      ✅
    Weights               → Deterministic      ✅
    Scoring               → Deterministic      ✅
    Ranking               → Deterministic      ✅

    Claim Extraction      → LLM (+ fallback)   ✅
    Question Wording      → LLM (+ fallback)   ✅

Note the last line: **question *selection* is deterministic; only the wording is
generative.** `plan_next()` picks the claim, the probe level and the target
dimension as a pure function; the model only phrases it. Never let selection
drift into a prompt.

## Rule 6: Family detection is routing, not judgement

Family detection determines which taxonomy applies, which claim categories
matter, and which probes can be asked.

    Router — not Judge.

**Correction to the draft:** the draft states family "should never directly
influence score." That is not achievable and not true today — family selects the
claim weights, the dimension weights, the fact-key vocabulary and the PROCESS
rubric's domain-term credit. All of those are score inputs.

The achievable version of the rule:

> Family determines **interpretation**, never **evidence collection quality**.
> A misrouted candidate must still have their evidence captured correctly, so
> that re-routing them later re-scores from stored signals with no
> re-interviewing.

That is testable, honest, and preserves the intent.

## Rule 7: Family detection must be explainable without a model call

Bad:

    "The model selected DevOps."

Good:

    Matched: kubernetes, terraform, ci/cd, on-call, uptime
    →  engineering 0.92 · it_support 0.41 · data 0.08
    Family = engineering (margin 0.51)

Confidence must be **margin-based**, not hit-count-based: 8 hits for one family
and 7 for another is *ambiguous*, not confident. Terms must be weighted by
discriminating power — `team` appears on nearly every management resume and
must not count as much as `shrinkage`.

## Rule 8: Family count follows evidence models, not job titles

**Correction to the draft.** The draft's recommended list contradicts its own
Rule 9 (below):

| Draft entry | Problem |
|---|---|
| Software Engineering **and** Backend Engineering | One contains the other. A backend engineer matches both by definition — unresolvable by any classifier, human or model |
| Sales **and** CASA Sales | Same containment problem |
| Engineering Management | An EM resume is a senior engineer resume plus people claims |
| Operations | A superset label over BPO |
| IT Support **and** Customer Support/BPO | Overlap on ticketing, SLA, escalation |

Four of ten entries are not mutually exclusive, while the stated goal is 95%
routing accuracy. That target is unreachable against categories a human cannot
separate.

**The rule:** two families that would share their claim types and fact keys
should be one family. The current `software_engineering` taxonomy already stores
`uptime_pct`, `deploy_frequency_per_week`, `incident_count`, `service_count` —
**that already is the DevOps evidence model.**

Growth happens on a second axis instead:

    Cohort          (evidence model)   ~6-12, must be unambiguous
      └── Specialization (vocabulary)  unlimited, may overlap freely

"DevOps", "SRE" and "Platform Engineer" become specializations of one
Engineering cohort: better wording and vocabulary recognition, **zero**
classification risk. See `FAMILY_TAXONOMY_REVIEW.md`.

## Rule 9: Claims are more stable than families

Families change. Evidence patterns change far less.

    Backend Engineer     built APIs · improved performance · reduced latency
    DevOps Engineer      built deploy systems · improved performance · reduced latency

The overlap is the point. Architecture should trend toward:

    Resume → Claims → Evidence → Role Lens → Evaluation

rather than `Resume → Family → Everything`.

## Rule 10: Apply the role lens late

Same evidence, different interpretation, no re-interviewing.

**Status: half-built, and the missing half is a silent no-op — see V1.** Claim
weights are applied late and work correctly. Dimension weights are not applied
at all.

## Rule 11: Evidence is the product

    Claim     "Improved system performance"
    Evidence  "Reduced latency from 1.2s to 300ms"

    Claim     "Led team"
    Evidence  "Managed 12 engineers"

Optimize for collecting evidence, not for collecting claims. A probe that
produces no new signals is a wasted question — which is why the adaptive stop
exists, and why a stalled claim earns a transfer probe rather than being
abandoned.

## Rule 12: Every score is traceable without another model call

    Evaluation → Dimension → Evidence → Quote

No opaque scores. No hidden reasoning. No unexplained ranking.

Corollary: any future capability that cannot meet this bar — an embedding
similarity score, a learned ranker — is a **different product surface** and must
be labelled as such in the UI, never blended into the competence score.

## Rule 13: Version everything that influences an evaluation

Taxonomies, prompts, rubrics, scoring logic, feature flags — stored on the
evaluation record.

**Prompts are product, not implementation.** Proven empirically in this
codebase: three prompt templates carried BPO-only worked examples and biased
extraction for every other cohort on the primary path. A prompt edit can move
scores as much as a rubric change.

---

# Part III — Known violations

Rules the code currently breaks. Both were found by checking rather than
assuming, and both are invisible in normal operation.

## V1 — Role dimension weights are fetched and discarded

`graph.py:212`:

```python
claim_weights, _dim_weights, role_ref = await resolve_weights(...)
```

`resolve_weights()` reads `dimension_weights` from the role profile
(`graph.py:136`) and returns them. `build_candidate_graph` binds them to
`_dim_weights` and **never uses them**. Only `claim_weights` reaches
`weighted_evidence_score` (`graph.py:326`, `graph.py:477`).

**Consequence:** Rule 10's own example does not work. A "Backend Lens" that
weights technical depth high and a "DevOps Lens" that weights incident handling
high produce **identical dimension scores**, because dimension weights were
baked in at claim-scoring time under family defaults and are never re-applied.

Worse, it is silent: `RoleWeightsIn` accepts `dimension_weights`, the API stores
them, `RoleOut` returns them — a recruiter can set them, see them persisted, and
observe no effect on any ranking.

**Fix:** re-run `scoring.claim_score()` over stored dimension scores using the
lens's dimension weights at graph-assembly time. The stored data already
supports it; this is arithmetic over rows we have.

## V2 — The model can override the deterministic family

`extract.py:196-199`:

```python
# If the model picked a different family, honour it only if it is real.
family = resolve_family(result.job_family) if result.job_family else guessed
```

The deterministic detector runs first, then the LLM may override it, with
`resolve_family` validating only that the returned key *exists*.

**Consequence:** family selection is non-deterministic, violating Rule 5, and
"why was this family selected?" cannot be answered without reference to a model
call, violating Rule 7. Two runs over the same resume can route to two cohorts
and produce two different scores.

**Fix options, in order of preference:** (a) take the family from the
requisition, which the recruiter already knows and `CandidateTextIn.job_family`
already accepts; (b) let the model *propose* and accept only when the
deterministic detector is below its confidence margin, recording which source
won; (c) ignore the model's family entirely.

## V3 — Rule 6 as originally drafted is unsatisfiable

Stated for completeness: "family detection should never directly influence
score" cannot hold while family determines weights, fact keys and vocabulary
credit. Restated in Rule 6 above as interpretation-vs-collection.

---

# Non-Goals

Do not optimize for:

- 100 job families
- AI-generated scoring logic
- End-to-end LLM pipelines
- Hidden reasoning
- Family-specific prompt engineering or `if family == …` in engine code

**The platform scales by adding taxonomy entries, not code paths.**

Success criterion:

    Adding a new cohort requires
      1. a taxonomy entry
      2. a weight definition
    and nothing else.

Anything that fails this test is technical debt, by definition.

---

# Changes from the source draft

| # | Change | Reason |
|---|---|---|
| 1 | Added Part I (Rules 0–4) | Model-never-scores, verbatim-in-Python, never-score-presentation, always-fallback and un-probed≠zero were absent. They are the product's non-negotiables and outrank everything in Part II |
| 2 | Restated "family never influences score" | Unsatisfiable as written; replaced with interpretation-vs-collection, which is testable |
| 3 | Replaced the ten-family list | Four of ten entries are not mutually exclusive (Software vs Backend Engineering; Sales vs CASA Sales), contradicting the draft's own Rule 9 and making 95% routing accuracy unreachable |
| 4 | Added the Cohort / Specialization split | Gives the 10→50 growth path without adding classification risk |
| 5 | Added Part III | Two rules are already violated in code, silently. A principles doc that does not say so is aspirational rather than binding |
| 6 | Sharpened Rule 5 to name question *selection* vs *wording* | The most important deterministic boundary in the system, and the easiest to erode |
