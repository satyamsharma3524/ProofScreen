# ProofScreen — API

Resume in, **evidence graph** out.

A candidate uploads a resume. The service extracts their most verifiable
claims, probes each one with adaptive questions over WhatsApp or web chat, and
turns the answers into an evidence graph: every claim scored, every point in
the score attached to a verbatim quote from the candidate's own words.

Backend only. The recruiter dashboard and candidate UI are a separate Next.js
app — this process serves JSON and nothing else.

> **The design rule that matters for the pitch:** the LLM produces evidence
> nodes with *enum verdicts*. It never produces a number. `claim_confidence`
> and `competence_score` are arithmetic over those verdicts, computed in
> `api/engine/scoring.py`. When a judge asks "how do we know the score isn't
> hallucinated?", the answer is: the score is arithmetic, and every term in it
> points at a quote from the candidate's own answer. Open `scoring.py` on the
> projector.

---

## Quickstart

### With Docker (Postgres included)

```bash
cp .env.example .env          # works as-is; add OPENAI_API_KEY for live mode
docker compose up --build
docker compose exec api python seed.py     # 3 demo candidates, 3 badges
open http://localhost:8000/docs
```

### Without Docker (SQLite, zero setup)

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export DATABASE_URL="sqlite+aiosqlite:///./proofscreen.sqlite3"
python seed.py
uvicorn api.main:app --reload
```

### Fixture mode — it runs with no API key at all

With `OPENAI_API_KEY` empty, every LLM call is served by a deterministic
heuristic instead: claims come from a scoring pass over the resume lines,
questions come from the hand-written per-dimension fallbacks, evidence comes
from a conservative signal check. Nothing touches the network.

This is not a stub. It is the same fallback path that protects you when the
model times out mid-demo, so it is exercised constantly rather than rotting.
`GET /api/health` tells you which mode you are in; `GET /api/dev/llm` tells you
how many calls fell back.

---

## One command that proves the whole pipeline

```bash
curl -s -X POST localhost:8000/api/dev/simulate \
  -H 'content-type: application/json' \
  -d '{
    "name": "Priya R.",
    "role": "Support Lead",
    "resume_text": "Managed a 50-member support team and improved CSAT from 78% to 92% in four quarters\nCut average first-response time from 9 hours to 45 minutes across three queues\nBuilt the escalation playbook now used by 4 regional support centres",
    "answers": [
      "I owned this end to end. I rebuilt the shift roster myself and moved four agents onto an early shift because that is where the backlog formed.",
      "Billing complaints were 40% of negative feedback, so we redesigned the escalation workflow and introduced callback SLAs."
    ]
  }' | python -m json.tool
```

Runs ingest → claims → questions → evidence → score with no WhatsApp, no
browser and no waiting, and persists the result so it appears on the dashboard.
This is how you test everything, and it is the demo fallback if Twilio dies on
stage.

---

## API surface

| Method | Path | Notes |
|---|---|---|
| `POST` | `/api/candidates` | multipart resume (PDF/DOCX/TXT/MD) → `{candidate_id, session_id, claims[], join_code, first_question}` |
| `POST` | `/api/candidates/text` | same, with `resume_text` as JSON — what the Next.js form should use |
| `GET` | `/api/sessions/{id}` | `{state, questions_asked, next_question, join_code}` |
| `POST` | `/api/web/message` | `{session_id, text?, audio_url?}` → next question. The channel with no external dependency |
| `POST` | `/api/webhooks/twilio` | Twilio form-encoded inbound; replies with TwiML |
| `GET` | `/api/recruiter/candidates` | ranked list, highest competence first |
| `GET` | `/api/recruiter/candidates/{id}` | the full evidence graph the dashboard renders |
| `POST` | `/api/dev/simulate` | whole pipeline in one call |
| `GET` | `/api/dev/fixture` | the hand-written `fixtures/sample_graph.json` |
| `GET` | `/api/dev/llm` | cache hits, call count, fallbacks used |
| `POST` | `/api/dev/reset` | drop and recreate every table |
| `GET` | `/api/health` | db status, llm mode, active policy |

`/docs` is Swagger, `/openapi.json` is the schema. **That schema is the
contract between this service and the Next.js app** — generate the TS client
from it rather than hand-writing types:

```bash
npx openapi-typescript http://localhost:8000/openapi.json -o src/lib/api.d.ts
```

---

## The scoring maths

```python
VERDICT_POINTS   = {SUPPORTED: 1.0, PARTIAL: 0.5, UNSUPPORTED: 0.0, CONTRADICTED: -0.5}
DIMENSION_WEIGHT = {OWNERSHIP: 0.30, DEPTH: 0.30, SPECIFICITY: 0.20, OPERATIONAL: 0.20}

claim_confidence = clamp(Σ(weight_d × best_points_d), 0, 1)   # per claim
competence_score = mean(claim_confidence for ALL claims)      # unprobed claim = 0.0
badge            = verified   if competence ≥ 0.70
                   partial    if competence ≥ 0.40
                   unverified otherwise
```

Two decisions worth being able to defend out loud:

- **Best verdict per dimension wins.** Once a candidate has demonstrably
  evidenced ownership, a later vague answer does not un-evidence it.
- **Unprobed claims count as 0.0.** One brilliant answer must not carry two
  claims the candidate never addressed.

`resume_score` is the deliberately shallow contrast metric: keyword overlap
between the resume and the job description — exactly what a GenAI-optimised
resume is built to maximise. Its only job is to sit next to the competence
score and be visibly different. Run `python seed.py` and look at Rohit Verma:
**resume 0.82, competence 0.05.** That row is the pitch.

Pass `job_description` when creating a candidate. Without one, `resume_score`
falls back to `DEFAULT_JOB_DESCRIPTION` from the env, and a candidate from a
different function will score near zero for the boring reason.

### The verbatim-quote guarantee

`api/engine/evidence.py` drops any evidence node whose quote is not actually
present in the candidate's answer (whitespace and case normalised; the words
must match). That is enforced in Python, not requested in the prompt — which
is what makes "every term in the score points at a real quote" true rather
than aspirational. `tests/test_pipeline.py` asserts it end to end.

---

## The question policy

Deterministic, in code, not in a prompt — reproducible and explainable on
stage, which is what makes "adaptive" a real claim rather than a marketing
word.

```
Q1 → claim 1, OWNERSHIP probe
Q2 → claim 1 follow-up on the weakest uncovered dimension
Q3 → claim 2, OWNERSHIP probe
Q4 → claim 2 follow-up  OR  claim 3 if claim 2 is already well covered (≥0.70)
Q5 → the single dimension with the least coverage across all claims
```

Never asks the same (claim, dimension) pair twice. On a resume that yielded one
claim, four dimensions cannot fill five questions, so the interview ends early
instead of repeating itself.

---

## WhatsApp setup (the only item with an external dependency)

1. Twilio Console → Messaging → **Try it out → WhatsApp sandbox**. Note the
   sandbox number and the `join <two-words>` code.
2. Put your public HTTPS URL in the sandbox's **"When a message comes in"**
   field: `https://<host>/api/webhooks/twilio`, method POST.
3. Fill `TWILIO_ACCOUNT_SID` and `TWILIO_AUTH_TOKEN` in `.env`. These are only
   needed for **voice notes** (media URLs require HTTP basic auth or they 401)
   and for proactive sends — the question/answer loop replies via TwiML and
   works without them.
4. Set `TWILIO_VALIDATE_SIGNATURE=true` and `PUBLIC_BASE_URL` before the URL is
   public. Leave it false while replaying payloads with curl.

**Candidate flow:** upload resume on the web → get a 6-character `join_code` →
message that code to the sandbox number → questions arrive on WhatsApp. The
code is what binds a phone number to a session.

```bash
# simulate an inbound message without Twilio
curl -X POST localhost:8000/api/webhooks/twilio \
  -d 'From=whatsapp:+919812345678' -d 'Body=ABC234'
```

---

## Cut list, as env flags

Decide on **7 September**, not on the 10th. Each of these is one env var, not a
code change:

| Cut | How |
|---|---|
| Voice → text only | leave `OPENAI_API_KEY` set but don't send voice notes; STT already fails soft to "please type your answer" |
| Adaptive follow-ups → fixed 5 questions | `ADAPTIVE_FOLLOWUPS=false` |
| WhatsApp → web chat | point the Next.js app at `/api/web/message` and stop using the webhook |
| Scoring off the critical path | `SCORE_INLINE=false` (scores in a background task; the dashboard polls) |
| Fewer questions | `MAX_QUESTIONS=3` |

**Never cut:** the evidence tree. That is the product.

---

## Tests

```bash
pytest -q          # 60 tests, ~1s, no Docker and no network
```

- `tests/test_scoring.py` — the maths. Weights, thresholds, clamping,
  best-per-dimension, and an assertion that `fixtures/sample_graph.json`'s
  numbers are exactly what `scoring.py` computes, so the fixture and the engine
  can never drift apart.
- `tests/test_pipeline.py` — the wiring, through HTTP: both channels, the
  verbatim-quote guarantee, evidence provenance, and the 7 September edge cases
  ("I don't know", empty answers, a one-claim resume, an abandoned interview,
  an unsupported file type).

The suite runs against in-memory SQLite in fixture mode on purpose. A test
suite you cannot run in one second is a test suite you stop running on day four.

---

## File ownership

`api/schemas.py` is the **only** file with two owners, and it is frozen. Every
other file has exactly one, so merge conflicts on `main` are impossible.

| Dev A — ingest, conversation, channels, infra | Dev B — evidence, scoring, dashboard |
|---|---|
| `api/main.py`, `config.py`, `db.py`, `models.py`, `ids.py` | `api/engine/evidence.py` |
| `api/llm.py`, `api/stt.py` | `api/engine/scoring.py` |
| `api/ingest/parse.py` | `api/engine/graph.py` |
| `api/engine/extract.py`, `question.py`, `orchestrator.py` | `api/routers/recruiter.py` |
| `api/routers/candidates.py`, `sessions.py`, `channel.py`, `dev.py` | `api/prompts/extract_evidence.txt` |
| `api/channels/*` | `fixtures/sample_graph.json`, `seed.py`, `tests/` |
| `api/prompts/extract_claims.txt`, `generate_question.txt` | the Next.js dashboard (separate repo) |
| `Dockerfile`, `docker-compose.yml`, deploy | |

**The seam is the `responses` table.** A fills it, B consumes it. In code, the
seam is one function: `evidence.score_response(ScoreRequest) -> ScoreResult`.

---

## Deviations from the build spec

All additive; nothing in the frozen contract changed.

| Change | Why |
|---|---|
| No `StaticFiles` mount, CORS open | Next.js is a separate origin, per the frontend decision |
| `candidates.role`, `resumes.job_description` | the dashboard shows a role label; `resume_score` needs a JD to overlap with |
| `sessions.join_code` | how a phone number binds to a session created on the web — without it WhatsApp cannot find the candidate |
| `questions.answered` | makes "the currently open question" a single indexed query, and makes a double-tapped WhatsApp send idempotent |
| `POST /api/candidates/text` | multipart is awkward from a JSON client and from tests |
| `GET /api/dev/fixture`, `/api/dev/llm`, `POST /api/dev/reset` | dashboard can render before the DB has rows; the other two are rehearsal tools |
| Enum columns are `String`, not native Postgres `ENUM` | adding an enum value would need a migration, and there is no Alembic by design |
| `RawEvidenceNode` (model output) vs `EvidenceNode` (stored) | the model is never asked for `source_response_id`; Python attaches it |

---

## What is not here

- **The Next.js dashboard** — Dev B, separate repo, built against `/openapi.json`
  and `fixtures/sample_graph.json`.
- **Deploy config** for Render/Railway — needs your account. The container is
  ready: it listens on `$PORT` if you change the compose command, and Twilio
  needs a stable public HTTPS webhook.
- **Auth** — deliberately none, per the build decision. The deployed URL exposes
  every candidate's evidence graph to anyone who finds it. Fine for nine days;
  not fine in production, and worth saying out loud before a judge asks.
- **Alembic** — by design. `create_all()` at startup; `docker compose down -v`
  to reset.
