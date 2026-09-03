# ProofScreen as a Multi-Cohort Verification Platform — Architecture Review

Scope: the whole verification engine, not the transfer probe. Question: what
survives at 100 job cohorts, and what quietly breaks. Grounded in the code as it
stands, not in the seeded personas.

---

## The governing frame: three layers

Every subsystem belongs in exactly one of these. Every architectural problem
found below is a **Layer 2 concern implemented in Layer 1 code**.

| Layer | Contains | Varies by cohort? | Lives in |
|---|---|---|---|
| **L1 — Universal reasoning** | the dimension model, probe protocol, rubric *shape*, scoring algebra, consistency algebra | **Never** | Python |
| **L2 — Domain vocabulary** | claim types, fact keys, keywords, dimension weights | **Per cohort** | `data/claim_taxonomy.json` |
| **L3 — Hiring priorities** | role weight profiles | **Per recruiter** | DB (`job_roles`) |

The healthiest thing in this codebase is that L2 and L3 already exist as real
extension points and **no engine module branches on family** — every module
calls a `taxonomy.*` accessor. The design is already most of the way to
multi-cohort. The failures are specific and enumerable.

**One property worth protecting deliberately:** `family_vocabulary()`
(`taxonomy.py:225-231`) is *derived* from the family's own keywords plus its
claim-type keywords — there is no separately curated vocabulary list. So one
keyword list per cohort powers family detection, claim classification, **and**
the PROCESS rubric's domain-term credit. **Onboarding a cohort is one config
entry, not four.** That is a genuinely good decision and should not be
regressed.

---

## Subsystem review

### 1. Claim extraction — *domain-agnostic, with a config-driven classifier*

**A. At 100 cohorts:** works. **B. New cohort:** config only. **C. Bias:** none
material. **D. Boundary:** correct.

The LLM path injects the family menu from taxonomy. The heuristic path
(`extract._score_line`, `extract.py:77-101`) scores *resume structure*, not
domain content: digits, `%`, strong verbs, minus fluff, with parenthesised-year
headings and comma-heavy skills lists excluded. `_STRONG_VERBS`
(`extract.py:33-42`) spans domains honestly — `led, built, migrated, shipped,
negotiated, onboarded, resolved, closed`. `_FLUFF` is universal resume filler.

Claim *typing* goes through `taxonomy.normalise_claim_type`, which trusts the
model only if the key exists in that family and otherwise falls back to
keyword classification. **This is the correct boundary**: the model proposes,
config validates.

### 2. Family detection — **architecturally dangerous at scale**

**A. At 100 cohorts:** degrades badly. **B.** config only. **C.** structural,
not BPO-specific. **D.** boundary is right, algorithm is not.

`detect_family` (`taxonomy.py:171-180`) takes `max()` over raw keyword hit
counts with a flat `>= 2` threshold. With 8 curated, well-separated families
this works. At 100 cohorts:

- **Keyword collision compounds.** "pipeline" hits sales, data engineering and
  DevOps. "risk" hits banking, finance and compliance. "operations" hits BPO,
  supply chain and DevOps. Raw hit count has no notion of a term's
  discriminating power.
- **A flat threshold of 2 does not scale** across cohorts whose keyword lists
  differ in size — a 40-keyword cohort outscores a 12-keyword cohort on
  vocabulary volume alone.
- **The failure is silent and expensive.** CLAUDE.md already records this:
  a BPO resume misdetected as `customer_support` has no `team_handling` claim
  type, so the weights collapse and every downstream number is quietly wrong.
  `tests/conftest.py` pins the family with BPO vocabulary specifically because
  of this fragility.

**Correct boundary:** detection should stay config-driven but become
**discrimination-weighted** (a term's value inversely proportional to how many
cohorts use it — IDF over the cohort corpus, computable at load time from the
taxonomy itself, no new data) and should **return a confidence**, with
low-confidence resumes falling to `general` or to an explicit
"family unresolved" state rather than silently picking a wrong winner.

This is the **single highest-priority platform issue in the codebase.**

### 3. Evidence extraction — **the LLM path is safe; the heuristic path is Layer 2 in Layer 1**

**A. At 100 cohorts:** LLM path fine, heuristic path degrades. **B.** heuristic
path needs **code changes**. **C.** yes, real. **D.** violated.

The LLM path injects `fact_key_menu` from taxonomy — correct. The heuristic
fallback (`evidence.py:93-135`) carries **seven global, hardcoded word lists**:
`_TOOL_VOCAB` (≈40 named products), `_INCIDENT_MARKERS`, `_CAUSAL_MARKERS`,
`_OUTCOME_MARKERS`, `_STEP_MARKERS`, `_USAGE_MARKERS`, `_MEASURE_MARKERS`.

- `_CAUSAL_MARKERS`, `_OUTCOME_MARKERS`, `_STEP_MARKERS` are **linguistic**, not
  domain — "because", "resulted in", "dropped", "then", "first". These are L1
  and belong in code. Safe forever.
- `_TOOL_VOCAB` and `_INCIDENT_MARKERS` are **domain vocabulary in code**.
  Cohort 100's tools are not in a 40-item list, and adding them is a Python
  edit. This is the clearest L2-in-L1 violation in the system.

**Correct boundary:** linguistic markers stay in code; tool and
domain-situation vocabulary moves to the taxonomy, where it can be derived from
existing keyword lists the way `family_vocabulary` already is. Mitigating
factor: this is the *fallback* path only — but fallback is what runs with no API
key, which is fixture mode, which is the demo's safety net.

### 4. The six dimensions — **three universal, one mis-detected, two role-shaped**

**A. At 100 cohorts:** partially. **B.** weights are config; **the set is code**.
**C.** yes, structural. **D.** the most important boundary question in the product.

| Dimension | Universal? | Assessment |
|---|---|---|
| `SPECIFICITY` | **Yes** | Concrete detail exists in every kind of work |
| `PROCESS` | **Yes** | "How did the work actually happen" transfers everywhere |
| `CAUSAL_REASONING` | **Yes** | Problem → action → result is domain-free |
| `AUTHENTICITY` | Yes in concept, **biased in detection** | See §7 |
| `METRIC_OWNERSHIP` | **No** | Assumes the role owns a named metric |
| `TOOL_FAMILIARITY` | **No** | Assumes instrumented, tooled work |

Dimension *weights* are per-family config, and a family can down-weight a
dimension — but weights are renormalised over all six, so a dimension that is
*meaningless* for a cohort still occupies conceptual space and still reports as
"probed / not probed" to the recruiter.

**This is the strongest argument for the dimension re-map I deferred** — and it
is a better argument than the original brief made. `ownership` (did they
personally do it) and `scenario_transfer` (does the reasoning move) are
**structurally more universal** than `METRIC_OWNERSHIP` and `TOOL_FAMILIARITY`,
because they describe the candidate's relationship to the work rather than the
work's instrumentation. The demo-timeline reason to postpone stands; the
platform reason to eventually do it is now much stronger than "the spec says
six."

**Correct boundary:** the dimension *set* is L1 and should stay code — a
per-cohort dimension set would make cross-cohort ranking meaningless, which is
the product. The fix is to choose six that are actually universal, not to make
the set configurable.

### 5. Scoring — *domain-agnostic; two gates carry a hidden assumption*

**A.** works. **B.** config only. **C.** yes, in the gates. **D.** nearly correct.

`scoring.py` is pure arithmetic over weights — no domain content, no LLM, and
weights arrive from taxonomy or a role profile. **Safe forever.**

The domain sensitivity is one layer up, in `signals.GATES` (`signals.py:70-77`).
A gate encodes "this dimension is meaningless without ingredient X":
`SPECIFICITY` caps at 55 without a quantity; `METRIC_OWNERSHIP` at 45 without a
definition; `TOOL_FAMILIARITY` at 40 without described usage. Those are **not
equally true across cohorts.** Quantity-poor but genuinely skilled work
(early-stage product, qualitative research, design, some compliance roles)
hits the SPECIFICITY gate structurally.

**Correct boundary:** gate *existence* is L1; gate *thresholds* are arguably L2
and would sit naturally beside the per-family `dimension_weights` that already
exist. Not urgent — but it is the mechanism by which a new cohort will first
look "wrong" to a recruiter.

### 6. Adaptive questioning — *domain-agnostic, safe forever*

**A.** works. **B.** config only (`probe_focus` per claim type already exists).
**C.** none. **D.** exemplary.

`plan_next` is a pure function over claim weights and dimension gaps.
`PROBE_LEVEL_DIMENSIONS` and `PROBE_ORDER` describe an interview protocol, not
an industry. `PROBE_BRIEFS` and `GAP_HINTS` are wording guidance; the prompt
template interpolates `$probe_level_brief` and `$family_label` and hardcodes no
family. Claim types already carry `probe_focus` in config.

**This subsystem is the reference implementation** for how the rest should look:
policy in code, vocabulary in config, wording in the model.

### 7. Authenticity / incident detection — **domain-biased, dangerous because of its gate**

**A.** degrades. **B.** **code changes.** **C.** yes, clearly. **D.** violated.

`_INCIDENT_MARKERS` (`evidence.py:110-115`) anchors on service-industry time:
`"before month-end"`, `"month end"`, `"during peak"`, `"on a saturday"`,
`"shift"`, `"our vp"`, `"a client"`. Absent: `"during the incident"`,
`"at 3am"`, `"on-call"`, `"the postmortem"`, `"before the release"`,
`"at the sprint review"`, `"during the audit window"`, `"at quarter close"`,
`"before go-live"`.

AUTHENTICITY carries the **harshest gate in the system** — capped at 40 without
a specific incident. So an SRE describing a 3am page, or a PM describing the
week before a launch, can produce genuinely specific recall and be scored as
though they produced none. On the LLM path this is fine; on the heuristic path
it is a systematic, silent penalty against every non-service cohort.

**Correct boundary:** generic temporal/episodic markers belong in code
(`"one day"`, `"I remember"`, `"there was a time"`, `"that week"`); cohort-specific
anchors belong in taxonomy, derivable from existing keywords.

### 8. Metric ownership — **structurally biased, and it is a dimension, not a detail**

**A.** works mechanically, misjudges systematically. **B.** config (fact keys)
+ **code** (the dimension itself). **C.** yes. **D.** violated at the dimension
level, not the config level.

Fact keys are properly per-family (`p95_latency_ms`, `quota_attainment_pct`,
`aht_seconds`) — that part is exemplary. The problem is upstream: the dimension
presumes the candidate *owns a metric at all*. IC engineers, designers,
researchers, junior PMs and many compliance roles own outcomes and judgement,
not a KPI. They are capped at 45 on one sixth of the score for a property of
their role, not their competence.

This is the same class of error the product was explicitly built to avoid — it
just happens to be role bias rather than linguistic bias. Worth naming plainly,
because the product's own anti-bias argument is what makes it credible.

### 9. Consistency checking — *domain-agnostic, one of the best-designed parts*

**A.** works. **B.** config only. **C.** none found. **D.** correct.

The stable/variable distinction lives in per-family fact-key config
(`"stability": "variable"`), the algebra is pure arithmetic on two numbers, and
thresholds (10% / 50%) are properties of human numerical recall, not of any
industry. `delta_pct` normalises against the larger magnitude so severity does
not depend on answer order.

Only latent risk at scale: `global_fact_keys` plus 100 cohort-specific key sets
means the same real-world quantity could be keyed differently in two cohorts
(`team_size` vs `headcount`), so a cross-cohort candidate could contradict
themselves invisibly. Not a problem within one session, which is all consistency
scopes today.

### 10. Recruiter explanations — *domain-agnostic, safe forever*

**A.** works. **B.** config only. **C.** none. **D.** correct.

The `basis` strings are generated from **counts of extracted signals**
(`"6 quantities, 5 named entities"`, `"capped at 55: no quantity given"`) — the
sentence structure is domain-free and the nouns come from the signal types,
which are universal. Quotes are the candidate's own words. Nothing in the
explanation path knows what industry it is in. This scales to 100 cohorts
unchanged, and it is why the recruiter drill-down needed no work.

### 11. Ranking — *domain-agnostic, safe forever*

**A.** works. **B.** config/DB only. **C.** none. **D.** correct.

`weighted_evidence_score` renormalises over the claim types a candidate actually
made and reports `role_coverage` separately; weights come from L3 role profiles
or L2 family defaults. Re-ranking is arithmetic over stored rows. Adding a
cohort adds a family's default weights; recruiters add role profiles at runtime.

Latent scale issue, not a bias: comparing candidates **across** cohorts assumes
scores are calibrated between families, which nothing currently guarantees —
different gate/weight profiles could make an "80" in one cohort easier than in
another. Within-cohort ranking, which is the actual use case, is unaffected.

---

## Classification

**1. Domain-agnostic — safe forever**
Adaptive questioning · scoring arithmetic · consistency algebra · recruiter
explanations · ranking · claim extraction (structure heuristics) · the
linguistic marker lists (`_CAUSAL_MARKERS`, `_OUTCOME_MARKERS`, `_STEP_MARKERS`)

**2. Domain-biased but configurable — safe with config discipline**
Claim types & weights · fact keys & stability · dimension weights ·
`probe_focus` · family keywords (and the vocabulary derived from them) ·
role profiles

**3. Domain-biased and architecturally dangerous**

| Rank | Issue | Why it is dangerous |
|---|---|---|
| **1** | `detect_family` — max-keyword-count with a flat threshold | Silent misclassification collapses every downstream weight; collision compounds with each cohort; already documented as fragile |
| **2** | `METRIC_OWNERSHIP` and `TOOL_FAMILIARITY` as two of six universal dimensions | Bakes an assumption about *instrumented work* into the one thing that cannot vary per cohort |
| **3** | `_INCIDENT_MARKERS` gating AUTHENTICITY at 40 | Domain vocabulary in code, feeding the harshest gate, penalising every non-service cohort on the fallback path |
| **4** | `_TOOL_VOCAB` as a 40-item hardcoded list | Every new cohort's tooling is a Python edit |
| **5** | `signals.GATES` thresholds as universal constants | The mechanism by which a new cohort first looks "wrong" |

---

## The architectural rule this review produces

> **Vocabulary is configuration. Reasoning is code. A subsystem that needs new
> words to serve a new cohort has put configuration in the wrong layer.**

Applied as an onboarding test: *adding cohort #101 should require exactly one
taxonomy entry and zero Python edits.* Today that is true for claim extraction,
questioning, consistency, scoring, explanation and ranking — and false for
evidence extraction's fallback vocabulary, incident detection, and (in effect)
the two role-shaped dimensions.

Order of repair, by platform value rather than demo value: **family detection
first** (silent and compounding), **the dimension set second** (it is the only
one that cannot be fixed later without re-scoring history), then the vocabulary
lists, then gate thresholds. None of this blocks the demo; all of it blocks
cohort ten.

---

# Appendix — Complete cohort-onboarding inventory

Method: AST pass over every module-level string collection in `api/` (every
tuple, list, set, frozenset and dict with ≥3 string members), plus a read of all
three prompt templates. This is an enumeration, not a sample.

**The test:** *launching engineering, product, banking, sales, operations,
finance and support simultaneously should require seven taxonomy entries and
zero Python edits.* Below is everything that fails that test today.

## Tier 1 — affects the PRIMARY (LLM) path

These bias every cohort in production, not just the offline fallback. Both were
missed by the subsystem review above.

| # | Location | What is hardcoded | Why it matters |
|---|---|---|---|
| **1** | `prompts/extract_claims.txt:23`, `extract_signals.txt:25,27,44`, `generate_question.txt:27` | The only worked examples in all three prompts are BPO: `"CSAT 78% -> 92%"`, `refers_to = "CSAT", "team size"`, `"reviewed call…"`, `"Three agents resigned…"`, `"what is the formula for CSAT?"` | **Few-shot anchors steer extraction.** A software-engineering resume is processed by a prompt whose every example is a call centre, so the model is nudged toward metric-and-team framing for cohorts where that framing does not fit. This is the single largest cross-cohort bias in the system, and it sits on the path that actually runs in production |
| **2** | `routers/dev.py` `PLACEHOLDER_ANSWERS` (6 entries) | Six full BPO answers — agents, pods, Genesys, AHT, escalations, CSAT | `/api/dev/simulate` is documented in the README as *"one command that proves the whole pipeline."* Simulate an engineering resume and the pipeline scores it against call-centre answers. The demo path is cohort-locked |

**Boundary for both:** prompt templates already interpolate `$family_label` and
`$fact_key_menu`; examples belong in the same slot, rendered per family from
taxonomy. `PLACEHOLDER_ANSWERS` belongs beside the family config, or the
endpoint should require caller-supplied answers.

## Tier 2 — affects the fallback path only

Runs when `OPENAI_API_KEY` is empty — which is fixture mode, the demo's safety
net.

| # | Location | Size | Verdict |
|---|---|---|---|
| **3** | `evidence._TOOL_VOCAB` | 45 named products | Domain vocabulary in code. Broad for tech and support, absent for finance, supply chain, marketing. Every new cohort's tooling is a Python edit |
| **4** | `evidence._INCIDENT_MARKERS` | 21 | Service-industry time anchors feeding the harshest gate (AUTHENTICITY, cap 40). Detailed in §7 |
| **5** | `evidence._MEASURE_MARKERS` | 12 | Mostly universal measurement language; `"survey"` is CSAT-flavoured. Low severity |
| **6** | `evidence._USAGE_MARKERS` | 17 | Mixed ops/tech verbs (`pulled`, `logged`, `configured`, `queried`, `dashboard`). Reasonable coverage, thin for non-desk roles |

## Tier 3 — correctly in code, universal, leave alone

Verified rather than assumed. Reporting these as bias would be wrong.

`_CAUSAL_MARKERS` (linguistic) · `_OUTCOME_MARKERS` (metric-movement verbs,
cross-domain) · `_STEP_MARKERS` (sequence language) · `_NON_ANSWERS` (evasion) ·
`extract._STRONG_VERBS` (43 achievement verbs spanning engineering, sales and
ops) · `extract._FLUFF` (universal resume filler) · `scoring._STOPWORDS`
(English) · `stt._EXTENSIONS`, `parse.SUPPORTED` (file formats)

## Tier 4 — structural, not vocabulary

Cannot be fixed by moving words into config.

| # | Item | Requires code for a new cohort? |
|---|---|---|
| **7** | `Dimension` — `METRIC_OWNERSHIP`, `TOOL_FAMILIARITY` | Yes, and *should* stay code — the fix is choosing six universal dimensions, not making the set configurable (§4) |
| **8** | `signals.GATES` / `signals.TARGETS` | Yes. Thresholds are arguably L2 and would sit naturally beside per-family `dimension_weights` |
| **9** | `taxonomy.detect_family` algorithm | No new code per cohort — but the algorithm degrades with cohort count (§2). The top platform issue |
| **10** | `evidence._UNIT` regex | **No.** Checked: the unit is *optional* in `_QTY`, so `120bps` still registers as the quantity `120`. Only the captured display string is affected, not detection. Cosmetic |

## Scorecard

| Subsystem | Cohort onboarding cost today |
|---|---|
| Claim extraction (typing, weights) | **Taxonomy only** ✅ |
| Adaptive questioning | **Taxonomy only** ✅ |
| Consistency | **Taxonomy only** ✅ |
| Scoring arithmetic | **Taxonomy only** ✅ |
| Recruiter explanations | **Nothing** ✅ |
| Ranking | **Taxonomy + role profile** ✅ |
| Evidence extraction — LLM path | **Code** ❌ (prompt examples) |
| Evidence extraction — fallback | **Code** ❌ (tools, incident markers) |
| Dev/simulate path | **Code** ❌ (placeholder answers) |
| Dimensions & gates | **Code** ❌ (structural) |
| Family detection | Taxonomy, but algorithm degrades ⚠️ |

**Six of eleven already pass.** The three vocabulary failures are mechanical
(move words into the taxonomy where `family_vocabulary` already proves the
pattern). The two structural ones are genuine architecture decisions, not
cleanup.
