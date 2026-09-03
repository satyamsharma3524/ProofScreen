# Phase 1 Success Metrics

Phase 1 ships when the **metrics** move, not when the tickets close. Every
metric below is computed from stored rows by `scripts/validation_report.py`,
with **zero model calls**.

Read the two counter-metrics (§C) before optimising anything.

---

## M1 — Transfer probe reach and completion

Split into two, because the failure mode is **reach**, not completion. The
adaptive stop drops a claim after two answers with no signals — so without the
stall exemption, transfer probes land on candidates who are already proving
themselves and never on the ones we are unsure about.

| | Definition | Source | Target |
|---|---|---|---|
| **M1a Reach** | % of completed sessions containing ≥1 `TRANSFER` question | `questions.probe_level = 'TRANSFER'` per session | **≥ 80%** |
| **M1b Reach on stalled claims** | % of stalled claims that received a transfer probe before being dropped | claims where `answers ≥ 2` and last `signals_found = 0` | **100%** — this is a correctness invariant, not a target |
| **M1c Completion** | % of transfer questions receiving a substantive answer | `responses` joined on those questions, minus `evidence.is_non_answer()` | **≥ 70%** |

**M1b is the one to watch.** If it is below 100%, the probe is not reaching the
population it exists for and every other transfer metric is measuring the wrong
candidates.

## M2 — Marginal evidence from the transfer probe

**Corrected from "+20% evidence".** Raw evidence volume is the wrong target: a
fabricator *should* produce near-zero signals on a transfer probe. That is the
probe working. Optimising for volume would reward the probe for making everyone
look better, which inverts its purpose.

What matters is **marginal contribution** and **separation**.

| | Definition | Source | Target |
|---|---|---|---|
| **M2a Marginal signals** | Median increase in a claim's deduplicated signal count when its transfer answer is included vs excluded | `signals.merge_signals()` over the claim's answers, with and without the TRANSFER response | **≥ +15%** |
| **M2b Separation** | Ratio of mean transfer-answer `signals_found` for top-tercile vs bottom-tercile candidates by competence score | `responses.signals_found` on TRANSFER rows | **≥ 2.0×** |

M2b is the real success measure of the transfer probe. A probe that produces
equal evidence from strong and weak candidates adds cost and no signal, whatever
its absolute volume.

## M3 — Score separation

**Corrected from "non-zero".** Any noise satisfies non-zero. A scoring system
that cannot separate candidates is useless even when it is correct.

| | Definition | Source | Target |
|---|---|---|---|
| **M3a Spread** | Interquartile range of `competence_score` across evaluated candidates | `profiles.competence_score` | **≥ 20 points** |
| **M3b Tie rate** | % of candidate pairs within 3 points of each other | same | **< 15%** |
| **M3c Divergence from resume** | % of candidates whose competence rank differs from their resume rank by ≥ 2 positions | `resume_score` vs `competence_score` | **≥ 40%** — if the two rankings agree, the product has no reason to exist |

## M4 — Signal quality vs resume screening ★

**The metric Phase 1 exists to produce.** All others are inputs to this one.

| | Definition | Source | Target |
|---|---|---|---|
| **M4a Correlation** | Spearman rank correlation between score and recruiter decision (`rejected < shortlisted < interviewed < offered < hired`), computed for `competence_score` and `resume_score` | `candidate_outcomes` ⋈ `profiles` | **competence > resume**, with a margin ≥ 0.15 |
| **M4b Precision@5** | Of the top 5 by each score, how many were shortlisted or better | same | **competence > resume** |
| **M4c Inversions caught** | Count of candidates ranked top-quartile by resume and bottom-quartile by competence who were **rejected** by the recruiter | same | Reported, not targeted — this is the case-study number |

**Minimum n = 30 decided candidates per cohort.** Below that the report prints
`insufficient data` and prints no correlation. Do not estimate.

**Pre-commit to publishing M4a before seeing it.** A negative result is a valid
finding about the method and must be reported as one; a metric you only publish
when it is favourable is not a metric.

## M5 — Routing quality

**Corrected from "confidence > 90%".** Confidence is self-reported — a
confidently wrong router scores 100%. Confidence must always be paired with
accuracy against a labelled set.

| | Definition | Source | Target |
|---|---|---|---|
| **M5a High-confidence rate** | % of resumes routed above the margin threshold | `detect_family()` margin | **≥ 90%** |
| **M5b Accuracy** | Agreement with a human label on a 50-resume golden set spanning all 8 families | `tests/data/routing_golden.json` | **≥ 95%** |
| **M5c Confident-and-wrong** | High-confidence routes that disagree with the human label | same | **≤ 2%** — the dangerous quadrant |

M5c is the metric that matters. A wrong route silently collapses every
downstream weight, and a *confident* wrong route is one nobody checks.

---

## G — Guardrails: must not get worse

Regressions here block the phase regardless of M1–M5.

| Guardrail | Baseline | Limit |
|---|---|---|
| Test suite | 103 passing | Never red; ≥ 118 by phase end |
| Median interview length | ~9–12 questions | ≤ 12, and no increase in abandonment |
| Median turn latency | current | +20% ceiling |
| Fixture / rubric agreement | exact | `test_pipeline` fixture assertions stay green |
| Anti-bias invariants | 3 structural tests green | Never edited to pass. If one needs changing, the change is wrong |
| Fallback quality | heuristics conservative | A fallback path must never outscore the model path on the same answer |

---

## C — Counter-metrics: what NOT to optimise

Stated explicitly, because these are the numbers that go up when someone
optimises the wrong thing.

**C1 — Do not optimise total evidence volume.** More signals per answer is not
better if strong and weak candidates gain equally. M2b (separation), not M2a
(volume), is the goal. A change that raises volume and lowers separation is a
regression.

**C2 — Do not optimise routing confidence.** Confidence is a number the system
prints about itself. Raising the threshold's generosity raises M5a and worsens
M5c. Confidence is only meaningful paired with M5b accuracy.

**C3 — Do not optimise competence scores upward.** The product's value is
discrimination, not generosity. If mean competence rises while M4a correlation
falls, the scoring got friendlier and less useful.

---

## Reporting

`scripts/validation_report.py` prints all of M1–M5 plus guardrails, per cohort
and overall. Run it weekly from week 3, and at every phase gate.

**Phase 1 is complete when:** M1b = 100%, M5c ≤ 2%, all guardrails green, and
M4a is **published** — whichever direction it points.
