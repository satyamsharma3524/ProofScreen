# ProofScreen — Production Readiness

Post-demo. Nothing here belongs in the current sprint; the sequencing section at
the end applies your own rule — *don't build infrastructure for hypothetical
cohort #83* — to this list itself.

**Only one item on this page is cheap now and expensive later.** The rest can
wait for a customer to ask.

---

## What I changed about the original outline

| # | Change | Why |
|---|---|---|
| 1 | **Sections 1, 2, 3 and 11 collapse into one provenance record** | Evaluation version, taxonomy version and prompt version are *fields in* Decision Provenance, not four systems. Presenting them separately implies four pieces of infrastructure when it is one stamp |
| 2 | **Store components; derive the composite** | `eval_v3` answers *"was this the same system?"* but not *"what changed?"* A recruiter asking why 82 became 71 needs the diff, not the label. Version the parts, hash them into the composite |
| 3 | **Replay is already ~80% built — and full replay is impossible** | See §3. This is the biggest correction |
| 4 | **The event model is mostly a rewrite of working tables** | See §5 |
| 5 | **Three sections are missing, and one of them is a legal gate, not a feature** | See §7–§9 |

---

## 1. Decision provenance *(absorbs original §1, §2, §3, §11)*

Every evaluation carries one immutable stamp:

```json
{
  "taxonomy_version":  "tax_v8",
  "prompt_versions":   { "extract_claims": "v4", "extract_signals": "v12", "generate_question": "v7" },
  "rubric_version":    "rub_v3",
  "scoring_version":   "score_v2",
  "dimension_version": "dim_v1",
  "code_sha":          "032943e",
  "model_requested":   "…",
  "model_returned":    "…",
  "evaluated_at":      "…",
  "feature_flags":     ["ADAPTIVE_PROBING", "TRANSFER_PROBE"],
  "evaluation_version": "eval_a91c…"
}
```

`evaluation_version` is a **hash of the fields above**, not a hand-maintained
counter. Two evaluations are comparable if and only if their hashes match, and
when they differ the components say *which* dimension of the system moved.

Two details that are easy to get wrong:

- **Store `model_returned`, not just what you asked for.** Providers alias model
  names; "the model we requested" and "the model that answered" diverge, and the
  divergence is exactly what you need when explaining drift.
- **Feature flags are part of the evaluation.** `ADAPTIVE_PROBING=false` produces
  a materially different interview. A provenance record without flags is
  incomplete.

**Prompts are product, not implementation.** This project already proved it
empirically: three prompt templates carried BPO-only worked examples, which
biased extraction for every non-BPO cohort on the primary path. A prompt edit
can move scores as much as a rubric change, so it must be versioned as tightly.

## 2. Audit trail — ~70% already exists

Reconstructing *"why is this candidate ranked #2"* needs: resume → claims →
questions → answers → signals → dimension scores → claim score → rank. Today the
schema already stores every link: `resumes`, `claims`, `questions`, `responses`
(with `signals_json`), `evidence` (one row per answer × dimension, with verbatim
quotes), `session_facts`, `contradictions`, `claim_scores`, `profiles` — all
timestamped, all foreign-keyed.

**The gaps are narrow:** `claim_scores` and `profiles` are updated in place
rather than appended, so a score's history is lost; and nothing carries the
provenance stamp from §1.

**Recommendation:** append-only `claim_score_history` + provenance columns.
That is a schema change, not an architecture. Do **not** rebuild this as event
sourcing to get something you already have.

## 3. Replayability — scope it correctly or it becomes unbuildable

**Full replay is impossible and promising it is a mistake.** LLM extraction is
non-deterministic even at temperature 0, and models are deprecated on the
provider's schedule, not yours. Any commitment to "re-run the March evaluation
and get March's output" will eventually be broken by someone else's release.

**But that is not what disputes are about.** Nobody argues about whether the
model saw three quantities — the quotes are right there, verbatim, stored.
People argue about **why three quantities produced 62.**

That part is *fully deterministic and already built*: signals are persisted
verbatim on `responses.signals_json` precisely so a claim can be rescored
without calling the model again — which is what makes live re-ranking work
today. So the honest, achievable contract is:

> **Extraction is recorded. Everything downstream of extraction is replayable.**

`replay(evaluation_id, versions=…)` re-runs rubrics, weights and consistency
over stored signals under any version set, and diffs against the original. That
covers 100% of the scoring-dispute surface, needs no model call, and is close to
free given the existing architecture. Scope the promise there and it is a
feature; scope it at the model and it is a liability.

## 4. Calibration and percentiles — three traps

Raw + percentile is right. The traps:

- **Percentiles need a population.** Customer one, cohort one, candidate one is
  in the 50th percentile of a sample of two. Define a **minimum n** (say 30)
  below which percentile is withheld, not estimated.
- **Which population?** Within-tenant percentiles are comparable to nothing;
  cross-tenant percentiles are more useful but expose the shape of other
  customers' candidate pools. Aggregate-only disclosure is probably fine, but it
  is a *decision*, not a default — and it interacts with §6.
- **Cross-cohort comparability is not free.** An 80 in engineering and an 80 in
  BPO are produced by different gates and weights. Percentile *within cohort* is
  the only honest early framing; a single global score ladder needs calibration
  work that has not been done.

## 5. Event model — derive before you dual-write

Events are the right long-term backbone, but "record `ResumeUploaded`,
`ClaimExtracted`, `QuestionAsked`…" today means doubling every write path in the
turn loop, which is the latency-sensitive part of the product.

Check the actual analytics questions against the current schema first:

| Question | Answerable today? |
|---|---|
| How many started / finished? | Yes — `sessions.state`, `completed_at` |
| Dropoff after question #3 | Yes — `questions` vs `responses` per session |
| Average score by role | Yes — `claim_scores` + `job_roles` |
| Most common weak dimension | Yes — `claim_scores.dimensions_json` |
| Median interview duration | Yes — `started_at` / `completed_at` |
| Score distribution | Yes — `profiles` |

**Every question on the original list is answerable from existing tables.** So
the event model earns its place when a question arrives that *isn't* — most
likely a behavioural one ("how long did candidates hesitate before abandoning").
Until then, derive events from timestamped rows and keep the write path thin.

## 6. Multi-tenancy — **the one thing to do early**

Add `tenant_id` to every table now.

The cost curve is the steepest on this page. Today: no Alembic, no production
data, `create_all()` at startup, `docker compose down -v` to reset — so
`tenant_id` is a column addition and a query-filter pass, on the order of an
afternoon. After the first customer's 500 resumes, it is a data migration, a
backfill, an access-control audit, and a period where cross-tenant leakage is a
live bug rather than an impossibility.

Related and currently absent: **there is no authentication at all.** That is a
deliberate, documented hackathon decision — but it means the deployed URL
exposes every candidate's evidence graph to anyone who finds it. Tenancy without
auth is decoration, so these two ship together or not at all.

## 7. *(missing)* Data protection — a legal gate, not a feature

This is a hiring product processing personal data of Indian candidates: names,
phone numbers, resumes, WhatsApp messages, **voice recordings**. India's DPDP
Act 2023 applies, and hiring is one of the most scrutinised processing contexts
there is.

Currently unaddressed: lawful basis and consent capture (the opt-in code
establishes contact, not informed consent to automated evaluation), purpose
limitation, retention and deletion, the candidate's right to access and erase,
and processor obligations to customers who will demand a DPA before signing.

**This outranks replayability and calibration.** Those are features a customer
asks for; this is a condition of selling at all, and it is the section an
enterprise buyer's legal team opens first.

## 8. *(missing)* Adverse-impact monitoring — evidence for the core claim

The product's central promise is that it does not score accent, fluency,
grammar, polish or region. Today that is enforced by *design* — no presentation
signal reaches the score, and there is a test asserting a blunt specific answer
beats a polished vague one.

**Design intent is not evidence.** Once real candidates flow through, the claim
becomes measurable and therefore contestable: score distributions by region,
language of answer, text vs voice, and any proxy a customer's counsel thinks to
ask about. A product that markets itself as bias-reducing and cannot show its
own distributions is in a worse position than one that never claimed it.

Build the measurement before someone demands it — the four-fifths rule is the
lens most legal teams will reach for, whatever jurisdiction they cite.

## 9. *(missing)* Candidate rights and dispute path

The candidate is the data subject and, per the product vision, the long-term
beneficiary — but has no way to see their own evidence profile, flag a
misheard transcript, or contest an evaluation. Voice transcription errors are
the obvious near-term failure: a wrong number in a transcript becomes a
"contradiction" and multiplies down a real person's score.

Minimum viable version: the candidate can view their own graph and flag a
transcript, and a flag suppresses the derived contradiction pending review.
Cheap, and it converts the product's fairness story from a claim into a
mechanism.

## 10. Explainability — already the strongest thing in the product

Nothing to build; something to protect. The current API already returns, per
claim: dimension scores with `basis` strings naming the counts behind them
(`"6 quantities, 5 named entities"`), gate explanations (`"capped at 55: no
quantity given"`), verbatim quotes, extracted facts, and every Q&A turn. That is
already an evidence-backed score rather than an opaque one.

**The rule to hold:** every number a recruiter sees must be reconstructible from
stored rows without a model call. Any future feature that cannot meet that bar —
an embedding-based similarity score, a learned ranker — is a different product
and must be labelled as such in the UI, not blended into the competence score.

---

## Sequencing, by cost curve rather than value

| When | Item | Why then |
|---|---|---|
| **Now** (afternoon) | `tenant_id` on every table | Only item whose cost multiplies with data. Free today, a migration project later |
| **Before customer 1** | Auth · §7 data protection basics (consent, retention, deletion) | Conditions of selling, not features |
| **With customer 1** | §1 provenance stamp · §2 append-only score history | The first "why did this change?" arrives with the first re-run |
| **With customer 3** | §3 replay-from-stored-signals · §10 hardening | Disputes need a population to arise from |
| **With cohort 10+** | §4 percentiles (once n ≥ 30) · §8 adverse-impact monitoring | Both need volume to mean anything |
| **When a question demands it** | §5 event model | Every analytics question on the list is answerable from current tables |
| **When the candidate side ships** | §9 rights and dispute path | Needs a candidate-facing surface to live in |

**The honest summary:** of eleven proposed systems, one should be built now
(`tenant_id`), two are legal gates rather than engineering work (§7, §8), one is
already 70% built (§2), one is already 80% built and should be scoped down
rather than up (§3), and one is a rewrite of tables that already answer the
questions it would answer (§5). The remainder are real, and none of them matter
until the verification signal itself is proven valuable.
