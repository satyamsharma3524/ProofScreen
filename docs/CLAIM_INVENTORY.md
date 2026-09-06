# Claim inventory — recall-first extraction

**Status: implemented, `CLAIM_INVENTORY=false`. One blocking dependency in
`api/engine/graph.py`, which is Developer B's file.**

## The separation

Extraction and prioritisation are different stages and this splits them.

```
Resume → Parse → Route family → EXTRACT (recall)  → PLAN (selection) → Ask → Evidence → Score
                                 ^ inventory        ^ importance weights,
                                                      interview budget
```

The extractor's job is a complete claim inventory. It does not rank, does not
prioritise, and does not drop a real claim because a stronger-looking one
exists. Selection already has a home: `orchestrator.plan_next` sorts by the
family's claim-type weights and spends a bounded question budget.

## What changed

### `api/prompts/extract_claims.txt` — rewritten, family-agnostic

Recall-first, and the ranking language is gone. It carries **no worked
examples and no cohort vocabulary** — A's contract forbids per-family examples
in prompts, and this project already paid for that once when three templates
carried BPO-only examples and biased extraction for every other cohort. The
capture list is written in abstract categories that land in any family:

> something they owned · something they built · a connection between two
> systems, teams or parties · a design or process they chose · a migration,
> rollout or delivery · an improvement to something that already existed ·
> people they led · a number they moved

Three instructions carry the recall:

- **Do not choose between related claims.** A method sentence and its outcome
  sentence are two claims, verified by two different questions.
- **Several claims may share a claim type.** Expected and correct.
- **The importance number is for a later stage.** The claim-type menu labels a
  claim already chosen; it never decides whether to include one.

Prompt hash `9e19b40fca26` → `e5fb3734ca77`.

### `api/engine/extract.py`

`extract_claims()` — three filters run in **both** modes, and none is a ranking
decision: `verifiable=false`, text under 15 chars, and duplicate **text**
(`_dedupe_key`, a new helper: one sentence stated twice is one claim).
Inventory mode stops there. Legacy mode additionally keeps one claim per type
and sorts by importance weight.

**Update: no number reaches the model in inventory mode at all.** `$max_claims`
used to do double duty — *how many to propose* and *how many to keep* — and
even phrased as a soft ceiling ("stop at N only if more exist") it measurably
anchored the model: docs/EXTRACTION_ARCHITECTURE_REVIEW.md D1 found raising
the rendered ceiling from 12 to 40 raised the model's own count from 12 to 17
and 14 on two real resumes, meaning 12 was never a true count. The prompt now
renders `$stop_condition`, which in inventory mode is a fixed sentence — *"there
is no fixed number to return"* — carrying no digit; legacy mode is unchanged
and still renders a number. `ceiling` (`max_inventory_claims`, 60, raised from
12 for the same D1 reason) survives only as a Python-side, warning-logged
backstop against a pathological reply, replacing what was previously a silent
`candidates[:ceiling]` top-N. Resume order is preserved, so `Claim.order_index`
still means "where this appeared on the page".

`heuristic_claims()` — the offline fallback is production code and gets the same
treatment. Per docs/EXTRACTION_ARCHITECTURE_REVIEW.md §E3, inventory mode now runs a
boolean `_is_claim_line` predicate (no `MIN_CLAIM_SCORE` threshold, no
score-sort, no type gating, no top-N) instead of `_score_line`'s rank, and
keeps resume order. `_is_claim_line` also recognises implementation/
integration verbs (`integrated`, `developed`, `collaborated`, ...) that
`_score_line` never scored, which is what let a comma-heavy, verb-less
integration bullet get misread as a skills list and rejected outright rather
than merely ranked low (D2). Legacy mode is untouched.

### `api/config.py`, `.env.example`, `api/engine/provenance.py`

```python
claim_inventory: bool = False        # recall-first extraction
max_inventory_claims: int = 12       # safety ceiling, not a budget
```

Both are added to `provenance.FEATURE_FLAGS` because both move scores. That
changes `evaluation_version` for every evaluation, which is D7 working as
designed.

## Measured recall

Three resumes, three families, production `extract_claims()`:

| resume | family | legacy | inventory |
|---|---|---|---|
| Abhishek (frontend) | `software_engineering` | 3 | **12** |
| Arshad (PM) | `product` | 3 | **12** |
| Ankush (banca sales) | `sales` | 1 | **4** |

All six bullets from the worked example are now captured, including both halves
of the split pair — *"Designed customizable dashboards, analytics tools, reward
systems…"* and *"Improved customer conversion rate by 20%…"* come back as two
claims instead of one folded claim.

## BLOCKING — `api/engine/graph.py` (Developer B)

`build_candidate_graph` appends **every** claim to `scored_pairs`
(`graph.py:403`), and `_claim_score_under(None, …)` returns `0`
(`graph.py:178`). So an extracted-but-unprobed claim enters the weighted mean
as a zero at full weight. Measured with production
`scoring.weighted_evidence_score` on the traced candidate's two real claim
scores:

| inventory size | claims probed | competence | role_coverage |
|---|---|---|---|
| 2 | 2 | **69** | 35 |
| 3 | 2 | 40 | 60 |
| 4 | 2 | 32 | 75 |
| 6 | 2 | **24** | 100 |

Identical evidence, identical answers — the score falls because the denominator
grew. **This is why the flag defaults false.**

The argument for changing it is not that unprobed things should be free.
CLAUDE.md is deliberate that un-probed dimensions contribute 0, and that is
right: the dimension set is fixed at six, so the denominator is the same for
everyone. Claims are not fixed. Once extraction is recall-first the denominator
becomes a property of *how much the extractor found*, so two candidates with
identical verified evidence score differently because one wrote a longer
resume. That breaks comparability across candidates, which is what ranking is
for.

**The change B needs to make:** exclude claims with no `ClaimScore` row from
`scored_pairs`, keeping them in `claim_graphs` (so the recruiter still sees the
full inventory) and in the `role_coverage` numerator (which is about what they
*claimed*, and is already computed from `seen_types`). One guarded append.

## Interview budget — a real trade, not a bug

Production `plan_next` over inventories of N, `MAX_QUESTIONS=12`:

| claims | asked | breadth | depth | probed | never asked | deepest claim |
|---|---|---|---|---|---|---|
| 2 | 10 | 2 | 8 | 2 | 0 | 5 levels |
| 3 | 12 | 3 | 9 | 3 | 0 | 5 levels |
| 6 | 12 | 6 | 6 | 6 | 0 | 5 levels |
| 8 | 12 | 8 | 4 | 8 | 0 | 5 levels |
| **12** | 12 | **12** | **0** | 12 | 0 | **1 level** |
| 16 | 12 | 12 | 0 | 12 | **4** | 1 level |

The breadth phase gives every claim one VALIDATION probe before anything is
deepened. At 12 claims the interview is a pure sweep: every claim touched once,
nothing verified in depth. Beyond 12, claims are extracted and never asked
about at all.

So inventory mode does not by itself improve the interview — it improves the
**inventory**, which is the right thing to store, and it hands the planner a
real choice it never had. Getting value from that choice needs `plan_next` to
select which claims earn the breadth probe rather than probing all of them.
That is a separate change in `orchestrator.py` (A's file), not attempted here.

## Enabling it

1. B lands the `graph.py` guard above.
2. Decide the breadth policy for inventories larger than ~6 claims.
3. `CLAIM_INVENTORY=true`. Re-seed and re-dump the fixture; `evaluation_version`
   moves for every evaluation.
