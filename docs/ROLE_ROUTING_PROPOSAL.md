# Role-family routing — root cause, and a two-rung fix

Measured 2026-09-06 against `ea0f76a` on the nine files in `resume_test/`.
Scope is routing only: the interview engine, claim extraction and scoring are
not redesigned.

---

# 1. The measurement

One header-slice LLM call, `gpt-4o` at temperature 0, against the current
keyword router. Human label is what a recruiter would say.

| Resume | Human | Taxonomy | Margin | LLM | LLM saw |
|---|---|---|---|---|---|
| Deloitte | product | `data_analytics` ✗ | 0.121 | **product** ✓ | "Product Lead – Pync" |
| Nykaa PM | product | `sales` ✗ | **0.591** | **product** ✓ | "Product Lead" |
| PM | product | `sales` ✗ | 0.323 | **product** ✓ | "Product Lead – Pync" |
| Glean PM | product | `data_analytics` ✗ | 0.121 | **product** ✓ | "Product Lead – Pync" |
| Livspace SrPM | product | `sales` ✗ | 0.033 | **product** ✓ | "Product Lead – Pync" |
| Nike | product | `product` ✓ | 0.031 | **product** ✓ | "Product Lead – Pync" |
| Ankush (banca) | general | `general` ✓ | 0.000 | **general** ✓ | no title in file |
| Sathiya (Java) | software_engineering | `software_engineering` ✓ | 0.529 | **software_engineering** ✓ | "Java Developer" |

**Taxonomy 3/8. Header-slice LLM 8/8.**

Ankush is the interesting agreement: both say `general`, and both are right —
his file genuinely carries no job title, only a career objective. The LLM
returned confidence 0.2 and `current_title: "Not specified"`, which is the
honest answer rather than a guess.

---

# 2. Root cause

## 2.1 The router scores vocabulary, and a PM's vocabulary is a salesperson's

[`match_family`](api/taxonomy.py#L365) sums IDF-weighted keyword hits per family
and divides by a per-family norm. On the Nike resume:

```
sales 2.017 · product 1.500 · data_analytics 1.442 · hr_recruitment 0.516
matched: sales, target, pipeline, conversion, revenue, arr, funnel, b2b
```

Every one of those eight terms appears in a product manager's resume for
legitimate reasons. The router has no way to know that `revenue` in
*"scaled revenue to ₹40 Lakhs"* is a PM reporting an outcome, while `revenue`
in *"managed $40M yearly revenue"* is an account manager describing their book.

`_idf()` cannot help: its own docstring records that **105 of 106 terms belong
to exactly one family**, so IDF is very nearly uniform and adds almost no
discrimination.

## 2.2 The damage is done at claim extraction, not at routing

This is the part that matters, and it is why the ordering in the brief needs
changing. [`extract_claims`](api/engine/extract.py#L163) routes **first**, then
builds the extraction prompt with `claim_type_menu(routed)`:

```python
routed = supplied if supplied != GENERAL else detect_family(trimmed)
prompt = load_prompt("extract_claims", family_key=routed,
                     claim_type_menu=claim_type_menu(routed), ...)
```

A resume routed to `sales` is handed the sales claim-type menu —
`quota_performance`, `deal_closing`, `account_management`, `pipeline_ownership`
— and asked to find claims that fit it. It obliges, from the only sales job on
the page. That is exactly what we observed: four of six PM resumes produced
claims from **ExxonMobil**, and the interview then asked about rebate contracts
and territory size.

**So the family must be decided BEFORE claim extraction.** The brief's pipeline
puts the classifier after it:

```
Resume → Claim extraction → Fast taxonomy → LLM role classifier → …   ✗
```

By then the claims already exist, typed against the wrong menu. Re-routing
afterwards would leave sales claims wearing product labels, which is worse than
the current behaviour because it looks correct.

## 2.3 The existing LLM family signal is contaminated by construction

`ClaimExtraction` already carries a `job_family`, and
[extract.py:205-217](api/engine/extract.py#L205-L217) deliberately discards it:

> *"The model still returns a family because the prompt still asks for one — it
> is a useful disagreement signal … It is observed, not obeyed."*

It has never been a useful signal, and the prompt is why.
[`extract_claims.txt:39`](api/prompts/extract_claims.txt) hands the model the
answer inside the response template:

```
"job_family": "$family_key",
```

The model is shown the taxonomy's verdict as the value to emit, and unsurprisingly
emits it. **Promoting the existing signal would promote an echo.** The new call
has to be a separate one, on different input, with nothing pre-filled.

---

# 3. Two corrections to the brief

## 3.1 `confidence` is a MARGIN, not a probability — and it does not predict correctness

[taxonomy.py:306-310](api/taxonomy.py#L306-L310) says so explicitly:

> *"`confidence` is a MARGIN, not a probability: how far the winner is clear of
> the runner-up … It answers 'was this close?' … **It is not a claim about being
> right.**"*

So "Nike PM → product (0.031)" does not mean *3% sure it is product*. It means
*product won by 3%* — and product was **the right answer**. Nike is the router's
best result on this sample, not its worst.

Sorted by margin against correctness on the eight:

```
0.591  sales                 WRONG      ← the most confident answer is wrong
0.529  software_engineering  right
0.323  sales                 WRONG
0.121  data_analytics        WRONG
0.121  data_analytics        WRONG
0.033  sales                 WRONG
0.031  product               right      ← the least confident answer is right
0.000  general               right
```

Above the floor: 1 of 2 correct. Below it: 2 of 6. **The margin carries no
signal about correctness here, and on this sample it mildly anti-correlates.**

**Therefore the proposed middle rung must go:**

```python
elif taxonomy_confidence >= 0.6:      # ✗ trusts Nykaa (0.591, WRONG)
    trust_taxonomy()                  #   and distrusts Nike (0.031, RIGHT)
```

That rung would have kept four of the five broken PM resumes broken. Taxonomy
belongs in the design as the **fallback when the model is unavailable**, not as
a confidence-gated peer.

## 3.2 Rule 1 forbids parsing a confidence out of a model response

CLAUDE.md, non-negotiable rule 1:

> *"If you find yourself parsing a rating, **confidence** or percentage out of a
> model response, stop."*

The proposed `if llm_confidence >= 0.8` is precisely that. One could argue
routing is not a competence score and the rule is about scoring — but the rule
is written without that carve-out, two tests enforce the surrounding invariant,
and a hackathon is a poor moment to litigate a non-negotiable.

**Resolution: do not read the model's confidence.** Take its `family` and
nothing else. We do not need the number — the measurement above shows the model
is right 8/8 including the case where it should abstain, and it abstains by
returning `general`, which is a *family*, not a score. Ask for `confidence` and
`seniority` anyway, log them, and let the field earn its way in later with data
behind it.

---

# 4. Proposed architecture

## 4.1 The pipeline

```
Resume text
   │
   ├─ header_slice()          deterministic Python, no model
   │      headline · job titles with date ranges · summary · skills
   │
   ├─ RUNG 1  requisition job_family        (unchanged, P1-07)
   ├─ RUNG 2  classify_role()  LLM #0       ← NEW
   ├─ RUNG 3  detect_family()  taxonomy     (today's rung 2, now the fallback)
   └─ RUNG 4  general
   │
   ▼
family  ──→  claim_type_menu(family)  ──→  claim extraction (LLM #1)
                                              │
                                              ▼
                                       interview generation
```

Routing precedence stays a single ordered list decided in one place, which is
what P1-07 established. It gains one rung; it does not gain arithmetic.

## 4.2 Why no hybrid arithmetic

The brief's `trust_llm / trust_taxonomy / route_to_general` is three branches
and two thresholds to tune, with §3.1 showing one threshold is actively
harmful. An ordered precedence list is the same idea with the tuning removed,
and it is the shape the file already uses.

`complete_json(..., fallback=...)` makes the degradation automatic: model down,
timeout, or unparseable → the taxonomy answer, which is exactly today's
behaviour. That satisfies rule 5 with no extra code.

## 4.3 What the model sees

Not the claims, and not the whole resume — the recruiter's first ten seconds:

```
HEADER:            first 5 non-empty lines (name, contact, headline)
JOB TITLES:        every line adjacent to a date range, in resume order
SUMMARY / SKILLS:  the named sections, 6 lines each
```

Capped at 1800 characters. The body — where the GTM and revenue language lives
— is deliberately excluded, because that language is the cause.

Sending less is also cheaper and faster than the body: ~500 tokens against
`MAX_RESUME_CHARS`.

## 4.4 `routing_confidence` needs no change, and this is not luck

`CandidateGraph.routing_confidence` is a frozen field
([schemas.py:401](api/schemas.py#L401)) computed by
[`family_margin(match, family)`](api/taxonomy.py#L404) — *"how clearly the
resume belongs to `family_key` — **not to the winner**"*.

That function exists **because P1-07 already introduced an external router that
overrides detection** (the requisition). Its docstring names the exact case:
Priya and Arjun are scored `bpo_operations` while the detector prefers
`customer_support`. An LLM rung is the same situation with a different source.

So the field keeps meaning what it already documents: *the keywords point at
this cohort this clearly*. Nike would still read 0.031 — and now that would be
a true and useful statement: **"we routed this to product on the title, and the
vocabulary does not corroborate it."** That is a better recruiter signal than
today's, not a worse one.

**No frozen field changes. No `FamilyMatch` change. No cross-stream contract change.**

---

# 5. Exact files

| File | Owner | Change | Lines |
|---|---|---|---|
| `api/prompts/classify_role.txt` | A | **new** — the classifier prompt | ~30 |
| `api/engine/extract.py` | A | `header_slice()`, `classify_role()`, one rung in `extract_claims` | ~70 |
| `api/config.py` | shared | `role_classifier: bool = True` | 3 |
| `tests/test_taxonomy.py` | — | routing tests | ~60 |

**Not touched:** `api/schemas.py` · `api/taxonomy.py` · `api/prompts/extract_claims.txt`
· `api/engine/signals.py` · `scoring.py` · `question.py` · `orchestrator.py` ·
`graph.py` · every router.

`taxonomy.py` staying untouched is the point: the keyword scorer is not the
problem to fix, it is the fallback to preserve.

## 5.1 One provenance consequence, stated up front

[`prompt_versions()`](api/llm.py#L92) **discovers prompts by globbing the
directory** — *"so a new prompt is versioned the moment it exists instead of the
moment somebody remembers"*. Adding `classify_role.txt` therefore changes
`prompt_versions`, which is hashed into `evaluation_version`.

That is correct behaviour, not a problem: evaluations finalized before the
change keep their stored hashes and **replay unchanged**, and evaluations after
it get a new `evaluation_version` because they were produced by a materially
different pipeline. Expect `/api/dev/provenance` to show a new `evx_...` and do
not treat it as a regression.

## 5.2 Seniority: return it, log it, do not store it

The classifier should return `seniority` — it is nearly free and it is useful
for the next iteration. **Do not persist it this week.** There is no column for
it, and CLAUDE.md rule 7 means adding one is `docker compose down -v`, a re-seed,
and an edit to `db._REQUIRED_COLUMNS`. Nothing consumes it yet, so the cost is
all downside. Log it on the routing line and revisit after the demo.

---

# 6. Minimal implementation

## 6.1 `api/prompts/classify_role.txt`

```
You are a recruiter deciding which job family a candidate should be INTERVIEWED
as. Not which words appear most often — what profession this person IS, judged
the way a recruiter judges it: the current title first, then the arc of recent
titles, then the summary they wrote about themselves.

A product manager who came from sales will still write about revenue, GTM and
pipeline. That does not make them a sales person. Weight the TITLE above the
vocabulary of the achievements.

Pick exactly one family:
$family_menu

Use "general" only when the titles genuinely do not fit any family. A resume
with no job title at all is "general" — do not infer one from an objective.

RESUME HEADER
$header

Return ONLY this JSON:
{"family": "<key>", "confidence": <0.0-1.0>, "seniority": "<junior|mid|senior|lead|director>", "current_title": "<title or 'not stated'>", "reasoning": ["<line from the resume>", "<line from the resume>"]}
```

Note `$family_menu` and `$header` — `string.Template`, not `str.format`, because
the template contains a literal JSON schema full of braces.

## 6.2 `api/engine/extract.py`

```python
_DATE_RANGE = re.compile(r"(19|20)\d{2}\s*[-–—]\s*((19|20)\d{2}|present|current)", re.I)
_SECTION = re.compile(
    r"^\s*(professional\s+summary|summary|profile|objective|core\s+skills|"
    r"skills|technology\s+stack.*|technical\s+skills)\s*:?\s*$", re.I)


def header_slice(text: str, max_chars: int = 1800) -> str:
    """Headline, job titles and the summary/skills sections. No model call.

    The BODY is deliberately excluded. A product manager's achievements are
    written in revenue, GTM and pipeline language, which is the exact vocabulary
    that routes them to sales -- so the fix is not to weigh the body better, it
    is not to send it.
    """
```

```python
class RoleClassification(BaseModel):
    """Local to extract.py -- NOT api/schemas.py, which is frozen and is the
    contract with the dashboard. Nothing outside this module reads it."""
    family: str | None = None
    confidence: float | None = None      # logged, never branched on -- rule 1
    seniority: str | None = None
    current_title: str | None = None
    reasoning: list[str] = Field(default_factory=list)


async def classify_role(resume_text: str, taxonomy_family: str) -> str:
    """LLM #0. Which profession should this person be interviewed as?

    Falls back to the taxonomy's answer, which is what routing did before this
    existed -- so the model being down costs accuracy, never the interview.
    """
    if not settings.role_classifier:
        return taxonomy_family
    header = header_slice(resume_text)
    if len(header) < 40:
        return taxonomy_family           # nothing to classify on
    result = await complete_json(
        load_prompt("classify_role", family_menu=_family_menu(), header=header),
        RoleClassification,
        temperature=0.0,
        fallback=lambda: RoleClassification(family=taxonomy_family),
    )
    chosen = resolve_family(result.family) if result.family else taxonomy_family
    log.info(
        "role classifier: %s (title=%r seniority=%s self-reported conf=%s) "
        "vs taxonomy %s",
        chosen, result.current_title, result.seniority, result.confidence,
        taxonomy_family,
    )
    return chosen
```

The routing rung in `extract_claims`, replacing one line:

```python
supplied = resolve_family(job_family) if job_family else GENERAL
if supplied != GENERAL:
    routed = supplied                                    # rung 1, requisition
else:
    detected = detect_family(trimmed)                    # rung 3, the fallback
    routed = await classify_role(trimmed, detected)      # rung 2, the model
```

Rung 4 is already there: `resolve_family` returns `GENERAL` for anything
unrecognised, and the classifier is told to answer `general` when the titles do
not fit.

## 6.3 `api/config.py`

```python
# Route on the candidate's TITLE via one extra model call, falling back to the
# keyword scorer. false reproduces pre-change routing exactly.
role_classifier: bool = True
```

The flag is the rollback lever and the A/B switch. `ROLE_CLASSIFIER=false`
restores today's behaviour with no deploy.

## 6.4 Cost

One extra call per candidate, ~500 input tokens, at onboarding only — never per
turn. Against the 12-question interview it is under 3% of a candidate's spend.
It lands inside the G7 acknowledgement window (§2.7 of the build order), so the
candidate sees no new silence.

---

# 7. Migration plan

Nothing to migrate. No schema change, no data backfill, no stored routing to
rewrite.

| Concern | Position |
|---|---|
| Existing candidates | Family is stored on `candidates` / `sessions` and is not recomputed. Old rows keep their routing. |
| Finalized evaluations | Replay reads **stored** provenance hashes, so they replay unchanged. Verified by `scripts/replay.py --all`. |
| Seeded demo | `seed.py` passes `job_family` explicitly → rung 1 → **classifier never fires**. §0's numbers cannot move. Confirm with `seed.py --reset`. |
| Fixture mode | `settings.llm_enabled` false → `complete_json` returns the fallback → taxonomy. The 465-test suite routes exactly as today. |
| Rollback | `ROLE_CLASSIFIER=false`. |

**Rollout order**

1. Land behind the flag, default `false`. Full suite green, `seed.py` unchanged.
2. Flip to `true` locally. Re-run the nine resumes through
   `scripts/demo_resume_flow.py`; confirm 8/8 and that claims now come from the
   product roles.
3. `scripts/replay.py --all` → every pre-change evaluation still MATCHes.
4. Default `true`.

---

# 8. Test plan

**Deterministic, no model — these run in the 465-suite.**

| Test | Asserts |
|---|---|
| `test_header_slice_keeps_titles_and_drops_the_body` | a resume whose body is full of `revenue/pipeline/quota` yields a slice containing the title and none of those terms |
| `test_header_slice_survives_a_resume_with_no_sections` | Ankush's shape — no title, no summary — returns < 40 chars and the caller falls back |
| `test_the_classifier_is_skipped_when_a_requisition_supplies_a_family` | rung 1 still wins; P1-07 intact |
| `test_fixture_mode_routes_exactly_as_the_taxonomy_does` | `llm_enabled=false` → identical family for all 64 golden entries |
| `test_role_classifier_false_reproduces_prior_routing` | the flag is a true no-op |
| `test_an_unrecognised_family_from_the_model_becomes_general` | `resolve_family` guards a hallucinated key |
| `test_the_classifier_confidence_is_never_branched_on` | AST scan of `extract.py`: no comparison operator applied to `.confidence` — rule 1, enforced structurally like the two tests that already do |

**Measured, outside the suite** — `scripts/demo_resume_flow.py`, the nine files,
recorded in this document. Re-run before the demo:

| Gate | Today | Required |
|---|---|---|
| Correct family, 8 parseable resumes | 3/8 | **≥ 7/8** |
| PM resumes whose claims come from a product role | 1/6 | **≥ 5/6** |
| Seeded personas' families | unchanged | **unchanged** |
| `scripts/replay.py --all` | MATCH | **MATCH** |

The second row is the one that matters. Routing is not the deliverable — the
questions are, and a correct family is only worth something if the claims move
with it.

---

# 9. What this does not fix

- **`.rtf` is still rejected.** `ingest/parse.py` accepts `.pdf/.docx/.txt/.md`,
  and one of the three real Shine resumes is `.rtf`. Unrelated to routing, real
  for a demo, not addressed here.
- **A resume with no job title still routes to `general`.** Ankush's file has a
  career objective and no title, and both routers agree it is `general`. That
  is correct — inferring a profession from an objective is guessing — but it
  means a thin interview. A `general` route is a signal to the recruiter, not a
  bug to patch.
- **Taxonomy accuracy is unchanged.** The keyword scorer still gets PM resumes
  wrong; it is now the fallback rather than the decision. Retuning it is a
  separate piece of work and, per counter-metric C6, not one to do reactively
  against nine files.
