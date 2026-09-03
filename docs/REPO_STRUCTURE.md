# ProofScreen — Repo Structure

FastAPI backend, hackathon build (Shine 2026). Resume in → WhatsApp interview → evidence-scored graph out. No LLM ever produces a score — Python does, from countable signals the model extracts.

## Directory tree

```
ProofScreen/
├── api/
│   ├── main.py                    # FastAPI app, CORS, router mounting
│   ├── config.py                  # env-driven settings (Pydantic settings)
│   ├── db.py                      # async SQLAlchemy engine/session, create_all()
│   ├── models.py                  # ORM tables (candidates, sessions, claims, questions, responses, ...)
│   ├── schemas.py                 # FROZEN — Pydantic contract, shared with Next.js dashboard
│   ├── ids.py                     # short prefixed ID generator (c_, s_, cl_, q_, r_, e_, f_, x_, jr_)
│   ├── llm.py                     # complete_json() wrapper: LLM calls + mandatory fallback + cache
│   ├── stt.py                     # Whisper voice transcription + duration
│   ├── taxonomy.py                # loads/validates data/claim_taxonomy.json, family detection
│   │
│   ├── ingest/
│   │   └── parse.py               # resume parsing (PDF/DOCX/TXT/MD), heuristic line classification
│   │
│   ├── engine/                    # the scoring core — no LLM imports except extract/question/evidence
│   │   ├── extract.py             # LLM #1 — job family + claims (typed to taxonomy) + heuristic fallback
│   │   ├── question.py            # LLM #2 — question wording only; FALLBACK_QUESTIONS; 5-level protocol
│   │   ├── orchestrator.py        # session lifecycle glue: create_session, ask_next, plan_next(), _persist_evidence
│   │   ├── evidence.py            # LLM #3 — countable signals + facts; enforce_verbatim() quote guard
│   │   ├── consistency.py         # stable-vs-variable fact memory, contradiction penalties
│   │   ├── signals.py             # NO LLM — 6 dimension rubrics + gates, counts → scores
│   │   ├── scoring.py             # NO LLM — dimension/role weights, consistency multiplier, badges
│   │   ├── graph.py               # assembles the evidence graph tree, live re-ranking by role profile
│   │   └── voice.py               # voice signal = duration + word count only (no fluency scoring)
│   │
│   ├── channels/
│   │   ├── base.py                # channel interface
│   │   └── whatsapp_cloud.py      # Meta WhatsApp Cloud API client (send, media fetch, templates)
│   │
│   ├── routers/
│   │   ├── candidates.py          # POST /api/candidates(+/text) — resume in, claims out
│   │   ├── sessions.py            # GET /api/sessions/{id}
│   │   ├── whatsapp.py            # webhook verify + inbound handling, HMAC, retry de-dup, background task
│   │   ├── recruiter.py           # ranked candidates, evidence graph, role weight profiles, taxonomy
│   │   └── dev.py                 # /api/dev/* — simulate, start/answer, fixture, llm stats, reset
│   │
│   └── prompts/                   # string.Template (.txt) — never str.format (braces are literal JSON schema)
│       ├── extract_claims.txt
│       ├── generate_question.txt
│       └── extract_signals.txt
│
├── data/
│   └── claim_taxonomy.json        # 8 job families, typed claims, importance weights, fact vocabulary
│
├── fixtures/
│   └── sample_graph.json          # generated (scripts/dump_fixture.py), never hand-written
│
├── tests/                         # 102 tests, sqlite + fixture mode, ~2s
│   ├── conftest.py                # fixtures, pins job family with BPO vocabulary
│   ├── test_taxonomy.py           # weight sums, family detection, invented-claim reclassification
│   ├── test_scoring.py            # rubrics, gates, no-LLM structural test, anti-bias, accumulation, badges
│   ├── test_consistency.py        # stable vs variable, symmetry, thresholds, floor
│   ├── test_policy.py             # breadth-before-depth, gap chasing, saturation, stall, TRANSFER, budget
│   ├── test_transfer.py           # D1: operator selection, family invariance, slot derivation, e2e
│   └── test_pipeline.py           # HTTP e2e, verbatim guarantee, re-ranking, webhook, voice, fixture drift
│
├── scripts/
│   └── dump_fixture.py            # regenerates fixtures/sample_graph.json from the live engine
│
├── seed.py                        # 3 candidates + 2 role profiles, offline & free (openai_api_key=None)
├── requirements.txt
├── Dockerfile / docker-compose.yml
├── .env.example
├── CLAUDE.md                      # ROOT, and must stay there: auto-loaded into every Claude session
├── README.md                      # product pitch, API surface, WhatsApp setup, file ownership table
└── docs/                          # every other .md — process, architecture, phase plans, reviews
    └── README.md                  # the index and the binding reading order
```

`CLAUDE.md` and `README.md` are the only markdown at the repo root. `CLAUDE.md`
stays because Claude Code loads it from the root of the working tree and moving
it silently drops the project's rules out of every session; `README.md` stays
because that is where GitHub renders it. Everything else lives in `docs/`.

## Data flow (one line each)

```
resume ─ingest/parse.py─▶ extract.py (LLM#1: family + claims)
     ─▶ orchestrator.create_session ─▶ AWAITING_OPT_IN
     ─▶ [candidate opts in via WhatsApp] ─▶ routers/whatsapp.py binds phone
     ─▶ orchestrator.ask_next ─▶ plan_next() policy ─▶ question.py (LLM#2: wording)
     ─▶ candidate answers ─▶ responses table (the seam between the two devs)
     ─▶ orchestrator._persist_evidence ─▶ evidence.py (LLM#3: signals + facts, verbatim-enforced)
     ─▶ consistency.py (fact memory, contradictions)
     ─▶ signals.py (counts → 6 dimension scores, no LLM)
     ─▶ scoring.py (weights + consistency multiplier → competence score/badge, no LLM)
     ─▶ graph.py (assembles tree, re-ranks per role profile)
```

## Existing module ownership (from README.md — already split)

| Dev A — ingest, conversation, channel, infra | Dev B — evidence, scoring, dashboard-facing |
|---|---|
| `main.py`, `config.py`, `db.py`, `models.py`, `ids.py` | `engine/signals.py` (rubrics) |
| `taxonomy.py`, `data/claim_taxonomy.json` | `engine/scoring.py` |
| `llm.py`, `stt.py` | `engine/consistency.py` |
| `ingest/parse.py` | `engine/evidence.py` |
| `engine/extract.py`, `question.py`, `orchestrator.py` | `engine/graph.py` |
| `channels/*` | `routers/recruiter.py` |
| `routers/candidates.py`, `sessions.py`, `whatsapp.py`, `dev.py` | `seed.py`, `scripts/`, `tests/` |
| `prompts/extract_claims.txt`, `generate_question.txt` | `prompts/extract_signals.txt` |
| `Dockerfile`, `docker-compose.yml`, deploy | Next.js dashboard (separate repo) |

`api/schemas.py` is the **only shared/frozen file** — the Pydantic contract with the Next.js dashboard via `/openapi.json`.

## Size snapshot (lines of code, non-test Python)

Biggest modules — where most future work will land: `orchestrator.py` (816), `schemas.py` (574), `graph.py` (512), `evidence.py` (402), `seed.py` (366), `signals.py` (382), `scoring.py` (315).

## What's done vs. not (per CLAUDE.md)

**Done:** taxonomy (8 families), typed claim extraction, 5-level adaptive question policy (capped at 12), signal extraction with verbatim enforcement, six rubrics with gates, deterministic consistency engine, role weight profiles with live re-ranking, Meta WhatsApp Cloud webhook (verify/HMAC/batching/retry-dedup/two-step media), Whisper voice, `/api/dev/*` tooling, engine-generated fixture, seed data, 102 tests, Docker.

**Not done:** Next.js dashboard (separate repo, Dev B), Render/Railway deploy, auth (deliberate), approved WhatsApp first-contact template (pending Meta approval), the separate "Shine Verified" code-sandbox product.
