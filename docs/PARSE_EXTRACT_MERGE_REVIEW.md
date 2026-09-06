# Review — merging claim extraction into parsing

**Verdict: reject the merge. Adopt option D.** The proposal correctly
identifies a real architectural defect and prescribes a change that would not
fix it, while costing determinism, offline seeding, one of the two ingest
paths, and failure isolation.

---

## 0. The premise does not hold in this codebase

> "We already send the entire resume to an LLM during parsing. The parser
> already extracts structured experience, projects, achievements, skills,
> companies, dates, etc."

`api/ingest/parse.py` is 93 lines. It imports `io`, `logging`, `re`, `pathlib`,
plus PyMuPDF and python-docx. **There is no model call and no structured
extraction anywhere in it.** Its entire public surface is
`extract_text(filename, data) -> str`, and its only transformation is
`normalise()` — CRLF, whitespace runs, blank-line collapse.

The four `complete_json` call sites in the whole system:

| Call | Site |
|---|---|
| LLM #0 `classify_role` | `extract.py:353` |
| LLM #1 `extract_claims` | `extract.py:437` |
| LLM #2 `generate_question` | `question.py:769` |
| LLM #3 `extract_signals` | `evidence.py:341` |

Parsing is not among them. Every one of the proposal's five reasoning bullets
rests on the first two, and both are false here:

- *"We already send the entire resume to an LLM during parsing"* — we do not.
- *"The parser already extracts structured experience… companies, dates"* — it
  does not. No company or date field exists anywhere in the system; that gap is
  already recorded in `RESUME_PIPELINE_TRACE.md` §Stage 5.
- *"Running a second LLM call may be redundant"* — it is not a *second* call.
  It is the first and only one that reads the resume body.

**Measured saving from the merge: zero calls.** Parsing costs **80 ms** and no
tokens. Merging does not remove a model call; it adds one to a stage that has
none and removes one from a stage that has one.

---

## 1. Separation of concerns — is extraction part of parsing?

No. They are opposite operations.

| | Parsing | Claim extraction |
|---|---|---|
| Objective | **Lossless** transcription | **Lossy** interpretation |
| Correctness | Byte-faithful to the document | Judgement about what is falsifiable |
| Determinism | Pure function of the file | Model output, temperature-dependent |
| Failure | The file is unreadable | The reasoning was wrong |
| Re-runnable | Only by re-uploading | Any time, over stored text |

The last row is the architecturally decisive one. `Resume.raw_text` is a
**durable artifact**: a pure function of the uploaded bytes, stored once,
stable forever. Claims are **derived** from it. Today you can re-run discovery
over stored `raw_text` with a new prompt and compare — which is exactly what
`scripts/replay.py` and the D7 provenance stamps exist to support.

Merging collapses the durable artifact into the derived one. `raw_text` would
become a model output, versioned by prompt hash, non-reproducible across a
prompt edit, and no longer a stable substrate to re-extract from. That is a
one-way door and it is the single strongest reason to reject.

## 2. Recall — would merging improve it?

No, and it would probably reduce it, because the two objectives fight inside
one completion.

The parse objective is *keep everything*. The extraction objective includes
`REJECT FLUFF` and `Also reject job-title headings and skill lists` — the
extractor is explicitly told to **discard**. A single prompt asked to be both
lossless and selective will resolve the contradiction somewhere, and you will
not know where. Worse, the discarding is invisible: with parsing separate, a
dropped claim is still in `raw_text` and recoverable. Merged, it is gone from
the only record.

Second-order: output length becomes the shared constraint. Structured parse
output (companies, dates, sections, skills) and a 17-claim inventory compete for
the same completion budget. Under pressure the model truncates *something*, and
nothing in the schema says which.

## 3. Routing dependency — the one place the proposal is right

**Claim extraction does not need routing, and the current coupling is a real
defect.** `extract_claims` renders `claim_type_menu(routed)` into the prompt,
and `extract.py:184` says so plainly: the menu *"decides which claims the model
is allowed to find."* For an inventory-first architecture that is backwards —
routing should constrain **labelling**, never **discovery**. The proposal's
instinct to unblock extraction from routing is correct.

But two things are lost if routing simply moves after extraction as drawn:

- **`claim_type` cannot be assigned**, and `models.Claim.claim_type` is
  non-nullable. `create_all()` cannot alter a column (CLAUDE.md rule 7), so
  typing must still happen before persistence — as a separate step, not by
  moving routing.
- **The trap:** it is tempting to then feed the extracted claims *into* routing,
  since they are now available and look like rich signal. Do not. `classify_role`
  deliberately withholds achievement bullets via `header_slice()` precisely
  because achievement vocabulary is what misroutes people. Measured and recorded
  in the code: keyword routing 3/8 correct vs title routing 8/8, and on six real
  PM resumes the keyword router chose `sales` three times and `data_analytics`
  twice. Claims *are* achievements. Routing on them rebuilds the defect that
  `header_slice` was written to kill.

The correct reading: routing and discovery read **disjoint inputs** — the header
(514 chars on the traced resume) versus the whole document (2,913 chars). They
have no data dependency at all once typing is separated. That makes them
**parallel**, not sequential in either direction.

## 4. Prompt complexity — competing objectives

Yes, and in the worst way: the objectives are not merely different, they are
contradictory (lossless vs selective, §2). You would also be putting the two
highest-value prompts in the product behind a single hash. D7 exists because
*prompts are product* — this project already measured three templates carrying
BPO-only examples and biasing extraction for every other cohort. Merging means
any tweak to date parsing re-versions claim discovery, and every A/B of a claim
instruction is confounded by parsing behaviour. You lose the ability to change
one without re-validating the other.

## 5. Failure isolation

Today the two failure modes are cleanly separable and separately actionable:

- Unreadable file → `UnsupportedResume` → **400 with a remedy**: *"extracted
  almost no text — the file may be a scan. Paste the resume text into
  POST /api/candidates/text instead."*
- Bad extraction → `heuristic_claims()` fallback → the interview still runs.

Merged, both collapse into one symptom — *"we got no claims"* — and you cannot
tell whether the model failed to **read** or failed to **reason**. On a scanned
PDF you would spend a full model call before discovering there was no text.

Two further consequences:

- **CLAUDE.md rule 5 — every LLM call has a fallback.** What is the fallback for
  a parsing call? The only honest one is the deterministic parser, which means
  you keep `parse.py` anyway and now maintain two parsers with different output
  quality and a branch that decides which ran.
- **Offline seeding breaks.** `seed.py:42` and `dump_fixture.py:22` both set
  `settings.openai_api_key = None`; the convention is that *seeding must be
  free, instant and offline*. A parser that needs a model ends that.

## 6. Cost and latency — measured

| Stage | Latency (3 runs) | Model calls |
|---|---|---|
| Parse (PyMuPDF + normalise) | **80 ms** | 0 |
| `classify_role` (header, 514 chars) | 2074 / 1158 / 1252 ms | 1 |
| `extract_claims` (whole resume) | 3405 / 4092 / 3556 ms | 1 |

Merging saves **no calls and no tokens**. The resume body has to be read by a
model exactly once either way.

**The real win the proposal misses.** Routing and discovery read disjoint inputs
and, once typing is decoupled, have no ordering dependency. Run them
concurrently: `max(1.2s, 2.3s) ≈ 2.3s` instead of `1.2s + 2.3s ≈ 3.5s` —
roughly **a third off resume onboarding**, and it requires the *opposite* of
merging. It requires separating discovery from routing.

## 7. Where inventory generation belongs

Its own stage, reading stored `raw_text`, family-agnostic, downstream of parsing
and independent of routing.

The test is re-runnability. A claim inventory is the asset with the longest
useful life in this system: it is reusable across job families, across
re-interviews, across role profiles, and it is what a recruiter's second lens
reads. You must be able to re-derive it from stored text when the prompt
improves, without re-uploading anything. That is only possible while parsing
produces a stable substrate and discovery is a separate, re-runnable step over
it.

## 8. Recommendation — D

Not A: A leaves discovery coupled to routing, which is the genuine defect.
Not B: §§1–6.
**Not C either**, and this is the least obvious call. A "lightweight inventory
during parsing, refined later" creates **two sources of truth for claims** and a
reconciliation problem harder than either extraction alone — which of the two
inventories is authoritative, what happens when they disagree, and which one did
the recruiter's score come from. It also pays every determinism, offline-seeding
and fallback cost of B to get a deliberately worse result. Lightweight now means
re-doing it properly later, with a migration.

**D — keep parsing deterministic; decouple discovery from routing instead.**

```
Resume upload
→ Parse                        deterministic, no model, stores raw_text
→ ┌ Discover claims            family-agnostic, whole document   ┐  in parallel
  └ Route job family           header only, achievements withheld┘
→ Type claims against family   labelling only, never inclusion
→ Plan / select                weights + interview budget
→ Generate questions → Evidence → Scoring
```

This gets everything the proposal wanted — extraction not gated on routing, a
complete inventory, no wasted call — and additionally buys the parallelism, at
the cost of a new typing step that is cheap and possibly deterministic.

### What must be checked before committing to D

- **Family-agnostic discovery is unmeasured.** Every inventory run so far still
  rendered `claim_type_menu(routed)` into the prompt. Removing it should help
  recall — it is the constraint that "decides which claims the model is allowed
  to find" — but that is a hypothesis, not a measurement. Run it before relying
  on it.
- **Typing needs a home and a cost.** Deterministic `classify_claim()` is not
  good enough on its own: measured, 9 of 10 bullets on the traced resume type as
  `system_ownership`, 5 of them only because `fallback_claim_type()` returns the
  family's heaviest type. If typing becomes a fourth model call, D's latency win
  is spent — so it should be a batched call over the inventory, not per claim.
- **`POST /api/candidates/text` never calls the parser.** It hands
  `resume_text` straight to `_onboard`. Any design that puts claim discovery
  inside parsing silently produces **zero claims** on that entire ingest path.
  This alone is disqualifying for B and C, and it is worth stating loudly because
  it is invisible from the pipeline diagram.
- **Evaluation impact.** Phase 3 is mid-flight and blocked on 100 human labels;
  changing discovery changes the population being studied. `evaluation_version`
  moves, and the fixture needs re-dumping.
