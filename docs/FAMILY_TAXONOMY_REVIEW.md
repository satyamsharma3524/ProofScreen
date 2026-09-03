# Family Taxonomy Review

**Question:** can 10 families cover 95% of real resumes without creating
ambiguity?

**Answer: not the ten proposed — and the reason is measurable.** The proposed
set (Engineering, DevOps, IT, BPO, Sales, Operations, Product, QA, Security,
Data/AI) spends six of its ten slots on tech sub-disciplines that share a
vocabulary core, and two more on near-synonyms (BPO, Operations). It makes
classification *harder* than the current eight while covering *less* of the
actual resume flow.

The larger finding: **the fix is not a better classifier. It is to make the
classification decision matter less, and to take the answer from someone who
already knows it.**

---

## 1. Why the current eight work — measured, not asserted

Keyword collision across the current taxonomy (family keywords ∪ claim-type
keywords, which is what `family_vocabulary()` actually unions):

| Metric | Value |
|---|---|
| Total distinct terms | 313 |
| Terms appearing in 2+ families | **35 (11%)** |
| Worst pair collision | 6 shared terms (`sales ↔ data_analytics`, `bpo_operations ↔ banking_operations`) |
| `software_engineering` worst collision | **2 terms** (`python`, `spark`) |

Eleven percent ambiguity, and the most tech-heavy family is almost perfectly
separated. That is why `detect_family`'s naive max-hit-count works today: the
families are **cross-industry**, so their vocabularies barely touch.

But look at *which* terms are ambiguous — they are the common ones:

```
3x  audit · tat · team · forecast · retention · pipeline
2x  turnaround · engagement · feedback · attrition · sla · nps · queue · calibration
```

**The ambiguous terms are the frequent terms.** A raw hit count gives `team`
(appears on nearly every management resume) exactly the same weight as
`shrinkage` (appears on almost none). The algorithm is dominated by its least
discriminating inputs. That is the defect, and it is independent of how many
families exist.

## 2. What the proposed ten would do to that number

Six of the ten are tech sub-disciplines sharing an unavoidable core:
`deploy, incident, uptime, latency, CI/CD, monitoring, kubernetes, docker,
pipeline, automation, on-call, service, infrastructure, access, patch, test`.

| Pair | Shared vocabulary | Distinguishable by keywords? |
|---|---|---|
| Engineering ↔ DevOps | deploy, CI/CD, incident, uptime, latency, services, on-call | **No** — a backend engineer who carries a pager is an SRE by vocabulary |
| DevOps ↔ IT | infrastructure, servers, monitoring, uptime, tickets, access | **No** |
| DevOps ↔ Security | IAM, patching, hardening, compliance, vulnerability | Barely |
| Engineering ↔ QA | test, automation, coverage, regression, CI, defects | **No** — automation engineers write code |
| Engineering ↔ Data/AI | python, pipelines, SQL, deployment, models | Barely |
| BPO ↔ Operations | process, SLA, throughput, quality, escalation, team | **No** — "Operations" is a superset label for BPO |

Today's worst pair shares **6** terms out of ~50. Several of these pairs would
share **20–30**. Ambiguity moves from ~11% of terms to something in the 40%
range, and `max(keyword_hits)` degrades in proportion — while the *cost* of
being wrong stays the same.

## 3. The question that resolves this: how many **evidence models** do we need?

Family granularity should be set by **how many distinct sets of claim types and
fact keys exist**, not by how many job titles exist. Two families that would
share their evidence model should be one family.

Check the current `software_engineering` fact keys:
`p95_latency_ms, requests_per_second, uptime_pct, service_count,
deploy_frequency_per_week, incident_count`.

**That already is the DevOps/SRE evidence model.** Splitting Engineering from
DevOps buys a near-identical taxonomy entry and costs an unwinnable
classification decision.

Applying that test to the proposed ten:

| Proposed family | Distinct evidence model? | Verdict |
|---|---|---|
| Engineering | Yes | **Keep** |
| DevOps / SRE | No — same keys as Engineering | **Merge into Engineering** |
| IT | No — support + infra keys | **Merge** into Support / Engineering |
| QA | Partly — defect escape rate, coverage, automation % | Borderline; merge now, split when volume justifies |
| Security | Yes — vulns, MTTR, audit findings, frameworks | Keep, **later** |
| Data / AI | Yes — volume, freshness, model metrics, pipelines | **Keep** (exists) |
| Product | Yes — activation, retention, adoption, launches | **Keep**, genuinely missing today |
| Sales | Yes | **Keep** (exists) |
| BPO | Yes | **Keep** (exists) |
| Operations | No — a superset label over BPO | **Do not add** |

**Net: the proposed ten collapses to about six evidence models**, of which five
already exist. The single genuinely missing family is **Product**.

## 4. The coverage question is really "95% of which population?"

This determines the answer and should not be assumed.

| If the target is… | The right ten look like |
|---|---|
| **Tech hiring** (LinkedIn-shaped flow) | Engineering (incl. DevOps/SRE/QA), Data/AI, Security, Product, Design, IT/Support, Sales/CS, Marketing, Finance, HR |
| **Shine's actual traffic** (mass-market Indian portal, WhatsApp-first) | BPO/Support, Sales, Banking/Financial ops, Accounting/Finance, Admin/Back-office, Healthcare, Teaching/Education, Retail, Logistics/Supply chain, IT |

The proposed ten is the first list. The existing eight is closer to the second
— it already carries `banking_operations`, `customer_support` and
`hr_recruitment`, which the proposed ten drops. **On a mass-market Indian
portal, six tech families would over-split perhaps a third of the flow while
losing coverage of the majority of it.**

This is a product decision, not an engineering one, and it should be made
explicitly before anyone writes ten taxonomy entries.

## 5. Ambiguous titles — the ones that will actually break

Keyword collision is the measurable problem; job titles are the human one. These
resolve to two or more families no matter how good the classifier is:

| Title | Plausible families |
|---|---|
| Operations Manager | BPO · supply chain · DevOps · banking ops |
| Business Analyst | Data · banking ops · product |
| Analyst | Data · finance · banking · research |
| Consultant / Associate | Anything |
| Solution Architect | Engineering · pre-sales |
| Technical Account Manager | Sales · support · engineering |
| Product Support Engineer | Support · engineering · QA |
| Program / Project Manager | Product · operations · engineering |
| Site Reliability Engineer | Engineering · DevOps |
| Sales Engineer | Sales · engineering |

**No classifier resolves these from the title alone**, because the title is
genuinely ambiguous — the same title means different work at different
companies. Which leads to the real strategy.

## 6. Detection strategy — three sources, in order of reliability

The most important realisation: **family is already an optional input.**
`CandidateTextIn.job_family` exists (`None ⇒ detected from the resume`), so a
recruiter can pin it.

| Priority | Source | Reliability | When it applies |
|---|---|---|---|
| **1** | **The requisition** — the recruiter posting the job knows its family | Definitive | The entire primary hiring flow |
| **2** | **Ask the candidate** — one multiple-choice question over the existing WhatsApp channel, before the interview starts | Near-definitive | Bulk or unsolicited resumes |
| **3** | Keyword detection from resume text | Best-effort | Fallback only |

**In the real product, detection is the third-choice path, not the first.** A
recruiter running a requisition for "Support Team Lead" already knows the
family; asking the classifier to rediscover it from prose is solving a problem
we were handed the answer to.

And option 2 costs almost nothing: the product already has a question channel
and already sends an opt-in exchange. One question — *"Which best describes your
work: (a) customer support / BPO, (b) sales, (c) software engineering…"* —
resolves ambiguity definitively, in the candidate's own judgement, before a
single scoring decision depends on it. **No classifier improvement competes
with asking.**

## 7. Confidence scoring — margin, not count

When detection *is* used, replace `max(hits) >= 2` with three changes, all
computable at load time from the taxonomy itself and needing no new data:

1. **Weight terms by discriminating power.** A term in one family is worth more
   than a term in three. Inverse-family-frequency over the taxonomy corpus fixes
   the "`team` counts as much as `shrinkage`" defect directly.
2. **Score on margin, not absolute count.** Confidence is
   `(top1 − top2) / top1`. A resume hitting 8 engineering and 7 DevOps terms is
   *ambiguous*, not "engineering with 8 hits."
3. **Normalise by family vocabulary size.** A 59-term family currently
   out-scores a 44-term family on breadth alone.

Return `(family, confidence)`, not `family`.

## 8. Unknown-family fallback — three behaviours, not one

Today: below threshold ⇒ silently `general`. Silence is the problem — CLAUDE.md
already records that a wrong family collapses every weight downstream.

| Confidence | Behaviour |
|---|---|
| High | Proceed |
| **Ambiguous** (small margin between top two) | **Ask the candidate** (§6.2), or fall back to the **shared parent** if both candidates are in one evidence-model group — in which case the ambiguity is harmless by construction |
| Low everywhere | `general`, **flagged visibly** in the graph and to the recruiter: *"cohort not confidently identified — scores are computed on the general model"* |

The middle row is the design payoff from §3: **if Engineering and DevOps share
an evidence model, confusing them costs nothing.** Merging families does not
just simplify the taxonomy — it converts a whole class of misclassification into
a non-event. That is far more robust than any classifier.

## 9. Taxonomy versioning

Consistent with `PRODUCTION_READINESS.md` §1 and `PROOFSCREEN_DOMAIN_MODEL.md`
F6: cohorts need identity *and* version, because adding a fact key silently
changes what every historical score on that family means.

- Ship the taxonomy as versioned artifacts (`taxonomy_v7.json`), loaded at
  startup, hash recorded.
- Every evaluation stores `(cohort_key, taxonomy_version)`.
- **Additive changes** (new fact key, new claim type) are a minor version and do
  not invalidate history. **Weight or claim-type changes** are a major version:
  historical scores stay valid under their own version and are not comparable
  across a major bump.
- The generated fixture must be regenerated per taxonomy version, or it drifts
  from the rubrics — the failure mode the fixture exists to prevent.

## 10. The path from 10 → 20 → 50

The scaling axis is **not** more families. It is a second level.

```
Cohort         (evidence model)   ~6–12, must be unambiguous, code-adjacent
  └── Specialization (vocabulary)  unlimited, may overlap freely, config-only
```

A **Cohort** owns claim types, fact keys and dimension weights — the things that
change what a score *means*. A **Specialization** owns vocabulary only —
keywords for detection and domain-term credit — and may overlap other
specializations without consequence, because it changes no scoring semantics.

So "DevOps", "SRE", "Platform Engineer" and "Infrastructure Engineer" become
four specializations of one Engineering cohort: better question wording and
better vocabulary recognition, **zero** classification risk. Growth to 50 is
then 50 specializations over a stable handful of cohorts, and the onboarding
test still passes — one config entry, no Python.

| Stage | Cohorts | Specializations |
|---|---|---|
| Now | 8 (add Product ⇒ 9) | — |
| 20 | 9–10 (add Security, maybe QA) | ~20 |
| 50 | ~12 | ~50, freely overlapping |

---

## Recommendation

1. **Do not adopt the proposed ten.** It over-splits tech, adds `Operations` as
   a superset of BPO, and drops three families that match the actual market.
2. **Add exactly one family now: Product.** It is the only proposed family with
   a genuinely distinct evidence model that does not already exist.
3. **Decide the target population explicitly** (§4) before adding any others.
   The right ten for tech hiring and for Shine's traffic are different lists.
4. **Take the family from the requisition, and ask the candidate when unsure.**
   This is worth more than any classifier work and is nearly free.
5. **Then** fix detection: IDF weighting, margin-based confidence, visible
   low-confidence fallback (§7–8).
6. **Introduce specializations before adding cohorts** (§10), so growth costs
   vocabulary rather than classification risk.

**Demo impact:** none of 1–6 is needed for the demo, because the demo pins its
family. The single most valuable line of insurance is §6 — pass `job_family`
explicitly on every demo call, and family detection cannot embarrass you on
stage at all.
