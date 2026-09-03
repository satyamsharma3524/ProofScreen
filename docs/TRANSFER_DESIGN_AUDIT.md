# TRANSFER Probe — Domain-Agnostic Design Audit

Written before PS-001. The question under audit: **is the proposed TRANSFER
probe a generic verification mechanism, or BPO logic wearing a generic label?**

Verdict: **the design as written was drifting toward domain transfer, which does
not scale past a handful of cohorts. The fix is to transfer the candidate's own
reasoning structure, not their industry context — and to make family branching
impossible by construction rather than forbidden by convention.**

---

## 1. Current design assumptions

The probe as specified in `SHIP_PLAN.md` / `EXECUTION_PLAN.md`:

> "Here is a situation you haven't mentioned — how would you handle it?"

Four assumptions hide in that sentence:

| # | Assumption | Why it is a problem |
|---|---|---|
| A1 | Someone can author a plausible *unfamiliar situation* for this candidate | Requires domain knowledge per cohort. Either a scenario library (100 cohorts = 100 libraries) or blind trust in the model to invent one for a niche role it may not understand |
| A2 | The interesting axis is **domain distance** — a different situation in the same field | Tests domain breadth, not whether they did the work. A fabricator who reads widely can bluff an adjacent scenario; a genuine practitioner in a narrow niche may legitimately not know it |
| A3 | The answer will contain the same *kinds* of signal as a recall answer | It will not. A hypothetical has **no quantities to cite and no tools they actually used** — the evidence shape is different, and rubrics tuned on recall answers will misread it |
| A4 | "Scenario quality" can be improved by injecting family vocabulary | This is the exact moment family logic starts leaking into the engine. My earlier PS-004 ("domain-specific scenarios") was that leak — I cut it for redundancy, but the stronger reason is that it doesn't scale |

**A1 and A4 are the dangerous pair.** Follow them and within three cohorts
someone writes `if family == "sales": ...`, and every new job cohort becomes
engineering work instead of configuration.

---

## 2. Hidden BPO biases in the current engine

Audited by reading the detectors, not by inspection of the seed personas.
Two findings are real, one suspected bias turned out not to exist, and the
taxonomy is already doing the right thing.

**Not a bias — process-step detection is broadly neutral.** The verb gate at
`evidence.py:163-165` looked ops-flavoured (`review`, `track`, `train`, `call`,
`audit`, `plan`, `assign`, `check`) but it is an *or* with `"ed "` / `"ing "`,
so any past-tense or gerund verb qualifies. "I profiled the query and added an
index" passes on `"ed "`. Reporting this as a bias would have been wrong.

**Real bias 1 — `_INCIDENT_MARKERS` (`evidence.py:110-115`) anchors on
service-industry time.** `"before month-end"`, `"month end"`, `"during peak"`,
`"on a saturday"`, `"shift"`, `"our vp"`, `"a client"`. Absent: `"during the
incident"`, `"at 3am"`, `"on-call"`, `"the postmortem"`, `"before the release"`,
`"at the sprint review"`, `"during the audit window"`, `"at quarter close"`.
This feeds AUTHENTICITY, which carries the **harshest gate in the system**
(caps at 40 without a specific incident). An SRE describing a 3am page produces
a genuinely specific incident and may score as though they produced none —
**in fixture mode, which is the mode the demo falls back to.**

**Real bias 2 — `METRIC_OWNERSHIP` assumes the role owns a metric.** Its gate
caps the dimension at 45 when no metric is defined (`signals.py:73`). That is
correct for ops, sales, marketing and analytics. It systematically penalises IC
engineers, designers, researchers and junior PMs who own *outcomes* but not a
named KPI. This is a pre-existing cross-domain bias in the six dimensions, not
something the transfer probe introduces — but transfer answers make it worse,
since a hypothetical has no metric to define at all.

**Already correct — the taxonomy keeps domain knowledge in data, not code.**

```
bpo_operations        aht_seconds, csat_pct, sla_pct, shrinkage_pct …
software_engineering  p95_latency_ms, requests_per_second, deploy_frequency_per_week …
sales                 quota_attainment_pct, conversion_pct, deal_size, sales_cycle_days …
```

Eight families, each with its own claim types and fact keys, all in
`data/claim_taxonomy.json`. **No engine module branches on family** — they call
`taxonomy.*` accessors. This is the pattern the transfer probe must not break.

---

## 3. Domain-agnostic redesign: transfer the reasoning, not the domain

**The unit of transfer is the candidate's own extracted reasoning skeleton.**

The evidence engine already stores, per claim, exactly the structure a transfer
question needs:

```
causal_links       cause → action → outcome
process_steps      the sequence they followed
metric_definitions how they knew it worked
quantities         the baseline and the result
```

A transfer question **holds that skeleton constant and substitutes the problem
instance.** Nothing about the substitution requires knowing the industry,
because the material comes from the candidate's own words.

### The five perturbation operators

Each takes only `{claim_text, causal_links, process_steps, metric_definitions,
quantities}`. **None reads `job_family`.**

| Operator | Transformation | What it exposes |
|---|---|---|
| **T1 Substitute the problem** | Their method from claim A, applied to the problem in **claim B — also their own** | Whether a claimed method is real enough to move. A fabricator who listed both cannot connect them |
| **T2 Remove the instrument** | The measurement or tool they named is unavailable | Whether they understood *why* they measured, or just named a tool |
| **T3 Invert the outcome** | The intervention made the number worse instead of better | Diagnostic reasoning. Fabricators narrate success; they cannot debug a failure they never had |
| **T4 Change the scale** | 10× or 1/10th a quantity they themselves cited | Whether they know what breaks first — only known by having operated it |
| **T5 Compress the constraint** | Same outcome, a fraction of the time, people or budget they had | Trade-off reasoning: what they would *give up* |

**T1 is the strongest and the cheapest**: both halves come from the candidate's
own resume, so Python can select it deterministically with zero authored
content, and it directly tests whether two claims on one resume belong to one
person.

### The architectural guarantee

Make family branching **unrepresentable, not merely forbidden**:

```python
def select_transfer(claim, evidence, other_claims) -> TransferSpec:
    """Pure. Deterministic. NOTE THE SIGNATURE: there is no job_family
    parameter, so a family branch cannot be written without changing the
    contract — which a reviewer will see."""
```

`job_family` may reach the **wording** call (for natural phrasing and
`family_label`), never the **selection** call. That is the repo's existing
planner/wording split applied to transfer: *Python decides what to ask, the
model decides how to say it.*

**Enforcing test:** run `select_transfer` over identical evidence twice, tagged
`bpo_operations` and `software_engineering`. The chosen operator and target must
be **byte-identical**. Family may change the wording; it may never change the
question.

### Rubric consequence — do not "fix" this later

A transfer answer legitimately contains **no quantities and no tools used**.
That is correct, not a deficiency:

- `PROBE_LEVEL_DIMENSIONS[TRANSFER] = (CAUSAL_REASONING, PROCESS)` — only these
  two are marked *probed* by a transfer question.
- Claim scoring runs the rubric over the **union** of a claim's signals, so a
  transfer answer *adds* causal and process evidence and **subtracts nothing**.
  SPECIFICITY is unaffected because no answer can lower it.

No scoring change is required. This paragraph exists so nobody later "fixes"
transfer answers for missing numbers.

---

## 4. The same operator across six families

Proof of genericity: **one template, six industries, zero family-specific code.**
The only domain content in any of these is the candidate's own words.

**T1 — Substitute the problem** · *"Suppose the problem wasn't X but Y. Walk me
through how you'd investigate it, using the same approach."*

| Family | Their claim (X) | Their other claim (Y) | Generated transfer question |
|---|---|---|---|
| **Software Engineering** | Cut p95 latency 40% with a read replica | Flaky deploy pipeline | "Suppose the problem wasn't latency but deploys failing one time in five. Walk me through how you'd find the cause, using the same approach you used on latency." |
| **DevOps / SRE** | Cut deploy time 40 → 8 min | On-call noise | "Suppose the problem wasn't deploy time but that half your pages are false alarms. How would you work out which ones to kill first?" |
| **Product** | Self-serve onboarding, activation +12% | Churn at month three | "Suppose the problem wasn't activation but that users leave at month three. Same approach — where do you start?" |
| **Sales** | 8 enterprise deals, 120% of quota | Pipeline coverage | "Suppose closing was fine but deals stalled in procurement. How would you find out why?" |
| **Banking Operations** | Reconciliation breaks down 30% | Manual exception handling | "Suppose breaks stayed flat but loss events doubled. Where do you look first, and what would tell you it isn't a control failure?" |
| **BPO / Operations** | Attrition 34% → 19% | Absenteeism | "Suppose attrition held steady but absenteeism doubled. Walk me through the same investigation." |

**T3 — Invert the outcome** · *"Suppose it got worse instead."*

| Family | Generated transfer question |
|---|---|
| Software Engineering | "You added the index and p95 fell. Suppose it had risen instead. What's your first hypothesis, and what would rule it out?" |
| DevOps / SRE | "The rollout succeeded. Suppose error rate had tripled ten minutes in — what do you do in the first five minutes?" |
| Product | "Suppose activation had dropped 12% after that launch. What would you check first, and what would you refuse to conclude yet?" |
| Sales | "Suppose the new pitch halved your win rate. How would you tell whether it was the pitch or the segment?" |
| Banking Operations | "Suppose the control passed clean but the loss still happened. Where do you look?" |
| BPO / Operations | "Suppose CSAT fell after the escalation redesign. What's your first check?" |

Every question above is one template plus the candidate's own two claims. **A
new cohort is a taxonomy entry, not an engineering ticket.**

---

## 5. Brittleness at 100 cohorts

| Component | At 100 cohorts | Verdict |
|---|---|---|
| Transfer operator selection | Reads no family — constant cost | **Safe by construction** |
| Transfer wording | One prompt, family only as a label | **Safe** |
| `claim_types` per family | ~7 per cohort, config | Fine — this is the intended extension point |
| `fact_keys` per family | ~7 per cohort, config; used only for consistency | Fine. Generic keys (`team_size`, `tenure_months`) cover much of it |
| `family_vocabulary` | Hand-curated word lists, 100 to maintain | **Degrades gracefully** — capped at `MAX_VOCAB_CREDIT = 1.5`, so a thin list costs a little PROCESS credit, never a gate |
| `_INCIDENT_MARKERS`, heuristic regexes | One global list tuned on ops language | **Brittle** — but fallback-only. Widen it with domain-neutral time anchors |
| `METRIC_OWNERSHIP` gate | Penalises every non-metric-owning role, in every cohort | **The most brittle thing in the system** — and it long predates this probe |
| A per-family scenario library | 100 libraries | **Never build this.** It is the failure mode this audit exists to prevent |

---

## 6. Final implementation recommendation

Changes to the six-task plan. Net effect: **+15 LOC over the previous estimate,
and the mechanism stops being BPO-shaped.**

**PS-002 — wording becomes a template, not a fixed question.**
`FALLBACK_QUESTIONS[TRANSFER]` becomes a `string.Template` with slots filled
from the candidate's own claims (`$their_method`, `$other_problem`), so the
offline path is domain-agnostic too. `PROBE_BRIEFS[TRANSFER]` instructs: pose a
problem the candidate has **not** solved, using their own reasoning steps; never
ask for numbers about a hypothetical.

**PS-003 — add `select_transfer()` with no `job_family` parameter.** Implement
**T1 and T3 only** (T1 when the candidate has a second claim, T3 otherwise —
which is also the fabricator's likely path, since their claims are thin). T2,
T4, T5 are designed above and deferred until real transcripts show they are
needed. Add the family-invariance test described in §3.

**PS-004 — seed answers must include one non-BPO family.** The audit's whole
point is undermined if the only demonstration is a call centre. Add transfer
answers for the existing three BPO personas **and** a short software-engineering
persona, so the demo can show the *same mechanism* producing a good question in
two unrelated domains. This is the one place I would spend extra time.

**Not in scope now, logged:** widen `_INCIDENT_MARKERS` with neutral time
anchors (`during the incident`, `on-call`, `the postmortem`, `before the
release`, `at quarter close`); revisit the `METRIC_OWNERSHIP` gate for
non-metric-owning roles. Both are pre-existing cross-domain biases, both are
fallback-path or dimension-tuning concerns, and neither blocks PS-001.

**One-line statement of the design:** *ProofScreen does not ask whether a call
centre manager can run another call centre. It asks whether the reasoning a
candidate demonstrated on one problem survives contact with a second problem
they have not solved — and the second problem comes from their own resume.*
