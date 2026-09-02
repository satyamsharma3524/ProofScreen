# ProofScreen API — working notes

FastAPI backend for the Shine 2026 hackathon (build day 10 Sep, demo 11 Sep).
Backend only; the recruiter dashboard and candidate UI are a separate Next.js
app that consumes `/openapi.json`.

## Non-negotiable rules

1. **`api/schemas.py` is frozen.** It is the contract between the two devs and
   between this service and the Next.js app. Adding an optional field is a
   conversation with the other dev; changing or removing anything is not a
   solo decision.
2. **One owner per file.** See the ownership table in README.md. Never edit a
   file the other dev owns — that is what keeps `main` conflict-free with both
   devs pushing several commits an hour.
3. **The LLM never produces a number.** Verdicts are enums; every float is
   computed in `api/engine/scoring.py`. If you find yourself parsing a score
   out of a model response, stop.
4. **Every LLM call has a fallback.** `complete_json(..., fallback=...)` must
   always be given one. A stack trace on the projector is the failure mode this
   entire architecture exists to prevent.
5. **Quotes are verified in Python, not requested in a prompt.**
   `evidence.py` drops any node whose quote is not verbatim in the answer.
6. **No Alembic.** `Base.metadata.create_all()` at startup. Schema change =
   `docker compose down -v` and re-seed.

## Commands

```bash
docker compose up --build                    # api + postgres 16
docker compose exec api python seed.py       # 3 demo candidates, 3 badges
pytest -q                                    # 60 tests, sqlite + fixture mode, ~1s

# no-Docker loop
export DATABASE_URL="sqlite+aiosqlite:///./proofscreen.sqlite3"
uvicorn api.main:app --reload
```

## Architecture in one paragraph

`routers/candidates.py` parses a resume (`ingest/parse.py`) and calls
`engine/orchestrator.create_session`, which runs `engine/extract.py` (LLM #1)
to get up to 3 verifiable claims. `orchestrator.ask_next` applies the question
policy — pure function `plan_next(index, claims, evidence, asked_pairs)` — and
calls `engine/question.py` (LLM #2) for wording only. Answers arrive through
`routers/channel.py` from either the web channel or the Twilio webhook, land in
the `responses` table (**the seam**), and `orchestrator._persist_evidence`
hands each one to `engine/evidence.py` (LLM #3), which returns enum verdicts
plus verbatim quotes. `engine/scoring.py` turns those into numbers.
`engine/graph.py` assembles the claim → Q&A → evidence tree that
`routers/recruiter.py` serves.

## Conventions

- Async throughout — every request blocks on an LLM call. Async SQLAlchemy 2.0,
  no lazy relationships (explicit `select()` everywhere) so there is no
  `MissingGreenlet` surprise at 2am.
- Prompts are `.txt` files rendered with `string.Template` (`$var`), never
  `str.format` — every prompt contains a literal JSON schema full of braces.
- IDs are short and prefixed (`c_`, `s_`, `cl_`, `q_`, `r_`, `e_`, `p_`), not
  UUIDs, because on demo day you read them off a screen out loud.
- Enum DB columns are `String`; Pydantic enforces the values.
- Heuristic fallbacks (`extract.heuristic_claims`,
  `question.FALLBACK_QUESTIONS`, `evidence.heuristic_extraction`) are
  production code, not stubs. They are what runs when the model is down.

## Env flags that change behaviour

| Var | Effect |
|---|---|
| `OPENAI_API_KEY` empty | fixture mode: no network, deterministic heuristics |
| `ADAPTIVE_FOLLOWUPS=false` | fixed question order (cut-list item #2) |
| `SCORE_INLINE=false` | evidence extraction moves to a background task |
| `MAX_QUESTIONS`, `MAX_CLAIMS` | interview length |
| `ENABLE_DEV_ENDPOINTS=false` | hides `/api/dev/*` |
| `TWILIO_VALIDATE_SIGNATURE=true` | requires `PUBLIC_BASE_URL` to be correct |

## Gotchas already paid for

- Twilio media URLs need HTTP basic auth (SID + token) or they 401. Handled in
  `stt.py`.
- The Twilio webhook replies with TwiML, so the Q&A loop needs **no** outbound
  credentials.
- CORS: wildcard origins and `allow_credentials=True` are mutually exclusive;
  `main.py` handles the combination.
- `pymupdf` renamed its module — `import pymupdf`, falling back to `fitz`.
- A resume line like `Support Lead, Northwind (2021 - present)` is a heading,
  not a claim; `extract.py` rejects parenthesised years and comma-heavy skill
  lists explicitly.
- Unit regexes must order alternatives longest-first or `120ms` compresses to
  `120m`.

## Where things stand

Done: full pipeline end to end, both channels, voice, scoring + 60 tests,
recruiter endpoints, `/api/dev/simulate`, seed data, Docker.

Not done: Next.js dashboard (Dev B), Render/Railway deploy, auth (deliberately
none), the separate "Shine Verified" code-sandbox product from the strategy doc.
