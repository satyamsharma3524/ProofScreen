# ProofScreen — API

Resume in, **evidence graph** out.

A candidate uploads a resume. ProofScreen extracts their claims, probes each
one over WhatsApp through five levels, and turns the answers into a scored
evidence graph where every point traces back to something the candidate
actually said.

Backend only. The recruiter dashboard is a separate Next.js app — this process
serves JSON and nothing else.

---

## The one thing to understand

**The model never produces a score. Not once.**

It does exactly five jobs: extract claims, write questions, extract *countable
signals* from answers, extract *facts* onto a controlled vocabulary, and write
a one-line summary. Everything numeric is computed in Python.

```
answer  ──LLM──▶  signals            ──rubrics──▶  6 dimension scores  0-100
                  · 3 quantities                    (engine/signals.py)
                  · 2 process steps                        │
                  · 1 complete cause→action→outcome        ▼
                  · 1 tool with described usage      claim score
                  · 2 remembered incidents           (× dimension weights)
                  · facts: team_size=35                    │
                  each quoted VERBATIM                     ▼
                                                    weighted evidence
                                                    (× role claim weights)
                                                           │
                                                           ▼
                                                    × consistency multiplier
                                                    (contradictions, arithmetic)
                                                           │
                                                           ▼
                                                    competence score → badge
```

So when a judge asks *"how do we know the score isn't the AI's opinion?"*, the
answer is: **the model found three quantities, two process steps and one
complete causal chain, and quoted each one. The score is arithmetic over those
counts.** Open `api/engine/signals.py` on the projector.

Two tests assert this rather than promising it:

```python
def test_scoring_modules_never_import_the_llm(module):     # scoring.py, signals.py
def test_answer_signals_carries_no_score_field():          # nowhere to put a grade
```

---

## Quickstart

```bash
cp .env.example .env          # works as-is; add keys to go live
docker compose up --build
docker compose exec api python seed.py
open http://localhost:8000/docs
```

Without Docker:

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL="sqlite+aiosqlite:///./proofscreen.sqlite3"
python seed.py && uvicorn api.main:app --reload
```

### Fixture mode — it runs with no keys at all

With `OPENAI_API_KEY` empty, claims and signal extraction come from
deterministic heuristics and nothing touches the network. Outbound WhatsApp
runs in dry-run. **Scoring, weighting and consistency are byte-identical in
both modes** — they never involve the model.

This is not a stub. It is the same fallback that protects you when the model
times out mid-demo, so it is exercised constantly rather than rotting.
`GET /api/health` says which mode you are in; `GET /api/dev/llm` proves how
many calls fell back.

---

## What the seed data demonstrates

```
  candidate           Q  resume  evidence  consist  competence  badge
  -------------------------------------------------------------------
  Priya Raghavan     12      28        56      100          56  partial
  Arjun Mehta        12      34        46      100          46  partial
  Rohit Verma         9      59        24       60          14  unverified  (1 contradiction)
```

**Rohit ranks first by resume score and last by competence.** His resume mirrors
the job description, which is exactly what an ATS-optimising candidate does and
exactly what `resume_score` rewards. Then he is asked about it: he cannot name a
number, cannot describe a process, and says he managed 45 agents before saying
20 reported to him. The consistency engine catches that arithmetically and
multiplies 24 down to 14.

He also gets a **shorter interview** — 9 questions instead of 12 — because the
adaptive stop gives up on a claim that stops producing signals.

Then the same three candidates, the same stored evidence, two recruiters:

```
  Team Lead — People First        Priya (68) > Arjun (28) > Rohit (17)
  Operations Excellence Lead      Arjun (63) > Priya (33) > Rohit (9)
```

The **order inverts**. No re-interviewing, no model calls — every dimension
score is already stored, so re-ranking is arithmetic over rows we have. That is
the strongest twenty seconds of the demo:

```bash
curl "localhost:8000/api/recruiter/candidates?role_id=<people_first_id>"
curl "localhost:8000/api/recruiter/candidates?role_id=<ops_excellence_id>"
```

---

## The five artifacts

The UI, the WhatsApp integration and the LLM calls are implementation details.
These five are the intellectual property, and each is one file you can open.

| # | Artifact | Where |
|---|---|---|
| 1 | **Claim taxonomy** — 8 job families, typed claims, importance weights, controlled fact vocabulary | `data/claim_taxonomy.json` + `api/taxonomy.py` |
| 2 | **Evidence dimensions** — the six, and what is deliberately absent | `Dimension` in `api/schemas.py` |
| 3 | **Question protocol** — 5 probe levels + the adaptive policy | `api/engine/question.py` + `orchestrator.plan_next()` |
| 4 | **Scoring engine** — rubrics, weights, consistency. No LLM. | `api/engine/signals.py`, `scoring.py`, `consistency.py` |
| 5 | **Ranking engine** — role weight profiles, live re-ranking | `api/engine/graph.py` + `api/routers/recruiter.py` |

### 1. Claim taxonomy

Weights live in **data, not code**, so a PM can retune "team handling is worth
25 for a BPO Team Lead" without a deploy. Eight families ship: BPO operations,
customer support, sales, banking operations, software engineering, data
analytics, HR/recruitment, and a general fallback. Every family's claim weights
sum to 100; dimension weight overrides are renormalised to exactly 1.0.

This breadth is deliberate. A judge who thinks this only works for engineers
prices the TAM at nothing.

### 2. The six evidence dimensions

| Dimension | What it measures | Gate — the score is capped without this |
|---|---|---|
| `SPECIFICITY` | concrete numbers, named things, timeframes | ≤55 with no quantity |
| `PROCESS` | how the work actually ran, step by step | ≤50 with no process step |
| `METRIC_OWNERSHIP` | can they *define* what they claim | ≤45 if the metric is never defined |
| `CAUSAL_REASONING` | cause → action → outcome | ≤50 with no complete chain |
| `AUTHENTICITY` | real people remember real incidents | ≤40 with no specific incident |
| `TOOL_FAMILIARITY` | usage, not certification | ≤40 if a tool is only named |

The gates are the interesting part. Without them, a candidate who names four
teams and no numbers scores 80 on Specificity.

**Deliberately absent: English fluency, accent, grammar, speaking confidence,
personality.** In India those track region, first language and schooling far
more than competence. A Team Lead from Jaipur must not score below one from
Bangalore for speaking less polished English. There is a test for it:

```python
def test_a_blunt_specific_answer_beats_a_polished_vague_one():
```

### 3. The question protocol

```
VALIDATION   → you claim X; what was the scope and what were the numbers
OPERATIONAL  → how did it run day to day; steps, cadence, systems
INCIDENT     → tell me about one specific time it went wrong
DECISION     → what did you decide, and what did you reject
OUTCOME      → what happened after, and how did you know
```

The **policy** is code, not a prompt — deterministic, reproducible and
explainable on stage. Budget `MAX_QUESTIONS` (12):

- **Breadth first.** One VALIDATION probe on every claim, heaviest first.
  Nobody gets deepened before every claim is touched, because an unprobed claim
  scores zero and would silently sink the candidate.
- **Then gap-driven depth.** Take the heaviest claim not yet saturated and ask
  the probe level that covers its weakest un-probed dimension. Gaps are chased
  in *weight* order, so an unprobed `PROCESS` (0.238 in BPO) goes before an
  unprobed `TOOL_FAMILIARITY` (0.048).
- **Adaptive stop.** A claim is dropped when it saturates (≥80), when all five
  levels are spent, or when the last answer produced no new signals. When every
  claim has stopped, the interview ends early — which is why a typical session
  lands at 8–10 rather than always 12, and why the evasive candidate gets 9.

`ADAPTIVE_PROBING=false` gives a strict VALIDATION→OUTCOME sweep instead.

### 4. Scoring

```python
claim_score      = Σ dimension_weight × dimension_score      # over all 6, un-probed = 0
weighted_evidence= Σ claim_weight × claim_score              # claim_weight from the ROLE
competence_score = weighted_evidence × consistency_multiplier
badge            = verified ≥ 70, partial ≥ 40, else unverified
```

Three decisions worth being able to defend out loud:

- **Evidence accumulates across answers.** The claim score is the rubric run
  over the *union* of that claim's signals, not the best single answer. Two
  complete causal chains in two different answers must beat one — taking the
  best per answer under-credited exactly the candidates the protocol is
  designed to find.
- **Un-probed dimensions contribute 0**, and `probed_dimensions` is reported
  alongside. This is a *confidence* score: one great answer is not confidence
  that the whole claim is real. A 0 nobody asked about is visibly different
  from a 0 the candidate earned.
- **`role_coverage` is separate from the score.** "Evidenced it badly" and
  "never claimed it" are different facts and a recruiter needs both.

#### Consistency — the one distinction that makes it work

Fact keys are **stable** or **variable**.

- `stable` (team_size, direct_reports, tenure_months…) — should not change
  between answers, so a divergence is a contradiction.
- `variable` (csat_pct, aht_seconds, frt_minutes…) — moves over time *by
  design*. "CSAT was 78, then 92" is the improvement the candidate is claiming.

Without that distinction the engine would flag every success story anyone tells
as an inconsistency. Divergence on a stable key: <10% is human approximation
(no flag), 10–50% is MINOR (−15), ≥50% is MAJOR (−40), floored at 20.

#### Voice

`VOICE_WEIGHT` (default 10%) applies **only to voice-answered claims**;
text-only claims are scored on content alone so nobody is penalised for typing.
The voice signal is **duration and word count, and nothing else** — see the
comment at the top of `api/engine/voice.py` for why. Set `VOICE_WEIGHT=0` to
remove the text/voice asymmetry entirely.

### 5. Ranking

`POST /api/recruiter/roles` stores a weight profile; recruiter weights are
rescaled to sum to 100, so a recruiter typing 40/30/20/20 gets what they meant
rather than a validation error. Pass `role_id` to any recruiter endpoint to
re-rank.

---

## API surface

| Method | Path | Notes |
|---|---|---|
| `POST` | `/api/candidates` | multipart resume (PDF/DOCX/TXT/MD) → claims + `opt_in_code` |
| `POST` | `/api/candidates/text` | same with `resume_text` as JSON — what the Next.js form should use |
| `GET` | `/api/sessions/{id}` | state, probe level, open question |
| `GET` | `/api/webhooks/whatsapp` | Meta's verification handshake |
| `POST` | `/api/webhooks/whatsapp` | inbound messages |
| `GET` | `/api/recruiter/candidates?role_id=` | ranked list |
| `GET` | `/api/recruiter/candidates/{id}?role_id=` | the full evidence graph |
| `GET`/`POST` | `/api/recruiter/roles` | weight profiles |
| `GET` | `/api/recruiter/taxonomy` | families, claim types, default weights — feeds the weight editor |
| `POST` | `/api/dev/simulate` | whole pipeline in one call |
| `POST` | `/api/dev/sessions/{id}/start` | ask Q1 without a WhatsApp opt-in |
| `POST` | `/api/dev/sessions/{id}/answer` | step one answer in |
| `GET` | `/api/dev/fixture` | the generated sample graph |
| `GET` | `/api/dev/llm` | cache hits, calls, fallbacks |
| `POST` | `/api/dev/reset` | drop and recreate every table |
| `GET` | `/api/health` | db, llm mode, whatsapp mode, policy |

`/openapi.json` **is the contract** with the Next.js app — generate the client,
don't hand-write types:

```bash
npx openapi-typescript http://localhost:8000/openapi.json -o src/lib/api.d.ts
```

### One command that proves the whole pipeline

```bash
curl -s -X POST localhost:8000/api/dev/simulate \
  -H 'content-type: application/json' \
  -d '{"name":"Test Candidate","resume_text":"Managed a team of 35 agents across 4 pods\nImproved CSAT from 78% to 92% in four quarters\nReduced AHT from 480 seconds to 430 seconds"}' \
  | python -m json.tool
```

---

## WhatsApp Business Cloud API (Meta, direct)

**Not a sandbox.** Four things differ from Twilio's, and all four bite:

1. **No inline reply.** There is no TwiML equivalent. The webhook must 200 fast
   and the answer goes out as a separate authenticated call — so outbound
   credentials are **mandatory** for the demo, not optional.
2. **The 24-hour window.** Free-form text is only allowed within 24h of the
   candidate's last message. That is why they opt in first: their opt-in
   message opens the window and every question after it rides on it. Outside
   it, only an approved template can be sent.
3. **Two-step media.** A voice note arrives as a media *id*. GET the id for a
   short-lived URL, then GET that URL — **bearer token on both calls**. Missing
   it on the second is a 401 that looks like a bug in your own code.
4. **Batched deliveries and status noise.** One webhook call can carry several
   messages, and most carry only delivery receipts. Anything assuming "one
   webhook, one message" silently drops answers. Meta also **retries**, so
   answers are de-duplicated on `provider_message_id`.

### Setup

1. Meta App Dashboard → WhatsApp → API Setup. Copy the phone number ID and
   WABA ID into `.env`.
2. Generate a **system user token**, not the 24-hour test token, or the demo
   dies mid-day.
3. Configure the callback URL as `https://<host>/api/webhooks/whatsapp` with
   your `WHATSAPP_VERIFY_TOKEN`, and subscribe to the `messages` field.
4. Set `WHATSAPP_VALIDATE_SIGNATURE=true` and `WHATSAPP_APP_SECRET` before the
   URL is public. Leave it off while replaying payloads with curl.
5. For first contact before the candidate messages you, get a template approved
   and set `WHATSAPP_TEMPLATE_NAME`. Without one, the candidate must send their
   opt-in code first — which the flow already handles.

**Candidate flow:** upload resume → get a 6-character `opt_in_code` → send it
to the business number → questions arrive, text or voice.

```bash
# simulate an inbound message with no Meta account at all
curl -X POST localhost:8000/api/webhooks/whatsapp -H 'content-type: application/json' -d '{
  "object":"whatsapp_business_account",
  "entry":[{"id":"W","changes":[{"field":"messages","value":{
    "messaging_product":"whatsapp",
    "metadata":{"phone_number_id":"PNID"},
    "contacts":[{"profile":{"name":"Priya"},"wa_id":"919810000001"}],
    "messages":[{"from":"919810000001","id":"wamid.X","type":"text","text":{"body":"ABC234"}}]}}]}]}'
```

---

## Cut list, as env flags

Decide on **7 September**, not on the 10th. Each is one env var:

| Cut | How |
|---|---|
| Adaptive probing → fixed sweep | `ADAPTIVE_PROBING=false` |
| Shorter interview | `MAX_QUESTIONS=8` |
| Voice out of the score | `VOICE_WEIGHT=0` |
| Scoring off the critical path | `SCORE_INLINE=false` |
| Fewer claims per candidate | `MAX_CLAIMS=2` |
| Dev endpoints hidden | `ENABLE_DEV_ENDPOINTS=false` |

**Never cut:** the evidence graph, or the fact that scores are arithmetic. That
is the product.

---

## Tests

```bash
pytest -q          # 102 tests, ~2s, no Docker, no network, no keys
```

| File | What it defends |
|---|---|
| `test_taxonomy.py` | weights sum, family detection, invented claim types get reclassified |
| `test_scoring.py` | every rubric and gate, the no-LLM structural claim, the anti-bias property, accumulation, badge thresholds |
| `test_consistency.py` | stable vs variable, symmetry, thresholds, penalties, the floor |
| `test_policy.py` | breadth before depth, weighted gap chasing, saturation, stall, budget, determinism |
| `test_pipeline.py` | HTTP end to end, verbatim guarantee, score reproducibility from the API response, re-ranking, Meta webhook incl. retry de-dup and signature rejection, voice, fixture consistency |

`fixtures/sample_graph.json` is **generated**, never hand-written
(`scripts/dump_fixture.py`), and a test asserts its numbers are still what the
rubrics compute. A hand-written fixture drifts the moment anyone tunes a target,
and then the dashboard Dev B built against it disagrees with the live API.

---

## File ownership

`api/schemas.py` is the **only** file with two owners, and it is frozen.

| Dev A — ingest, conversation, channel, infra | Dev B — evidence, scoring, dashboard |
|---|---|
| `main.py`, `config.py`, `db.py`, `models.py`, `ids.py` | `engine/signals.py` — the rubrics |
| `taxonomy.py`, `data/claim_taxonomy.json` | `engine/scoring.py` |
| `llm.py`, `stt.py` | `engine/consistency.py` |
| `ingest/parse.py` | `engine/evidence.py` |
| `engine/extract.py`, `question.py`, `orchestrator.py` | `engine/graph.py` |
| `channels/*` | `routers/recruiter.py` |
| `routers/candidates.py`, `sessions.py`, `whatsapp.py`, `dev.py` | `seed.py`, `scripts/`, `tests/` |
| `prompts/extract_claims.txt`, `generate_question.txt` | `prompts/extract_signals.txt` |
| `Dockerfile`, `docker-compose.yml`, deploy | the Next.js dashboard (separate repo) |

**The seam is the `responses` table.** A fills `raw_text`; B fills
`signals_json`. In code it is one function:
`evidence.score_response(ScoreRequest) -> ScoreResult`.

---

## What is not here

- **The Next.js dashboard** — Dev B, separate repo, built against
  `/openapi.json` and `fixtures/sample_graph.json`.
- **Web chat** — removed in v2. WhatsApp is the only candidate channel; the dev
  start/answer endpoints replace it for testing and are dev-flagged because
  they skip the consent that opting in represents.
- **Deploy config** for Render/Railway — needs your account. Meta requires a
  stable public HTTPS webhook.
- **Auth** — deliberately none. The deployed URL exposes every candidate's
  evidence graph to anyone who finds it. Fine for nine days; say it out loud
  before a judge asks.
- **Alembic** — by design. `create_all()` at startup; `docker compose down -v`
  to reset.
