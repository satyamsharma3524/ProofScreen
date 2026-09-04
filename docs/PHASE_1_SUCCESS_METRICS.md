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

## A — Amendments, measured (added 2026-09-05, after Phase 1 exit)

**Targets above are not edited.** The metrics document pre-commits to
publishing whichever way a number points, and editing a target because it was
missed is the exact failure this section exists to avoid. What follows is the
measurement that says three of them ask the wrong question, recorded beside
them so a reader sees both.

**A1 — M1a's target contradicts the mechanism it measures.** M1a is reach:
% of completed sessions containing ≥1 TRANSFER question. But D1 activates
TRANSFER *only* on a stalled claim, and acceptance criterion 1 pins that rule.
So M1a is bounded above by the stall rate, and reaching 80% would require 80%
of candidates to stall — which on a healthy pipeline is alarming, not good.
Measured: **25%**, from one stalled persona in four. **M1b, reach on stalled
claims, is the metric that measures what the probe was built to do, and it is
at 100%.** Recommend M1a be re-specified over *stalled sessions* rather than
all sessions, or dropped in favour of M1b. Not changed above.

**A2 — M2a and M2b are not measurable on authored demo data, by
construction.** Both need a transfer-probed candidate who *does* produce
evidence. Only the fabricator is transfer-probed, and his three transfer
answers score `signals_found = 0` — which is **C1 working exactly as written**:
*"a fabricator should produce near-zero signals on a transfer probe."* The
three honest personas never stall, so they are never probed. Measured: M2a
**0%**, M2b **n/a**. Both become measurable with real candidates. Do not seed a
persona designed to make them move; that is optimising the counter-metric.

**A3 — the TRANSFER probe is a situational question, and the literature says
that matters.** VALIDATION / OPERATIONAL / INCIDENT / DECISION / OUTCOME are
all *behaviour description* — they ask what the candidate actually did.
TRANSFER asks about a problem they have not solved, which makes it
*situational*. Meta-analytic evidence is that situational questions are
considerably less predictive than behaviour-description questions for
higher-level roles, and that the two formats yield different conclusions about
the same construct. This does not argue for removing TRANSFER: it argues that
its output should be read as a **fabrication signal**, which is what C1 already
says, and never as a competence measure. M2's framing should follow that.

## Reporting

`scripts/validation_report.py` prints all of M1–M5 plus guardrails, per cohort
and overall. Run it weekly from week 3, and at every phase gate.

**Phase 1 is complete when:** M1b = 100%, M5c ≤ 2%, all guardrails green, and
M4a is **published** — whichever direction it points.

**Measured 2026-09-05: all four hold.** M1b = 100%, M5c = 0%, guardrails green
(186 tests, anti-bias invariants unedited, `TRANSFER_PROBE=false` reproduces the
pre-phase system exactly), and M4a published as `insufficient data (n < 30)` at
n = 0. **Phase 1 exits.** The missed targets are M1a, M2a and M2b, all covered
in §A above; M3a is 19.2 against ≥ 20 at n = 4. None is an exit criterion.
