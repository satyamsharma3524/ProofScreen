# ProofScreen — Ship Plan (the only plan to follow)

Supersedes the MVP section of `PLAN_REVIEW.md`. `ARCHITECTURE_AUDIT.md`,
`IMPLEMENTATION_PLAN.md` and `PLAN_REVIEW.md` are retained as rationale for
what was cut and what would later justify reinstating it.

Owner's frame: **7 days, one goal — prove the product can tell someone who did
the work from someone who decorated a resume, in front of a recruiter.**
Baseline to protect: 102/102 tests, ~1.7s.

---

## The finding that changes the plan

The transfer probe is the right idea. **Implemented naively it would never reach
the candidates it exists to catch.**

`ClaimState.stalled` (`orchestrator.py:112-114`) drops a claim when
`answers >= 2 and last_answer_signals == 0`, and `exhausted`
(`orchestrator.py:121-122`) then removes it from the depth loop entirely. The
README documents the consequence proudly: the evasive seeded candidate *"gets a
shorter interview — 9 questions instead of 12 — because the adaptive stop gives
up on a claim that stops producing signals."*

So the fabricator is the candidate who gets **fewer** questions. Under a naive
implementation, transfer probes — the one question type that cannot be answered
from a memorised resume — would be spent almost exclusively on candidates who
are already proving themselves, and never on the candidate we are unsure about.

**Fix, and it is nearly free:** a stalled claim earns exactly one `TRANSFER`
probe before it is dropped. The stall stops meaning *"give up"* and starts
meaning *"confirm."* One condition in `exhausted`, plus a flag on `ClaimState`.

This single change is what converts the transfer probe from a nice question type
into the product's fraud-detection mechanism. It is ~15 lines.

## The second gap nobody named

The acceptance test is *"why did ProofScreen rank A above B?"* — but
`CandidateSummary` (`schemas.py:411-429`), the payload behind the ranked list,
contains **only numbers**: scores, badge, counts. Not one piece of evidence, not
one quote, not one differentiating fact.

The per-candidate drill-down is excellent and already ships. The **ranked list
answers "that", never "why"** — and the ranked list is the first screen a
recruiter sees and the first screen in the demo. Closing that with a single
generated sentence per candidate is ~25 lines and is the highest recruiter value
per line available anywhere in this plan.

---

## Ranking of every proposed change

Scored 1–5. "Fraud detection" is weighted highest per the product's core claim.

| Change | Fraud detection | Recruiter value | Demo value | Cost | Risk | Long-term |
|---|---|---|---|---|---|---|
| TRANSFER probe **+ stall exemption** | **5** | 4 | **5** | M | M | 5 |
| "Why above" line on ranked list | 3 | **5** | **5** | S | L | 4 |
| Verification flags roll-up | **4** | **5** | 4 | S | L | 4 |
| Domain-specific transfer scenarios | 4 | 3 | 4 | S | L | 3 |
| `VOICE_WEIGHT=0` | 1 | 2 | 3 (defensibility) | XS | L | 4 |
| Burst debounce | 1 | 1 | 4 (*if live WhatsApp*) | S | L | 3 |
| Delete dead `merge_dimension_scores` | 0 | 0 | 0 | XS | none | 1 |
| `dict[Dimension,"object"]` annotation | 0 | 0 | 0 | XS | none | 2 |
| Turn logging line | 0 | 0 | 1 (build-day debugging) | XS | L | 2 |
| `RUBRIC_VERSION` constant | 0 | 0 | 0 | XS | none | 1 |
| Shared JSON codec dedup | 0 | 0 | 0 | S | L | 3 |
| Evidence-node table | 1 | 1 | 1 | L | M | 4 |
| Dimension re-map (D1) | 2 | 1 | 1 | **XL** | **H** | 3 |
| Claim-scoped consistency (D3) | 2 | 3 | 2 | L | **H** | 4 |
| Planner / orchestration / ranking extraction | 0 | 0 | 0 | **XL** | M | 3 |
| `api/contracts/` package | 0 | 0 | 0 | L | M | 1 |
| Observability subsystem + `turn_traces` | 0 | 0 | 0 | L | L | 3 |
| Versioned rubric config | 0 | 1 | 0 | M | M | 2 |

---

## Answers to the six questions

**1. Genuinely improves verification quality:** the TRANSFER probe with the
stall exemption; domain-specific transfer scenarios; the verification-flags
roll-up (it makes "this candidate produced zero quantities across 12 questions"
legible instead of buried). Everything else on the list is presentation,
plumbing, or organisation.

**2. Architecture cleanliness, little recruiter value:** `api/contracts/`, all
three extractions (planner, orchestration, ranking), the JSON codec dedup, the
observability subsystem, versioned rubric config, `RUBRIC_VERSION`. Together
~1,600 LOC that no recruiter would ever perceive.

**3. Risk without demo benefit:** the dimension re-map (~36 of 102 tests, six
tuned rubrics, a frozen two-owner enum), claim-scoped consistency (rewrites the
subsystem the demo's headline moment depends on), and the orchestration split
(the file every router imports, rewritten in the last week).

**4. Would personally approve for a 7-day demo:** TRANSFER + stall exemption,
"why above" line, verification flags, `VOICE_WEIGHT=0`, burst debounce, the two
free deletions, one log line. ~230 LOC total.

**5. Explicitly reject** (not "later" — reject): `api/contracts/`, the
observability subsystem with its table, versioned rubric config, and the ranking
extraction. The first three solve problems this product does not have; the
fourth is filing.

**6. Defer until after the first paying customer:** evidence-node table
(needs a real cross-candidate query), claim-scoped consistency (needs a real
recruiter complaining about a real candidate), the dimension re-map (do it the
week the dashboard is built, never after), orchestration/planner extraction
(needs a third engineer or ~1,200 lines).

---

## A. MVP scope — 1–2 engineering days

| # | Change | Files | LOC | Risk |
|---|---|---|---|---|
| 1 | `ProbeLevel.TRANSFER` + `PROBE_LEVEL_DIMENSIONS` entry + fallback question + prompt block | `schemas.py`, `signals.py`, `question.py`, `generate_question.txt` | +45 | **M** — additive enum value on a frozen file; needs the two owners' nod |
| 2 | **Stall exemption**: a stalled claim gets one TRANSFER probe before being dropped | `orchestrator.py` (`ClaimState`, `plan_next`) | +15 | **M** — touches 12 policy tests; expect 2–3 assertion updates |
| 3 | Transfer scenarios drawn from the family's own vocabulary (`taxonomy.family_vocabulary`) | `question.py`, `generate_question.txt` | +15 | L |
| 4 | `VOICE_WEIGHT=0` default; drop the effort blend from the claim-score path (keep measuring duration/words as metadata) | `config.py`, `scoring.py` | +10 | L — 17 test lines mention voice |
| 5 | Delete dead `merge_dimension_scores`; fix `dict[Dimension,"object"]` | `scoring.py`, `evidence.py` | −25 | none |
| 6 | Re-seed, regenerate fixture, re-verify both demo moments | `seed.py`, `scripts/dump_fixture.py` | 0 | — mandatory gate |

**Subtotal ≈ 60 net lines. This is the whole MVP.**

## B. Demo scope — maximises recruiter impact

Everything above, plus the two items that make the first screen argue for
itself:

| # | Change | Files | LOC | Risk |
|---|---|---|---|---|
| 7 | **"Why above" line** on each ranked candidate — one generated sentence from stored numbers, e.g. *"3 complete causal chains and 6 quantities across 4 claims; no contradictions"* vs *"no quantity in any answer; 1 major contradiction; 2 claims stalled."* Pure arithmetic over rows we already have, no model call | `graph.py`, `schemas.py` (one optional field) | +25 | L |
| 8 | **Verification flags** per candidate — claims with zero quantities, claims that stalled, dimensions never evidenced, contradictions. A roll-up of data that already exists | `graph.py`, `schemas.py` (one optional field) | +30 | L |
| 9 | Burst debounce on inbound WhatsApp — **only if the demo includes live typing**; skip entirely if demoing via `/api/dev/simulate` | `routers/whatsapp.py` | +40 | L |
| 10 | One structured log line per turn (request id + per-stage timings) | `orchestrator.py` | +20 | none — build-day debugging only; **first thing to cut if time slips** |

**Demo total ≈ 175 net lines.**

## C. Post-demo scope

In the order the triggers are likely to fire: claim-scoped consistency (first
recruiter complaint) → dimension re-map (the week the dashboard starts) →
evidence-node table (first cross-candidate query or the embedding work) →
orchestration/planner extraction (third engineer) → codec dedup and the rest of
the cleanliness backlog.

---

## Implementation sequence

| Slot | Work | LOC | Risk | Gate |
|---|---|---|---|---|
| Day 1 AM | Items 1–3: TRANSFER probe, stall exemption, domain scenarios | +75 | M | `pytest -q` green; `test_policy.py` reviewed line by line, not just made to pass |
| Day 1 PM | Items 4–5: voice weight, deletions | −15 | L | full suite green |
| Day 1 PM | Item 6: re-seed, regenerate fixture, **read the three seeded numbers aloud** | 0 | — | ranking inversion + two-role re-rank both still land |
| Day 2 AM | Items 7–8: "why above" + verification flags | +55 | L | ranked list answers "why" without opening a candidate |
| Day 2 PM | Item 9 (conditional), item 10, full dry run of the acceptance test end to end | +60 | L | resume → claims → adaptive Qs incl. transfer → voice answer → evidence → scoring → graph → ranking → drill-down |

**Stop rule:** if Day 1 AM slips past midday, cut items 9 and 10 and ship
1–8. If items 1–2 are not green by end of Day 1, cut the transfer probe entirely
and ship 4–8 — a working demo without transfer beats a broken one with it.

---

## Owner's call

Approve items 1–8. Reject `api/contracts/`, the observability subsystem,
versioned rubric config and the ranking extraction outright. Defer the rest
behind named triggers.

The bet is a single sentence: **a candidate can memorise a resume, but cannot
reason through a situation they have never seen.** Item 1 asks that question and
item 2 makes sure it gets asked of the people who need it most. Items 7–8 make
the answer legible on the first screen a recruiter opens.

Everything else in the original 2,500-line plan can wait for a customer who
asks for it.
