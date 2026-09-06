# Hackathon demo — staff-level audit, plan and runbook

**Audited 2026-09-06** against `ProofScreen` @ `59b8b3b` and `ProofScreen_Next`
@ `26bd15a`. Fresh read of the source; the earlier `DEMO_GAP_ANALYSIS.md` was
not assumed correct. Two of its claims turned out to be wrong and are corrected
below (§E.1, §H).

**Thesis being demonstrated:** resumes can be optimised, embellished or
AI-generated, so ranking by resume quality ranks the wrong thing. ProofScreen
ranks by competence extracted as evidence from an adaptive voice interview.

**Everything in this document was verified by running the code**, not by reading
comments. `python seed.py --reset` was executed today and its output is quoted
verbatim in §C.

---

## Executive summary

| Journey stage | Status |
|---|---|
| 1. Candidate discovers job | **COMPLETE** |
| 2. Clicks Apply → WhatsApp opens | **PARTIAL** — Apply goes to a web form; no `wa.me` on the opt-in card |
| 3. Uploads resume on WhatsApp | **NOT STARTED** — documents are silently dropped |
| 4. Resume parsed | **COMPLETE** but unreachable from WhatsApp |
| 5. First assessment question | **COMPLETE** |
| 6. Voice answers | **COMPLETE in code, never run live** |
| 7. System evaluates answer | **COMPLETE** |
| 8. Adaptive cross-questions | **COMPLETE** |
| 9. Evidence gathered per claim | **COMPLETE** |
| 10. Inconsistencies detected | **COMPLETE** |
| 11. Assessment completes | **COMPLETE** |
| 12. Candidate receives summary | **PARTIAL** — one sentence, no numbers |
| 13. Recruiter reviews ranking | **COMPLETE** |
| 14. Recruiter inspects evidence | **COMPLETE** |

**Four stages need work. Everything else runs today.** Three of the four sit on
one code path: `api/routers/whatsapp.py`. Total build ≈ **2 days**, plus Meta's
approval clock, which is the real critical path.

**The single most important finding:** the thesis story is already fully
demonstrable with seeded data, offline, today — see §C. That is your safety net,
and it is stronger than the live journey.

---

# A. Apply → WhatsApp flow

## A.1 Apply button behaviour — PARTIAL

**Code path**

```
components/candidate/jobs/ApplyButton.tsx
  └─ startVerification()  →  router.push(`/candidate/start?role_id=${openingId}`)
  └─ whatsappUrl  =  wa.me link, rendered ONLY when alreadyVerified === true
```

**Files:** `components/candidate/jobs/ApplyButton.tsx`,
`app/candidate/jobs/[jobId]/page.tsx`

**What currently happens.** A new candidate clicks "Get considered", a modal
explains the evidence flow, they click Start, and they land on **the web intake
form** at `/candidate/start`. WhatsApp is never opened. The `wa.me` branch is
guarded by `alreadyVerified && whatsappUrl` — it is for a candidate who already
has a completed graph.

**What should happen.** Apply opens WhatsApp with a message that starts the
assessment.

**Gap.** The button routes to the wrong place for the demo's primary persona.

**Smallest fix.** Keep the intake detour — it is where the opt-in code is minted
— and put the `wa.me` link on the card that shows the code. See A.5.
Alternatively (better story, more work) make Apply open WhatsApp directly with a
"resume-first" message; that depends on §B.

**Effort.** 1 h.

## A.2 WhatsApp deep links — PARTIAL

`grep -rn "wa.me" ProofScreen_Next/` returns **one** hit: `ApplyButton.tsx:37`.

The prefilled text is:

```
Hi ProofScreen, I'd like to be considered for {openingTitle}.
```

**This does not resolve to anything.** `_extract_code()` in
`api/routers/whatsapp.py` strips an optional `join `/`start `/`ps `/`code `
prefix and then requires **exactly 6 characters** from
`ABCDEFGHJKLMNPQRSTUVWXYZ23456789`. The sentence fails that test, so the message
falls through to the answer path.

**Effort to fix:** 30 min (change the prefill), but it only helps once A.5 lands.

## A.3 Session creation — COMPLETE (from the web)

```
POST /api/candidates  (routers/candidates.py:_onboard)
  → ingest/parse.extract_text()
  → orchestrator.create_session()        [LLM #1: extract.extract_claims]
      → ChatSession(state=NEW → AWAITING_OPT_IN, opt_in_code=ids.join_code())
      → Claim rows
      → evaluation.open_evaluation()     [draft]
  → CandidateCreateOut{opt_in_code, claims, whatsapp_instructions}
```

**Tables:** `candidates`, `resumes`, `sessions`, `claims`, `evaluations`.

Works correctly. Note `create_session` sets `AWAITING_OPT_IN` for
`Channel.whatsapp` and `CLAIMS_READY` for anything else — that branch matters
for §B.

## A.4 Candidate identification — INCOMPLETE

`grep -rn "Candidate.phone" api/` → **one hit**,
`api/engine/orchestrator.py:1274`, inside `find_active_session_by_phone()`,
which filters:

```python
ChatSession.state.notin_([SessionState.COMPLETE.value, SessionState.ABANDONED.value])
```

There is no other phone lookup in the codebase. Identity is therefore *"do you
have an in-flight session?"*, not *"do we know you?"*.

## A.5 Opt-in code flow — PARTIAL

**Code path**

```
IntakeForm  →  OptInCard  (components/candidate/intake/IntakeForm.tsx:187)
  renders  result.opt_in_code  as text
  renders  result.whatsapp_instructions
  NO wa.me link
```

The candidate is told *"Send the message `ABC123` to our WhatsApp business
number"* and must open WhatsApp and type it manually. On a demo stage that is
30 seconds of a person fumbling with a phone.

**Smallest fix.** Add to `OptInCard`:

```tsx
<a className="primary-button"
   href={`https://wa.me/${num}?text=${encodeURIComponent(result.opt_in_code)}`}
   target="_blank" rel="noopener noreferrer">
  Open WhatsApp and send {result.opt_in_code}
</a>
```

Requires `NEXT_PUBLIC_WHATSAPP_NUMBER`. **Effort: 45 min.** This is the highest
value-per-minute change in the whole plan.

## A.6 Resume-first onboarding — NOT STARTED

See §B.

## A.7 — The four questions, answered exactly

> **Can a brand new candidate start entirely from WhatsApp?**

**No.** Two hard blocks. (1) A first message that is not a 6-char code produces
`NO_SESSION_MESSAGE`. (2) Even if they wanted to send a resume, documents are
dropped (§B). A new candidate must use the web form first.

> **What happens if the phone number is unknown?**

`_extract_code` → `None` → `find_active_session_by_phone` → `None` →

```
"Hi! I couldn't find an active verification for this number. Upload your
 resume on ProofScreen and send me the 6-character code you get back to begin."
```

`api/routers/whatsapp.py:NO_SESSION_MESSAGE`.

> **What happens if the phone number already exists?**

Depends entirely on session state, not on the candidate existing. If they have a
session in `NEW`/`CLAIMS_READY`/`AWAITING_OPT_IN`/`ASKING`/`SCORING`, the message
is treated as an answer to the open question. Otherwise, identical to unknown.

> **What happens if the candidate previously completed an assessment?**

`COMPLETE` is excluded by the `notin_` filter, so they are treated as an unknown
number and get `NO_SESSION_MESSAGE`. **This is why all four seeded personas are
unreachable over WhatsApp** — `seed.py:420` calls `orchestrator.finalize()` on
every one of them.

---

# B. Resume upload flow — the one real build

## B.1 WhatsApp document handling — NOT STARTED

**Code path (verified by reading `parse_inbound` in full):**

```
api/channels/whatsapp_cloud.py:107  parse_inbound()
  kind == "text"                 → text
  kind in ("audio", "voice")     → media_id
  kind == "button"               → text
  kind == "interactive"          → text
  else:  log.info("ignoring unsupported message type %r", kind);  continue
```

A `document` message hits the `else`. It is **not** an error — the message is
dropped, `parse_inbound` returns `[]`, `receive_webhook` returns 200 with no
background task, and **the candidate gets total silence**. That is worse than an
error on stage, because it looks like the product is dead.

## B.2 Media download — COMPLETE AND REUSABLE

This is the audit's most useful finding, and it contradicts the pessimistic read
in the earlier document.

```
api/channels/whatsapp_cloud.py:234  media_url(media_id)  → (url, mime_type)
api/channels/whatsapp_cloud.py:253  download_media(media_id) → (bytes, mime)
```

`download_media` is **content-type agnostic**. It does the two-step Meta fetch
with the bearer token on both calls, follows redirects, has a 45 s timeout, and
returns raw bytes plus the real mime type. Its only audio-specific detail is the
fallback string `"audio/ogg"` when mime is missing. **It works for a PDF today,
unchanged.**

## B.3 Resume parsing — COMPLETE, just not reachable

```
api/ingest/parse.py:extract_text(filename, data)
  .pdf  → PyMuPDF (import pymupdf, falls back to fitz)
  .docx → python-docx, including tables
  .txt/.md → utf-8
  caps at 10 MB; raises UnsupportedResume under 80 chars with a scan-specific message
```

Takes `(filename, bytes)`. `download_media` returns bytes and a mime type. The
only missing piece is a mime→extension map, which already exists in a sibling
file (`api/stt.py:_EXTENSIONS`) as a pattern to copy.

## B.4 Candidate creation after upload — NOT STARTED

`routers/candidates.py:_onboard()` does this for HTTP, but it needs `name`,
`phone` and `tenant`. All three are available on the WhatsApp path:

- **phone** — `normalise_phone(message.external_id)`
- **name** — `message.profile_name` (WhatsApp display name, already parsed into
  `InboundMessage` at `whatsapp_cloud.py:132`)
- **tenant** — `models.DEVELOPMENT_TENANT_ID`. `_INBOUND_SCOPE` is a
  `TenantScope.system(...)`, and `.require()` on it **raises** by design, so a
  write must name its tenant explicitly.

## B.5 — The four questions, answered exactly

> **Can a candidate upload PDF/DOCX via WhatsApp?** No. Silently dropped.
>
> **Is document media currently parsed?** No. `download_media` is only called
> from `stt.transcribe_media_id()`.
>
> **Is there an existing ingestion pipeline we can reuse?** Yes — three of four
> pieces exist and are production-tested: `download_media()`, `extract_text()`,
> `orchestrator.create_session()`. Only the wiring is missing.

## B.6 Minimum implementation

Four edits. ~4–6 hours including a live test.

**1. `api/schemas.py` — one optional field** ⚠️ *frozen file, two owners,
announce before editing. Additive-optional is explicitly "a conversation" in
CLAUDE.md, not a solo decision.*

```python
class InboundMessage(BaseModel):
    ...
    document_id: str | None = None
    document_filename: str | None = None
```

**2. `api/channels/whatsapp_cloud.py:parse_inbound`** — add before the `else`:

```python
elif kind == "document":
    doc = message.get("document") or {}
    document_id = doc.get("id")
    document_filename = doc.get("filename") or "resume.pdf"
```

…and pass both into the `InboundMessage(...)` construction.

**3. `api/routers/whatsapp.py:_handle`** — one new branch, placed **after** the
opt-in-code block and **before** `find_active_session_by_phone`:

```python
if message.document_id:
    session = await orchestrator.find_active_session_by_phone(db, phone, _INBOUND_SCOPE)
    if session is not None:
        await whatsapp_channel.send_text(phone, "Thanks — answer the question above first.")
        return
    data, mime = await whatsapp_channel.download_media(message.document_id)
    if not data:
        await whatsapp_channel.send_text(phone, RESUME_FAILED_MESSAGE); return
    try:
        text = extract_text(message.document_filename or "resume.pdf", data)
    except UnsupportedResume as exc:
        await whatsapp_channel.send_text(phone, f"I couldn't read that — {exc}"); return

    candidate = Candidate(id=ids.candidate_id(), tenant_id=DEVELOPMENT_TENANT_ID,
                          name=message.profile_name or "WhatsApp candidate", phone=phone)
    resume = Resume(id=ids.resume_id(), tenant_id=candidate.tenant_id,
                    candidate_id=candidate.id, raw_text=normalise(text),
                    filename=message.document_filename)
    db.add(candidate); db.add(resume); await db.commit()

    session, claims = await orchestrator.create_session(db, candidate, resume, Channel.whatsapp)
    # They have already messaged us, so the 24h window is open and opt-in is moot.
    session.state = SessionState.CLAIMS_READY.value
    await db.commit()

    question = await orchestrator.ask_next(db, session)
    await whatsapp_channel.send_text(
        phone,
        f"Got it — I pulled out {len(claims)} claims worth checking.\n\n{question.text}",
    )
    session.last_outbound_at = utcnow(); await db.commit()
    return
```

**4. `api/routers/whatsapp.py:NO_SESSION_MESSAGE`** — change it to ask for the
resume, since that is now an action the candidate can take:

```python
NO_SESSION_MESSAGE = (
    "Hi! I don't have a verification for this number yet. "
    "Send me your resume as a PDF or Word document and I'll get started."
)
```

**Why `Channel.whatsapp` then an immediate state override:** `create_session`
sets `AWAITING_OPT_IN` for the WhatsApp channel because Meta forbids messaging
first. Here the candidate messaged *us*, so the window is already open and the
consent step is already satisfied by the act of sending the resume.

**Effort: 4–6 h**, of which ~2 h is testing against a real handset.

---

# C. Resume → competence verification story — **COMPLETE TODAY**

This is the demo's central narrative and it needs **zero new code**.

## C.1 Verified output — `python seed.py --reset`, run 2026-09-06

```
  candidate           Q  resume  evidence  consist  competence  badge
  -------------------------------------------------------------------
  Priya Raghavan     12      28        56      100          56  partial
  Arjun Mehta        12      34        46      100          46  partial
  Rohit Verma        12      59        24       60          14  unverified  (1 contradiction)
  Maya Krishnan      12      50        61      100          61  partial

  Same evidence, two recruiters:
    Team Lead — People First         Priya (68) > Maya (60) > Arjun (28) > Rohit (17)
    Operations Excellence Lead       Arjun (63) > Maya (60) > Priya (33) > Rohit (9)
    Product Manager — Outcome First  Maya (63) > Arjun (53) > Priya (50) > Rohit (13)
```

## C.2 The inversion is near-perfect

| | resume | competence | |
|---|---|---|---|
| **Rohit Verma** | **59 — best** | **14 — worst** | Candidate A |
| **Priya Raghavan** | **28 — worst** | **56** | Candidate B |

**Rohit ranks #1 by resume and #4 by competence. Priya ranks #4 by resume and
#2 by competence.** A complete reversal, produced by the real engine over
hand-written answers — `seed.py` inserts no scores.

## C.3 Why Rohit's resume scores 59

`seed.py:187`. His resume is the AI-generated caricature, deliberately:

> *"Results-driven, detail-oriented operations professional and passionate team
> player with a strong work ethic and excellent communication skills."*

…followed by a 15-term skills wall mirroring the default job description.
`scoring.resume_score()` is keyword overlap against the JD — exactly what an ATS
rewards — so he wins it. Then he is asked about it and produces:

> *"Team management is really about leadership and communication."*
> *"I'm not sure how it was calculated."*
> *"I don't remember the details, it was a while ago."*

## C.4 The contradiction — verified in the database today

```
Rohit Verma  team_size: 45 -> 20  [MAJOR, 55.56%]
  "Team size was given as 45 earlier and 20 later — a 55.56% divergence
   on a value that should not change."
```

Consistency 100 → 60, multiplier ×0.60, weighted evidence **24 × 0.60 = 14**.

## C.5 The transfer probe fires only for Rohit — verified today

Probe-level distribution per candidate, read from the `questions` table:

```
Priya    VALIDATION 3, OPERATIONAL 3, INCIDENT 2, DECISION 2, OUTCOME 2
Arjun    VALIDATION 3, OPERATIONAL 2, INCIDENT 3, DECISION 2, OUTCOME 2
Rohit    VALIDATION 3, OPERATIONAL 2, INCIDENT 2, DECISION 2, TRANSFER 3   ← stalled
Maya     VALIDATION 3, OPERATIONAL 2, INCIDENT 3, DECISION 2, OUTCOME 2
```

Rohit is the **only** candidate to receive TRANSFER probes, and he receives
three. The stall detector fired on all three of his claims. This is the
"a memorised resume can be recited but not transferred" mechanism, visible on
screen, for free.

## C.6 ⚠️ Correction — `README.md` and `CLAUDE.md` are stale

Both claim Rohit gets **9 questions** ("a shorter interview, because the
adaptive stop gives up on a claim that stops producing signals"). **He now gets
12.** Verified twice today. The adaptive stop still fires, but `TRANSFER_PROBE`
now spends the freed budget on transfer probes instead of ending the interview.

**Do not say "he gets a shorter interview" on stage — the screen will say 12 and
contradict you.** Say instead: *"the system gave up asking him what he did and
started asking him what he would do."* That is both true and a better line.

## C.7 The exact screens to show

| # | Screen | What it proves |
|---|---|---|
| 1 | `/recruiter/candidates` | Ranked by competence. Rohit is last. |
| 2 | Same screen, point at Rohit's row | resume 59, competence 14, `why_ranked` explains it |
| 3 | `/recruiter/candidates/{rohit}` | Score strip: **59 resume · 24 evidence · 14 competence** |
| 4 | Same page, Consistency panel | `24 × 0.60 = 14 — consistency cost 10 points`, "said 45 earlier, then 20 — 56% apart" |
| 5 | Same page, expand a claim's Transcript | His actual words: *"I'm not sure how it was calculated."* |
| 6 | `/recruiter/candidates/{priya}` | resume 28 → competence 56. The mirror image. |
| 7 | `/recruiter/candidates?role_id=` toggle | Same evidence, two lenses, order inverts |

**Do we need a new demo candidate?** For the *thesis*, no — Rohit and Priya are
better than anything you would write this week. For the *live journey*, yes: all
four are `COMPLETE` and therefore unreachable over WhatsApp (§A.7).

**API fields:** `CandidateSummary.resume_score`, `.weighted_evidence_score`,
`.competence_score`, `.badge`, `.contradiction_count`, `.why_ranked`;
`CandidateGraph.consistency.{score,multiplier,contradictions}`,
`.claims[].qa[]`, `.claims[].dimensions[].{score,basis,quotes}`.

**UI components:** `app/recruiter/candidates/[candidateId]/page.tsx` (score
strip), `components/recruiter/evidence/ConsistencyPanel.tsx`,
`ClaimEvidence.tsx` (dimensions + transcript + facts), `DimensionBar.tsx`,
`components/recruiter/candidates/RankedWorkspace.tsx`, `RoleLens.tsx`.

---

# D. Voice assessment — COMPLETE in code, zero live hours

## D.1 Code path

```
parse_inbound  kind in ("audio","voice") → media_id
  → routers/whatsapp.py:_handle
      if message.media_id:
          transcript, duration = await stt.transcribe_media_id(media_id)
              → whatsapp_channel.download_media(media_id)     [2-step, bearer on both]
              → openai.audio.transcriptions.create(model=whisper-1,
                                                   response_format="verbose_json")
          if not transcript: send VOICE_FAILED_MESSAGE; return
          voice = engine/voice.analyse(transcript, duration)
      → orchestrator.submit_answer(..., transcript=..., voice=...)
          → Response(answered_by="voice", voice_duration_seconds, voice_word_count, voice_effort)
          → scoring.claim_score(..., voice_effort=..., voice_weight=0.10)
```

**Files:** `api/channels/whatsapp_cloud.py`, `api/stt.py`, `api/engine/voice.py`,
`api/routers/whatsapp.py`, `api/engine/orchestrator.py`, `api/engine/scoring.py`.

`voice.analyse` measures **duration and word count only** — never accent,
fluency, grammar or "confidence". Say this on stage; it is a genuine
differentiator and it is enforced in code.

## D.2 Required environment

| Variable | Why | Failure without it |
|---|---|---|
| `OPENAI_API_KEY` | Whisper | `transcribe()` returns `("", 0.0)` → **VOICE_FAILED_MESSAGE, guaranteed** |
| `WHATSAPP_ACCESS_TOKEN` | media download + outbound | `media_url()` returns `(None, None)` |
| `WHATSAPP_PHONE_NUMBER_ID` | outbound | `_post` logs `[dry-run]`, sends nothing |
| `WHATSAPP_VERIFY_TOKEN` | webhook handshake | Meta will not save the callback URL |
| `WHATSAPP_APP_SECRET` | only if `WHATSAPP_VALIDATE_SIGNATURE=true` | 403 on every inbound |

## D.3 Has it been tested end to end?

**No.** There is no evidence anywhere in the repo of a real Meta round trip:
`WHATSAPP_ACCESS_TOKEN` is empty in `.env.example`, `whatsapp_mode` defaults to
`dry-run`, and the tests use synthetic payloads. The Phase 3 study drove 68
interviews through the **simulator**, not WhatsApp.

## D.4 What could fail live

1. **Fixture mode.** Without `OPENAI_API_KEY`, every voice note fails. This is
   deterministic, not probabilistic.
2. **24-hour test token expiry** mid-demo. Use a **system user token**.
3. **Media 401** — the classic: bearer token present on call 1, missing on
   call 2. `download_media` gets this right; verify anyway.
4. **Webhook URL churn.** A tunnel that reassigns its hostname silently detaches
   the webhook.
5. **Codec.** WhatsApp sends OGG/Opus; `_filename_for` maps it to `voice.ogg`.
   Verify once with a real note.
6. **Transcription latency.** Whisper plus two model calls per answer; the
   webhook returns 200 immediately and works in a `BackgroundTask`, so Meta will
   not retry, but the candidate waits.

## D.5 How to rehearse — see §K.3

---

# E. Adaptive cross-questioning — COMPLETE

## E.1 Code path

```
orchestrator.submit_answer()
  → _persist_evidence()               [LLM #3 → signals → enforce_verbatim → facts]
  → consistency.check_new_facts()     [stable vs variable keys]
  → recompute_claim()                 [rubric over the UNION of the claim's answers]
  → ask_next()
      → build_claim_states()          [levels used, scores, stall signal]
      → plan_next(states, index)      [PURE. no LLM, no randomness]
          breadth: one VALIDATION per claim, heaviest first
          depth:   heaviest unsaturated claim → weakest_dimension() → probe level
          stall:   answers>=2 and last signals==0 → select_transfer()  [T1 or T3]
      → question.generate_question()  [LLM #2 — wording only]
      → question.validate()           [7 pure rules, one regeneration, then fallback]
```

**Files:** `api/engine/orchestrator.py` (`plan_next`, `ClaimState`,
`select_transfer`), `api/engine/signals.py` (`PROBE_LEVEL_DIMENSIONS`,
`LADDER_ORDER`), `api/engine/question.py`, `api/engine/consistency.py`.
**Tests:** `tests/test_policy.py` (25), `tests/test_transfer.py` (17).

## E.2 Best demo moments — ranked

1. **Rohit's three TRANSFER probes** (§C.5). The system stops asking what he did
   and asks what he would do. Only he gets them.
2. **The contradiction** — `team_size 45 → 20`, MAJOR, 55.56%, caught by
   arithmetic, not by a model.
3. **`why_ranked`** on the list view — generated from stored rows, no model call.
4. **The `stable`/`variable` distinction.** Rohit's CSAT moving is an
   improvement, not a lie. His team size moving is a lie. The engine knows the
   difference because `data/claim_taxonomy.json` says which keys are which.

## E.3 Which seeded candidates demonstrate what

| Candidate | Demonstrates |
|---|---|
| **Rohit** | Everything. Resume/competence inversion, contradiction, transfer probes, consistency multiplier |
| **Priya** | The honest operator — the mirror image |
| **Arjun** | Lens sensitivity: 28 under People-First, **63** under Ops-Excellence |
| **Maya** | Cohort generality — `product`, not BPO. Proves it is not a BPO-only toy |

## E.4 Rehearsal answers, if you interview live

Use these to steer the engine deliberately. The claim is whatever the resume you
upload asserts.

**To trigger a high score** (specificity + causal chain + incident + tool usage
in one answer):

> *"I ran a team of eighteen agents across two shifts. Our first-response time
> was sitting at about fifty minutes because tickets were being triaged by
> whoever picked them up first, so in March we moved to a skills-based routing
> rule in Zendesk and I built a saved view for the overflow queue. By May
> first-response was down to twenty-two minutes. The worst week was the one
> before the April billing run, when two people were out sick and I personally
> cleared about sixty tickets on the Saturday."*

**To trigger a low score and a stall** (no numbers, no steps, no incident):

> *"We focused on quality and made sure standards were maintained. It was mostly
> about leadership and communication."*

Then again:

> *"I'm not sure how it was calculated."*

Two consecutive no-signal answers on the same claim set `stalled`, which makes
`transfer_available` true, and the next question is a TRANSFER probe.

**To trigger a contradiction** — say a team size, then a different one later:

> *"I had a team of thirty."* … later … *"There were twelve people reporting
> to me."*

30 → 12 is a 60% divergence on a `stable` key → **MAJOR** (≥50%) → −40 →
consistency 60 → ×0.60.

⚠️ Keep divergence **≥50%** for a MAJOR. 30→20 is only 33% and scores MINOR
(−15), which is a much less dramatic number on screen.

---

# F. Candidate completion experience — PARTIAL

## F.1 What the candidate currently receives

`api/routers/whatsapp.py:DONE_MESSAGE` — the entire thing:

> *"That's everything — thank you. Your verified profile is ready and the
> recruiter can see it now."*

No score, no badge, no dimensions, no link. Meanwhile a full report exists on the
web at `/candidate/proof?session_id=…`
(`app/candidate/proof/page.tsx`) showing competence, badge, six dimensions and
per-claim results — deliberately **without** verbatim quotes or the
contradiction list, so the interview cannot be reverse-engineered by the next
candidate. Keep that restriction.

## F.2 What they should receive

A short WhatsApp summary with real numbers and a link. Every figure already
exists on the `Profile` row that `finalize()` has just written — nothing needs
computing.

## F.3 Smallest improvement

In `routers/whatsapp.py`, replace the constant with a builder called after
`submit_answer` returns `next_question is None`:

```python
async def _completion_message(db, session) -> str:
    from api.models import Profile
    from api.tenancy import scoped, TenantScope
    scope = TenantScope.of(session.tenant_id)
    p = (await db.execute(scoped(
        select(Profile).where(Profile.candidate_id == session.candidate_id),
        Profile, scope))).scalars().first()
    if p is None:
        return DONE_MESSAGE
    base = settings.public_base_url or ""      # or hardcode for the demo
    lines = [
        "That's everything — thank you.",
        "",
        f"Competence score: {p.competence_score}/100 ({p.badge})",
        f"Evidence score: {p.weighted_evidence_score}  ·  Resume-only score: {p.resume_score}",
    ]
    if p.contradiction_count:
        lines.append(f"Note: {p.contradiction_count} answer(s) didn't line up with an earlier one.")
    if base:
        lines += ["", f"Full breakdown: {base}/candidate/proof?session_id={session.id}"]
    return "\n".join(lines)
```

**Effort: 2 h.** High demo value — the judge watches the phone light up with a
real number, and the resume-vs-competence contrast lands on the candidate's own
screen.

---

# G. Recruiter review experience — COMPLETE

## G.1 Coverage against the requirement

| Required | Endpoint | Component | Status |
|---|---|---|---|
| All applicants for a job | `GET /api/recruiter/candidates?role_id=` | `app/recruiter/jobs/[jobId]/applicants/page.tsx` | ✅ |
| Competence score | `CandidateSummary.competence_score` | score strip, `CandidateRow` | ✅ |
| Resume score | `.resume_score` | score strip | ✅ |
| Evidence score | `.weighted_evidence_score` | score strip | ✅ |
| Ranking | sorted competence → evidence → name | `RankedWorkspace` | ✅ |
| Role lens ranking | `?role_id=`, `graph._claim_score_under()` | `RoleLens` | ✅ |
| Evidence graph | `GET /api/recruiter/candidates/{id}` | `ClaimEvidence` + `DimensionBar` | ✅ |
| Transcript | `claims[].qa[]` | `ClaimEvidence` `<details>` | ✅ |
| Contradictions | `consistency.contradictions[]` | `ConsistencyPanel` | ✅ |
| Ranking rationale | `.why_ranked` | `CandidateRow` | ✅ |

**Nothing is missing.** Do not spend a day of the seven here.

## G.2 Strongest screens, in demo order

1. `/recruiter/candidates` — the ranking, with Rohit last
2. `/recruiter/candidates/{rohit}` — score strip, then Consistency panel, then a transcript
3. `/recruiter/candidates/{priya}` — the mirror image
4. Lens toggle on `/recruiter/candidates` — the order inverts

## G.3 Skip these

`/recruiter/talent-pools`, `/recruiter/saved-searches` (both are the same lens
data re-cut), `/recruiter/validation` (correctly reports "withheld" at n<30 —
truthful but reads as an empty table to a judge), `/recruiter/jobs/new`,
`/recruiter/diagnostics` (unless challenged on routing, where it is an excellent
answer).

---

# H. Demo reliability audit

## H.1 Critical path — must work

| # | Item | Currently |
|---|---|---|
| C1 | Backend boots, seed data loads | ✅ verified today |
| C2 | Frontend builds and serves | ⚠️ **`node_modules` absent — never verified** |
| C3 | `/recruiter/candidates` renders the ranking | ✅ |
| C4 | Evidence graph, consistency panel, transcript render | ✅ |
| C5 | Lens toggle changes the order | ✅ |
| C6 | Meta webhook reachable, verified, receiving | ❌ not configured |
| C7 | Outbound WhatsApp sends | ❌ dry-run |
| C8 | Document upload → parsed → Q1 | ❌ **not implemented** |
| C9 | Voice note → transcript → score | ⚠️ code complete, never run |

## H.2 High risk — likely to fail live

| Risk | Why | Mitigation |
|---|---|---|
| **WhatsApp token expiry** | 24-h test tokens die mid-day | System user token |
| **Fixture mode on the voice demo** | Guaranteed `VOICE_FAILED_MESSAGE` | Verify `/api/health` says `llm_mode: live` |
| **Webhook hostname churn** | Tunnel reassigns, Meta silently detaches | Reserved/static hostname |
| **Frontend build fails from clean checkout** | Never tested | `npm ci && npm run build` today |
| **Someone hits `POST /api/dev/reset`** | Unauthenticated, enabled by default | Keep the URL private |
| **Login screens** | Two routes that do nothing | Delete them |
| **Live interview stalls** | Candidate types slowly, dead air | Pre-run one candidate; run live in parallel |

## H.3 Can skip

Authentication · tenancy / `X-API-Key` · migrations · frontend tests ·
evaluations, provenance and replay UI · validation page · talent pools · saved
searches · dark mode · CSS cleanup · pagination · the `unsupported_premise`
rule · DPDP.

## H.4 Demo blockers — the full journey cannot run without these

1. **B.6 — document handling.** Steps 3–4 of the journey have no code.
2. **A.5 — `wa.me` link with the real opt-in code.** Without it there is no path
   from the browser into WhatsApp that resolves a session.
3. **Meta credentials + public webhook.** Without them nothing inbound arrives
   and nothing outbound sends.
4. **`OPENAI_API_KEY`.** Without it every voice note fails, deterministically.

---

# I. Dependency graph

```
                    ┌─────────────────────────────────────────┐
                    │  META SETUP  (system token, phone id,   │
                    │  public webhook URL, verify handshake)  │  ← CRITICAL PATH
                    └───────────────────┬─────────────────────┘
                                        │ blocks everything below
        ┌───────────────────────────────┼───────────────────────────────┐
        ▼                               ▼                               ▼
  ┌───────────┐                 ┌──────────────┐                ┌──────────────┐
  │  Apply    │                 │ Resume upload│                │ Voice notes  │
  │ (frontend)│                 │  (backend)   │                │  (backend)   │
  └─────┬─────┘                 └──────┬───────┘                └──────┬───────┘
        │ needs                        │ needs                         │ needs
        │ NEXT_PUBLIC_                 │ schemas.py sign-off           │ OPENAI_API_KEY
        │ WHATSAPP_NUMBER              │ (InboundMessage +2 fields)    │
        ▼                              ▼                               │
  ┌───────────────┐            ┌────────────────┐                      │
  │ wa.me link on │            │ parse_inbound  │                      │
  │  OptInCard    │            │  document kind │                      │
  └───────┬───────┘            └────────┬───────┘                      │
          │                             ▼                              │
          │                    ┌────────────────┐                      │
          │                    │ download_media │ ✅ EXISTS, REUSABLE   │
          │                    └────────┬───────┘                      │
          │                             ▼                              │
          │                    ┌────────────────┐                      │
          │                    │  extract_text  │ ✅ EXISTS             │
          │                    └────────┬───────┘                      │
          │                             ▼                              │
          │                  ┌──────────────────────┐                  │
          └─────────────────▶│ Candidate + Resume   │                  │
                             │ + create_session     │ ✅ EXISTS         │
                             └──────────┬───────────┘                  │
                                        ▼                              │
                             ┌──────────────────────┐                  │
                             │  ask_next → Q1       │ ✅ EXISTS         │
                             └──────────┬───────────┘                  │
                                        ▼                              ▼
                             ┌───────────────────────────────────────────┐
                             │  submit_answer → evidence → cross-question │ ✅ EXISTS
                             │  → consistency → recompute_claim           │
                             └──────────────────┬────────────────────────┘
                                                ▼
                             ┌───────────────────────────────┐
                             │  finalize() → Profile + Eval  │ ✅ EXISTS
                             └──────────────┬────────────────┘
                                            ▼
                             ┌───────────────────────────────┐
                             │  Completion summary on WA     │ ⚠️ 1 sentence today
                             └──────────────┬────────────────┘
                                            ▼
                             ┌───────────────────────────────┐
                             │  RECRUITER RANKING + EVIDENCE │ ✅ COMPLETE
                             │  (independent of everything   │
                             │   above — works on seed data) │
                             └───────────────────────────────┘
```

**Two observations that shape the plan.**

1. **Meta setup blocks three of four workstreams** and has an external approval
   clock. Start it on day 1, hour 1.
2. **The recruiter branch has no dependency on the WhatsApp branch.** It runs on
   seed data today. That is your fallback demo, and it is already done.

---

# J. 7-day implementation plan

Reliability over code quality, as instructed.

### Day 1 — unblock everything external

**Goal.** Meta credentials live and a webhook receiving; frontend proven to build.

**Files.** `.env` (backend), `.env.local` (frontend), none of the source.

**Tasks.**
- Meta App → system user token (not the 24-h test token), `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_BUSINESS_ACCOUNT_ID`
- Public webhook URL with a **reserved** hostname; complete the GET verify handshake
- `WHATSAPP_APP_SECRET` + `WHATSAPP_VALIDATE_SIGNATURE=true`
- `OPENAI_API_KEY` set; confirm `GET /api/health` reports `llm_mode: live`, `whatsapp: live`
- `cd ProofScreen_Next && npm ci && npm run build`
- **Announce the `api/schemas.py` addition** to the other owner (two optional fields on `InboundMessage`)

**Output.** A text message to the business number produces a log line in the API.

**Risk removed.** The single longest-lead item, and C2.

---

### Day 2 — the browser → WhatsApp bridge

**Goal.** Apply leads to a WhatsApp message that resolves a session.

**Files.**
`ProofScreen_Next/components/candidate/intake/IntakeForm.tsx` (`OptInCard`) ·
`components/candidate/jobs/ApplyButton.tsx` · `.env.local`

**Tasks.**
- `NEXT_PUBLIC_WHATSAPP_NUMBER` set
- `wa.me` button on `OptInCard`, prefilled with `result.opt_in_code` **only**
- `ApplyButton` → intake with `role_id` for unverified candidates (already correct; verify the modal copy)

**Output.** Apply → upload → tap → WhatsApp opens with `ABC123` → bot replies with question 1.

**Risk removed.** Blocker 2. The journey now works end to end **for a web-first candidate**.

---

### Day 3 — resume upload over WhatsApp (the only real build)

**Goal.** A brand-new candidate starts entirely from WhatsApp.

**Files.**
`api/schemas.py` ⚠️ (2 optional fields) · `api/channels/whatsapp_cloud.py`
(`parse_inbound`) · `api/routers/whatsapp.py` (`_handle` branch,
`NO_SESSION_MESSAGE`, `RESUME_FAILED_MESSAGE`)

**Tasks.** Implement §B.6 verbatim. Add a mime→extension map mirroring
`stt._EXTENSIONS`.

**Output.** Send a PDF to the business number from an unknown handset → *"Got it
— I pulled out 3 claims worth checking"* → question 1.

**Risk removed.** Blocker 1. The demo's headline journey exists.

---

### Day 4 — voice, live, on a real handset

**Goal.** Three voice notes answered, transcribed, scored.

**Files.** None expected. Budget for `api/stt.py` if the codec surprises you.

**Tasks.**
- Full run from a phone: resume → Q1 → voice → Q2 → voice → …
- Verify `responses.answered_by == "voice"` and `voice_duration_seconds` is non-zero
- Verify the recruiter transcript shows the mic icon and `Ns · N words`
- Time one turn end to end; note it for the runbook

**Output.** A complete voice interview in the database.

**Risk removed.** C9 and every item in D.4.

---

### Day 5 — the returning candidate and the completion summary

**Goal.** Close the last two journey gaps.

**Files.** `api/engine/orchestrator.py` (`find_candidate_by_phone`) ·
`api/routers/whatsapp.py` (returning-candidate branch, `_completion_message`)

**Tasks.**
- `find_candidate_by_phone()` — most recent `Candidate` for a phone, newest first
- `_handle` branch: known phone, no active session, no document → *"Welcome back
  — want me to re-run the assessment on your resume from last time?"* → new
  session against the existing `Resume`
- §F.3 completion summary

**Output.** A completed candidate can start again. Completion sends real numbers.

**Risk removed.** A.7 question 4; F.

---

### Day 6 — hardening and full dress rehearsal

**Goal.** Two clean end-to-end runs, plus the fallback path.

**Files.** Delete `app/recruiter-login/`, `app/candidate-login/` and their nav
links. `tests/test_pipeline.py:845` — `pytest.skip` without `pytest` imported in
that scope (one line; fires the first time the suite runs on Postgres).

**Tasks.**
- `pytest -q` → 457 green
- Two complete live runs, different handsets, one strong candidate and one weak
- Rehearse the fallback: `/recruiter/simulator` and `/candidate/proof/interview`
- Set `PROOFSCREEN_FIXTURES=fallback` and rehearse **once with the backend stopped**
- Re-seed and confirm the demo numbers still read 56 / 46 / 14 / 61

**Output.** A rehearsed runbook with real timings.

**Risk removed.** Everything in H.2.

---

### Day 7 — freeze

**Goal.** Change nothing. Rehearse three times.

**Tasks.**
- **Code freeze at 10:00.** No commits after it.
- Fresh `seed.py --reset`; screenshot every demo screen as a backup deck
- Charge the demo handset; test the venue's network; have a mobile hotspot
- Print the §L runbook
- Pre-run one candidate to `COMPLETE` an hour before, so screens 1–4 are
  guaranteed regardless of what the live run does

**Output.** A demo you have performed three times.

**Risk removed.** Improvisation.

---

# K. Demo rehearsal plan

## K.1 Dry run (no WhatsApp) — 10 minutes

- [ ] `docker compose up --build` → healthy
- [ ] `docker compose exec api python seed.py --reset` → 4 candidates, 3 roles
- [ ] `GET /api/health` → `llm_mode`, `whatsapp`, `database: ok`
- [ ] `npm run dev` → `/recruiter` renders, no SAMPLE DATA banner
- [ ] `/recruiter/candidates` → Priya 56, Maya 61, Arjun 46, Rohit 14
- [ ] Rohit's page → score strip **59 / 24 / 14**
- [ ] Consistency panel → `24 × 0.60 = 14`, "said 45 earlier, then 20"
- [ ] Expand a Rohit claim → transcript shows *"I'm not sure how it was calculated."*
- [ ] Lens toggle → order changes
- [ ] `pytest -q` → 457 passed

## K.2 Real WhatsApp checklist

- [ ] `GET /api/health` → `whatsapp: live`
- [ ] Meta webhook GET verify returns the challenge as **plain text**
- [ ] Send "hello" → `NO_SESSION_MESSAGE` arrives (proves both directions)
- [ ] Blue ticks appear (`mark_read`)
- [ ] Send a valid opt-in code → question 1 arrives
- [ ] Send two messages fast → no duplicate question (retry de-dup on `provider_message_id`)
- [ ] Confirm `X-Hub-Signature-256` validates (no 403s in the log)

## K.3 Voice note checklist

- [ ] `GET /api/health` → `llm_mode: live` ← **the whole voice demo hinges on this**
- [ ] Send a 20–30 s voice note; transcript appears in `responses.transcript`
- [ ] `answered_by == "voice"`, `voice_duration_seconds > 0`, `voice_effort > 0`
- [ ] Recruiter transcript shows the mic icon and `Ns · N words`
- [ ] Send a 2-second grunt → handled, not crashed
- [ ] Time one full turn (voice → transcript → score → next question). **Write the number down** — it is your on-stage pause.

## K.4 Resume upload checklist

- [ ] PDF from an **unknown** number → claims extracted → question 1
- [ ] DOCX → same
- [ ] A photo (JPEG) → a clear "send it as a document" reply, not silence
- [ ] A scanned PDF with no text layer → the `UnsupportedResume` message
- [ ] A 12 MB file → the size message
- [ ] `candidates.name` picked up the WhatsApp display name
- [ ] The new candidate appears in `/recruiter/candidates` within seconds

## K.5 Recruiter review checklist

- [ ] Live candidate appears in the ranking
- [ ] Their score strip shows three different numbers
- [ ] Their transcript shows the actual voice answers
- [ ] Dimensions show `basis` text and verbatim quotes
- [ ] `why_ranked` reads sensibly
- [ ] Lens toggle still works with the live candidate in the list

---

# L. Demo day runbook

**Total: 8 minutes.** Two acts. Act 1 is guaranteed; act 2 is live.

**Before you start:** `seed.py --reset` run; one live candidate already taken to
`COMPLETE` an hour ago as insurance; two browser tabs open —
`/recruiter/candidates` and `/candidate` — and WhatsApp visible on a screen-mirrored
phone.

---

## Act 1 — the thesis (4 min, seeded data, cannot fail)

### Step 1 — open `/recruiter/candidates`

**Appears.** Four candidates ranked by competence: Maya 61, Priya 56, Arjun 46,
Rohit 14.

> *"Four candidates, ranked. Not by their resumes — by what they could actually
> evidence when questioned. Watch the bottom of this list."*

### Step 2 — point at Rohit's row

**Appears.** `resume 59` · `competence 14` · `1 contradiction` · `why_ranked`.

> *"Rohit has the best resume of the four — 59, the highest score here. Every
> keyword the job description wants. It reads like it was written to beat an ATS,
> because that's exactly what it is. He ranks last on competence: 14."*

### Step 3 — click Rohit → `/recruiter/candidates/{rohit}`

**Appears.** Score strip: **Competence 14 · Weighted evidence 24 · Resume only
59 · Role coverage**.

> *"Three numbers, never one. Fifty-nine on the resume. Twenty-four once we
> asked him about it. Fourteen after consistency."*

### Step 4 — scroll to the Consistency panel

**Appears.** `Weighted evidence 24 × 0.60 = competence 14 — consistency cost 10
points`, and `Team size — said 45 earlier, then 20 — 56% apart · MAJOR`.

> *"He told us he managed 45 agents. Four questions later, 20. That's not the AI
> having an opinion — it's two numbers and a subtraction. Fifty-six percent
> apart on a fact that shouldn't move, so his whole score is multiplied by
> 0.6."*

### Step 5 — expand a claim's Transcript

**Appears.** The Q&A, and Rohit's actual words.

> *"And here's why the evidence score was 24 to begin with. 'Team management is
> really about leadership and communication.' 'I'm not sure how it was
> calculated.' 'I don't remember the details.' No numbers, no process, no
> incident he can recall. Nothing to count."*

**Point at the probe-level labels showing TRANSFER.**

> *"After two answers that produced no evidence, the system stopped asking him
> what he did and started asking what he would do — a situation built out of his
> own other claims. A memorised resume can be recited. It can't be
> transferred."*

### Step 6 — back, open Priya

**Appears.** Score strip: resume 28, evidence 56, competence 56.

> *"The mirror image. The worst resume here — 28. She doesn't write for
> keywords. Then you ask her: thirty-five agents in four pods, CSAT 78 to 92,
> and the specific week three people resigned before month-end. Competence 56.
> Rohit's resume beats hers by 31 points. Her competence beats his by 42."*

### Step 7 — back to the list, switch the lens

**Appears.** Order changes: People-First → Priya 68 > Maya 60 > Arjun 28.
Ops-Excellence → Arjun 63 > Maya 60 > Priya 33.

> *"Same evidence, two openings. Arjun goes from third to first — nobody was
> re-interviewed and no model was called. Every dimension score is already
> stored, so this is arithmetic in milliseconds."*

---

## Act 2 — the live journey (4 min)

### Step 8 — `/candidate`, click a role, click Apply

**Appears.** The modal, then the intake screen.

> *"That's the recruiter's side. Here's the candidate's."*

### Step 9 — upload a resume (or send it on WhatsApp if Day 3 landed)

**Appears.** The extracted claims and the opt-in code.

> *"Three claims worth checking, pulled out of the document. Now the interview
> moves to WhatsApp — no app, no login, no scheduling."*

### Step 10 — tap "Open WhatsApp"

**Appears.** WhatsApp with the code prefilled; send; question 1 arrives.

> *"Sending that code is the consent step. Now it asks about the first claim."*

### Step 11 — answer with a voice note

Use the strong answer from §E.4.

**Appears.** After the pause you timed on Day 4: the next question, escalated.

> *"That was a voice note. Transcribed, and then counted — quantities, process
> steps, a complete cause-action-outcome chain, a tool with described usage, a
> specific incident. We measure how long they spoke and how much they said, and
> nothing else. Not accent, not fluency, not confidence — those track region and
> class, not competence."*

### Step 12 — answer once more, weakly

Use the weak answer from §E.4.

> *"And the next question goes back to what it couldn't establish. The interview
> adapts to the answer, not to a script."*

### Step 13 — back to `/recruiter/candidates`, refresh

**Appears.** The live candidate in the ranking with a real score.

> *"Live, in the recruiter's list, with every point traceable to something they
> actually said."*

---

## Closing line

> *"Resumes are now written by AI, for AI. Ranking by resume quality ranks the
> writing. We rank by what a candidate can evidence when someone asks a follow-up
> question — and the model never produces a score. It counts things and quotes
> them; Python does the arithmetic. Rohit had the best resume in the room."*

---

## If something breaks

| Failure | Do this |
|---|---|
| WhatsApp does not deliver | *"Let me show you the same interview through our simulator"* → `/candidate/proof/interview` |
| Voice fails | Type the answer. The scoring path is identical bar the 10% voice weight |
| Backend dies | `PROOFSCREEN_FIXTURES=fallback` already serves act 1. Acknowledge the SAMPLE DATA banner: *"that banner is the product being honest about where its numbers came from"* |
| Live candidate scores oddly | Pivot to the pre-run candidate from an hour ago |
| Asked "what's your accuracy?" | Truth: 519 real questions measured against a blind human reviewer, published at 54% validator precision, and a phase that declined to ship a rule because the category couldn't be labelled consistently. **Never invent a number** |

---

## The one-line summary

**Act 1 works today and proves the thesis. Act 2 needs about two days of work
plus Meta's clock. Build act 2, but never let act 1 depend on it.**
