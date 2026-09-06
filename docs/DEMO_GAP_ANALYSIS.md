# Demo Gap Analysis — hackathon readiness

**Audited 2026-09-05.** `ProofScreen` @ `59b8b3b`, `ProofScreen_Next` @ `26bd15a`.
Scope is the demo flow only: apply → WhatsApp → assessment → report → recruiter
review. Nothing here is about production, scale or enterprise features.

Everything below was read out of the working tree. Where a claim is "does not
exist", it means grep found nothing and the code path is named.

---

## Verdict in one paragraph

**The assessment engine and the recruiter side are done. The WhatsApp candidate
journey is not.** Steps 1, 2, 6, 7 of your flow (discover, apply, cross-question,
complete) are built. Steps 3, 4, 5 (redirect to WhatsApp, resume-exists branch,
resume upload over WhatsApp) are either wired wrong or absent. If you demo
tomorrow, the candidate journey breaks at the first WhatsApp message — the bot
replies *"I couldn't find an active verification for this number."* Details in
§"What breaks tomorrow".

---

# Capability audit

## 1. Candidate discovers a job — **COMPLETE**

**Evidence**
- `app/candidate/page.tsx` — discover screen, lists openings with per-opening coverage
- `components/candidate/jobs/OpeningsBrowser.tsx`, `JobCard.tsx` — search + cards
- `app/candidate/jobs/[jobId]/page.tsx` — one opening, scored under its own `role_id`
- `lib/api/openings.ts` — the `JobRole` → "opening" mapping
- API: `GET /api/recruiter/roles`, `GET /api/recruiter/candidates/{id}?role_id=`
- Tables: `job_roles`

**Works.** Openings are role lenses. A verified candidate sees their own
`role_coverage` per opening, fetched per role because coverage is lens-specific.
Search and filtering work. Mobile shell with bottom nav.

**Missing.** Nothing for the demo.

**Effort.** 0.

---

## 2. Candidate clicks Apply → redirected to WhatsApp — **PARTIAL (wired wrong)**

**Evidence**
- `components/candidate/jobs/ApplyButton.tsx` — the Apply button
- `components/candidate/intake/IntakeForm.tsx` → `OptInCard` — where the code is shown
- `NEXT_PUBLIC_WHATSAPP_NUMBER` in `.env.example`

**What works.** A button exists, a modal explains the evidence flow, and a
`wa.me` URL is constructed.

**What is missing — three separate defects.**

1. **Apply does not go to WhatsApp.** `ApplyButton.startVerification()` calls
   `router.push('/candidate/start?role_id=…')` — the *web* upload form. The
   `wa.me` link is only rendered when `alreadyVerified === true`, i.e. for a
   candidate who already has a completed evidence graph. A new candidate — the
   demo case — never sees WhatsApp from this button.

2. **The prefilled message is not an opt-in code.** The link sends
   `"Hi ProofScreen, I'd like to be considered for {title}."`
   `_extract_code()` in `api/routers/whatsapp.py` requires **exactly 6
   characters** from the alphabet `ABCDEFGHJKLMNPQRSTUVWXYZ23456789`. That
   sentence is not a code, so it falls through to
   `find_active_session_by_phone()`, which excludes `COMPLETE` and `ABANDONED`
   sessions. Result: `NO_SESSION_MESSAGE`.

3. **`OptInCard` shows the code as plain text with no `wa.me` link.** The
   candidate is told to "Send the message `ABC123` to our WhatsApp business
   number" and must open WhatsApp and type it by hand. `grep -rn "wa.me"` across
   the frontend returns exactly one hit, in `ApplyButton.tsx`.

**Effort.** 2–3 h. Add a `wa.me` deep link to `OptInCard` prefilled with the
opt-in code, and make `ApplyButton` route unverified candidates into intake with
`role_id` (it already does) so they land on that card.

---

## 3. Resume exists → start assessment immediately — **NOT STARTED**

**Evidence**
- `api/engine/orchestrator.py:1268` — `find_active_session_by_phone()` is the
  only phone lookup in the codebase (`grep -rn "Candidate.phone" api/` → one hit)
- It filters `ChatSession.state.notin_([COMPLETE, ABANDONED])`

**What works.** Nothing. There is no "returning candidate" concept.

**What is missing.** No endpoint or function answers *"does a candidate with this
phone number already have a resume?"* A candidate who has finished one interview
and messages again gets `NO_SESSION_MESSAGE`, because their session is
`COMPLETE`. Note this also means **every seeded persona is unreachable over
WhatsApp** — `seed.py:393` creates them with `Channel.simulated` and
`seed.py:420` finalizes them, so all four are `COMPLETE`.

**Effort.** 3–4 h. A `find_candidate_by_phone()` in `orchestrator.py` plus a
branch in `whatsapp._handle` that opens a new session against the existing
`Resume` row when one is found.

---

## 4. Resume does not exist → request upload over WhatsApp → parse → assess — **NOT STARTED**

**This is the single largest gap.**

**Evidence**
- `api/channels/whatsapp_cloud.py`, `parse_inbound()` — handles `text`,
  `audio`/`voice`, `button`, `interactive`. Everything else hits
  `else: log.info("ignoring unsupported message type %r", kind); continue`
- `api/schemas.py:558` `InboundMessage` — fields are `text`, `media_id`,
  `external_id`, `profile_name`, `provider_message_id`. No document field, and
  `media_id` is consumed only by the audio path
- `api/stt.py:transcribe_media_id()` — the only `download_media` caller, and it
  pipes straight into Whisper
- `api/ingest/parse.py:extract_text()` — works, but is only reachable from
  `POST /api/candidates`

**What works.** Two of the three pieces exist independently: `download_media()`
does the two-step Meta fetch correctly (bearer token on both calls), and
`extract_text()` parses PDF/DOCX/TXT/MD. Nothing connects them.

**What is missing.** A WhatsApp `document` message is silently dropped. There is
no prompt asking for a resume, no branch that recognises one arriving, and no
path from a document `media_id` to `Candidate` + `Resume` + `create_session`.

**Effort.** 1 day. `parse_inbound` document branch → `InboundMessage.document_id`
+ `filename` → a `_handle` branch that downloads, calls `extract_text`, creates
the rows, and asks the first question. Touches `whatsapp_cloud.py`,
`schemas.py` (**frozen file — needs sign-off**), `routers/whatsapp.py`.

> **`api/schemas.py` is frozen and has two owners.** Adding `document_id` to
> `InboundMessage` is additive and low-risk, but it is a conversation, not a
> solo edit. Raise it before starting.

---

## 5. Assessment engine — **COMPLETE**

**Evidence**
- `api/engine/orchestrator.py` — `plan_next()` (pure policy), `ask_next()`,
  `submit_answer()`, `finalize()`
- `api/engine/question.py` — LLM #2 + seven-rule validator + one regeneration + fallback
- `api/engine/extract.py` — LLM #1, claims typed against the taxonomy
- `api/engine/signals.py`, `scoring.py`, `consistency.py` — the arithmetic
- Tables: `sessions`, `claims`, `questions`, `responses`, `evidence`,
  `claim_scores`, `session_facts`, `contradictions`
- 457 tests pass in 12.7 s

**Works.** Breadth-then-depth adaptive policy, 12-question budget with an early
stop, six published rubrics with gates, deterministic consistency, full
heuristic fallbacks so it runs with no API key.

**Missing.** Nothing for the demo.

**Effort.** 0. **Do not touch this.**

---

## 6. Voice note processing — **PARTIAL (needs live keys)**

**Evidence**
- `api/channels/whatsapp_cloud.py:parse_inbound` — `kind in ("audio", "voice")` → `media_id`
- `api/stt.py:transcribe_media_id()` → `download_media()` → Whisper `verbose_json`
- `api/engine/voice.py:analyse()` — duration + word count → effort score
- `api/routers/whatsapp.py:_handle` — transcribes, falls back to `VOICE_FAILED_MESSAGE`
- `responses.answered_by`, `voice_duration_seconds`, `voice_word_count`, `voice_effort`

**Works.** The whole chain is written and correct. Duration comes free from
Whisper's `verbose_json` rather than a native audio dependency. Voice contributes
a fixed 10% (`VOICE_WEIGHT`) of a claim's score, and only for voice-answered
claims.

**Missing.** `stt.transcribe()` returns `("", 0.0)` when `settings.llm_enabled`
is false. In fixture mode every voice note replies *"I couldn't make out that
voice note. Could you type your answer instead?"* **The voice demo requires a
live `OPENAI_API_KEY` and live WhatsApp credentials.** It has never been run
against a real handset.

**Effort.** 0 code. 2–3 h of rehearsal with real credentials and a real phone.

---

## 7. Cross-questioning — **COMPLETE**

**Evidence**
- `api/engine/orchestrator.py:plan_next()` — picks the claim's weakest un-probed dimension
- `ClaimState.weakest_dimension()`, `.stalled`, `.transfer_available`
- `api/engine/orchestrator.py:select_transfer()` — T1/T3 operators, pure, no job family
- `api/engine/signals.py:PROBE_LEVEL_DIMENSIONS`, `LADDER_ORDER`
- `api/engine/consistency.py:check_new_facts()` — contradiction detection
- `tests/test_policy.py` (25), `tests/test_transfer.py` (17)

**Works.** Five probe levels walked adaptively, driven by the answer just given.
A stalled claim earns one TRANSFER probe built from the candidate's own other
claim. Contradictions between answers are caught arithmetically and multiply the
whole score down. This is the most demo-worthy behaviour in the product and it
runs today.

**Missing.** Nothing.

**Effort.** 0.

---

## 8. Candidate report on WhatsApp — **PARTIAL**

**Evidence**
- `api/routers/whatsapp.py:DONE_MESSAGE` — the entire completion message:
  > *"That's everything — thank you. Your verified profile is ready and the recruiter can see it now."*
- `app/candidate/proof/page.tsx` — a full web report exists (competence, badge,
  six dimensions, per-claim results)

**Works.** The interview terminates cleanly and the candidate is told so. A rich
report exists **on the web**, reachable at
`/candidate/proof?session_id=…`.

**Missing.** No summary, score, badge or link is sent over WhatsApp. The
candidate finishes and gets one sentence. Note the web report deliberately
withholds verbatim quotes and the contradiction list — that restriction is
documented and correct, keep it.

**Effort.** 2–3 h. In `orchestrator.finalize()` or after it in `_handle`, read
the already-computed `Profile` / `Evaluation` and send a 4–6 line summary plus a
`/candidate/proof?session_id=` link. All the numbers already exist; nothing needs
computing.

---

## 9. Recruiter dashboard API — **COMPLETE**

**Evidence**

| Demo requirement | Endpoint | Status |
|---|---|---|
| All applicants for a job | `GET /api/recruiter/candidates?role_id=` | ✅ |
| Competence score | `CandidateSummary.competence_score` | ✅ |
| Resume score | `CandidateSummary.resume_score` | ✅ |
| Ranking | sorted by competence, then weighted evidence, then name | ✅ |
| Interview transcript | `CandidateGraph.claims[].qa[]` | ✅ |
| Evidence extracted | `claims[].dimensions[].quotes` + `claims[].facts` | ✅ |
| Reasoning / breakdown | `dimensions[].basis`, `consistency`, `why_ranked` | ✅ |

All seven required views are served. `api/routers/recruiter.py`, `api/engine/graph.py`.

**Missing.** Nothing for the demo.

**Effort.** 0.

---

## 10. Recruiter UI — **COMPLETE**

**Evidence**
- `app/recruiter/page.tsx` — counts, top of ranking, M4 headline, fixture/dry-run banner
- `app/recruiter/candidates/page.tsx` + `components/recruiter/candidates/RankedWorkspace.tsx` — ranked list, lens in URL
- `app/recruiter/candidates/[candidateId]/page.tsx` — the evidence graph
- `components/recruiter/evidence/ClaimEvidence.tsx` — per-claim dimensions, **transcript**, facts on record
- `components/recruiter/evidence/ConsistencyPanel.tsx`, `DimensionBar.tsx`, `OutcomePanel.tsx`
- `app/recruiter/jobs/[jobId]/applicants/page.tsx` — applicants for one opening

**Works.** Every one of the seven recruiter requirements is on screen. Three
scores side by side (resume / weighted evidence / competence). Six dimensions
with their basis text and verbatim quotes. Transcript in a `<details>` per claim,
with voice duration and word count when the answer was a voice note. Facts on
record. Consistency arithmetic shown. `why_ranked` on every row.

The **lens switcher** re-ranks the same evidence under a different opening's
weights, with the lens in the URL. This is the strongest twenty seconds available
and it works.

**Missing.** Nothing for the demo. (No UI exists for evaluations, provenance or
replay — not needed for the stated flow.)

**Effort.** 0.

---

## 11. Ranking candidates — **COMPLETE**

**Evidence**
- `api/engine/graph.py:rank_candidates()`, `_claim_score_under()` (late lens),
  `_why_ranked()`
- `api/engine/scoring.py:weighted_evidence_score()`, `competence_score()`, `badge_for()`
- Sorting deliberately not offered in the UI — the order *is* the ranking

**Works.** Passing a different `role_id` recomputes every claim score from stored
dimension scores under that role's weights. No model calls, milliseconds. The
seeded data demonstrates an actual order inversion between two lenses.

**Missing.** Nothing.

**Effort.** 0.

---

## 12. Authentication — **NOT STARTED (and fine for a demo)**

**Evidence**
- `app/recruiter-login/page.tsx`, `app/candidate-login/page.tsx` — 19 lines each,
  an `<input>` and a `<button>` wired to nothing
- `lib/api/actions.ts:requireWriteAccess()` — an env-var check with a
  `REPLACE ME` comment
- `api/config.py` — `REQUIRE_API_KEY` defaults to `false`
- The frontend never sends `X-API-Key`; everything runs as tenant `t_dev`

**Works.** Nothing. There is no authentication anywhere.

**Missing for the demo.** Only one thing: **the two login screens are a live
demo risk.** A judge who clicks "Continue" and watches nothing happen has found
your weakest point without trying.

**Effort.** 10 min to remove them from navigation, or 30 min to delete the routes.

Do **not** build auth this week. It is not on the demo path.

---

## 13. Demo data setup — **COMPLETE**

**Evidence**
- `seed.py` — 4 personas (Priya 56, Arjun 46, Rohit 14, Maya 61), 3 role lenses
- Runs the **real** engine over hand-written answers, so no number is hand-inserted
- `settings.openai_api_key = None` at the top — seeding is free, instant, offline
- `lib/api/fixtures.ts` (frontend) — typed sample data mirroring `seed.py`,
  including the lens ordering flip, shown behind an unmissable `SAMPLE DATA` banner

**Works.** `docker compose up` → `python seed.py` → data on screen. Rohit ranks
first by resume score and last by competence, and contradicts himself on team
size, so the consistency multiplier visibly drags 24 → 14. Under two lenses the
order inverts. The frontend renders all of it with the backend switched off.

**Missing.** One thing that matters: **all four seeded candidates are
`COMPLETE`**, so none of them can be resumed over WhatsApp. You need a fifth
candidate created live (or via intake) for the WhatsApp demo.

**Effort.** 0 for the recruiter demo. 15 min to prepare a live candidate.

---

# What would break the demo if you presented it tomorrow

Brutally, in order of how fast it kills you.

### 1. The WhatsApp journey dead-ends on the first message — **fatal**

Click Apply as a new candidate and you go to a **web upload form**, not WhatsApp.
If you instead hand someone the `wa.me` link, their message
(*"Hi ProofScreen, I'd like to be considered for…"*) is not a 6-character code,
so `_extract_code` returns `None`, `find_active_session_by_phone` finds nothing,
and the bot replies:

> *"Hi! I couldn't find an active verification for this number. Upload your resume on ProofScreen and send me the 6-character code you get back to begin."*

Your demo's step 3 ends there, in front of the audience.

### 2. Sending a resume on WhatsApp does nothing at all — **fatal to steps 4–5**

Not an error. Silence. `parse_inbound` logs `ignoring unsupported message type
'document'` and drops the message. The candidate sees no reply and assumes the
product is broken.

### 3. Voice notes have never been tested against a real handset — **high risk**

Every line of the chain exists and none of it has run against Meta. Missing
credentials, an expired 24-hour test token, an unapproved webhook URL, or a media
download 401 all present as the same thing on stage: *"I couldn't make out that
voice note."* And in fixture mode that message is **guaranteed**, not
probabilistic.

### 4. The completion message is one sentence — **embarrassing, not fatal**

You will say "and the candidate gets their report on WhatsApp" and the phone will
show a single line with no score in it.

### 5. `node_modules` is absent in `ProofScreen_Next` — **fatal if unlucky**

`npm run build` and `tsc` have never been verified in this environment. There are
zero frontend tests. You do not currently know that the dashboard compiles from a
clean checkout.

### 6. The two login screens — **credibility**

A judge clicks Continue. Nothing happens. Now every other screen is suspect.

### 7. `POST /api/dev/reset` is unauthenticated and enabled by default — **low probability, total loss**

`ENABLE_DEV_ENDPOINTS=true` and `REQUIRE_API_KEY=false` are the defaults. One
curl wipes every table mid-demo. Re-seeding takes seconds, but not in front of
people.

### What will NOT break

The engine, the scoring, the cross-questioning, the ranking, the lens flip, the
evidence drill-down and the recruiter dashboard. Those are done, tested and
reproducible. If you demo *only* the recruiter side against seeded data, you have
a strong showing today with zero code changes.

---

# 7-Day Hackathon Checklist

Only tasks required for the demo. Effort is one developer already in the code.

## Must do before demo

| # | Task | Files | Effort | Depends on |
|---|---|---|---|---|
| M1 | **Verify the frontend builds.** `npm ci && npm run build` in `ProofScreen_Next`. Nothing has ever confirmed this compiles | — | 30 min | none |
| M2 | **Go live on WhatsApp.** System-user token (not the 24-h test token), `WHATSAPP_PHONE_NUMBER_ID`, public webhook URL, verify handshake, `WHATSAPP_APP_SECRET` | `.env` | 3–4 h + Meta's clock | none |
| M3 | **`wa.me` deep link on the opt-in card**, prefilled with the actual opt-in code so the first inbound message resolves a session | `components/candidate/intake/IntakeForm.tsx` (`OptInCard`), `.env` (`NEXT_PUBLIC_WHATSAPP_NUMBER`) | 2 h | M1 |
| M4 | **Handle `document` messages** — `parse_inbound` branch, `InboundMessage.document_id` + `filename`, `_handle` branch that downloads → `extract_text` → creates `Candidate` + `Resume` → `create_session` → asks Q1 | `api/channels/whatsapp_cloud.py`, `api/schemas.py` ⚠️ frozen, `api/routers/whatsapp.py`, `api/stt.py` | 1 day | M2; **schemas.py sign-off first** |
| M5 | **Ask for a resume when the phone is unknown.** Replace `NO_SESSION_MESSAGE` with a prompt to send the resume as a document | `api/routers/whatsapp.py` | 1 h | M4 |
| M6 | **Returning-candidate lookup.** `find_candidate_by_phone()` + a `_handle` branch that opens a new session against the existing `Resume` | `api/engine/orchestrator.py`, `api/routers/whatsapp.py` | 3–4 h | M4 |
| M7 | **Rehearse the voice path end to end** on a real handset with a live `OPENAI_API_KEY`. Send three voice notes and read the transcripts back | — | 2–3 h | M2 |
| M8 | **Delete the two login screens** | `app/recruiter-login/`, `app/candidate-login/`, any nav links | 20 min | none |
| M9 | **Lock the demo instance.** Keep it private/IP-restricted, or set `ENABLE_DEV_ENDPOINTS=false` on the backend once the simulator is no longer needed | `.env` both apps | 30 min | after rehearsals |
| M10 | **Prepare a live demo candidate.** All four seeded personas are `COMPLETE` and unreachable over WhatsApp — create a fresh one on the day | — | 15 min | M3 |

**Must-do total: ~2.5 days of work + Meta's approval clock.**

**Dependency chain:** `M1 → M3` · `M2 → M4 → M5, M6` · `M2 → M7` · M8, M9, M10 independent.
**M2 is the critical path.** Start it first — the rest of the WhatsApp work is
untestable until a real message can arrive.

## Should do before demo

| # | Task | Files | Effort | Depends on |
|---|---|---|---|---|
| S1 | **Send a real completion summary** — competence, badge, dimensions probed, contradictions, plus a `/candidate/proof?session_id=` link. Every number already exists | `api/routers/whatsapp.py`, `api/engine/orchestrator.py:finalize()` | 2–3 h | M2 |
| S2 | **Apply button routes to intake with `role_id`** for unverified candidates, so the opt-in card is the landing point | `components/candidate/jobs/ApplyButton.tsx` | 1 h | M3 |
| S3 | **Set `PROOFSCREEN_FIXTURES=fallback`** on the demo machine and rehearse once with the backend stopped, so you have seen the SAMPLE DATA banner before an audience does | `.env.local` | 15 min | M1 |
| S4 | **Fix `tests/test_pipeline.py:845`** — `pytest.skip` without `pytest` in scope; becomes a `NameError` the first time the suite runs against Postgres | `tests/test_pipeline.py` | 5 min | none |
| S5 | **Write the fallback script.** If WhatsApp dies on stage, `/recruiter/simulator` and `/candidate/proof/interview` reproduce the interview exactly. Rehearse the switch, do not improvise it | — | 1 h | none |

## Nice to have

| # | Task | Effort |
|---|---|---|
| N1 | A provenance/replay screen — "here is the version stamp that produced this score, and a replay proving it reproduces from stored evidence with zero model calls". Endpoints already exist, no UI | half a day |
| N2 | Record 3–5 outcomes so the decision workflow and the M4 page have something to show (correlations stay withheld at n<30, which is correct) | 1 h |
| N3 | Loading skeletons on the two slowest routes | 2 h |

## Explicitly out of scope this week

Authentication · tenant API keys · database migrations · frontend tests · the
`unsupported_premise` validator rule · DPDP/consent · dark mode · CSS cleanup ·
pagination · observability · the evaluation/audit UI.

---

# The honest recommendation

You have two demos available.

**Demo A — recruiter-only, available today, zero risk.** Seeded data, the lens
flip, the resume/competence inversion, the evidence drill-down with verbatim
quotes, the consistency catch, the transcript. It works right now, offline,
reproducibly. It proves the hard part — that the score is arithmetic over counted,
quoted evidence rather than a model's opinion.

**Demo B — the full WhatsApp journey.** Needs M1–M10, roughly 2.5 days of work
plus Meta's approval clock, and it has never once run end to end against a real
handset.

Build toward B, but **have A rehearsed and ready as the spine of the
presentation**, with B as the live flourish. If you present B tomorrow without
M2–M6, it fails at the first message and takes A's credibility with it.
