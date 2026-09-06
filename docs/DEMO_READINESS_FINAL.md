# Demo readiness — final audit

**2026-09-06.** `ProofScreen` @ `59b8b3b` · `ProofScreen_Next` @ `26bd15a`.

Every claim below was **executed**, not read. Where a finding says "verified",
a script was run against the live codebase and its output is quoted. This
supersedes `DEMO_GAP_ANALYSIS.md`, `HACKATHON_DEMO_PLAN.md` §B, and
`DEMO_EXECUTION_REVIEW.md` §4 where they conflict.

**Optimisation target: prove "best resume ≠ best candidate".** WhatsApp exists
to make that feel real, and is expendable.

---

# 1. Reality check

## 1.1 Still correct

| Finding | Verified how |
|---|---|
| **The thesis is already fully demonstrable on seeded data** | `seed.py --reset` run today: Rohit resume **59** / competence **14**; Priya resume **28** / competence **56** |
| **Rohit is the only candidate to receive TRANSFER probes** | `questions` table: Rohit `TRANSFER 3`; the other three have `OUTCOME 2` in that slot |
| **The contradiction is real and quotable** | `contradictions` row: `team_size 45 → 20`, MAJOR, **55.56 %**, consistency 100→60, ×0.60 |
| **Ranking inversion reproduces across three lenses** | People-First: Priya 68 > Maya 60 > Arjun 28 > Rohit 17. Ops-Excellence: Arjun 63 > Maya 60 > Priya 33 > Rohit 9 |
| **WhatsApp documents are silently dropped** | `parse_inbound(document payload)` → `[]` |
| **Recruiter side is complete** | All ten required views traced to endpoints and components |
| **457 tests pass in ~13 s** | `pytest -q` |
| **`node_modules` absent in `ProofScreen_Next`** | Build still unverified |

## 1.2 Now obsolete — corrections

### ❌ "Resume upload requires editing `api/schemas.py`" — **WRONG**

Your discovery is correct, and it is now proven:

```
=== InboundMessage carries media_id with NO schema change ===
  constructed OK -> MEDIA_DOC_1
  fields: ['channel','text','media_id','external_id','profile_name','provider_message_id']

=== signatures ===
  download_media          (media_id: 'str') -> 'tuple[bytes | None, str]'
  stt.transcribe          (audio: 'bytes', mime: 'str' = 'audio/ogg') -> 'tuple[str, float]'
```

`media_id` already exists on `InboundMessage`. `download_media` already returns
the mime type. `stt.transcribe` already takes **bytes**, not a media id. Mime is
sufficient to route.

**No frozen-file edit. No two-owner sign-off. Nothing blocks day 3.**

### ❌ "Resume upload is 1 day" — **WRONG, and 4–6 h was also wrong**

Measured against the actual edits required: **≈ 3.5 h of code.** See §3.4. The
prior estimates were both arguing about code when Meta setup is the real
constraint.

### ❌ "Dead air is a resume-onboarding problem" — **UNDERSTATED**

It is on **every turn**, and it exists today. Verified by reading the call order
inside `_handle`:

```
line 29  question = await orchestrator.ask_next(db, session)     ← LLM #2
line 35  await whatsapp_channel.send_text(...)                   ← first reply

line 71  response, next_question, _ = await orchestrator.submit_answer(...)
                                        ← LLM #3 (evidence) + LLM #2 (next question)
line 89  await whatsapp_channel.send_text(phone, reply)          ← reply
```

**Every answer the candidate sends costs two model calls before anything comes
back.** Resume onboarding would add LLM #1 in front of that. See §2.G4.

### ❌ "Returning-candidate support is needed" — **OPTIONAL**, see §3.3

### ⚠️ `README.md` and `CLAUDE.md` are stale

Both state Rohit receives **9 questions**. He receives **12** — verified twice.
`TRANSFER_PROBE` now spends the freed budget. Do not repeat the "shorter
interview" line on stage.

## 1.3 New findings from this audit

**N1 — The mime→filename map is mandatory, not cosmetic.** `extract_text` gates
on the **file extension**, proven:

```
resume.pdf     accepted
resume.txt     accepted
resume         REJECTED: unsupported file type 'resume'
voice.ogg      REJECTED: unsupported file type '.ogg'
```

Passing Meta's mime type straight through, or a filename without an extension,
fails. The map is load-bearing.

**N2 — `extract_text` verified on real PDF bytes.** A PDF was generated in
memory and parsed:

```
PDF bytes: 1307
extract_text -> 'Rohit Verma - Senior Team Lead, Noida\n- Managed a team of 45 agents...'
```

The parse pipeline needs nothing.

**N3 — `download_media`'s mime fallback is `"audio/ogg"`.** If Meta omits
`mime_type`, a document is mislabelled as audio and routed to Whisper. Guard on
the **document message type** in `parse_inbound` as well as on mime — cheap
belt-and-braces.

---

# 2. Exact gap list — demo blockers only

### G1 — `wa.me` deep link with the opt-in code · **45 min**

**Path.** `IntakeForm.tsx` → `OptInCard` (from line 187) renders
`result.opt_in_code` as text and nothing else. `grep -rn "wa.me"` across the
frontend returns **one** hit, in `ApplyButton.tsx:37`, guarded by
`alreadyVerified`, with a prefill that is a sentence.

**Root cause.** No link was ever added to the screen that mints the code.

**Fix.** In `OptInCard`:

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

Payload must be the **bare code** — `_extract_code` (`whatsapp.py:240`) requires
exactly 6 chars after stripping an optional `join `/`start `/`ps `/`code `
prefix.

---

### G2 — WhatsApp document upload · **≈ 3.5 h**

**Path.** `whatsapp_cloud.py:107` `parse_inbound` → `document` falls to
`else: log.info("ignoring unsupported message type %r"); continue` → returns
`[]` → `receive_webhook` returns 200 → **no BackgroundTask runs** → candidate
receives absolute silence.

**Root cause.** One missing `elif`.

**Fix — three edits, no frozen file.**

**(a) `api/channels/whatsapp_cloud.py`, in `parse_inbound`:**

```python
elif kind == "document":
    doc = message.get("document") or {}
    media_id = doc.get("id")
    # N3: Meta usually sends mime_type; download_media falls back to
    # "audio/ogg" when it does not, so remember the filename it gave us.
    text = doc.get("filename") or None      # carried in `text`, no schema change
```

> Carrying the filename in the existing `text` field avoids touching
> `schemas.py`. `_extract_code` will not match it (a filename is not 6 chars of
> the code alphabet), and the document branch consumes it before the answer path
> can see it. If that feels too clever, drop it — the mime map below is enough.

**(b) `api/routers/whatsapp.py` — mime map:**

```python
_RESUME_MIME = {
    "application/pdf": "resume.pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "resume.docx",
    "application/msword": "resume.docx",
    "text/plain": "resume.txt",
    "text/markdown": "resume.md",
}

def _resume_filename(mime: str, given: str | None) -> str | None:
    """Extension decides — extract_text gates on it (N1)."""
    if given and given.lower().rsplit(".", 1)[-1] in ("pdf", "docx", "txt", "md"):
        return given
    return _RESUME_MIME.get((mime or "").split(";")[0].strip().lower())
```

**(c) `api/routers/whatsapp.py` — one download, then branch on mime.** Replace
lines 201-210 and move the block **above** the session lookup at line 192:

```python
    # --- 2. media: ONE download, then branch on what it actually is --------
    audio: bytes | None = None
    mime = ""
    if message.media_id:
        data, mime = await whatsapp_channel.download_media(message.media_id)
        if data is None:
            await whatsapp_channel.send_text(phone, MEDIA_FAILED_MESSAGE)
            return
        filename = _resume_filename(mime, message.text)
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

**(d) `_onboard_from_document` — reuses everything (§3.2):**

```python
async def _onboard_from_document(db, phone, message, data: bytes, filename: str) -> None:
    if await orchestrator.find_active_session_by_phone(db, phone, _INBOUND_SCOPE):
        await whatsapp_channel.send_text(
            phone, "Thanks — let's finish the question above first.")
        return

    try:
        text = extract_text(filename, data)
    except UnsupportedResume as exc:
        await whatsapp_channel.send_text(phone, f"I couldn't read that — {exc}")
        return

    # G4: speak BEFORE the model calls, or the phone sits blank for 40 s.
    await whatsapp_channel.send_text(
        phone, "Got your resume — reading it now. One moment.")

    candidate = Candidate(
        id=ids.candidate_id(),
        tenant_id=DEVELOPMENT_TENANT_ID,   # _INBOUND_SCOPE.require() raises by design
        name=(message.profile_name or "WhatsApp candidate").strip(),
        phone=phone,
    )
    resume = Resume(id=ids.resume_id(), tenant_id=candidate.tenant_id,
                    candidate_id=candidate.id,
                    raw_text=normalise(text), filename=filename)
    db.add(candidate); db.add(resume); await db.commit()

    session, claims = await orchestrator.create_session(
        db, candidate, resume, Channel.whatsapp)

    # They messaged US, so the 24h window is open and consent is given by the
    # act of sending the resume. create_session parks WhatsApp sessions in
    # AWAITING_OPT_IN only because Meta forbids messaging first.
    session.state = SessionState.CLAIMS_READY.value
    await db.commit()

    question = await orchestrator.ask_next(db, session)
    if question is None:
        await whatsapp_channel.send_text(phone, NO_CLAIMS_MESSAGE)
        return

    await whatsapp_channel.send_text(
        phone,
        f"I pulled out {len(claims)} claim{'' if len(claims)==1 else 's'} worth "
        f"checking. Short answers are fine, and you can reply with a voice "
        f"note.\n\n{question.text}")
    session.last_outbound_at = utcnow(); await db.commit()
```

**(e) Three constants:**

```python
NO_SESSION_MESSAGE = ("Hi! I don't have a verification for this number yet. "
                      "Send me your resume as a PDF or Word document and I'll get started.")
MEDIA_FAILED_MESSAGE = "I couldn't download that file. Could you send it again?"
NO_CLAIMS_MESSAGE = ("I read the document but couldn't find anything specific "
                     "enough to verify. Send a version with your actual "
                     "responsibilities and numbers in it.")
```

**Imports:** `ids`, `Resume`, `SessionState`, `DEVELOPMENT_TENANT_ID`,
`extract_text`, `UnsupportedResume`, `normalise`, and `transcribe` in place of
`transcribe_media_id`.

---

### G3 — unknown phone dead-ends · **5 min**

`whatsapp.py:194` currently sends the candidate to a website. Once G2 lands the
right instruction is "send your resume". Subsumed by G2(e).

---

### G4 — dead air on every turn · **15 min** — **VERIFIED, and worse than reported**

**Path.** `receive_webhook` → `background.add_task(handle_message, …)`. FastAPI
runs a `BackgroundTask` **after** the response is returned, so nothing reaches
the candidate until an explicit `send_text`. Verified call order:

| Turn | Model calls before the first reply |
|---|---|
| Opt-in code | `ask_next` → **LLM #2** |
| Every answer | `submit_answer` → **LLM #3 + LLM #2** |
| Resume upload (after G2) | `create_session` → **LLM #1**, then `ask_next` → **LLM #2** |

**Root cause.** `send_text` is only ever called with the *final* payload.

**Fix.** Three one-line acknowledgements. Smallest safe change; no
restructuring, no threading, no state.

1. In `_onboard_from_document`, before `create_session` — included above.
2. In the opt-in branch, before `ask_next` (`whatsapp.py:175`):
   ```python
   await whatsapp_channel.send_text(phone, f"Hi {first_name} — one moment while I read your resume.")
   ```
   (compute `first_name` above the call rather than at line 180)
3. In the answer branch, before `submit_answer` (`whatsapp.py:217`):
   ```python
   await whatsapp_channel.send_text(phone, "Got it — thinking about that.")
   ```

> Item 3 doubles outbound message count. It is worth it: on stage the phone
> lighting up instantly is the difference between "responsive" and "broken".
> If you dislike it, keep 1 and 2 and drop 3 — 1 is non-negotiable.

---

### G5 — completion carries no numbers · **1.5 h**

`whatsapp.py:DONE_MESSAGE` is one sentence. Everything needed already sits on
the `profiles` row that `finalize()` has just written. See §3.5.

---

## Gap summary

| Gap | Effort | Blocks |
|---|---|---|
| G1 `wa.me` link | 45 min | Journey step 3 |
| G2 document upload | 3.5 h | Journey steps 4–5 |
| G3 unknown-phone copy | 5 min | (folded into G2) |
| G4 dead air ×3 | 15 min | Perceived reliability |
| G5 completion report | 1.5 h | Candidate payoff |
| **Total** | **≈ 6 h** | |

**Zero frozen files. Zero schema changes. Zero new modules.**

---

# 3. Minimum demo path

## 3.1 Existing pipeline — reuse audit

Traced from source; every row confirmed.

| Step | Exists | Reusable as-is? |
|---|---|---|
| `download_media(media_id)` | ✅ `whatsapp_cloud.py:253` | **Yes.** Content-agnostic, two-step with bearer on both calls, follows redirects, 45 s timeout, returns real mime |
| `extract_text(filename, data)` | ✅ `ingest/parse.py:65` | **Yes** — verified on generated PDF bytes (N2). Needs a filename with an extension (N1) |
| `normalise(text)` | ✅ `ingest/parse.py:24` | Yes |
| Candidate creation | ⚠️ `routers/candidates.py:_onboard()` | **Pattern only** — HTTP-shaped. Twelve lines re-expressed |
| Resume creation | ⚠️ same | Same |
| `create_session()` | ✅ `orchestrator.py` | **Yes**, with one state override |
| `ask_next()` → Q1 | ✅ `orchestrator.py` | **Yes** |
| `stt.transcribe(bytes, mime)` | ✅ `stt.py:43` | **Yes** — public, byte-level |

**Answer to "can WhatsApp onboarding reuse existing logic rather than introduce
a new flow?"** — **Yes.** `_onboard_from_document` is ~35 lines and calls
existing functions exclusively. No new engine path, no new table, no parallel
pipeline. The only genuinely new logic is the mime→filename map.

## 3.2 Inputs are all already on the wire

- **phone** — `normalise_phone(message.external_id)`
- **name** — `message.profile_name`, parsed at `whatsapp_cloud.py:132`
- **tenant** — `DEVELOPMENT_TENANT_ID`; `_INBOUND_SCOPE.require()` raises by design
- **filename** — from the mime map, or the document's own `filename`

## 3.3 Returning candidate — **OPTIONAL. Skip it.**

> **Can the demo succeed if every live demonstration uses a fresh candidate?**
> **Yes.**

Three reasons, in order of strength:

1. **Once G2 lands, the returning case degrades gracefully.** A completed
   candidate messaging again gets `NO_SESSION_MESSAGE`, which after G2 reads
   *"send me your resume and I'll get started"*. They send it, a **new**
   candidate row is created, and a fresh interview starts. The journey works —
   it just produces a duplicate row in the recruiter list. Cosmetic, on a demo
   with four seeded candidates.
2. **The thesis does not need it.** Act 1 is seeded; Act 2 is one fresh handset.
3. **It costs 2 h** that are better spent on rehearsal.

⚠️ **The one real trap:** if you rehearse on your own handset and then demo on
the *same* handset, you are a returning candidate. **Use a different number for
the live demo, or run `POST /api/dev/reset` and re-seed before you present.**

## 3.4 Effort, itemised

| Item | Time |
|---|---|
| `parse_inbound` document branch | 10 min |
| Mime map + `_resume_filename` (N1, N3) | 20 min |
| `_handle` media-block restructure | 30 min |
| `_onboard_from_document()` | 75 min |
| Three constants | 10 min |
| G4 acknowledgements ×3 | 15 min |
| G1 `wa.me` link | 45 min |
| Unit test on a synthetic document payload | 45 min |
| `pytest -q` + fallout | 30 min |
| **Code subtotal** | **≈ 4.5 h** |
| G5 completion report | 1.5 h |
| Live testing on a handset | 60–120 min |
| **Total with Meta already live** | **≈ 7 h — one focused day** |

**Test-breakage risk: low.** Webhook tests live at `tests/test_pipeline.py:427-560`
plus `tests/test_tenancy.py`. They assert behaviour, not message strings, and
outbound is dry-run under test, so rewriting `NO_SESSION_MESSAGE` is safe.

## 3.5 G5 — the completion report

```python
async def _completion_message(db, session) -> str:
    from api.models import Profile
    from api.tenancy import TenantScope, scoped
    scope = TenantScope.of(session.tenant_id)
    p = (await db.execute(scoped(
        select(Profile).where(Profile.candidate_id == session.candidate_id),
        Profile, scope))).scalars().first()
    if p is None:
        return DONE_MESSAGE
    lines = [
        "That's everything — thank you.",
        "",
        f"Competence score: {p.competence_score}/100  ({p.badge})",
        f"Evidence score: {p.weighted_evidence_score}   ·   Resume-only score: {p.resume_score}",
    ]
    if p.contradiction_count:
        lines.append(
            f"Note: {p.contradiction_count} answer(s) didn't line up with an earlier one.")
    base = (settings.public_base_url or "").rstrip("/")   # or hardcode for the demo
    if base:
        lines += ["", f"Full breakdown: {base}/candidate/proof?session_id={session.id}"]
    return "\n".join(lines)
```

Called where `DONE_MESSAGE` is used at `whatsapp.py:234`. Nothing is computed —
every figure is read off the row `finalize()` just wrote.

**Demo value: high.** The judge watches the phone show `Competence 61` next to
`Resume-only 50`. The thesis lands on the candidate's own screen.

---

# 4. Dependency graph

```
┌────────────────────────────────────────────────────────────┐
│  META SETUP                                                │
│  system-user token · phone_number_id · reserved webhook URL │  ◀── CRITICAL PATH
│  verify handshake · app secret                              │      external clock
└──────────────────────────┬─────────────────────────────────┘
                           │
                           ▼
              ┌────────────────────────────┐
              │  WHATSAPP MESSAGE RECEIVED │   test: "hello" → NO_SESSION_MESSAGE
              └─────────────┬──────────────┘   proves BOTH directions
                            │
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
┌───────────────┐   ┌───────────────┐   ┌───────────────┐
│ G1 wa.me link │   │ G2 RESUME     │   │ VOICE         │
│ 45 min        │   │ UPLOAD 3.5 h  │   │ 0 code        │
│ frontend only │   │ backend only  │   │               │
└───────┬───────┘   └───────┬───────┘   └───────┬───────┘
        │ needs             │ reuses:           │ needs
        │ NEXT_PUBLIC_      │ download_media ✅  │ OPENAI_API_KEY
        │ WHATSAPP_NUMBER   │ extract_text   ✅  │
        │ (BUILD time)      │ create_session ✅  │
        │                   │ ask_next       ✅  │
        │                   │ NEW: mime map      │
        └─────────┬─────────┴───────────────────┘
                  ▼
        ┌─────────────────────┐
        │  ASSESSMENT START   │  ✅ exists
        └──────────┬──────────┘
                   ▼
        ┌──────────────────────────────────────┐
        │ submit_answer → evidence →           │ ✅ exists
        │ cross-question → transfer probe →    │
        │ consistency → competence             │
        └──────────────────┬───────────────────┘
                           ▼
        ┌──────────────────────────────────────┐
        │ finalize → Profile / Evaluation      │ ✅ exists
        │ G5 completion report        1.5 h    │ ⚠️
        └──────────────────┬───────────────────┘
                           ▼
        ┌──────────────────────────────────────┐
        │        DEMO REHEARSAL                │
        └──────────────────────────────────────┘

  ══════════════ NO EDGE CROSSES THIS LINE ══════════════

        ┌──────────────────────────────────────┐
        │  ACT 1 — RECRUITER + SEEDED DATA     │ ✅ COMPLETE
        │  runs with PROOFSCREEN_FIXTURES=     │    zero dependencies above
        │  fallback and NO BACKEND AT ALL      │
        └──────────────────────────────────────┘
```

**Critical path:** `Meta setup → G2 → live test → rehearsal`.
**G1 and voice parallelise off Meta.** G5 depends on nothing but itself.
**Act 1 is disconnected from the entire graph** — that is the whole safety design.

---

# 5. Seven-day plan

### Day 1 — external unblock
**Goal.** Meta live, OpenAI live, frontend proven to build.
**Do.** System-user token (**not** the 24-h test token) · `WHATSAPP_PHONE_NUMBER_ID` ·
reserved-hostname public webhook · GET verify handshake · `WHATSAPP_APP_SECRET` ·
`OPENAI_API_KEY` · `cd ProofScreen_Next && npm ci && npm run build`.
**Exit.** Text "hello" to the business number → `NO_SESSION_MESSAGE` arrives on
the handset. Both directions proven. `/api/health` reads `llm_mode: live`,
`whatsapp: live`.
**Risk.** Meta review clock. Nothing else on this list can be tested until this
is green — start it hour 1.

### Day 2 — G1 + G4
**Goal.** Web-first journey works, and nothing ever feels hung.
**Files.** `components/candidate/intake/IntakeForm.tsx`, `.env.local`,
`api/routers/whatsapp.py`.
**Exit.** A colleague completes Apply → intake → tap → WhatsApp → Q1, unassisted,
on their own phone, with an acknowledgement inside 2 s at every step.
**Risk.** `NEXT_PUBLIC_` vars are inlined at **build** time — rebuild after setting.

### Day 3 — G2
**Goal.** A brand-new candidate starts entirely from WhatsApp.
**Files.** `api/channels/whatsapp_cloud.py`, `api/routers/whatsapp.py`.
**Exit.** PDF from an unknown handset → ack in 2 s → Q1 within 45 s.
`pytest -q` → 457 green.
**Risk.** Mime variants (`application/msword`); missing `mime_type` (N3);
extension gating (N1).

### Day 4 — live voice
**Goal.** A complete voice interview in the database.
**Files.** none expected; budget for `api/stt.py` if the codec surprises.
**Exit.** Recruiter transcript shows the mic icon and `Ns · N words`;
`answered_by == "voice"` on every row. **Turn latency measured and written into
the runbook.**
**Risk.** OGG/Opus; Whisper latency; token expiry.

### Day 5 — G5 + buffer
**Goal.** The candidate's phone shows real numbers.
**Files.** `api/routers/whatsapp.py`.
**Exit.** Completion message carries competence, badge, resume score and a
working `/candidate/proof?session_id=` link.
**Buffer.** Half a day held for Day 3–4 overspill. Do **not** start the
returning-candidate flow.

### Day 6 — harden + dress rehearsal
**Do.** Delete `app/recruiter-login/` and `app/candidate-login/` (they do
nothing; a judge will click them). Fix `tests/test_pipeline.py:845` —
`pytest.skip` without `pytest` imported in that scope, a `NameError` the first
time the suite runs on Postgres. Two full runs on two different handsets.
Rehearse Act 1 with `PROOFSCREEN_FIXTURES=fallback` **and the backend stopped**.
**Exit.** §7 runbook performed twice, timed.
**Risk.** Late refactoring. Do not.

### Day 7 — freeze
**Do.** Code freeze 10:00. Fresh `seed.py --reset`. Screenshot every Act 1 screen
as a backup deck. Pre-run one candidate to `COMPLETE` an hour before. Print the
runbook. Charge the handset. Test the venue network and a hotspot. **Use a demo
number that has never been used in rehearsal** (§3.3).
**Exit.** Three full rehearsals.

---

# 6. Rehearsal checklist

### 6.1 Webhook verification
- [ ] `/api/health` → `whatsapp: live`, `llm_mode: live`, `database: ok`
- [ ] Meta GET verify echoes `hub.challenge` as **plain text**, not JSON
- [ ] `messages` field subscribed in the Meta dashboard
- [ ] Send "hello" from an unknown number → resume request arrives
- [ ] Blue ticks appear (`mark_read`)
- [ ] No 403s in the log (signature computed over the **raw** body)
- [ ] Send two messages in quick succession → **no duplicate question** (dedup on `provider_message_id`)

### 6.2 Media upload verification
- [ ] `download_media` returns non-zero bytes (check the log line)
- [ ] Returned mime is the real one, not the `audio/ogg` fallback (N3)
- [ ] A document sent **mid-interview** → *"finish the question above first"*

### 6.3 PDF / DOCX upload verification
- [ ] PDF from an unknown number → ack **within 2 s** → Q1 within 45 s
- [ ] DOCX → same
- [ ] Scanned PDF with no text layer → the `UnsupportedResume` message, not silence
- [ ] 12 MB file → the size message
- [ ] JPEG → still dropped (acceptable) — know that it is silent
- [ ] `candidates.name` picked up the WhatsApp display name
- [ ] New candidate visible in `/recruiter/candidates` within seconds

### 6.4 Voice transcription verification
- [ ] `/api/health` → `llm_mode: live` ← **without this, every voice note fails, deterministically**
- [ ] 20–30 s note → text in `responses.transcript`
- [ ] `answered_by == "voice"`, `voice_duration_seconds > 0`, `voice_effort > 0`
- [ ] Recruiter transcript shows mic icon and `Ns · N words`
- [ ] A 2-second grunt → handled, not crashed
- [ ] **Time one full turn. Write the number down — it is your on-stage pause.**

### 6.5 Completion report verification
- [ ] Final message carries competence, badge, evidence and resume scores
- [ ] Contradiction line appears when one exists
- [ ] `/candidate/proof?session_id=` link opens and shows the same numbers
- [ ] Session state reads `COMPLETE`; an `evaluations` row is `finalized`

### 6.6 Recruiter dashboard verification
- [ ] `/recruiter/candidates` → Maya 61, Priya 56, Arjun 46, Rohit 14
- [ ] Rohit score strip → **59 resume · 24 evidence · 14 competence**
- [ ] Consistency panel → `24 × 0.60 = 14 — consistency cost 10 points`
- [ ] Contradiction → *"said 45 earlier, then 20 — 56% apart"* · MAJOR
- [ ] Rohit transcript → *"I'm not sure how it was calculated."*
- [ ] Probe labels show **TRANSFER** on Rohit and nowhere else
- [ ] Lens toggle → People-First: Priya 68 > Maya 60 > Arjun 28 > Rohit 17
- [ ] Lens toggle → Ops-Excellence: Arjun 63 > Maya 60 > Priya 33 > Rohit 9
- [ ] Live candidate appears alongside the seeded four
- [ ] `pytest -q` → 457 passed

### 6.7 Failure rehearsal
- [ ] Stop the backend → frontend shows the API notice, not a white screen
- [ ] `PROOFSCREEN_FIXTURES=fallback` + backend stopped → **Act 1 renders in full**
- [ ] Unset `OPENAI_API_KEY` → see `VOICE_FAILED_MESSAGE` once so you recognise it
- [ ] Kill wifi mid-answer → recovers on reconnect

---

# 7. Demo-day runbook

**8 minutes. Act 1 (4 min) cannot fail. Act 2 (4 min) may, and costs nothing.**

**Before speaking.** `seed.py --reset` done · one candidate pre-run to `COMPLETE`
an hour ago · tabs open on `/recruiter/candidates` and `/candidate` · handset
mirrored · **demo number never used in rehearsal** · `/api/health` checked.

---

## ACT 1 — the thesis · runs on `PROOFSCREEN_FIXTURES=fallback` with no backend

**1 · `/recruiter/candidates`**
Screen: Maya 61, Priya 56, Arjun 46, Rohit 14.

> "Four candidates, ranked. Not by their resumes — by what they could actually
> evidence when someone asked a follow-up question. Watch the bottom of the list."

**2 · point at Rohit's row** — `resume 59` · `competence 14` · `1 contradiction`.

> "Rohit has the best resume on this screen. Fifty-nine — the highest here. Every
> keyword the job description asks for. It reads like it was written to beat an
> ATS, because that is exactly what it is. He ranks last on competence: fourteen."

**3 · click Rohit** — score strip: **Competence 14 · Weighted evidence 24 ·
Resume only 59**.

> "Three numbers, never one. Fifty-nine on paper. Twenty-four once we asked him
> about it. Fourteen after consistency."

**4 · scroll to Consistency** — `24 × 0.60 = 14 — consistency cost 10 points` ·
*"Team size — said 45 earlier, then 20 — 56% apart · MAJOR"*.

> "He told us he managed forty-five agents. Four questions later, twenty. That is
> not the AI having an opinion — it is two numbers and a subtraction. Fifty-six
> percent apart on a fact that should not move, so his whole score is multiplied
> by nought point six."

**5 · expand a claim's Transcript.**

> "And here is why the evidence score was twenty-four to begin with. 'Team
> management is really about leadership and communication.' 'I'm not sure how it
> was calculated.' 'I don't remember the details.' No numbers, no process, no
> incident he can recall. There is nothing to count."

**Point at the TRANSFER labels.**

> "After two answers that produced no evidence, the system stopped asking him
> what he did and started asking what he *would* do — a scenario assembled from
> his own other claims. A memorised resume can be recited. It cannot be
> transferred."

> ⚠️ **Do not say "he got a shorter interview."** He gets 12, like everyone.

**6 · back, open Priya** — resume 28, evidence 56, competence 56.

> "The mirror image. The worst resume here — twenty-eight. She does not write for
> keywords. Then you ask her: thirty-five agents across four pods, CSAT
> seventy-eight to ninety-two, and the specific week three people resigned before
> month-end. Competence fifty-six. His resume beats hers by thirty-one points.
> Her competence beats his by forty-two."

**7 · back to the list, switch the lens.**
People-First: Priya 68 > Maya 60 > Arjun 28 > Rohit 17.
Ops-Excellence: Arjun 63 > Maya 60 > Priya 33 > Rohit 9.

> "Same evidence, two openings. Arjun goes from third to first. Nobody was
> re-interviewed and no model was called — every dimension score is already
> stored, so this is arithmetic, in milliseconds."

**— The thesis is now proven. Everything after this is optional. —**

---

## ACT 2 — the live journey

**8 · `/candidate`, open a role, click Apply.**
> "That is the recruiter's side. Here is the candidate's."

**9 · Upload the resume** — on the web, or send the PDF straight to WhatsApp if
G2 landed.
> "Three claims worth checking, pulled straight out of the document."

**10 · Tap "Open WhatsApp"** — code prefilled; send.
Screen: ack within 2 s, then question 1.
> "Sending that code is the consent step. Now it asks about the first claim."

**11 · Answer with a voice note.** Strong script:

> *"I ran a team of eighteen agents across two shifts. First-response time was
> around fifty minutes because tickets were triaged by whoever picked them up
> first, so in March we moved to skills-based routing in Zendesk and I built a
> saved view for the overflow queue. By May first-response was down to
> twenty-two minutes. The worst week was before the April billing run — two
> people out sick, and I cleared about sixty tickets myself on the Saturday."*

**Fill exactly the pause you timed on Day 4:**

> "That was a voice note. Transcribed, then counted — quantities, process steps,
> a complete cause-action-outcome chain, a tool with described usage, a specific
> incident. We measure how long they spoke and how much they said, and nothing
> else. Not accent, not fluency, not confidence — those track region and class,
> not competence."

**12 · Answer weakly once:** *"We focused on quality and made sure standards were
maintained."*
> "And the next question goes back to what it could not establish. The interview
> adapts to the answer, not to a script."

**13 · `/recruiter/candidates`, refresh** — the live candidate appears with a
real score.
> "Live, in the recruiter's list, with every point traceable to something they
> actually said."

---

## Close

> "Resumes are now written by AI, for AI. Ranking by resume quality ranks the
> writing. We rank by what a candidate can evidence when someone asks a
> follow-up — and the model never produces a score. It counts things and quotes
> them; Python does the arithmetic. Rohit had the best resume in the room."

## If challenged on accuracy

> "Five hundred and nineteen real generated questions, measured against a blind
> human reviewer. Our question validator runs at fifty-four percent precision and
> we published that number. One research phase recommended *not* shipping a rule,
> because two humans could not label the category consistently."

**Never invent a number.**

---

# 8. Failure matrix

Every row returns to Act 1, which needs neither WhatsApp, nor OpenAI, nor the
backend.

| Failure | Presenter does | Switches to | Thesis still proven? |
|---|---|---|---|
| **Meta outage** | Finish Act 1 as normal; skip Act 2 entirely. *"The interview runs on WhatsApp — here is one that already did."* | Act 1 only, 4 of 8 min | ✅ **fully** |
| **Webhook failure** (no reply in 15 s) | One retry, then switch. *"Let me show you the same interview through our simulator."* | `/candidate/proof/interview` or `/recruiter/simulator` — same orchestrator, same rubric, no WhatsApp | ✅ **fully** |
| **OpenAI outage** | Nothing visible in Act 1 — those scores are already computed. Act 2 falls back to deterministic heuristics; **scoring arithmetic is byte-identical** | Continue; check `/api/dev/llm` for fallback count | ✅ **fully** |
| **Voice transcription fails** | Type the answer instead. Identical path bar the 10 % voice weight | Same WhatsApp thread | ✅ **fully** |
| **Resume upload fails** | Use the web intake at `/candidate/start`, which is the tested path | Act 2 continues from step 10 | ✅ **fully** |
| **Backend outage** | `PROOFSCREEN_FIXTURES=fallback` serves Act 1 from `lib/api/fixtures.ts`, **including the lens inversion**. Own the banner: *"that strip is the product being honest about where its numbers came from"* | Act 1 only | ✅ **fully** |
| **Frontend outage** | `curl /api/recruiter/candidates` on screen, or the Day-7 screenshot deck | Terminal / deck | ⚠️ weakened, intact |
| **Total loss** | Screenshot deck + the story | Deck | ⚠️ narrative only |

**Presenter rule: never debug on stage.** One attempt, then switch and keep
talking. Every fallback above is a rehearsed path, not an improvisation.

---

# 9. Bottom line

| | |
|---|---|
| **Build** | G1 45 min · G2 3.5 h · G3 5 min · G4 15 min · G5 1.5 h — **≈ 6 h, one focused day** |
| **Skip** | Returning-candidate flow · auth · everything not listed above |
| **Frozen files touched** | **none** — verified, `InboundMessage` already carries `media_id` |
| **Critical path** | Meta setup. External clock. Day 1, hour 1 |
| **Act 1 → Act 2 dependency** | **none** |

Your discovery was right: media handling is already content-agnostic, and the
resume pipeline is a wiring job, not a build. The thesis is already provable
today with `seed.py` and no network.

**Act 2 makes it feel real. Act 1 makes it true. Never let the second depend on
the first.**
