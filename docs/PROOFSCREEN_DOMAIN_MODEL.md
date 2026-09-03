# ProofScreen — Domain Model Review

Fifteen entities, defined. Then the four things this review is actually for:
wrong table boundaries, wrong aggregate roots, ownership confusion, and what
breaks at scale.

Grounded in `api/models.py` as it stands. **Almost none of this should be acted
on before the demo** — the sequencing section says which single change is cheap
now and expensive later.

---

## Part 1 — The fifteen definitions

| Entity | Definition | Today | Verdict |
|---|---|---|---|
| **Person** | A human being, identified by a phone number. Exists once, forever, across every application and every customer | **Does not exist** | ❌ Missing — see F1 |
| **Candidate** | A *person in the context of one application*: this person, for this job, at this company | `candidates` — but it holds identity (`name`, `phone`, `email`) *and* application context (`job_family`, `role`, `role_id`) in one row | ⚠️ Conflated with Person |
| **Resume** | The document a candidacy starts from. Immutable once parsed | `resumes` — clean, append-only in practice | ✅ Correct |
| **Claim** | An assertion the resume makes that is worth testing, typed against a cohort's taxonomy. The **unit of verification** | `claims` | ✅ Correct — the strongest entity in the model |
| **Verification Session** | One conversation with one candidate over one channel: the interview. Owns questions, answers, facts and contradictions | `sessions` (`ChatSession`) | ✅ Correct aggregate root for the interview |
| **Question** | One probe at one level against one claim, inside one session | `questions` | ✅ Correct |
| **Response** | What the candidate said, in one modality, once. **The seam** between conversation and assessment | `responses` | ✅ Correct |
| **Signal** | One countable, verbatim-quoted item extracted from a response: a quantity, a process step, a causal chain, a tool, an incident. The **atom of the product** | JSON blob on `responses.signals_json` | ⚠️ Not an entity — see F5 |
| **Evidence** | Ambiguous term — see F5. Currently: a *dimension reading* derived from one response | `evidence` (one row per response × dimension) | ❌ Wrong name for what it holds |
| **Fact** | A typed value on a cohort's controlled vocabulary (`team_size = 35`), asserted at a point in the conversation. The memory consistency compares against | `session_facts` | ✅ Correct |
| **Contradiction** | A relation between **two Facts** on the same stable key that cannot both be true | `contradictions` — modelled as a property of a *Session*, storing values as strings rather than referencing the two facts | ⚠️ Wrong subject — see F4 |
| **Score** | Not one thing. Five things at three grains: answer, dimension, claim, candidate — plus `resume_score`, which is a deliberately different kind of number | Spread across `responses.answer_score`, `evidence.score`, `claim_scores`, `profiles` | ⚠️ Needs naming discipline, not restructuring |
| **Evaluation** | **A candidate's evidence assessed under one role's weights by one version of the system, at a point in time.** The thing a customer disputes | **Does not exist** — computed on the fly by `build_candidate_graph(candidate_id, role_id)` | ❌ Missing — the most important gap |
| **Profile** | Intended as a fast read-model of the default evaluation | `profiles` — but also holds `badge`, `status`, `scored_role_id` | ⚠️ Three jobs in one table — see F3 |
| **Cohort** | A job family: the taxonomy entry defining claim types, fact keys and weights for a kind of work | A bare string on `candidates`, `sessions`, and in the taxonomy JSON | ⚠️ No referential integrity, no version |
| **Role** | Overloaded three ways today — see F2 | `job_roles` + `candidates.role` + `candidates.role_id` | ❌ Three concepts, one word |
| **Recruiter** | A person who defines what matters for a job and reads the output | **Does not exist** | ❌ Missing |
| **Organization** | The company hiring. Owns jobs, role profiles and candidacies | **Does not exist** | ❌ Missing |
| **Tenant** | The isolation boundary. In practice, one Organization | **Does not exist** | ❌ Missing — the one to fix early |

---

## Part 2 — Structural findings

### F1. `Candidate` conflates Person with Candidacy — and it already breaks routing

`candidates` (`models.py:69-81`) carries identity (`name`, `phone`, `email`) and
application context (`job_family`, `role`, `role_id`) in one row. So the same
human applying twice becomes two rows with duplicated identity and no link
between them.

**This is not theoretical. It breaks WhatsApp routing today.** `phone` is
indexed but **not unique** (`models.py:74`), and
`find_active_session_by_phone()` resolves an inbound message by joining
`Candidate.phone` and taking the *most recent live session*. One person with two
open candidacies — two jobs at one company, or one job at two customers — has
their answers routed to whichever interview started later. Silently.

**Correct boundary:**
```
Person (phone unique, global)
  └── Candidacy (person × job × tenant)   ← what "Candidate" means today
        ├── Resume
        └── VerificationSession
```
WhatsApp resolves to a **Person**; the session is then disambiguated by which
candidacy has an open question, not by recency.

### F2. "Role" means three different things

| Where | What it actually is |
|---|---|
| `candidates.role` (free text, `"Support Team Lead"`) | The job title someone typed |
| `job_roles` (`title`, `claim_weights`, `dimension_weights`) | **A scoring lens** — how to weight evidence |
| `candidates.role_id` → `job_roles.id` | Implies the lens *is* the job applied to |

A **Job / Requisition** ("Support Team Lead at Northwind, 3 openings") and a
**Role Profile** ("weight team handling 25%, CSAT 20%") are different things with
different lifecycles. A job exists once; its weighting may be revised weekly, and
two recruiters may rank the same pipeline through two lenses — which is the
product's headline demo.

Collapsing them means you cannot express "re-rank this job's pipeline under a
different lens" without mutating the job, and cannot answer "which job did this
person apply to" independently of "how were they scored."

### F3. `Evaluation` is the missing aggregate — and it is the one everything else needs

Today an evaluation is **implicit**: `build_candidate_graph(candidate_id,
role_id)` computes it on demand and throws it away; `profiles` caches exactly one
of them (the default-role variant) and overwrites it in place.

That single absence is the root of four separately-identified problems:

| Problem found elsewhere | Actually the same problem |
|---|---|
| No provenance stamp (`PRODUCTION_READINESS.md` §1) | Nothing to stamp — an evaluation isn't a record |
| No score history (§2) | `profiles` overwrites; nowhere to append |
| Replay has no subject (§3) | `replay(evaluation_id)` needs an `evaluation_id` |
| Disputes have no referent (§9) | A recruiter disputes *an evaluation*, not a candidate |

**Make it an entity** and all four become schema, not architecture:

```
Evaluation
  candidacy_id · role_profile_id · taxonomy_version · rubric_version
  prompt_versions · code_sha · model · computed_at · evaluation_version (hash)
  weighted_evidence · competence · badge · consistency · role_coverage
  dimension_profile
```
Append-only. `Profile` then becomes what it was meant to be: **a pointer to the
latest evaluation**, not a mutable score store.

Note what this also fixes: `profiles.status` (`models.py:298`) currently
duplicates `sessions.state`. Two copies of one fact, free to drift.

### F4. `Contradiction`'s subject is wrong

A contradiction is a **relation between two Facts**. It is modelled as a property
of a Session that stores the two values as *strings* (`earlier_value`,
`later_value`) plus response ids — but no fact ids and no claim ids
(`models.py:258-274`).

Consequences: you cannot navigate from a contradiction back to the facts that
produced it; you cannot scope a contradiction to the claims involved (which is
exactly why claim-scoped consistency needed two new columns); and the values are
frozen strings that will not follow a correction if a transcript is ever fixed.

**Correct:** `Contradiction(earlier_fact_id, later_fact_id, severity, delta_pct)`
— claim scope and displayed values both derive from the facts.

### F5. "Evidence" is overloaded three ways — including by me, earlier in this project

| Usage | Means |
|---|---|
| `evidence` table | A **dimension reading** (score + basis + quotes) from one answer |
| "Evidence Graph" | The **whole tree** — claims, Q&A, dimensions, scores |
| `EvidenceNode` (in `IMPLEMENTATION_PLAN.md`) | An individual **signal item** with provenance |

I proposed an `evidence_nodes` table in this project while an `evidence` table
already existed meaning something different at a different grain. That is
precisely the ownership confusion this review is for, and it came from the word,
not from carelessness.

**Correct vocabulary:**
- **Signal** — one extracted item (quantity, step, chain, tool, incident)
- **DimensionReading** — what the `evidence` table actually holds
- **EvidenceGraph** — the assembled read model, and nothing else

Rename `evidence` → `dimension_readings`, and the word *evidence* is freed for
the concept the product is named after.

### F6. Cohort has no identity

`job_family` is a bare string denormalized onto `candidates` **and** `sessions`,
with a third derivation through `resolve_family()`. Three copies, no foreign key,
no version. Once taxonomies are versioned, `"software_engineering"` cannot
express *which* definition of that cohort scored this candidate — and a cohort
that gains a fact key silently changes the meaning of every historical score
that references it by name.

**Correct:** `Cohort(key, taxonomy_version)` as a referenced entity; sessions and
evaluations point at a specific version.

### F7. Minor integrity gaps

- `claims` carries both `resume_id` **and** `candidate_id` (`models.py:127-131`);
  the second is derivable, and nothing prevents them disagreeing.
- `session_facts` has no uniqueness on `(session, key, response)`; "earliest
  reading per key" is enforced in Python (`orchestrator.known_facts`), not the
  schema.
- `responses.signals_json` as a blob is correct for now, but it is the reason
  signals cannot be queried across candidates — the real constraint behind the
  deferred `evidence_nodes` idea.

---

## Part 3 — Target aggregates

Four roots, each owning a clear lifecycle:

```
Organization (tenant)
  ├── Job ──────────────► RoleProfile (the scoring lens; many per job, versioned)
  └── Candidacy (person × job)
        ├── Resume ──► Claim*          [what we test]
        ├── VerificationSession        [the interview: questions, responses,
        │     └── Response ──► Signal*  facts, contradictions]
        └── Evaluation*                [assessment under one lens, one version,
                                        one point in time — append-only]

Person (global, phone-unique, crosses tenants by identity only, never by data)
```

**Aggregate rules:**
1. **VerificationSession owns the conversation.** Questions, responses, facts and
   contradictions are meaningless outside it.
2. **Claim owns what is being tested.** It outlives any single session.
3. **Evaluation owns the assessment.** Immutable, versioned, disputable.
   Re-ranking creates a new Evaluation; it never mutates an old one.
4. **Person crosses tenants; nothing else does.** A person is one human globally,
   but their evidence, scores and even the fact of their candidacy stay inside
   the organization that collected them.

That last rule is where the domain model and multi-tenancy meet, and getting it
wrong is a data-leak class of bug rather than a modelling preference.

---

## Part 4 — What to do, and when

Consistent with every other review in this repo: almost nothing now.

| When | Change | Why then |
|---|---|---|
| **Now** (afternoon) | `tenant_id` on every table | Same argument as `PRODUCTION_READINESS.md` §6 — the only change whose cost multiplies with data |
| **Now** (free) | Adopt the vocabulary: **Signal / DimensionReading / EvidenceGraph**, in docs and new code | Costs nothing today, prevents the confusion in F5 from being designed into the next feature |
| **Before customer 1** | `Organization` · `Recruiter` · split `Job` from `RoleProfile` (F2) | A customer *is* an organization; the model cannot represent one |
| **With customer 1** | `Evaluation` as an entity (F3); `Profile` becomes a pointer | Unblocks provenance, history, replay and disputes in one change |
| **When one person can hold two candidacies** | Split `Person` from `Candidacy` (F1) | The routing bug is dormant while every phone maps to one candidacy — and fires the day it doesn't |
| **With claim-scoped consistency** | Re-point `Contradiction` at two facts (F4) | Already a prerequisite for that feature |
| **With versioned taxonomies** | `Cohort` as an entity (F6) | Meaningless until taxonomies are versioned |
| **Rename** `evidence` → `dimension_readings` | With the next schema reset | Free while `create_all()` + `down -v` is the migration story; a migration afterwards |

**The compounding item is the vocabulary, not the schema.** F5 cost this project
a proposed table that duplicated an existing one at a different grain, and that
happened inside a single week. Fixing the words is free today and gets
expensive in proportion to how much code adopts the wrong ones.

**The dormant bug is F1.** One phone, two open candidacies, answers routed by
recency. It cannot fire while the demo has one candidacy per person — and it
fires quietly the first week a real customer runs two requisitions.
