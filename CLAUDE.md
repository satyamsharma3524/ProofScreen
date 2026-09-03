# ProofScreen API — working notes (v2)

FastAPI backend for the Shine 2026 hackathon (build day 10 Sep, demo 11 Sep).
Backend only; the recruiter dashboard is a separate Next.js app consuming
`/openapi.json`. WhatsApp Business Cloud API (Meta, direct) is the only
candidate channel.

## Read this before proposing code

**All process, architecture and phase documents live in `docs/`. Start at
[docs/README.md](docs/README.md)** — it carries the binding reading order and
marks which documents are superseded history rather than instructions. The
order is not advisory: `docs/EXECUTION_STANDARD.md` §1 requires the frozen
documents to be read *before* proposing code, and forbids new architecture, new
modules, new layers and new abstractions without explicit approval. Default
assumption: **the architecture is correct; the implementation fits inside it.**

`CLAUDE.md` and `README.md` are the only markdown at the repo root. This file
must stay here — Claude Code loads it from the root of the working tree, and
moving it drops these rules out of every session silently.

Do not restate a frozen document's contents in a new file. Cite it. A drifted
copy of a frozen decision is worse than a pointer to it
(`docs/EXECUTION_STANDARD.md` C3).

## Two developers, one `main`

Both push to `main` hourly, which only stays conflict-free because ownership is
strict. **Never edit the other developer's files** — that is rule 3 below, and
it is the whole mechanism.

- **Each developer has a brief: `docs/DEVELOPER_A_CONTRACT.md` (intelligence
  path — routing, questioning, evidence) and `docs/DEVELOPER_B_CONTRACT.md`
  (everything the recruiter reads).** Each carries ownership, task order,
  branch names, and a precondition to verify *before* branching. Both are
  subordinate to `EXECUTION_STANDARD.md`, `ARCHITECTURE_LOCK_v1.md` and
  `PHASE_1_TASKS.md`; where they conflict, they win.
- **The only interface between the two streams is `FamilyMatch`**, the
  NamedTuple A publishes from `taxonomy.py` in P1-06. Do not change its shape
  once B has started P1-08b without telling them.
- **Ownership has three sources and they disagree.** The table in `README.md`
  assigns `engine/signals.py` to B and `models.py` / `ids.py` to A; both
  contracts say the opposite. **For Phase 1 the contracts win** — they are
  per-file, explicit and mutually consistent. `PHASE_1_TASKS.md` P1-03 says why
  for `signals.py`: *A edits, B reviews the hunk.* Settled — do not
  re-litigate it per task.
- **`api/schemas.py` is the tripwire.** Frozen, two owners, and Phase 1 needs
  **zero** edits to it — P1-00 pre-landed every field both developers need. If
  a task seems to require opening it, the task is wrong. Stop and raise it.
- **`tests/conftest.py` is shared, append-only, by announcement.** Its BPO
  vocabulary is load-bearing for family detection; restructuring it silently
  collapses weight assertions across the suite.
- Anything touching the other owner's file — including a test of theirs that
  your change necessarily breaks — is **announced and reviewed, never silent.**

## Non-negotiable rules

1. **The model never produces a score.** It returns countable signals and
   quotes them; Python turns counts into numbers. If you find yourself parsing
   a rating, confidence or percentage out of a model response, stop. Two tests
   enforce this structurally (`test_scoring_modules_never_import_the_llm`,
   `test_answer_signals_carries_no_score_field`).
2. **`api/schemas.py` is frozen.** It is the contract between the two devs and
   between this service and the Next.js app. Adding an optional field is a
   conversation; changing or removing anything is not a solo decision.
3. **One owner per file** (table in README.md). Never edit the other dev's
   files — that is what keeps `main` conflict-free with both pushing hourly.
4. **Quotes are verified in Python, not requested in a prompt.**
   `evidence.enforce_verbatim()` drops any signal whose quote is not literally
   in the answer. A paraphrase is exactly the hallucination this product exists
   to kill.
5. **Every LLM call has a fallback.** `complete_json(..., fallback=...)` must
   always be given one. A stack trace on the projector is the failure mode the
   whole architecture exists to prevent.
6. **Never score presentation.** No accent, fluency, grammar, speaking
   confidence or personality — anywhere, ever. Those are bias vectors, and
   removing them is a stated product decision, not an oversight.
7. **No Alembic.** `create_all()` at startup. Schema change =
   `docker compose down -v` and re-seed.

## Commands

```bash
docker compose up --build                    # api + postgres 16
docker compose exec api python seed.py       # 3 candidates + 2 role profiles
pytest -q                                    # 102 tests, sqlite + fixture mode, ~2s

# no-Docker loop
export DATABASE_URL="sqlite+aiosqlite:///./proofscreen.sqlite3"
python seed.py && uvicorn api.main:app --reload

# after changing any rubric or weight
python seed.py --reset && python scripts/dump_fixture.py && pytest -q
```

## Architecture in one paragraph

`routers/candidates.py` parses a resume (`ingest/parse.py`) and calls
`orchestrator.create_session`, which runs `engine/extract.py` (LLM #1) for a
job family plus up to 3 claims **typed against the taxonomy**. The session waits
in `AWAITING_OPT_IN` because Meta will not let us message first. The candidate
sends their opt-in code; `routers/whatsapp.py` binds the phone and
`orchestrator.ask_next` applies the policy — pure function
`plan_next(states, index)` — then calls `engine/question.py` (LLM #2) for
wording only. Answers land in `responses` (**the seam**), and
`orchestrator._persist_evidence` hands each to `engine/evidence.py` (LLM #3),
which returns *countable signals* plus *facts*, drops any non-verbatim quote,
and runs `engine/consistency.py` over the fact memory. `engine/signals.py`
turns counts into six dimension scores; `engine/scoring.py` applies dimension
and role weights and the consistency multiplier; `engine/graph.py` assembles
the tree and re-ranks live for any role profile.

## Conventions

- Async throughout — every request blocks on a model call. Async SQLAlchemy
  2.0, **no lazy relationships** (explicit `select()` everywhere) so there is no
  `MissingGreenlet` surprise at 2am.
- Prompts are `.txt` rendered with `string.Template` (`$var`), never
  `str.format` — every prompt contains a literal JSON schema full of braces.
- Short prefixed IDs (`c_`, `s_`, `cl_`, `q_`, `r_`, `e_`, `f_`, `x_`, `jr_`),
  not UUIDs, because on demo day you read them off a screen out loud.
- Enum DB columns are `String`; Pydantic enforces values. A native Postgres
  enum would need a migration to add a value and `create_all()` cannot.
- Heuristic fallbacks (`extract.heuristic_claims`,
  `question.FALLBACK_QUESTIONS`, `evidence.heuristic_signals`) are production
  code, not stubs — they are what runs when the model is down. They are
  deliberately more conservative than real extraction; if a fallback ever looks
  *better*, the fallback has become the product.
- `settings.openai_api_key = None` at the top of `seed.py` and
  `scripts/dump_fixture.py`: seeding must be free, instant and offline.

## Env flags that change behaviour

| Var | Effect |
|---|---|
| `OPENAI_API_KEY` empty | fixture mode: no network, deterministic heuristics |
| `WHATSAPP_ACCESS_TOKEN` empty | outbound dry-run; inbound webhooks still parse |
| `ADAPTIVE_PROBING=false` | strict VALIDATION→OUTCOME sweep |
| `SCORE_INLINE=false` | signal extraction moves to a background task |
| `VOICE_WEIGHT=0` | removes the text/voice asymmetry |
| `MAX_QUESTIONS`, `MAX_CLAIMS` | interview size |
| `WHATSAPP_VALIDATE_SIGNATURE=true` | requires a correct `WHATSAPP_APP_SECRET` |
| `ENABLE_DEV_ENDPOINTS=false` | hides `/api/dev/*` |

## Gotchas already paid for

- **Meta media needs the bearer token on BOTH calls** (id → URL, then URL →
  bytes). Missing it on the second is a 401 that looks like your own bug.
- **Meta retries webhooks.** Answers are de-duplicated on
  `provider_message_id`; without it one retry becomes a second answer and the
  interview desyncs mid-demo.
- **One webhook can carry several messages**, and most carry only delivery
  statuses. `parse_inbound` returns a *list* for that reason.
- **The webhook must 200 fast** — real work happens in a `BackgroundTask`.
- **X-Hub-Signature-256 is over the RAW body.** Re-serialising parsed JSON
  changes whitespace and key order and the digest never matches.
- **The 24-hour window**: free-form text only within 24h of the candidate's
  last message. The opt-in flow exists to open it.
- **CORS**: wildcard origins and `allow_credentials=True` are mutually
  exclusive; `main.py` handles the combination.
- **`pymupdf` renamed its module** — `import pymupdf`, falling back to `fitz`.
- **Resume heuristics**: a parenthesised year is a job-title heading, a
  comma-heavy line with no verb is a skills list, and bare `lead`/`design` are
  nouns on a resume as often as verbs. All three are excluded explicitly.
- **OPEN BUG — `taxonomy._INFLECTION` has no y-to-ies plural.** It covers
  `s|es|ed|ing|er|ers|or|ors|ion|ions|ment|ments`, so a consonant+y keyword
  never matches its plural: **`query` misses "queries"**, `policy` misses
  "policies", `user story` misses "user stories". 20 keywords end in `-y`
  across 7 families (~14 are consonant+y), so an engineer writing "optimised
  slow queries" earns nothing for `query`. Found while adding the `product`
  family; **not fixed**, because it changes routing for six families and P1-06
  already shipped a reviewed golden-set diff. Fixing it means re-running that
  diff. Owner: A (`taxonomy.py`).
- **A family's keyword must be a compound wherever another family holds the
  bare word.** `hr_recruitment` carries `onboarding` and `interview`; a product
  resume saying "rebuilt user onboarding after twenty user interviews" fed HR
  two hits and `product` none, and lost a real PM resume to HR by 0.016. Hence
  `user onboarding` / `user interview` / `user retention` / `feature launch` in
  the `product` family, and no bare `product` (it double-counts with `product
  manager` and fires on "Product Support Engineer"). When adding a family,
  check term collisions **in both directions** — a set intersection misses the
  case where one family's compound contains another's bare term.
- **Unit regexes must order alternatives longest-first** or `120ms` compresses
  to `120m`.
- **Weight renormalisation must absorb the rounding remainder** in its last
  key, or a recruiter typing 40/30/20/20 sees 99.9999 and assumes the product
  is broken.
- **Family detection is load-bearing in tests.** A resume saying
  "support / escalation / Zendesk" classifies as `customer_support`, which has
  no `team_handling` or `aht_control` claim type — and every weight assertion
  silently collapses. `tests/conftest.py` pins the family with BPO vocabulary
  and says so.

## Design decisions worth defending out loud

- **Evidence accumulates across a claim's answers** (union of signals, rubric
  run once) rather than taking the best per-answer score. Best-of
  under-credited candidates who spread evidence across probe levels — which is
  precisely what the 5-level protocol asks them to do.
- **Un-probed dimensions contribute 0**, with `probed_dimensions` reported.
  This is a confidence score; thin questioning should show as low confidence,
  and the dashboard can say "4 of 6 probed".
- **`role_coverage` is separate from the score** — "evidenced badly" and "never
  claimed it" are different facts.
- **Consistency is session-level, applied once.** It is a property of the whole
  interview, not of any claim, and counting it inside a claim *and* as a
  multiplier would penalise the same fact twice.
- **`stable` vs `variable` fact keys.** Without that split the engine flags
  every improvement a candidate describes as a contradiction.

## Where things stand

**Verify this section rather than trusting it** — it is the first thing to go
stale. `git log --oneline -5` and `pytest -q` are the source of truth.

Baseline: taxonomy (8 families), typed claim extraction, adaptive policy capped
at 12, signal extraction with verbatim enforcement, six rubrics with gates,
deterministic consistency, role weight profiles with live re-ranking, Meta
Cloud API webhook (verify, HMAC, batching, retry de-dup, two-step media),
Whisper voice with duration, `/api/dev/*` tooling, engine-generated fixture,
seed showing the resume/competence inversion and the ranking flip, Docker.

Phase 1 (`docs/PHASE_1_TASKS.md`): **P1-00 … P1-04 complete — 126 tests
passing.** D1, the TRANSFER probe, is built: one probe to a stalled claim,
operator selected in pure Python with no `job_family` in the signature, both
halves of the question taken from the candidate's own claims.
`TRANSFER_PROBE=false` reproduces the pre-phase interview exactly.

Next: A on P1-06 → P1-07 (deterministic family routing) and the `dev.py` half
of P1-08; B on the order in `docs/DEVELOPER_B_CONTRACT.md`, starting at P1-09.
**P1-05 goes last** — A's P1-06 and P1-07 both change what the fixture
contains, so regenerating before they land means regenerating twice.

Not done: Next.js dashboard, Render/Railway deploy, auth (deliberately none),
approved WhatsApp template for first contact (needs Meta approval), the
separate "Shine Verified" code-sandbox product from the strategy doc.
