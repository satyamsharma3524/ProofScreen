# Claim extraction: why business-metric claims beat engineering-depth claims

Investigation, not a design document. Answers a specific report: for
`resume_test/Abhishek-Singh-Resume-New.pdf` (Senior Frontend Developer),
`extract_claims` kept two generic-percentage claims and never surfaced four
stronger engineering signals (Twilio SDK integration, multi-API integration,
frontend architecture ownership, dashboard/automation platform work).

No new run was needed: `docs/RESUME_PIPELINE_TRACE.md` already drove this exact
resume through the real path today (`llm_mode=live`, `gpt-4o-2024-08-06`,
`temperature=0.0`) and captured the raw provider JSON. `extract_claims` is
called at `temperature=0.0` and the call is content-addressed-cached, so this
is reproducible, not a one-off sample. This report re-derives the mechanism
from that trace plus the current source of `api/engine/extract.py` and
`api/taxonomy.py` — nothing below is speculative.

## 1. All candidate claims before truncation

The resume has 10 achievement bullets. Two separate truncation points act on
them, and they are not the same code:

**Truncation point A — inside the model call, not in Python.**
`api/prompts/extract_claims.txt` renders `max_claims=$limit` directly into the
instruction *sent to the model*:

> Return at most 3 claims, the most verifiable first. Prefer claims that carry
> a number, a scale, a timeframe or a named system.

`MAX_CLAIMS` defaults to 3 (`api/config.py:30`). The model is told to hand back
exactly the final count — not a larger pool for Python to choose from. Its raw
reply (`RESUME_PIPELINE_TRACE.md:272-295`) contains exactly 3 claims:

| # | claim (model's text) | claim_type (model) | metric |
|---|---|---|---|
| 1 | Optimized platform performance by 40% through architecting the entire front-end using ReactJS and Redux... | `performance_work` | 40% |
| 2 | Boosted storefront businesses' customer base by 45% with a hyper-local SaaS platform... | `delivery` | 45% |
| 3 | Developed internal enterprise dashboards, forms, and workflow tools... resulting in a 25% increase in user interaction and productivity | `delivery` | 25% |

The other 7 resume bullets — including all four the report flags — **were
never returned by the model at all.** They are invisible to every later
stage; Python cannot rank, weight, or keep what it never receives.

**Truncation point B — Python, `extract.py:422-441`.** Of the 3 the model
returned, one is dropped: claim #3 shares `delivery` with claim #2, and the
loop keeps one claim per type (`if claim_type in seen_types: continue`). Final
kept set = claims #1 and #2 (`RESUME_PIPELINE_TRACE.md:297-314`, "claims kept: 2").

## 2. Ranking logic, exactly as it runs today

`api/engine/extract.py:422-441`:

```python
kept: list[ExtractedClaim] = []
seen_types: set[str] = set()
for claim in result.claims:
    text = (claim.text or "").strip()
    if not claim.verifiable or len(text) < 15:
        continue
    claim_type = normalise_claim_type(family, claim.claim_type, text)
    if claim_type in seen_types:
        continue           # one claim per type: breadth beats depth here
    seen_types.add(claim_type)
    kept.append(ExtractedClaim(text=text, claim_type=claim_type,
                                metric=claim.metric or _metric_of(text),
                                verifiable=True))
    if len(kept) >= limit:
        break
```

This is a **filter + dedup + truncate**, applied in the order the model's JSON
array came back. There is no sort, no comparison of `claim_type` importance,
nothing that reads `taxonomy.default_claim_weights()`. "Ranking" is a
misnomer for what happens today — the effective rank *is* whatever position
the model put the claim in its `claims` list.

`taxonomy.default_claim_weights("software_engineering")` already exists
(`api/taxonomy.py:155-157`) and already returns:

```
system_ownership  25   (built, owned, designed, architect, service, platform, module)
performance_work  20   (latency, p95, p99, throughput, scale, optimis/optimiz, cache, query)
reliability       20   (on-call, incident, outage, uptime, monitoring, alert, sre)
delivery          15   (migrat, rollout, shipped, released, zero downtime, rewrite, cutover)
tech_depth        15   (kubernetes, kafka, redis, postgres, terraform, spark, grpc, docker, aws, gcp)
mentoring          5   (mentor, code review, onboarded, tech lead, interviewed, hiring)
```

`extract_claims()` imports `normalise_claim_type` and `classify_claim` from
this module but never imports or calls `default_claim_weights`. It is used
elsewhere (`fallback_claim_type`, `engine/scoring.py`) but not here — this is
the "already-defined weights, unused for ranking" the report asks about, and
it is real.

## 3. Discarded claims — exact reason each one lost

| Discarded claim | Where it was lost | Exact mechanism |
|---|---|---|
| "Integrated Twilio's SDK to enable SMS, voice, and WhatsApp communications, building a robust communication platform that scales with user needs." | **Never returned by the model** (truncation point A) | No metric/number in the sentence. The prompt's selection instruction is "the most verifiable first. Prefer claims that carry a number..." — this bullet has none, so it lost to three bullets that do, before Python ever saw it. |
| "Developed a seamless integration with Google, Facebook, WhatsApp, and Twilio's APIs, resulting in a 35% increase in user engagement and retention." | **Never returned by the model** | *Has* a metric (35%) and by keyword count would deterministically classify as `system_ownership` (no direct hit, falls to `fallback_claim_type` = heaviest weight in family = `system_ownership`, 25 — see §4). It still lost to the model's top-3, which is evidence the loss is about the model's own selection heuristic, not about lacking a number. |
| "Led frontend architecture with scalable component libraries and API integrations driving a significant increase in user retention and customer satisfaction." | **Never returned by the model** | No number ("significant increase" is not parsed as a metric). By keyword count this line would classify `system_ownership` (`architect` inside "architecture"), the single highest-weighted claim type in the family — and it was still never proposed, because the prompt never tells the model that claim type importance should drive selection. |
| "Designed customizable dashboards, analytics tools, reward systems, and whatsapp marketing automations... Improved customer conversion rate by 20%..." | **Never returned by the model** | Has a metric (20%) and lost anyway — the model's top-3 already had two `platform`-flavored bullets (#1, #2 above) and one more `delivery`-typed one (#3); this bullet, also plausibly `delivery`, simply wasn't among the 3 the model chose. Model claim selection is a black box beyond "prefer verifiable/numbered," so no more precise reason is available than: it did not make an arbitrary top-3 cut sized by `MAX_CLAIMS`. |
| "Developed internal enterprise dashboards, forms, and workflow tools... resulting in a 25% increase in user interaction and productivity" | **Dropped in Python** (truncation point B) | This one *was* returned by the model (claim #3), typed `delivery`. Claim #2 already claimed `delivery`. `extract.py:429-430`'s one-claim-per-type rule drops the second `delivery` claim regardless of its metric or content. |

## 4. Does the extractor lack a notion of engineering leverage?

No — **the taxonomy already encodes it**, and nothing downstream uses it.
`classify_claim()` (`api/taxonomy.py:453-460`, keyword hit-count) disagrees
with the model on *both* claims that were kept:

- Claim #1 ("Optimized platform performance by 40% through architecting the
  entire front-end...") contains `architect` and `platform` → 2 hits for
  `system_ownership` vs. 1 hit for `performance_work` (`optimiz`). The model
  labeled it `performance_work`; the deterministic classifier says
  `system_ownership` (`RESUME_PIPELINE_TRACE.md:493`, "DISAGREES").
- Claim #2 ("Boosted storefront businesses' customer base by 45% with a
  hyper-local SaaS platform...") contains `platform` → 1 hit for
  `system_ownership`, 0 for `delivery`. The model labeled it `delivery`; the
  classifier again says `system_ownership` (`RESUME_PIPELINE_TRACE.md:502`).

`normalise_claim_type()` (`api/taxonomy.py:463-469`) keeps the model's label
whenever it is *merely a valid key in the family* — it does not consult
`classify_claim` to arbitrate, only to backfill when the model's key is
missing or invented. So the one place in the codebase that already recognizes
"architecture/platform work outweighs a bare percentage" is present and
computed, but its answer is discarded whenever the model supplies any
syntactically valid label of its own.

Net: this is not a missing concept. It is a computed, taxonomy-backed signal
that exists at runtime and is thrown away twice — once because
`normalise_claim_type` prefers the model's label over the classifier's, and
once because `extract_claims()`'s Python loop never reads
`default_claim_weights()` at all.

## 5. Should `software_engineering` prioritize system ownership / architecture / integrations / platform design / scalability over generic percentages?

The taxonomy weights already say yes: `system_ownership` (25) outweighs
`performance_work` and `reliability` (20 each), which outweigh `delivery` and
`tech_depth` (15 each), which outweigh `mentoring` (5). Nothing needs to
change in `data/claim_taxonomy.json` — the family's priorities are already
ordered correctly. The gap is that this ordering is never applied to
*selection*, only ever consulted for scoring after the fact
(`engine/scoring.py`) and for the `fallback_claim_type` used when
classification totally fails.

## 6. Should claim ranking use the existing claim_type weights instead of the model's ordering?

Yes, and it is a small, mechanical change — but it requires fixing **both**
truncation points, not just the Python one. Reranking by weight inside
`extract_claims()`'s existing loop only reorders whatever 2–3 claims the model
already decided to return; it cannot resurrect the Twilio/integration/
architecture bullets, because those never survive truncation point A. A
Python-only fix would correctly reorder claims #1/#2 (both would resolve to
`system_ownership` if reclassified) but would still never see the four
flagged claims.

## Minimal code change

Two edits, no new files, no schema change, no new abstraction — reuses
`taxonomy.default_claim_weights`, already public and already used elsewhere.
**Not applied.** `extract.py` and its prompt are extraction-path files;
per `CLAUDE.md`'s two-developer rule this is Developer A's file and the
change should be reviewed before landing, so this is left as a proposal.

**a. Give the model room to surface more than the kept count**
(`api/engine/extract.py`, inside `extract_claims`, where `prompt = load_prompt(...)` is built):

```python
# before
prompt = load_prompt(
    "extract_claims",
    resume_text=trimmed,
    max_claims=limit,
    ...
)

# after
overshoot = min(limit + 3, len(claim_types(routed)))
prompt = load_prompt(
    "extract_claims",
    resume_text=trimmed,
    max_claims=overshoot,
    ...
)
```

(`claim_types` already importable from `api.taxonomy`, same module the file
already imports from.)

**b. `api/prompts/extract_claims.txt`** — tell the model the importance
numbers it's already shown are meant to drive selection, not just labeling:

```text
# before
Return at most $max_claims claims, the most verifiable first. Prefer claims
that carry a number, a scale, a timeframe or a named system.

# after
Return up to $max_claims claims. Prefer claims that carry a number, a scale,
a timeframe or a named system, but a claim's IMPORTANCE (shown next to its
claim type above) matters more than whether it has a percentage — system or
architecture ownership and integration/platform work outrank a generic
outcome percentage with no owned system behind it.
```

**c. Rank by taxonomy weight in Python instead of trusting model order**
(`api/engine/extract.py:422-441`):

```python
# before
kept: list[ExtractedClaim] = []
seen_types: set[str] = set()
for claim in result.claims:
    text = (claim.text or "").strip()
    if not claim.verifiable or len(text) < 15:
        continue
    claim_type = normalise_claim_type(family, claim.claim_type, text)
    if claim_type in seen_types:
        continue
    seen_types.add(claim_type)
    kept.append(ExtractedClaim(text=text, claim_type=claim_type,
                                metric=claim.metric or _metric_of(text),
                                verifiable=True))
    if len(kept) >= limit:
        break

# after
weights = default_claim_weights(family)
candidates: list[ExtractedClaim] = []
seen_types: set[str] = set()
for claim in result.claims:
    text = (claim.text or "").strip()
    if not claim.verifiable or len(text) < 15:
        continue
    claim_type = normalise_claim_type(family, claim.claim_type, text)
    if claim_type in seen_types:
        continue
    seen_types.add(claim_type)
    candidates.append(ExtractedClaim(text=text, claim_type=claim_type,
                                      metric=claim.metric or _metric_of(text),
                                      verifiable=True))
candidates.sort(key=lambda c: -weights.get(c.claim_type, 0.0))
kept = candidates[:limit]
```

(`default_claim_weights` added to the existing `from api.taxonomy import
(...)` block at the top of the file.)

Effect on this exact resume: the model would have room to also return the
Twilio-SDK and multi-API-integration bullets (both `system_ownership` by
keyword, weight 25) alongside the two currently kept (weight 20/15 once
correctly typed). The Python sort would then keep the `system_ownership`
claims ahead of the generic-percentage ones instead of whichever the model
happened to list first. This does not touch `classify_claim` vs. model-label
arbitration (§4) — that is a separate, second question and a separate change
if the team wants it.

**Not recommended as part of this change:** having `normalise_claim_type`
prefer `classify_claim` over the model's label. That's a real second gap
(§4) but it changes claim *typing* behavior for every family, not just
selection for this one resume, and the report asked for the minimal change —
flagging it here so it isn't lost, not folding it in.
