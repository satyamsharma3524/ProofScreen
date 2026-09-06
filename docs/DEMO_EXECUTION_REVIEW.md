# Demo Execution Review

**2026-09-06.** `ProofScreen` @ `59b8b3b` · `ProofScreen_Next` @ `26bd15a`.
Verified against source and against a live `seed.py --reset` run, not against
documentation. Supersedes the resume-upload design in
`HACKATHON_DEMO_PLAN.md` §B.6 — see §0.

---

## 0. Three findings that change the plan

### 0.1 `api/schemas.py` does **not** need to change

The prior design added `document_id` + `document_filename` to `InboundMessage`,
which put a frozen, two-owner file on the critical path and required sign-off
before day 3 could start.

**It is avoidable.** `InboundMessage.media_id` already exists and is generic, and
`download_media()` already returns the **mime type** alongside the bytes:

```python
# api/channels/whatsapp_cloud.py:253
async def download_media(self, media_id: str) -> tuple[bytes | None, str]:
```

So: set `media_id` for a `document` message exactly as for `audio`, download
once, and **branch on the returned mime type**. `application/pdf` → resume path.
`audio/*` → transcription path.

`api/stt.py:43` already exposes the byte-level entry point, so no rework is
needed on the voice side either:

```python
async def transcribe(audio: bytes, mime: str = "audio/ogg") -> tuple[str, float]:
```

**Consequence: zero edits to the frozen file, no sign-off, no blocked day.**

### 0.2 Revised effort: **~5 h of code**, and code was never the constraint

Itemised in §4.4. The honest statement is that the build is half a day and
**Meta setup is the whole critical path**. Both prior estimates (1 day, then
4–6 h) were arguing about the wrong number.

### 0.3 A dead-air bug you will hit on stage

`_handle` runs inside a `BackgroundTask`. `create_session()` invokes LLM #1
(`extract.extract_claims`), which on a real resume takes 10–40 s. During that
window the candidate's phone shows **nothing** — no tick, no reply. On stage that
reads as a crash and the presenter starts apologising.

**Fix: send an acknowledgement before the extraction call.** Five minutes of work,
disproportionate demo value. Included in §4.3.

---

## 1. Stage-by-stage status

Verified against code. `COMPLETE` means "I traced it and it runs today".

| # | Stage | Status |
|---|---|---|
| 1 | Candidate discovers job | **COMPLETE** |
| 2 | Clicks Apply | **PARTIAL** — goes to a web form, not WhatsApp |
| 3 | WhatsApp opens | **PARTIAL** — one `wa.me` link exists, on the wrong screen, with the wrong payload |
| 4 | Uploads resume | **NOT STARTED** — documents silently dropped |
| 5 | Resume parsed | **COMPLETE** — unreachable from WhatsApp |
| 6 | Candidate + Resume created | **COMPLETE** — HTTP path only |
| 7 | Session created | **COMPLETE** |
| 8 | Question 1 generated | **COMPLETE** |
| 9 | Voice answer received | **COMPLETE** — never run live |
| 10 | Transcription | **COMPLETE** — never run live |
| 11 | Answer evaluated | **COMPLETE** |
| 12 | Cross-questioning | **COMPLETE** |
| 13 | Contradiction detection | **COMPLETE** |
| 14 | Completion | **COMPLETE** |
| 15 | Candidate report | **PARTIAL** — one sentence, no numbers |
| 16 | Recruiter ranking | **COMPLETE** |
| 17 | Evidence / transcript / contradictions | **COMPLETE** |

**14 of 17 complete. Three gaps, all on one file: `api/routers/whatsapp.py`.**

---

## 2. Exact execution paths

### 2.1 Discover → Apply → intake (works, wrong destination)

```
FRONTEND   app/candidate/page.tsx
             └─ components/candidate/jobs/OpeningsBrowser.tsx → JobCard.tsx
           app/candidate/jobs/[jobId]/page.tsx
             └─ components/candidate/jobs/ApplyButton.tsx
                  startVerification() → router.push('/candidate/start?role_id=…')
                  ⚠ wa.me branch is guarded by `alreadyVerified === true`

FRONTEND   app/candidate/start/page.tsx → components/candidate/intake/IntakeForm.tsx
             └─ lib/api/actions.ts :: createCandidateFromResume()   ["use server"]
                  → lib/api/client.ts :: apiPostForm(120 s timeout)

BACKEND    POST /api/candidates            api/routers/candidates.py :: create_candidate
             → api/ingest/parse.py :: extract_text()
             → api/routers/candidates.py :: _onboard()
                 → api/engine/orchestrator.py :: create_session()
                     → api/engine/extract.py :: extract_claims()        [LLM #1]
                     → api/engine/evaluation.py :: open_evaluation()    [draft]

TABLES     tenants, candidates, resumes, sessions, claims, evaluations

FRONTEND   IntakeForm → OptInCard  (renders opt_in_code as TEXT, no link)
```

### 2.2 WhatsApp inbound — the whole surface

```
Meta → POST /api/webhooks/whatsapp        api/routers/whatsapp.py :: receive_webhook
         ├─ whatsapp_channel.validate_signature(raw_body, X-Hub-Signature-256)
         ├─ whatsapp_channel.parse_inbound(payload) → list[InboundMessage]
         └─ BackgroundTask → handle_message() → _handle()   [own SessionLocal]

_handle():
  L146  phone = normalise_phone(external_id)
  L149  _already_processed(provider_message_id)          → dedup on responses
  L156  whatsapp_channel.mark_read()
  L159  code = _extract_code(text)                       → exactly 6 chars
  L161      find_session_by_opt_in_code(_INBOUND_SCOPE)  → bind, CLAIMS_READY, ask_next
  L192  session = find_active_session_by_phone(...)      → None ⇒ NO_SESSION_MESSAGE
  L201  if media_id: transcribe_media_id() → analyse()   ⚠ assumes audio
  L217  orchestrator.submit_answer(...)
  L234  reply = next_question.text or DONE_MESSAGE
```

### 2.3 Answer → evidence → next question (complete)

```
orchestrator.submit_answer()
  → Response row                                   [responses]
  → _persist_evidence()
      → engine/evidence.py :: score_response()      [LLM #3]
          → enforce_verbatim()                      drops non-verbatim quotes
          → consistency.check_new_facts()           [session_facts, contradictions]
          → signals.score_answer()                  six rubrics
      → Evidence rows                               [evidence]
  → recompute_claim()                               [claim_scores]
  → graph.recompute_profile()                       [profiles]
  → ask_next()
      → build_claim_states() → plan_next()          PURE — no LLM
      → question.generate_question()                [LLM #2 — wording only]
      → question.validate()                         7 pure rules, 1 regen, fallback
                                                    [questions]
  → finalize() when plan_next returns None
      → evaluation.finalize_evaluation()            [evaluations]
```

### 2.4 Recruiter review (complete)

```
FRONTEND  app/recruiter/candidates/page.tsx
            → lib/api/recruiter.ts :: getRankedCandidates(roleId)
BACKEND   GET /api/recruiter/candidates?role_id=
            → engine/graph.py :: rank_candidates() → _claim_score_under() → _why_ranked()
TABLES    candidates, profiles, claims, claim_scores, sessions, job_roles

FRONTEND  app/recruiter/candidates/[candidateId]/page.tsx
            → getCandidateGraph(id, roleId), getOutcomes(id), getRoles()   [Promise.all]
            → ConsistencyPanel · ClaimEvidence · DimensionBar · OutcomePanel
BACKEND   GET /api/recruiter/candidates/{id}?role_id=
            → engine/graph.py :: build_candidate_graph()
TABLES    + evidence(unused on read), session_facts, contradictions, resumes
```

---

## 3. Demo gaps — what breaks, where, and the smallest fix

### G1 — Apply does not open WhatsApp

**Breaks:** journey step 2→3.
**Why:** `ApplyButton.tsx:42` pushes `/candidate/start`; the `wa.me` branch at
`:37` only renders when `alreadyVerified`.
**Smallest fix:** leave the routing alone. Put the link on `OptInCard` (G2). The
intake detour is where the opt-in code is minted, so it is load-bearing.
**Effort:** 0 (subsumed by G2).

### G2 — no `wa.me` link with the opt-in code

**Breaks:** journey step 3. The candidate must open WhatsApp and type `ABC123`
by hand — 30 seconds of fumbling on stage.
**Where:** `components/candidate/intake/IntakeForm.tsx`, `OptInCard` (from :187).
**Fix:**

```tsx
{process.env.NEXT_PUBLIC_WHATSAPP_NUMBER && (
  <a className="primary-button"
     href={`https://wa.me/${process.env.NEXT_PUBLIC_WHATSAPP_NUMBER.replace(/\D/g,"")}`
           + `?text=${encodeURIComponent(result.opt_in_code)}`}
     target="_blank" rel="noopener noreferrer">
    Open WhatsApp and send {result.opt_in_code}
  </a>
)}
```

The prefill must be **the bare code and nothing else** — `_extract_code()`
(`whatsapp.py:240`) requires exactly 6 characters after stripping an optional
`join `/`start `/`ps `/`code ` prefix.
**Effort:** 45 min. **Highest value per minute in the plan.**

### G3 — documents are silently dropped

**Breaks:** journey steps 4–5 entirely.
**Where:** `api/channels/whatsapp_cloud.py:107` `parse_inbound` — `document`
falls to `else: log.info("ignoring unsupported message type %r"); continue`.
`parse_inbound` returns `[]`, `receive_webhook` returns 200, **no background task
runs, and the candidate receives nothing at all.** Silence, not an error.
**Fix:** §4.
**Effort:** ~5 h.

### G4 — unknown phone is a dead end

**Where:** `whatsapp.py:194` `NO_SESSION_MESSAGE` tells the candidate to go to a
website. Once G3 lands, the right instruction is "send me your resume".
**Fix:** rewrite the constant.
**Effort:** 5 min.

### G5 — returning candidate is treated as unknown

**Where:** `orchestrator.py:1274` `find_active_session_by_phone` filters
`state.notin_([COMPLETE, ABANDONED])`. `grep -rn "Candidate.phone" api/` returns
**one hit** — this is the only phone lookup in the codebase.
**Consequence:** all four seeded personas are unreachable over WhatsApp
(`seed.py:420` finalizes every one).
**Fix:** `find_candidate_by_phone()` + a branch that opens a new session against
the existing `Resume`.
**Effort:** 2 h. **Optional for the demo** — a fresh handset never hits it.

### G6 — completion message carries no numbers

**Where:** `whatsapp.py:DONE_MESSAGE`.
**Fix:** §6.3 of `HACKATHON_DEMO_PLAN.md` — read the `Profile` row `finalize()`
just wrote. Nothing is computed.
**Effort:** 2 h.

### G7 — dead air during claim extraction

**Where:** `_handle` → `create_session` → LLM #1, 10–40 s, no interim reply.
**Fix:** one `send_text` before the call.
**Effort:** 5 min.

---

## 4. Resume upload audit

### 4.1 The chain, piece by piece

| Step | Exists? | Where |
|---|---|---|
| WhatsApp document message | ❌ | `whatsapp_cloud.py:107` — dropped in `else` |
| Media download | ✅ **reusable as-is** | `whatsapp_cloud.py:234` `media_url()` + `:253` `download_media()` — content-agnostic, 2-step with bearer on both calls, follows redirects, 45 s timeout, **returns mime** |
| Resume parsing | ✅ | `ingest/parse.py:65` `extract_text(filename, data)` — PDF via PyMuPDF, DOCX incl. tables, 10 MB cap, `UnsupportedResume` under 80 chars with a scan-specific message |
| Candidate creation | ⚠️ pattern only | `routers/candidates.py:_onboard()` — HTTP-shaped; needs a WhatsApp-shaped twin |
| Resume creation | ⚠️ pattern only | same |
| Session creation | ✅ | `orchestrator.py:create_session()` |
| Question 1 | ✅ | `orchestrator.py:ask_next()` |

**Five of seven exist and are production-tested. Two need writing.**

### 4.2 Inputs are all already available

- **phone** — `normalise_phone(message.external_id)`
- **name** — `message.profile_name`, parsed at `whatsapp_cloud.py:132` from the
  webhook's `contacts[].profile.name`
- **tenant** — `models.DEVELOPMENT_TENANT_ID` (`"t_dev"`). Must be named
  explicitly: `_INBOUND_SCOPE` is `TenantScope.system(...)` and `.require()`
  **raises** on it by design
- **filename** — not needed; derive the extension from mime (§0.1)

### 4.3 Minimum implementation — three files, no frozen file

**File 1 — `api/channels/whatsapp_cloud.py`**, in `parse_inbound`, one branch:

```python
elif kind == "document":
    media_id = (message.get("document") or {}).get("id")
```

Two lines. No schema change: `media_id` already carries it.

**File 2 — `api/routers/whatsapp.py`**, a mime map and a helper:

```python
_RESUME_MIME = {
    "application/pdf": "resume.pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "resume.docx",
    "application/msword": "resume.docx",
    "text/plain": "resume.txt",
    "text/markdown": "resume.md",
}

def _resume_filename(mime: str) -> str | None:
    return _RESUME_MIME.get((mime or "").split(";")[0].strip().lower())
```

**File 2 — restructure the media block.** Move it **above** the session lookup at
`:192`, so a document from an unknown number is reachable. Replace `:201-210`:

```python
    # --- 2. media: ONE download, then branch on what it actually is --------
    audio: bytes | None = None
    mime = ""
    if message.media_id:
        data, mime = await whatsapp_channel.download_media(message.media_id)
        if data is None:
            await whatsapp_channel.send_text(phone, MEDIA_FAILED_MESSAGE)
            return
        filename = _resume_filename(mime)
        if filename is not None:
            await _onboard_from_document(db, phone, message, data, filename)
            return
        audio = data

    # --- 3. otherwise this is an answer to an open question ---------------
    session = await orchestrator.find_active_session_by_phone(db, phone, _INBOUND_SCOPE)
    if session is None:
        await whatsapp_channel.send_text(phone, NO_SESSION_MESSAGE)
        return

    text = (message.text or "").strip()
    transcript = None
    voice = None
    if audio is not None:
        transcript, duration = await transcribe(audio, mime)   # api.stt.transcribe
        if not transcript:
            await whatsapp_channel.send_text(phone, VOICE_FAILED_MESSAGE)
            return
        voice = analyse(transcript, duration)
```

`transcribe_media_id` becomes unused. Leave it; deleting it is a day-7 risk for
no gain.

**File 2 — the onboarding function:**

```python
async def _onboard_from_document(db, phone, message, data: bytes, filename: str) -> None:
    """A resume arrived from a number we do not know. Start an interview."""
    existing = await orchestrator.find_active_session_by_phone(db, phone, _INBOUND_SCOPE)
    if existing is not None:
        await whatsapp_channel.send_text(
            phone, "Thanks — but let's finish the question above first.")
        return

    try:
        text = extract_text(filename, data)
    except UnsupportedResume as exc:
        await whatsapp_channel.send_text(phone, f"I couldn't read that — {exc}")
        return

    # G7: say something BEFORE the model call, or the phone sits blank for 40s.
    await whatsapp_channel.send_text(
        phone, "Got your resume — reading it now, one moment.")

    candidate = Candidate(
        id=ids.candidate_id(),
        tenant_id=DEVELOPMENT_TENANT_ID,        # _INBOUND_SCOPE.require() raises
        name=(message.profile_name or "WhatsApp candidate").strip(),
        phone=phone,
    )
    resume = Resume(
        id=ids.resume_id(), tenant_id=candidate.tenant_id,
        candidate_id=candidate.id, raw_text=normalise(text), filename=filename,
    )
    db.add(candidate); db.add(resume)
    await db.commit()

    session, claims = await orchestrator.create_session(
        db, candidate, resume, Channel.whatsapp)

    # They messaged US, so the 24h window is open and opt-in is already given
    # by the act of sending the resume. create_session parks WhatsApp sessions
    # in AWAITING_OPT_IN because Meta forbids messaging first; that does not
    # apply here.
    session.state = SessionState.CLAIMS_READY.value
    await db.commit()

    question = await orchestrator.ask_next(db, session)
    if question is None:
        await whatsapp_channel.send_text(phone, NO_CLAIMS_MESSAGE)
        return

    await whatsapp_channel.send_text(
        phone,
        f"I pulled out {len(claims)} claim{'' if len(claims)==1 else 's'} worth "
        f"checking. A few questions — short answers are fine, and you can reply "
        f"with a voice note.\n\n{question.text}",
    )
    session.last_outbound_at = utcnow()
    await db.commit()
```

**File 2 — three new constants:**

```python
NO_SESSION_MESSAGE = (
    "Hi! I don't have a verification for this number yet. Send me your resume "
    "as a PDF or Word document and I'll get started."
)
MEDIA_FAILED_MESSAGE = "I couldn't download that file. Could you send it again?"
NO_CLAIMS_MESSAGE = (
    "I read the document but couldn't find anything specific enough to verify. "
    "Send a version with your actual responsibilities and numbers in it."
)
```

**File 3 — `.env`:** nothing new. `WHATSAPP_ACCESS_TOKEN` already gates
`download_media`.

**Imports to add to `whatsapp.py`:** `ids`, `Resume`, `SessionState`,
`DEVELOPMENT_TENANT_ID`, `extract_text`, `UnsupportedResume`, `normalise`,
`transcribe` (replacing `transcribe_media_id`).

### 4.4 Is 4–6 h realistic? — itemised

| Item | Time |
|---|---|
| `parse_inbound` document branch | 5 min |
| Mime map + `_resume_filename` | 15 min |
| `_handle` media-block restructure | 30 min |
| `_onboard_from_document()` | 90 min |
| Three message constants | 10 min |
| G7 acknowledgement | 5 min |
| Unit test (synthetic document payload, mirroring the existing webhook tests in `tests/test_pipeline.py:427-560`) | 60 min |
| Re-run `pytest -q`, fix fallout | 30 min |
| **Code subtotal** | **≈ 4 h** |
| Live test against a real handset | 60–120 min |
| **Total, with Meta already live** | **≈ 5–6 h** |

**Verdict.** The 1-day estimate was pessimistic; **4–6 h is realistic, and ~5 h
is the number to plan against** — *conditional on Meta being configured first*.
Without Meta, none of it is testable and the estimate is meaningless.

**Test-breakage risk: low.** Existing webhook tests
(`test_pipeline.py:446-560`, plus `test_tenancy.py`) cover the verify handshake,
status-only deliveries, retry de-dup and unknown numbers. The unknown-number test
asserts behaviour, not message text, and outbound is dry-run under test — so
rewriting `NO_SESSION_MESSAGE` is safe. Budget the 30 min anyway.

---

## 5. WhatsApp readiness audit

| Capability | Status | Minimum viable implementation |
|---|---|---|
| Opt-in flow | **COMPLETE** | none — `_extract_code` + `find_session_by_opt_in_code` work |
| `wa.me` deep link | **PARTIAL** | G2 — link on `OptInCard`, bare code as payload. 45 min |
| Session creation | **COMPLETE** | none |
| Unknown phone | **PARTIAL** | G4 — reword after G3 lands. 5 min |
| Returning candidate | **NOT STARTED** | G5 — `find_candidate_by_phone()`. 2 h. **Skippable** |
| Voice notes | **COMPLETE (untested live)** | none — §6 |
| Completion | **PARTIAL** | G6 — real numbers + link. 2 h |

**Minimum viable WhatsApp demo = G2 + G3 + G4 + G7 ≈ 6 h.** G5 and G6 are
polish; G6 buys a lot of stage value for 2 h, G5 buys almost none.

---

## 6. Voice demo readiness

### 6.1 Path

```
parse_inbound  kind in ("audio","voice")  → media_id
  → _handle  → download_media(media_id) → (bytes, "audio/ogg; codecs=opus")
             → stt.transcribe(bytes, mime)
                  _filename_for(mime) → "voice.ogg"
                  openai.audio.transcriptions.create(
                      model=whisper-1, response_format="verbose_json")
                  → (text, duration)
             → engine/voice.analyse(transcript, duration)
                  effort = 100 × (0.5·min(1, dur/30) + 0.5·min(1, words/60))
  → orchestrator.submit_answer(text=transcript, transcript=…, voice=…)
      → Response(answered_by="voice", voice_duration_seconds, voice_word_count, voice_effort)
      → scoring.claim_score(..., voice_effort, voice_weight=0.10)
  → ask_next() → next question over WhatsApp
```

`voice.analyse` measures **duration and word count only**. No accent, fluency,
grammar or "confidence". That is enforced in code, not policy — say it on stage.

### 6.2 Every dependency that must exist on demo day

**Meta**
- [ ] Meta app with WhatsApp product added
- [ ] **System user token** — a 24-hour test token will expire mid-day
- [ ] `WHATSAPP_PHONE_NUMBER_ID`
- [ ] `WHATSAPP_BUSINESS_ACCOUNT_ID`
- [ ] `WHATSAPP_VERIFY_TOKEN` matching the value typed into Meta
- [ ] `WHATSAPP_APP_SECRET` if `WHATSAPP_VALIDATE_SIGNATURE=true`
- [ ] Demo handset **not** the business number, and added as a test recipient
- [ ] ⚠️ An approved template is **not** required — the candidate messages first,
      which opens the 24-hour window. Do not block on template review.

**Webhook**
- [ ] Public HTTPS URL with a **reserved** hostname (a tunnel that reassigns
      silently detaches the webhook)
- [ ] GET verify handshake returns `hub.challenge` as **plain text**
- [ ] `messages` field subscribed
- [ ] Signature computed over the **raw** body

**OpenAI**
- [ ] `OPENAI_API_KEY` with credit
- [ ] `OPENAI_MODEL=gpt-4o` — LLM #1/#2/#3
- [ ] `OPENAI_STT_MODEL=whisper-1` — transcription
- [ ] `GET /api/health` reports `llm_mode: live`

### 6.3 The one deterministic failure

Without `OPENAI_API_KEY`, `stt.transcribe` returns `("", 0.0)` at the
`if not settings.llm_enabled` guard, and **every** voice note replies
*"I couldn't make out that voice note. Could you type your answer instead?"*
This is not a risk; it is a certainty. Check `/api/health` before you present.

---

## 7. Dependency graph

```
        ┌──────────────────────────────────────────────┐
        │  META SETUP                                  │
        │  system token · phone id · public webhook     │  ◀── CRITICAL PATH
        │  verify handshake · app secret                │      external clock
        └───────────────────┬──────────────────────────┘
                            │ blocks all three branches
      ┌─────────────────────┼─────────────────────┐
      ▼                     ▼                     ▼
┌───────────┐       ┌───────────────┐     ┌──────────────┐
│ wa.me     │       │ RESUME UPLOAD │     │ VOICE        │
│ (G2)      │       │ (G3)          │     │              │
│ 45 min    │       │ ~5 h          │     │ 0 code       │
└─────┬─────┘       └───────┬───────┘     └──────┬───────┘
      │ needs               │ needs              │ needs
      │ NEXT_PUBLIC_        │ nothing frozen ✅   │ OPENAI_API_KEY
      │ WHATSAPP_NUMBER     │                    │
      │                     ▼                    │
      │            ┌─────────────────┐           │
      │            │ download_media  │ ✅ exists │
      │            │ extract_text    │ ✅ exists │
      │            └────────┬────────┘           │
      │                     ▼                    │
      └────────────▶┌──────────────────┐         │
                    │ create_session   │ ✅       │
                    │ ask_next → Q1    │ ✅       │
                    └────────┬─────────┘         │
                             ▼                   ▼
                    ┌────────────────────────────────┐
                    │ submit_answer → evidence →     │ ✅ COMPLETE
                    │ cross-question → consistency   │
                    └────────────┬───────────────────┘
                                 ▼
                    ┌────────────────────────────────┐
                    │ finalize → Profile/Evaluation  │ ✅
                    │ completion message (G6, 2 h)   │ ⚠️
                    └────────────┬───────────────────┘
                                 ▼
   ══════════════════════════════════════════════════════════
                    ┌────────────────────────────────┐
                    │  RECRUITER RANKING + EVIDENCE  │ ✅ COMPLETE
                    │  NO DEPENDENCY ON ANY OF ABOVE │    runs on seed data
                    └────────────────────────────────┘
```

**Critical path:** `Meta setup → resume upload → live test`. Everything else is
parallelisable or optional. **The recruiter branch is fully disconnected** — that
is what makes Act 1 unconditionally safe.

---

## 8. Seven-day execution plan

### Day 1 — external unblock

**Goal.** Meta live, OpenAI live, frontend proven to build.
**Deliverables.** A text to the business number produces a log line; `/api/health`
reads `llm_mode: live`, `whatsapp: live`; `npm run build` succeeds.
**Files.** `.env` (backend), `.env.local` (frontend). No source.
**Risks.** Meta review; reserved-hostname tunnel; `node_modules` absent in
`ProofScreen_Next` so `npm ci` is required first.
**Exit criteria.** Send "hello" → `NO_SESSION_MESSAGE` arrives on the handset.
Both directions proven.

### Day 2 — browser→WhatsApp bridge

**Goal.** Apply → intake → tap → WhatsApp → question 1.
**Deliverables.** G2.
**Files.** `components/candidate/intake/IntakeForm.tsx`, `.env.local`.
**Risks.** `NEXT_PUBLIC_` var must be set at **build** time, not run time.
**Exit criteria.** A colleague completes the web-first journey on their own phone,
unassisted.

### Day 3 — resume upload

**Goal.** A brand-new candidate starts entirely from WhatsApp.
**Deliverables.** G3, G4, G7.
**Files.** `api/channels/whatsapp_cloud.py`, `api/routers/whatsapp.py`.
**No frozen-file edit.**
**Risks.** Mime strings vary (`application/msword`); `profile_name` may be absent;
`create_session` latency (mitigated by G7).
**Exit criteria.** PDF from an unknown handset → ack within 2 s → question 1
within 45 s. `pytest -q` → 457 green.

### Day 4 — live voice

**Goal.** A full voice interview in the database.
**Deliverables.** A `COMPLETE` session with `answered_by == "voice"` on every row.
**Files.** none expected; budget for `api/stt.py` if the codec surprises.
**Risks.** OGG/Opus handling; Whisper latency; token expiry.
**Exit criteria.** Recruiter transcript shows the mic icon and `Ns · N words`.
**Turn latency measured and written into the runbook.**

### Day 5 — completion report (+ returning candidate if time)

**Goal.** The candidate's phone shows real numbers at the end.
**Deliverables.** G6. G5 only if Day 3–4 ran clean.
**Files.** `api/routers/whatsapp.py`, optionally `api/engine/orchestrator.py`.
**Risks.** None material — every figure already exists on `profiles`.
**Exit criteria.** Completion message contains competence, badge, resume score
and a working `/candidate/proof?session_id=` link.

### Day 6 — hardening + dress rehearsal

**Goal.** Two clean end-to-end runs and a rehearsed fallback.
**Deliverables.** Login screens deleted; `tests/test_pipeline.py:845` fixed
(`pytest.skip` without `pytest` imported in that scope — a `NameError` the first
time the suite runs on Postgres); two full runs on two handsets; fallback path
rehearsed with the backend **stopped**.
**Files.** `app/recruiter-login/`, `app/candidate-login/`,
`tests/test_pipeline.py`.
**Risks.** Late changes destabilising a working system — **do not refactor**.
**Exit criteria.** The §11 runbook performed twice, end to end, timed.

### Day 7 — freeze

**Goal.** Change nothing.
**Deliverables.** Code freeze 10:00. Fresh `seed.py --reset`. Screenshots of every
Act 1 screen as a backup deck. One candidate pre-run to `COMPLETE` an hour before.
Runbook printed. Handset charged. Hotspot tested.
**Risks.** The urge to fix one more thing. Resist it.
**Exit criteria.** Three full rehearsals.

---

## 9. Rehearsal checklist

### 9.1 Candidate-side
- [ ] `/candidate` loads; openings visible
- [ ] Open a role; Apply modal renders
- [ ] Intake accepts a PDF; claims + opt-in code returned
- [ ] `wa.me` button opens WhatsApp with the code **prefilled and alone**
- [ ] `/candidate/proof?session_id=` shows scores after completion
- [ ] No SAMPLE DATA banner when the API is up

### 9.2 Recruiter-side
- [ ] `/recruiter/candidates` → Maya 61, Priya 56, Arjun 46, Rohit 14
- [ ] Rohit's score strip → **59 resume · 24 evidence · 14 competence**
- [ ] Consistency panel → `24 × 0.60 = 14 — consistency cost 10 points`
- [ ] Contradiction → *"said 45 earlier, then 20 — 56% apart"* · MAJOR
- [ ] Expand a Rohit claim → transcript shows *"I'm not sure how it was calculated."*
- [ ] Probe labels show **TRANSFER** on Rohit and nowhere else
- [ ] Lens toggle → People-First: Priya 68 > Maya 60 > Arjun 28 > Rohit 17
- [ ] Lens toggle → Ops-Excellence: Arjun 63 > Maya 60 > Priya 33 > Rohit 9
- [ ] `pytest -q` → 457 passed

### 9.3 WhatsApp
- [ ] `/api/health` → `whatsapp: live`
- [ ] GET verify returns the challenge as plain text
- [ ] "hello" from an unknown number → resume request
- [ ] Blue ticks appear
- [ ] Valid code → question 1
- [ ] Two fast messages → no duplicate question (dedup on `provider_message_id`)
- [ ] No 403s in the log (signature validates)

### 9.4 Voice
- [ ] `/api/health` → `llm_mode: live` ← **the demo hinges on this line**
- [ ] 20–30 s note → transcript in `responses.transcript`
- [ ] `answered_by == "voice"`, `voice_duration_seconds > 0`, `voice_effort > 0`
- [ ] Recruiter transcript shows mic icon and `Ns · N words`
- [ ] **Time one full turn and write the number down**

### 9.5 Resume upload
- [ ] PDF from an unknown number → ack → question 1
- [ ] DOCX → same
- [ ] JPEG → still dropped (acceptable), or a friendly reply if you added one
- [ ] Scanned PDF, no text layer → the `UnsupportedResume` message
- [ ] 12 MB file → the size message
- [ ] `candidates.name` picked up the WhatsApp display name
- [ ] New candidate appears in `/recruiter/candidates`

### 9.6 Failure testing
- [ ] Stop the backend → frontend shows the API notice, not a white screen
- [ ] `PROOFSCREEN_FIXTURES=fallback` + backend down → Act 1 still renders, banner visible
- [ ] Unset `OPENAI_API_KEY` → voice note replies `VOICE_FAILED_MESSAGE` (know what it looks like)
- [ ] Send a document mid-interview → *"finish the question above first"*
- [ ] Kill wifi mid-answer → recover on reconnect

---

## 10. Live failure plan

**The thesis — Best Resume ≠ Best Candidate — lives entirely in Act 1, which
runs on seeded data and needs neither WhatsApp nor OpenAI.** Every fallback below
returns to it.

| Failure | Detection | Fallback | Thesis preserved? |
|---|---|---|---|
| **Webhook fails** | No reply within 15 s | `/recruiter/simulator` or `/candidate/proof/interview` — same orchestrator, same rubric, no WhatsApp. *"Let me show you the same interview through our simulator."* | ✅ fully |
| **Transcription fails** | `VOICE_FAILED_MESSAGE` | Type the answer. Identical path minus the 10 % voice weight | ✅ fully |
| **Meta outage** | Nothing sends or arrives | Skip Act 2. Act 1 is 4 of the 8 minutes and carries the argument. *"The interview runs on WhatsApp; here is one that already did."* | ✅ fully |
| **OpenAI outage** | `/api/dev/llm` shows fallbacks climbing | Fixture mode still produces claims, questions and signals from deterministic heuristics; **scoring is byte-identical**. Act 1 is unaffected because it is already scored | ✅ fully |
| **Backend down** | API notice on every screen | `PROOFSCREEN_FIXTURES=fallback` serves Act 1 from `lib/api/fixtures.ts`, including the lens inversion. Own the banner: *"that banner is the product being honest about where its numbers came from"* | ✅ fully |
| **Frontend down** | — | `GET /api/recruiter/candidates` in a terminal, or the Day-7 screenshot deck | ⚠️ weakened but intact |
| **Everything down** | — | Screenshot deck | ⚠️ narrative only |

**Rule for the presenter: never debug on stage.** One attempt, then switch to the
fallback and keep talking. The fallbacks are rehearsed paths, not improvisation.

---

## 11. Demo day runbook

**8 minutes. Act 1 (4 min) is guaranteed. Act 2 (4 min) may fail and costs
nothing if it does.**

**Setup before you speak.** `seed.py --reset` done · one candidate pre-run to
`COMPLETE` an hour ago · tabs open on `/recruiter/candidates` and `/candidate` ·
handset screen-mirrored · `/api/health` checked.

---

### ACT 1 — the thesis (offline-capable)

**1 · `/recruiter/candidates`** — Maya 61, Priya 56, Arjun 46, Rohit 14.

> "Four candidates, ranked. Not by their resumes — by what they could actually
> evidence when questioned. Watch the bottom of this list."

**2 · point at Rohit's row** — `resume 59` · `competence 14` · `1 contradiction`.

> "Rohit has the best resume here. Fifty-nine — the highest score on the screen.
> Every keyword the job description asks for. It reads like it was written to
> beat an ATS, because that is exactly what it is. He ranks last on competence:
> fourteen."

**3 · click Rohit** — score strip **Competence 14 · Weighted evidence 24 ·
Resume only 59**.

> "Three numbers, never one. Fifty-nine on paper. Twenty-four once we asked him
> about it. Fourteen after consistency."

**4 · scroll to Consistency** — `24 × 0.60 = 14 — consistency cost 10 points`;
*"Team size — said 45 earlier, then 20 — 56% apart · MAJOR"*.

> "He told us he managed forty-five agents. Four questions later, twenty. That is
> not the AI having an opinion — it is two numbers and a subtraction. Fifty-six
> percent apart on a fact that should not move, so the whole score is multiplied
> by nought point six."

**5 · expand a claim's Transcript** — his actual words.

> "And here is why the evidence score was twenty-four to begin with. 'Team
> management is really about leadership and communication.' 'I'm not sure how it
> was calculated.' 'I don't remember the details.' No numbers, no process, no
> incident he can recall. Nothing to count."

**Point at the TRANSFER labels.**

> "After two answers that produced no evidence, the system stopped asking him
> what he did and started asking what he would do — a situation built out of his
> own other claims. A memorised resume can be recited. It cannot be transferred."

> ⚠️ **Do not say "he got a shorter interview."** He gets 12 questions, same as
> everyone. `README.md` and `CLAUDE.md` are stale on this — verified today.

**6 · back, open Priya** — resume 28, evidence 56, competence 56.

> "The mirror image. The worst resume here — twenty-eight. She does not write for
> keywords. Then you ask her: thirty-five agents in four pods, CSAT seventy-eight
> to ninety-two, and the specific week three people resigned before month-end.
> Competence fifty-six. His resume beats hers by thirty-one points. Her
> competence beats his by forty-two."

**7 · back to the list, switch lens** — People-First: Priya 68 > Maya 60 >
Arjun 28. Ops-Excellence: Arjun 63 > Maya 60 > Priya 33.

> "Same evidence, two openings. Arjun goes from third to first. Nobody was
> re-interviewed and no model was called — every dimension score is already
> stored, so this is arithmetic, in milliseconds."

---

### ACT 2 — the live journey (expendable)

**8 · `/candidate`, open a role, click Apply.**

> "That is the recruiter's side. Here is the candidate's."

**9 · upload a resume** (or send the PDF on WhatsApp if Day 3 landed).

> "Three claims worth checking, pulled straight out of the document. Now the
> interview moves to WhatsApp — no app, no login, no scheduling."

**10 · tap "Open WhatsApp"** — code prefilled; send; question 1 arrives.

> "Sending that code is the consent step. Now it asks about the first claim."

**11 · answer with a voice note.** Use the strong script:

> *"I ran a team of eighteen agents across two shifts. First-response time was
> about fifty minutes because tickets were triaged by whoever picked them up
> first, so in March we moved to skills-based routing in Zendesk and I built a
> saved view for the overflow queue. By May first-response was down to
> twenty-two minutes. The worst week was before the April billing run, when two
> people were out sick and I cleared about sixty tickets myself on the
> Saturday."*

Then, while it processes — **fill exactly the pause you timed on Day 4**:

> "That was a voice note. Transcribed, then counted — quantities, process steps,
> a complete cause-action-outcome chain, a tool with described usage, a specific
> incident. We measure how long they spoke and how much they said, and nothing
> else. Not accent, not fluency, not confidence — those track region and class,
> not competence."

**12 · answer weakly once:** *"We focused on quality and made sure standards
were maintained."*

> "And the next question goes back to what it could not establish. The interview
> adapts to the answer, not to a script."

**13 · `/recruiter/candidates`, refresh** — the live candidate appears.

> "Live, in the recruiter's list, with every point traceable to something they
> actually said."

---

### Close

> "Resumes are now written by AI, for AI. Ranking by resume quality ranks the
> writing. We rank by what a candidate can evidence when someone asks a
> follow-up — and the model never produces a score. It counts things and quotes
> them; Python does the arithmetic. Rohit had the best resume in the room."

### If challenged on accuracy

> "Five hundred and nineteen real generated questions, measured against a blind
> human reviewer. Our question validator runs at fifty-four percent precision and
> we published that. One phase recommended *not* shipping a rule because two
> humans could not label the category consistently."

**Never invent a number.**

---

## 12. Bottom line

| | |
|---|---|
| **Must build** | G2 (45 min) · G3 (~5 h) · G4 (5 min) · G7 (5 min) — **≈ 6 h** |
| **Should build** | G6 completion report (2 h) |
| **Skip** | G5 returning candidate · auth · everything in the "can skip" list |
| **Critical path** | Meta setup — external clock, start day 1 hour 1 |
| **Frozen files touched** | **none** |
| **Act 1 dependency on Act 2** | **none** |

The demo already exists. Act 2 makes it a story; Act 1 makes it true.
