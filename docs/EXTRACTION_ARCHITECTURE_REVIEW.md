# Architecture review — extraction is doing selection

**Review only. Nothing in this document is implemented.**
Line numbers are against the working tree at the time of writing.

Scope: every place in the extraction flow that ranks, prioritises, budgets or
filters by claim type, and where each of those behaviours belongs instead.

Partially addressed already: `docs/CLAIM_INVENTORY.md` added a
`CLAIM_INVENTORY` flag that removes the type dedup and the weight sort. **That
work was incomplete against the standard set here** — it kept a top-N, and it
did not touch the heuristic path at all. Both are itemised below as defects.

**Update: Phase 1 (family-agnostic discovery) landed and was measured live,
gpt-4o-2024-08-06, temperature 0, on the two traced resumes.** Recall: clean
gain, zero losses — variant claim set ⊇ baseline set on both (Abhishek 15→16,
Arshad 14→15), and the added claim in each case is real, verbatim resume text
the old prompt never surfaced (Abhishek: the Profile-section "driving a 40%
performance boost and a 35% increase in user engagement" sentence; Arshad: the
"Operated as an independent SaaS extension on top of Shopify" bullet).

**But typing collapsed on the `software_engineering` resume: 15 of 16 variant
claims (94%) came back `system_ownership`**, versus 4 distinct types in the
baseline (`delivery`, `system_ownership`, `performance_work`, `tech_depth`).
Root cause, measured directly with `_hits`: most of this resume's claims score
**zero keyword hits in every claim type** (e.g. "Delivered responsive designs
using Material UI and Tailwind CSS..." scores 0/0/0/0/0/0) — `classify_claim`
falls through to `fallback_claim_type`, the family's *heaviest* type by
construction (D6), for nearly every claim once the model stops supplying a
label. `product`'s taxonomy did not show this (Arshad's types stayed varied:
`launch_delivery`, `outcome_ownership`, `stakeholder_alignment`) — the defect
is specific to how sparse and generic-vs-narrow `software_engineering`'s
keyword lists are (`system_ownership`: built/owned/designed/platform, broad;
`tech_depth`: literal infra nouns like kubernetes/kafka/docker, a frontend
resume never says these), not to the discovery/typing split itself.

**This is a pre-existing defect (D6), not one this change created** — but
Phase 1 removes the one thing that was masking it. Recommendation: **do not
enable `CLAIM_INVENTORY=true` on top of Phase 1** until `classify_claim`'s
keyword coverage is measured and improved for at least
`software_engineering`, or scoring will read a wall of `system_ownership` at
weight 25 as real signal. That is a taxonomy/keyword change, not a discovery
or typing-split change, and out of scope here — flagging it as the actual
blocker, sharper than "P1/P2 remain open."

**Update: E1, E2 and E3 are now done.** `heuristic_claims()` in inventory mode
runs `_is_claim_line` (a boolean predicate, no threshold, no rank, no type
gating, no top-N) and recognises the implementation/integration verbs D2
measured missing. The model path's prompt no longer renders any number in
inventory mode — `$stop_condition` replaces `$max_claims` and says only "there
is no fixed number to return"; `ceiling` still exists but is never
substituted into the prompt text in this mode. The Python-side
`candidates[:ceiling]` top-N (the second, silent truncation point E2 named —
fixing the prompt alone would not have removed it) is now a warning-logged
backstop, not a selection budget, and `max_inventory_claims` moved 12 → 60
(D1: measured real-resume saturation was 17; 12 was an active truncation
point, not a safety margin). See `docs/CLAIM_INVENTORY.md` and
`tests/test_extract.py`. P1/P2 (planner breadth selection, `graph.py`
unprobed-claim scoring) remain open — none of E1–E3 unblocks enabling the
flag on their own.

---

## 1. Files involved

| File | Owner | Role in this defect |
|---|---|---|
| `api/prompts/extract_claims.txt` | A | Sends the model a cap; the model selects before Python sees anything |
| `api/engine/extract.py` | A | Both extraction paths rank, threshold and truncate |
| `api/config.py`, `.env.example` | A | `max_claims`, `max_inventory_claims` — interview budget living in extraction |
| `api/engine/orchestrator.py` | A | `plan_next` — where selection *should* live; today it has none |
| `api/engine/graph.py` | **B** | Scores unprobed claims as 0 — blocks recall-first extraction |
| `api/models.py` | A | `Claim.claim_type` non-nullable — forces typing at discovery time |
| `api/taxonomy.py` | A | `fallback_claim_type()` returns the **heaviest** type |
| `api/engine/provenance.py` | Ph4 | Stamps the extraction caps as score-moving flags |
| `tests/conftest.py` | shared | Pins `MAX_CLAIMS=3` for the suite |

`api/schemas.py` needs **no** change: `ExtractedClaim` and `ClaimExtraction`
already impose no cap and no ordering.

---

## 2. Exact code paths

### 2a. The LLM path — `extract.extract_claims()`

| Line | Code | Category |
|---|---|---|
| 384 | `trimmed = (resume_text or "")[:MAX_RESUME_CHARS]` (8000) | **Budget** — input truncation |
| 424–427 | `ceiling = max_inventory_claims if claim_inventory else min(limit+3, len(claim_types))` | **Budget** |
| 431 | `max_claims=ceiling` rendered into the prompt | **Budget delegated to the model** |
| 478 | `if not claim.verifiable or len(text) < 15` | Valid (filters 2 and 4) |
| 481 | `key = _dedupe_key(text)` — lowercased, whitespace-collapsed, **first 60 chars** | Valid (filter 3), but see D4 |
| 486 | `normalise_claim_type(family, claim.claim_type, text)` | Labelling — but see D6 |
| 487–489 | `if claim_type in seen_types: continue` | **Type filtering** (legacy mode only) |
| 500 | `kept = candidates[:ceiling]` | **Top-N** (inventory mode) |
| 503–504 | `candidates.sort(key=-weight)` then `[:limit]` | **Ranking + top-N** (legacy mode) |

### 2b. The heuristic path — `extract.heuristic_claims()`

Production code, not a stub — CLAUDE.md is explicit that this is what runs when
the model is down. **`CLAIM_INVENTORY` did not change any of this.**

| Line | Code | Category |
|---|---|---|
| 125–126 | `limit = limit or (max_inventory_claims if … else max_claims)` | **Budget** |
| ~130 | `if not (25 <= len(line) <= 300)` | **Budget** — a 301-char bullet is silently not a claim |
| 134 | `if score >= MIN_CLAIM_SCORE` (2) | **Precision threshold** |
| 137 | `candidates.sort(key=lambda p: (-p[0], len(p[1])))` | **Ranking** |
| 153 / 161 | `passes = (True, False)` / `require_new_type and claim_type in seen_types` | **Type filtering** (legacy mode) |
| 155 | `if len(claims) >= limit: break` | **Budget** |
| 184 | `return claims[:limit]` | **Top-N** |

### 2c. Where selection *should* be, and isn't

| Line | Code | Note |
|---|---|---|
| `orchestrator.py:617` | `untouched = [s for s in states if not s.levels_used]` | Breadth probes **every** claim. No selection step exists. |
| `orchestrator.py:~378` | `sorted(states, key=(-weight, order_index))` | Correct home for ranking — already here |
| `graph.py:403` | `scored_pairs.append((claim.claim_type, claim_score))` | Appends unprobed claims; `_claim_score_under(None,…)` returns `0` (`graph.py:178`) |

---

## 3. Measured evidence

### D1 — the ceiling is active truncation, not a safety net

`max_inventory_claims=12` was documented as a guard against a runaway reply. It
is not:

| resume | ceiling 12 | ceiling 40 |
|---|---|---|
| Abhishek (frontend) | 12 | **17** |
| Arshad (PM) | 12 | **14** |

Five and two real claims were being dropped. The resume has roughly 14–17
achievement bullets, so at 40 the model **saturates** rather than running away —
the failure mode the ceiling was defending against does not occur.

### D2 — the heuristic fallback drops the exact claims in question

`_score_line` against `MIN_CLAIM_SCORE = 2`:

| score | verdict | bullet |
|---|---|---|
| **−1** | **DROPPED** | Integrated Twilio's SDK to enable SMS, voice, and WhatsApp communications… |
| 5 | kept | Developed a seamless integration with Google, Facebook, WhatsApp, and Twilio's APIs… |
| 2 | kept | Led frontend architecture with scalable component libraries… |
| **1** | **DROPPED** | Collaborated with backend teams and QA to integrate RESTful APIs… |
| **1** | **DROPPED** | Delivered responsive designs using Material UI and Tailwind CSS… |
| 6 | kept | Optimized platform performance by 40%… |

Two compounding causes:

- **`integrated`, `developed`, `collaborated`, `implemented` are not in
  `_STRONG_VERBS`.** The list is outcome verbs (`reduced`, `increased`, `cut`,
  `grew`). Implementation and integration claims score nothing for their verb.
- **The skills-list rule misfires.** `line.count(",") >= 3 and not has_verb`
  returns −1. An integration claim is comma-heavy *by nature* — it lists the
  systems integrated — and its verb is not in the list, so
  "Integrated Twilio's SDK to enable SMS, voice, and WhatsApp communications, …"
  is classified as a keyword list.

So on the offline path the Twilio claim is not deprioritised; it is **not a
claim at all**.

### D3 — `MAX_RESUME_CHARS` is latent, not active

Longest resume in `resume_test/` is 6,779 chars against a 8,000 cap. Not biting
today. Still a recall cap that belongs in the review, and a two-page senior CV
will reach it.

### D4 — `_dedupe_key` truncates to 60 chars

Not reproduced on the current corpus, so this is a design risk rather than a
measured defect. Two genuinely different claims sharing a 60-character opening
("Developed internal enterprise dashboards, …") would collide and one would be
discarded as a duplicate. A duplicate filter that can delete a distinct claim is
the wrong shape for a recall-first stage.

### D5 — the model is still the selector

Even with a perfect Python path, `$max_claims` in the prompt makes the model do
the selection before anything reaches `extract.py`. The prompt currently ends
*"Stop at $max_claims only if the resume genuinely contains more than that."*

### D6 — claim typing carries a prioritisation default

`normalise_claim_type` → `classify_claim` → `fallback_claim_type`, which returns
the family's **heaviest** type. Measured earlier on this resume: 9 of 10 bullets
type as `system_ownership`, 5 of them purely because nothing matched. That is
tolerable when a type is only a label. It stops being tolerable once inventory
mode multiplies the number of claims, because `weighted_evidence_score` reads
that type as a weight.

---

## 4. Which behaviour belongs where

### Extraction — claim discovery

- Read the resume text
- Find every distinct claim
- Apply exactly four filters: not a claim · not verifiable · duplicate ·
  corrupted or empty
- Attach `metric` when the claim states one
- Attach `claim_type` **as a label only**, because `models.Claim.claim_type` is
  non-nullable and `create_all()` cannot alter a column (CLAUDE.md rule 7).
  Typing stays here for schema reasons; it must never gate inclusion.

### Planning — claim selection

- Rank claims by the family's importance weights *(already correct:
  `build_claim_states` sorts by `-weight`)*
- Decide **which** claims earn a breadth probe *(missing)*
- Decide how deep to go *(already correct: `plan_next` depth phase)*
- Enforce the interview budget *(`MAX_QUESTIONS`, already here)*
- Decide a claim is not worth asking about *(missing)*

### Scoring — a third home, and the blocker

- Decide what an unprobed claim contributes. Today: `0` at full weight.
  Recall-first extraction makes the denominator a property of resume length, so
  two candidates with identical verified evidence score differently. Measured:
  the same two probed claims give **69** in an inventory of 2 and **24** in an
  inventory of 6.

---

## 5. Concrete changes required

Ordered. E-changes are extraction (all Developer A). P-changes must land for the
result to be usable.

### E1 — stop capping the model *(prompt, line 431)*
Remove `max_claims` from the rendered prompt and the "Stop at $max_claims"
sentence; instruct the model to return every claim it finds. Keep one hard guard
in Python far above any real resume (60 is ~3.5× observed saturation) that
**logs a warning when it bites**, so a runaway reply is visible rather than
silent. Risk: a longer, more expensive reply — measured at 17 claims for a
2,913-char resume, so bounded.

### E2 — delete the top-N *(line 500, and 503–504)*
`kept = candidates` in inventory mode. The weight sort and `[:limit]` become
legacy-only and should be deleted outright once `CLAIM_INVENTORY` stops being a
flag.

### E3 — rebuild the heuristic path as a boolean test *(lines 125–184)*
The largest single change, and the one the flag missed entirely.
- Convert `_score_line` from a **rank** to an **is-this-a-claim** predicate.
  Keep its negative signals as rejections (fluff, job-title heading, date-range
  heading, skills list); drop the `>= MIN_CLAIM_SCORE` threshold, which is a
  precision filter with no place here.
- Fix the skills-list rule so it cannot fire on a bullet that is clearly an
  achievement — e.g. require *no digits* as well as *no verb*, or extend
  `_STRONG_VERBS` with `integrated`, `developed`, `implemented`, `collaborated`,
  `architected`, `enabled`. Both are needed; the verb list alone leaves the
  comma rule live for verb-less integration bullets.
- Remove the `limit` break, the `[:limit]` return and the `(True, False)`
  two-pass type walk.
- Revisit the `<= 300` line cap.

### E4 — make the duplicate filter exact *(line 68, `_dedupe_key`)*
Compare full normalised text, not a 60-character prefix. If near-duplicate
matching is wanted later it belongs behind a similarity threshold, not a prefix.

### E5 — raise or justify `MAX_RESUME_CHARS` *(line 35)*
Not biting today; will bite on a long CV. Decide deliberately and record the
number.

### E6 — make typing explicitly a label *(taxonomy, and a comment at line 486)*
No code change required to `fallback_claim_type` itself, but its "heaviest type"
default must be documented as a *labelling* fallback, and E-stage code must not
read the type for any inclusion decision. Flag for planning: once many claims
carry a fallback `system_ownership`, `weighted_evidence_score` is reading a
guess as a weight.

### E7 — retire the flag
`CLAIM_INVENTORY` exists only to keep `main` green while P1 and P2 land. Once
they have, inventory is the only behaviour and `max_claims` /
`max_inventory_claims` come out of `config.py` and `provenance.FEATURE_FLAGS`.

### P1 — give `plan_next` a breadth selector *(orchestrator.py:617, A)*
The breadth phase gives **every** claim a VALIDATION probe. Measured against
`MAX_QUESTIONS=12`: at 6 claims it is 6 breadth + 6 depth; at 12 claims it is 12
breadth and **zero** depth; beyond 12, claims are extracted and never asked
about. Selection must choose the top-K claims by weight for breadth and leave
the rest in the inventory unprobed. **Without this, E1–E3 make the interview
strictly shallower.**

### P2 — stop scoring unprobed claims *(graph.py:403, Developer B)*
Exclude claims with no `ClaimScore` row from `scored_pairs`, keeping them in
`claim_graphs` (the recruiter still sees the whole inventory) and in the
`role_coverage` numerator (which is about what they *claimed*, and is already
computed from `seen_types`). One guarded append. **Not A's file — needs B.**

### Test and provenance impact
- `tests/conftest.py:19` pins `MAX_CLAIMS=3`; several suites assume a small
  claim set.
- `tests/test_transfer.py:373` needs ≥ 2 claims — unaffected, recall only grows.
- `evaluation_version` moves when the flags change. Re-seed and re-dump the
  fixture (`seed.py --reset && scripts/dump_fixture.py`).
- Extraction cost rises: 17 claims instead of 3 is a longer completion per
  resume, once per candidate.

---

## Recommended order

**P2 → P1 → E1/E2 → E3 → E4/E5/E6 → E7.**

P2 first because until it lands, every extraction improvement lowers scores.
P1 second because until it lands, every extraction improvement shortens the
interview. The E-changes are cheap and safe once both are in.
