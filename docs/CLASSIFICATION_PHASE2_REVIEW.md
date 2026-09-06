# Claim classification — Phase 2 taxonomy coverage fix

Follow-on to `docs/CLAIM_INVENTORY.md` and `docs/EXTRACTION_ARCHITECTURE_REVIEW.md`.
Those cover *extraction* (recall-first discovery, now shipped). This covers
what discovery's own measurement surfaced next: **typing**, specifically
`classify_claim()`'s keyword coverage for `software_engineering`.

## The problem, measured

Live (gpt-4o-2024-08-06, temperature 0) on two traced resumes, inventory-mode
discovery, before any taxonomy change:

| Resume | Claims | Fallback rate | `system_ownership` share |
|---|---|---|---|
| Abhishek (frontend) | 16 | 62.5% | 100% |
| Sathiya (Java backend) | 27 | 74% | 93% |
| Combined | 43 | 70% | 95% |

`fallback_claim_type()` returns the family's *heaviest* type
(`system_ownership`, weight 25) whenever `classify_claim()` scores zero
keyword hits. At a 70% fallback rate this is no longer a rare safety net —
it is the dominant path, and it always resolves to the same, maximum-weight
answer.

Root causes, in order of measured contribution:

1. **Insufficient keyword coverage.** `tech_depth`'s list is cloud-native-only
   (kubernetes/kafka/redis/postgres/terraform/spark/grpc/docker/aws/gcp) —
   0% hit rate across all 43 claims, including a backend engineer's resume
   full of Spring/Hibernate/OAuth/JWT. `delivery` and `performance_work` are
   both missing their own name-verb ("deliver", "performance").
   `develop*`/`integrat*`/`deliver*` are the lead verb on 19%/19%/5% of all
   43 claims and appear in zero of the six types' keyword lists.
2. **`system_ownership`'s keywords are uniquely generic** (owned, built,
   designed, service, platform, module) compared to every other type's
   discriminative, jargon-specific list. Every non-fallback match in both
   resumes landed on `system_ownership` for exactly this reason.
3. **Raw hit-count arbitration** — a claim can score higher on a generic type
   than a specific one purely by word count, not relevance (measured once:
   "Optimized platform performance by 40%..." scored `system_ownership: 2`
   vs `performance_work: 1`).
4. **`fallback_claim_type()` → heaviest type** amplifies every miss above
   into the same, maximum-weight answer.

**Comparison across families**: `product`'s fallback rate on its own traced
resume was 33%, with three distinct types represented — this is not a
universal defect in `classify_claim`'s mechanism, it is specific to
`software_engineering`'s keyword content.

**Ontology check**: `probe_focus` (what dimensions a claim type steers
questions toward) shows `system_ownership`, `reliability`, and `mentoring`
are all `[AUTHENTICITY, PROCESS]` — identical. `tech_depth` is the *only*
type whose `probe_focus` (`TOOL_FAMILIARITY`, `SPECIFICITY`) is used by no
other type — and it's the one that never fires. Fixing `tech_depth`'s
coverage has outsized planning value for exactly this reason: those two
interview dimensions are otherwise unreachable for this family, regardless
of what a candidate actually did. `data_analytics` has zero duplicate
`probe_focus` pairs across its six types — the design baseline to compare
`software_engineering` against, though restructuring the ontology itself
was evaluated and rejected: the measured defects are all keyword/mechanism
level, not structural (see "Not shipped" below).

## Precision audit of the proposed keywords

Every proposed keyword was tested **in isolation** against the same 43
claims, then in combination, specifically to catch collisions invisible to
one-at-a-time testing.

**Finding: 6 real ties appear only once keywords combine.** E.g. "Created a
gaming-focused blog platform with React..." — `system_ownership` (`platform`)
vs `tech_depth` (`react`), 1-1. `classify_claim`'s tie-break
(`max(scores, key=...)`) returns the first key in `claim_types()`'s
iteration order, which is `system_ownership` — so **5 of 6 ties silently
resolve back to `system_ownership`**, the same type this whole change is
trying to de-monopolize. None of the 5 are *wrong* outcomes (both types are
defensible), but it means the shipped keyword set has less effect than its
raw per-keyword match count suggests. This is a property of the classifier's
tie-break rule, not of any keyword — **deliberately not fixed here** (see
below).

**`react` — the one keyword changed before shipping.** Bare `react` matches
`_INFLECTION`'s `ed`/`ing` suffixes, so "reacted quickly to the outage"
would false-positive as a React.js signal — a real risk from the word itself,
not from this corpus. Shipped as the two-word phrase `react js` instead,
which still matches the one genuine case measured ("...Node and **React JS**
for authentication") while eliminating the verb collision.

**`node` — kept as proposed.** Same shape of risk (short, some overload
even within engineering — "node" in a distributed system, not just
Node.js), but it is not a common English *verb*, and narrowing it to
`node.js`/`nodejs` would lose the one measured match (the real resume text
says bare "Node", not "Node.js").

**`integrat` — kept, but isolated in its own commit.** 6 matches, none
clearly wrong, but 3 of 6 are "plausibly correct" rather than clean — some
integration claims are really business-outcome or system-ownership stories
that happen to use the word "integration". Isolated so it can be reverted
independently without touching the other nine keywords.

**`microservice` — measured safe.** All 3 matches are unambiguous
architecture claims; it's a specific noun with no common-English collision
risk, unlike the other three keywords this review specifically scrutinized.

## Shipped (this phase)

Three isolated commits, each independently revertable:

1. `delivery`: `deliver`, `deploy`. `performance_work`: `performance`.
2. `tech_depth`: `spring`, `hibernate`, `oauth`, `jwt`, `junit`, `typescript`,
   `microservice`, `node`, `react js`.
3. `tech_depth`: `integrat` (isolated per the precision-audit finding above).

See the fixture/measurement diff appended below once seeded.

## Not shipped this phase, and why

- **Silent-e stemming fix in `_term_pattern`** (`scale`→`scaled`/`scaling`,
  `cache`→`cached`/`caching`). Real, measured, but affects all nine
  families' keyword lists (58 keywords end in "e" taxonomy-wide) — a
  different blast radius than a `software_engineering`-scoped keyword
  addition. Kept out so this phase's story stays "taxonomy coverage,
  JSON-only, easy to attribute" — landing it separately keeps its effect
  distinguishable from the keyword additions' effect.
- **Tie-break redesign** (`system_ownership` winning every tie by dict
  order). Real, measured (5/43 claims), but this is classifier *behavior*,
  a different layer from keyword *content*. Mixing the two would make it
  impossible to attribute a distribution change to keywords vs. tie-break
  vs. both.
- **`fallback_claim_type()` redesign, `unclassified`, multi-label typing.**
  Evaluated in the taxonomy redesign audit; all require touching schema,
  scoring aggregation, or planning — explicitly out of scope for a
  taxonomy-coverage-only phase. Phase 3+ concerns.

## Metrics to track (not just fallback rate)

Fallback rate collapses to a single number; it doesn't say whether planning
actually gained anything. Also tracked: **type distribution** (already
above) and **distinct claim types per resume** — the latter is the more
direct proxy for interview-planning quality, since `probe_focus` diversity
is what determines how many of the six interview dimensions a resume's
claims can actually steer toward.
