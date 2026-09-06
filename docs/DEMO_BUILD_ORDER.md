# Demo build order — G1–G8 verified against the code

Audited 2026-09-06 against `6c4b8a5`. `pytest -q` → **457 passed in 11.61s**.
`seed.py --reset` re-run today; §0 is that run's stdout.

Uses the **G1–G8 numbering from the current brief**, which differs from
`DEMO_EXECUTION_REVIEW.md` §3 (there, returning-candidate was G5 and there was
no G8). Do not merge the two lists.

Constraints honoured throughout: **`api/schemas.py` is not touched. No
refactors. No new modules, layers or abstractions.** Where a refactor would
have been cleaner, §4.3 says so and does the duplicative thing instead, with
the reason.

---

# 0. The thesis needs no code — verified today

```
  candidate           Q  resume  evidence  consist  competence  badge
  Priya Raghavan     12      28        56      100          56  partial
  Arjun Mehta        12      34        46      100          46  partial
  Rohit Verma        12      59        24       60          14  unverified  (1 contradiction)
  Maya Krishnan      12      50        61      100          61  partial

  Team Lead — People First         Priya (68) > Maya (60) > Arjun (28) > Rohit (17)
  Operations Excellence Lead       Arjun (63) > Maya (60) > Priya (33) > Rohit (9)
  Product Manager — Outcome First  Maya (63) > Arjun (53) > Priya (50) > Rohit (13)
```

Rohit is first on resume, **last on competence under all three lenses.** Priya
is the exact inversion. This is the centrepiece and it is already on disk.
Everything below is the *journey* to this screen. Nothing below is allowed to
put it at risk — see §12, fallback tier 3.

---

# 1. Updated gap analysis

| Gap | Status | Blockers found | Est. | Cuttable? |
|---|---|---|---|---|
| **G1** Apply → WhatsApp | **Confirmed. Not done.** | 1 | 20 min | No — the flow requires it |
| **G2** two opt-in sites | **Confirmed. Neither has a link.** | 2 | 45 min | No — it is fallback tier 2 |
| **G3** resume over WhatsApp | **Confirmed. Four blockers, not one.** | 4 (+1 test-env trap) | 4–5 h | No — the flow's core |
| **G4** `NO_SESSION_MESSAGE` | **Confirmed. Ordering-dependent.** | 1 | 5 min | No, but must not ship early |
| **G5** returning candidate | **Feature deferred (agreed).** Its one guard is **G8b**, §7.1 | 0 | — | **Yes — deferred** |
| **G6** completion summary | **Confirmed. Score free, link is not.** | 1 | 1 h | **Yes** |
| **G7** dead air | **Confirmed and understated.** | see §2.7 | 20 min | No |
| **G8** duplicate onboarding | **Confirmed real. Demo-fatal.** | 1 | 15 min | No — ship it first |
| **G8b** live-session guard | **Confirmed. Closes 3 of 4 duplicate routes** (§7.1) | 1 | 10 min | **No** |

**Total ≈ 7 h of code.** Code was never the constraint; §8 is.

---

# 2. Verification of every finding

## 2.1 G1 — ApplyButton routes to web intake · **CONFIRMED**

[ApplyButton.tsx:41-43](../ProofScreen_Next/components/candidate/jobs/ApplyButton.tsx#L41-L43):

```ts
const startVerification = () => {
  router.push(`/candidate/start?role_id=${encodeURIComponent(openingId)}`);
};
```

The `wa.me` URL is built at
[ApplyButton.tsx:35-40](../ProofScreen_Next/components/candidate/jobs/ApplyButton.tsx#L35-L40)
but is rendered **only under `alreadyVerified && whatsappUrl`**
([:88](../ProofScreen_Next/components/candidate/jobs/ApplyButton.tsx#L88)) —
the opposite of the demo candidate. An unverified candidate gets a web form
asking name, phone and a resume file.

The docstring at
[:8-20](../ProofScreen_Next/components/candidate/jobs/ApplyButton.tsx#L8-L20)
explains why: Apply routes into intake with `role_id` preselected so the graph
is scored under that opening's weights from the start. **That is good product
design and the wrong flow for this demo.**

**The consequence, stated plainly: flipping G1 deletes the web intake from the
demo path, which makes G3 fatal rather than optional.** There is then no other
way for a resume to enter the system on stage. Take that consciously, on
Day 5 — not by accident on Day 6.

## 2.2 G2 — two opt-in sites, **neither** has a link · **CONFIRMED**

| Site | What renders the code | Has `wa.me`? |
|---|---|---|
| `OptInCard` component, [IntakeForm.tsx:190-198](../ProofScreen_Next/components/candidate/intake/IntakeForm.tsx#L190-L198) | `<p className="optin-code">{result.opt_in_code}</p>` | **No** |
| Inline block (not the component), [proof/page.tsx:115-120](../ProofScreen_Next/app/candidate/proof/page.tsx#L115-L120) | `<p className="optin-code">{data.opt_in_code ?? "—"}</p>` | **No** |

The second is a **duplicated block, not a reuse of `OptInCard`**. Fix one and
the demo can still walk through the other. Both change, or neither.

Plumbing already exists: `NEXT_PUBLIC_WHATSAPP_NUMBER` is consumed at
[ApplyButton.tsx:35](../ProofScreen_Next/components/candidate/jobs/ApplyButton.tsx#L35)
and documented in `.env.example` — **but it ships unset.** Set it or both
fixes render nothing.

**One trap in the deep link.** `_extract_code`
([whatsapp.py:245-258](api/routers/whatsapp.py#L245-L258)) strips only the
prefixes `join `, `start `, `ps `, `code ` and then requires the remainder to
be **exactly 6 characters** from the alphabet `ABCDEFGHJKLMNPQRSTUVWXYZ23456789`.
Prefill the **bare code**. A friendly sentence around it fails the parse
silently, and the candidate gets `NO_SESSION_MESSAGE` instead of a question.

## 2.3 G3 — feasible without `schemas.py`. **Four blockers.** · **CONFIRMED**

### Feasibility verdict: yes, and the mime approach is the right one

`InboundMessage` ([schemas.py:558-571](api/schemas.py#L558-L571)) carries
`media_id` and **no mime, kind or filename**. The naive fix — add a field — is
an edit to the frozen tripwire (CLAUDE.md rule 2). The proposed path avoids it
entirely and is *also* more correct:

```python
audio, mime = await whatsapp_channel.download_media(media_id)   # already returns mime
```

[whatsapp_cloud.py:253-269](api/channels/whatsapp_cloud.py#L253-L269) already
returns `(bytes, mime)`, and `stt.transcribe(audio, mime)`
([stt.py:44](api/stt.py#L44)) already takes bytes. **Confirmed feasible with
zero schema change.** It also stays correct when a candidate sends a document
*mid-interview*, which a message-type branch would not.

### B1 — documents never reach the handler

[whatsapp_cloud.py:113-129](api/channels/whatsapp_cloud.py#L113-L129):

```python
if kind == "text":                ...
elif kind in ("audio", "voice"):  media_id = (message.get(kind) or {}).get("id")
elif kind == "button":            ...
elif kind == "interactive":       ...
else:
    log.info("ignoring unsupported message type %r", kind)
    continue                                  # <-- a PDF dies here
```

`parse_inbound` returns `[]` for a document-only webhook, so
`receive_webhook` ([:100](api/routers/whatsapp.py#L100)) adds no background
task and **`_handle` is never invoked.** No reply, no trace. This is the first
line to change.

### B2 — voice and document are indistinguishable downstream

[whatsapp.py:201-202](api/routers/whatsapp.py#L201-L202) branches on
`if message.media_id:` and nothing else, sending everything to
`transcribe_media_id`. Emitting `media_id` for documents without a mime branch
sends the PDF into Whisper. Resolved by the mime check above.

### B3 — `extract_text` keys on file **suffix**, not mime

[parse.py:70-76](api/ingest/parse.py#L70-L76):

```python
suffix = Path(filename or "").suffix.lower()
if suffix not in SUPPORTED:      # {".pdf", ".docx", ".txt", ".md"}
    raise UnsupportedResume(...)
```

Needs a four-entry mime→suffix map to synthesise a filename. **`parse.py` is
not edited** — the map lives in `whatsapp.py`.

### B4 — `_onboard()` raises under the webhook's only scope

[candidates.py:83](api/routers/candidates.py#L83):

```python
tenant_id=scope.require(),
```

The webhook's scope is `_INBOUND_SCOPE = TenantScope.system(...)`
([whatsapp.py:134-137](api/routers/whatsapp.py#L134-L137)), and `require()` on
a system scope **raises `TenantContextMissing`** by design
([tenancy.py:113-117](api/tenancy.py#L113-L117)).

So `_onboard(db, scope=_INBOUND_SCOPE, ...)` is a **guaranteed exception**,
caught at [whatsapp.py:106-117](api/routers/whatsapp.py#L106-L117) and shown to
the candidate as *"Something went wrong on our side."* On stage.

Fix: pass `TenantScope.of(DEVELOPMENT_TENANT_ID)`
([models.py:75](api/models.py#L75)). That is a **named** tenant, the same one
[tenancy.py:150-160](api/tenancy.py#L150-L160) already serves unkeyed requests
as — not an unfiltered read.

### B5 — the session must be advanced past `AWAITING_OPT_IN`

`create_session` sets `AWAITING_OPT_IN` for `Channel.whatsapp`
([orchestrator.py:789-793](api/engine/orchestrator.py#L789-L793)). Correct in
general, wrong here: the candidate has already messaged us, the 24-hour window
is open, and the resume is a stronger consent signal than a code. The document
branch must do what the opt-in branch already does at
[whatsapp.py:170-186](api/routers/whatsapp.py#L170-L186). See §4.3 for why
this is **duplicated, not extracted**.

### The test-environment trap — you cannot test G3 in dry-run

`media_url` returns `(None, None)` when `whatsapp_enabled` is false
([whatsapp_cloud.py:254-255](api/channels/whatsapp_cloud.py#L254-L255)), and
`download_media` then returns **`(None, "audio/ogg")`**
([:258](api/channels/whatsapp_cloud.py#L258)) — a *default audio mime* for a
document. A mime-first branch will classify it as a voice note, transcribe
nothing, and reply `VOICE_FAILED_MESSAGE`.

**Check `data is None` before you check the mime** (§4.2), and accept that G3
is only truly testable against a live token. Budget Day 3 accordingly.

## 2.4 G4 — correct fix, wrong if shipped early · **CONFIRMED**

[whatsapp.py:47-51](api/routers/whatsapp.py#L47-L51):

```python
NO_SESSION_MESSAGE = (
    "Hi! I couldn't find an active verification for this number. Upload your "
    "resume on ProofScreen and send me the 6-character code you get back to "
    "begin."
)
```

Sent from [whatsapp.py:193-195](api/routers/whatsapp.py#L193-L195).

The replacement is an **instruction the system cannot honour until G3 ships.**
Shipping G4 first is strictly worse than today: the candidate obeys, sends a
PDF, and gets total silence (B1). **Same commit as G3, or after it.**

## 2.5 G5 — returning candidate · **FEATURE DEFERRED. Guard renumbered to G8b.**

**The feature is deferred and stays deferred.** "Interviewed last month →
resume already exists → reuse profile" is not demo-critical. `Apply →
Interview → Done` is the whole journey. Nothing to build.

`find_active_session_by_phone` excludes `COMPLETE` and `ABANDONED`
([orchestrator.py:1272-1276](api/engine/orchestrator.py#L1272-L1276)), which
is why two of the three scenarios already work with no code:

| Scenario | Today's behaviour | Needed? |
|---|---|---|
| Phone finished an interview, sends a new resume | falls through to the document branch → **clean new interview** | **Nothing to build** |
| Phone has no history, sends a resume | document branch → new interview | **Nothing to build** |
| Phone has a **live** session, sends a resume | *(after G3)* would start a **second interview** | **10 min. Now G8b.** |

The third row was filed here and it does not belong here. It is not a
returning-candidate feature — it is **a duplicate-onboarding route that G3
creates**, and `_CLAIMED_DOCS` does not close it. See §7.1 for the four
duplicate routes and which guard closes each. Renumbered **G8b** so that
deferring G5 cannot silently drop it.

## 2.6 G6 — score is free; profile link is not · **CONFIRMED**

### Exact data available at `finalize()`

At [whatsapp.py:234](api/routers/whatsapp.py#L234), `next_question is None`
means `submit_answer` already called `finalize()`
([orchestrator.py:1104-1105](api/engine/orchestrator.py#L1104-L1105)), which
recomputes the profile **before returning**
([orchestrator.py:1213](api/engine/orchestrator.py#L1213)) and then finalizes
the evaluation. Everything is committed by the time you send the reply.

**Exact source:** one read of
[`graph.build_candidate_graph(db, candidate_id, scope=...)`](api/engine/graph.py#L265),
returning [`CandidateGraph`](api/schemas.py#L392-L422). Read-only — `graph.py`
is **not edited**, so no ownership question.

Fields available, verified:

| Field | Type | Use |
|---|---|---|
| `competence_score` | `int` 0–100 | the headline |
| `badge` | `Badge` — `verified` ≥70, `partial` ≥40, else `unverified` ([scoring.py:43-44](api/engine/scoring.py#L43-L44)) | the status word |
| `dimension_profile` | `list[DimensionScore]`, each with **`probed: bool`** ([schemas.py:265](api/schemas.py#L265)) | "N of 6 dimensions" |
| `claims` | `list[ClaimGraph]` | "across N claims" |
| `resume_score`, `weighted_evidence_score`, `role_coverage`, `consistency` | | available, **do not send** — see below |

**Use `d.probed`, not `d.score > 0`.** `candidate_dimension_profile` sets
`probed=probed_any` explicitly
([scoring.py:243-252](api/engine/scoring.py#L243-L252)); it is the field that
means what "covered" means. A score-based count will disagree with the
dashboard.

**Use the badge vocabulary that is already on the dashboard.** `Badge` is
exactly `verified` / `partial` / `unverified`
([schemas.py:95-98](api/schemas.py#L95-L98)), rendered by the dashboard as
"Verified" / "Partially verified" / "Unverified"
([format.ts:66-70](../ProofScreen_Next/lib/api/format.ts#L66-L70)). **There is
no "Strong".** Inventing a word here means the WhatsApp message and the
recruiter screen use different vocabulary for the same candidate, in the same
demo, ninety seconds apart.

**Do not put consistency in the summary.** `ConsistencyReport.score` is an
`int` 0–100 ([schemas.py:372](api/schemas.py#L372)) with no band — "High"
would be a new vocabulary you invent for one message. It is also the
recruiter's insight: Rohit's 60 versus Priya's 100 is *why* the inversion
happens, and it lands in §13 at 3:30, not on the candidate's phone.

**Do not send `resume_score` to the candidate.** The inversion is the
recruiter's insight and the demo's punchline; handing it to the candidate
mid-demo gives it away and, per
[proof/page.tsx:20-30](../ProofScreen_Next/app/candidate/proof/page.tsx#L20-L30),
the product deliberately withholds audit detail from candidates anyway.

### The profile link is an unbudgeted dependency — **skip it**

- The **backend has no public-app-URL setting.** `config.py` has none; a new
  `Settings` field would be required to build the link.
- The URL must be **reachable from a phone**, so the Next app needs its own
  tunnel or deploy, not just the API's.

**Ship G6 without the link.** A dead link in the last WhatsApp message of the
demo is worse than no link.

## 2.7 G7 — dead air, and it is worse than 10–40 s · **CONFIRMED**

### Exact call chain, with every long-running operation

```
document received                                          t=0
 └ download_media()          2 HTTP GETs to graph.facebook.com   1–3 s
 └ extract_text()            pure Python, PyMuPDF                <0.5 s
 └ _onboard()  candidates.py:52
     └ create_session()      orchestrator.py:740
         └ extract_claims()  extract.py:194  ── LLM #1 ──        8–20 s
            complete_json(max_retries=2, cache=True, fallback=…)
            → up to 2 HTTP round-trips
 └ ask_next()  orchestrator.py:803
     └ generate_question()   question.py:801  ── LLM #2 ──       3–8 s
        complete_json(max_retries=2, cache=FALSE)
        → up to 2 HTTP round-trips
     └ validate()            pure Python, 7 rules                <10 ms
     └ [25.5% of the time]   ── LLM #3, regeneration ──          3–8 s
        question.py:829      → up to 2 more round-trips
 └ send_text(first question)
```

**Verified facts that make this worse than reported:**

1. **`complete_json` retries internally.** `max_retries: int = 2`
   ([llm.py:206](api/llm.py#L206)), and the `except Exception` arm at
   [llm.py:259](api/llm.py#L259) catches **timeouts and 5xx**, not just schema
   errors. So each of the three logical calls is up to **2 HTTP round-trips**.
2. **Worst case is 6 round-trips**, each with `llm_timeout_seconds = 25.0`
   ([config.py:22](api/config.py#L22)) → a theoretical ceiling of **150 s**.
3. **The regeneration is not rare.** M7h live reject rate is **25.5%** over 519
   generated questions (`PHASE_3_VALIDATION_STUDY.md`). **One turn in four
   takes the long path.**
4. **`generate_question` passes `cache=False` deliberately**
   ([question.py:775-777](api/engine/question.py#L775-L777)) — "wording is
   non-deterministic on purpose". **The question step can never be warmed.**

### Is one acknowledgement enough? **No.**

One ack at the top leaves a second silent gap between claim extraction and the
first question — the longer, more variable one. **Two messages**, and the
second is the better demo beat because it says what the system *found*:

1. on receipt, before `extract_text`: *"Got your resume — reading it now."*
2. after `_onboard` returns, before `ask_next`: *"Found N claims worth
   verifying. First question coming up."*

`_onboard` returns `CandidateCreateOut` with `claims` populated
([candidates.py:143-158](api/routers/candidates.py#L143-L158)), so N is free.

**20 min, and it converts dead air into narration.**

### The one thing that *can* be pre-warmed — verified

`extract_claims` uses the **default `cache=True`**
([extract.py:194-201](api/engine/extract.py#L194-L201)), keyed on
`sha256(model|temperature|schema|prompt)` ([llm.py:226-228](api/llm.py#L226-L228)).
The cache is **process-local** ([llm.py:48](api/llm.py#L48)) and
**`POST /api/dev/reset` does not clear it** — `reset()` only calls `drop_all()`
([dev.py:428-434](api/routers/dev.py#L428-L434)), and `clear_cache()` has **no
callers anywhere in the repo**.

**Therefore:** uploading the *exact demo resume* at T-10, then `/api/dev/reset`
**without restarting the API process**, leaves LLM #1 warm for the real run.
That removes the 8–20 s step. It does **not** help LLM #2 (`cache=False`), and
a *different* resume warms nothing. §11 T-10 depends on this being done
precisely.

## 2.8 G8 — duplicate onboarding · **CONFIRMED REAL. Demo-fatal.**

De-duplication is `_already_processed`
([whatsapp.py:119-129](api/routers/whatsapp.py#L119-L129)) — a query against
the **`responses`** table on `provider_message_id`, called at
[:151](api/routers/whatsapp.py#L151).

A document upload creates **no `Response` row.** It creates `Candidate`,
`Resume`, `ChatSession` and up to 3 `Claim`s. **The guard is blind to it.**

Nothing at the DB layer saves you: `candidates.phone` is
`mapped_column(String(40), index=True)` — **indexed, not unique**
([models.py:161](api/models.py#L161)). `sessions` has no unique on
`candidate_id` either ([models.py:185-209](api/models.py#L185-L209)).

And the document path is the **slowest path in the product** — it blocks on
LLM #1 for up to 20 s (§2.7), which is exactly the latency that makes Meta
retry. CLAUDE.md, gotchas already paid for: *"**Meta retries webhooks.**"*

**Sequence of the failure:**

```
t=0    Meta POST #1, document  → 200 → BackgroundTask starts _onboard
t=0-20   _onboard blocked on extract_claims, nothing committed
t=~15  Meta POST #2, same message (retry) → 200 → BackgroundTask #2
         _already_processed → no responses row → False
         find_active_session_by_phone → still None (POST #1 uncommitted)
         → _onboard runs a SECOND time
t=~25  two candidates, two sessions, two first-questions in one chat
```

**Smallest safe fix — no schema change, ~10 lines in `whatsapp.py`:** an
in-process `set()` of `provider_message_id`s claimed by the document path,
checked and inserted **before** `_onboard` is awaited (§4.2). A single-process
demo, so a set is sufficient — and the comment should say that rather than
pretend otherwise. The §2.5 live-session guard closes the remaining window.

**15 minutes. It prevents the single most visible on-stage failure in this
build. Ship it first.**

---

# 3. Exact files affected

| File | Owner | Gaps | Diff size |
|---|---|---|---|
| `api/routers/whatsapp.py` | **A** | G3, G4, G5-guard, G6, G7, G8 | ~110 lines added |
| `api/channels/whatsapp_cloud.py` | **A** | G3-B1 | **+3 lines** |
| `ProofScreen_Next/components/candidate/jobs/ApplyButton.tsx` | **B** | G1 | ~3 lines |
| `ProofScreen_Next/components/candidate/intake/IntakeForm.tsx` | **B** | G2 | ~8 lines |
| `ProofScreen_Next/app/candidate/proof/page.tsx` | **B** | G2 | ~8 lines |

**Zero edits to:** `api/schemas.py` · `api/ingest/parse.py` · `api/routers/candidates.py` ·
`api/config.py` · `api/tenancy.py` · everything in `api/engine/`.

If a task starts to require one, the task is wrong — CLAUDE.md, *"`api/schemas.py`
is the tripwire."*

**The whole backend change is one file with one owner.** A and B never collide.
Keep it on a single branch off `main`.

---

# 4. Smallest implementation

Sketches, so the estimates are checkable.

## 4.1 G3-B1 — `parse_inbound`, three lines

`api/channels/whatsapp_cloud.py`, after the audio branch at
[:115](api/channels/whatsapp_cloud.py#L115):

```python
elif kind == "document":
    # G3: emit it. WHAT it is gets decided after download, from the mime
    # download_media() already returns. InboundMessage is frozen and carries
    # no type — and does not need to.
    media_id = (message.get("document") or {}).get("id")
```

## 4.2 G3 + G5-guard + G7 + G8 — the document branch

`api/routers/whatsapp.py`. Sits **before** the
`find_active_session_by_phone` call at [:193](api/routers/whatsapp.py#L193).

```python
_RESUME_SUFFIX = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "text/plain": ".txt",
    "text/markdown": ".md",
}

# G8. `_already_processed` queries `responses`, and a resume upload writes no
# Response row — so the existing guard cannot see this path. One process, one
# demo: a set is enough, and it is honest about being enough.
_CLAIMED_DOCS: set[str] = set()

PROCESSING_MESSAGE = "Thanks — reading your resume now. This takes a few moments."
UNSUPPORTED_FILE_MESSAGE = (
    "I can read PDF, Word, or plain text resumes. Could you send one of those?"
)


async def _try_resume_intake(db, phone, message) -> bool:
    """A media message that turns out not to be audio. True if handled here."""
    if not message.media_id:
        return False

    # G8 — claim it BEFORE the 20s _onboard, which is what triggers the retry.
    mid = message.provider_message_id or ""
    if mid and mid in _CLAIMED_DOCS:
        log.info("ignoring retried document delivery %s", mid)
        return True

    data, mime = await whatsapp_channel.download_media(message.media_id)

    # ORDER MATTERS. In dry-run, media_url() returns (None, None) and
    # download_media() defaults the mime to "audio/ogg" — so a nil body must be
    # checked before the mime, or every document looks like a voice note.
    if data is None:
        return False                                  # let the voice path report it

    kind = (mime or "").split(";")[0].strip().lower()
    if kind.startswith("audio/"):
        return False                                  # genuinely a voice note

    if mid:
        _CLAIMED_DOCS.add(mid)

    suffix = _RESUME_SUFFIX.get(kind)
    if not suffix:
        await whatsapp_channel.send_text(phone, UNSUPPORTED_FILE_MESSAGE)
        return True

    # G5 — never start a second interview over a live one. This is also the
    # second half of the G8 guard, once the first upload has committed.
    live = await orchestrator.find_active_session_by_phone(db, phone, _INBOUND_SCOPE)
    if live is not None:
        open_q = await orchestrator._open_question(db, live.id)
        await whatsapp_channel.send_text(
            phone,
            f"You already have an interview in progress — here's where we left "
            f"off:\n\n{open_q.text}" if open_q else ALREADY_DONE_MESSAGE,
        )
        return True

    await whatsapp_channel.send_text(phone, PROCESSING_MESSAGE)        # G7 ack #1

    try:
        resume_text = extract_text(f"resume{suffix}", data)
    except UnsupportedResume as exc:
        await whatsapp_channel.send_text(phone, f"I couldn't read that file — {exc}")
        return True

    result = await _onboard(
        db,
        # G3-B4. `_INBOUND_SCOPE` is a system scope and require() raises on it
        # by design. A WhatsApp-originated candidate belongs to the NAMED
        # development tenant. A second customer needs a number-to-tenant
        # resolver, and this line is where it goes.
        scope=TenantScope.of(DEVELOPMENT_TENANT_ID),
        name=message.profile_name or "WhatsApp candidate",
        phone=phone,
        resume_text=resume_text,
        filename=f"resume{suffix}",
    )
    await whatsapp_channel.send_text(                                  # G7 ack #2
        phone,
        f"Found {len(result.claims)} claims worth verifying. "
        f"First question coming up.",
    )

    session = await db.get(ChatSession, result.session_id)
    # --- start the interview. Deliberately duplicated; see §4.3. ---
    candidate = await db.get(Candidate, session.candidate_id)
    session.channel = Channel.whatsapp.value
    session.last_inbound_at = utcnow()
    if session.state == SessionState.AWAITING_OPT_IN.value:
        session.state = SessionState.CLAIMS_READY.value
    await db.commit()

    question = await orchestrator.ask_next(db, session)
    if question is None:
        await whatsapp_channel.send_text(phone, ALREADY_DONE_MESSAGE)
        return True
    await whatsapp_channel.send_text(phone, question.text)
    session.last_outbound_at = utcnow()
    await db.commit()
    return True
```

Called from `_handle`, replacing the bare media check at
[:201](api/routers/whatsapp.py#L201):

```python
if message.media_id and await _try_resume_intake(db, phone, message):
    return
# ...existing session lookup and voice path unchanged...
```

## 4.3 Why the interview start is **duplicated**, not extracted

The opt-in branch at [whatsapp.py:170-186](api/routers/whatsapp.py#L170-L186)
does the same eight lines. The clean move is to extract a
`_begin_interview(db, session, phone)` helper and call it from both.

**Do not do it.** Two reasons, both about this week specifically:

1. **The opt-in path is fallback tier 2** (§12). It works today, and G2 is
   built on it. Refactoring it means the fallback and the primary path share a
   failure mode — exactly the coupling you do not want six days before a demo.
2. The brief says no refactors, and eight duplicated lines in one file is a
   smaller risk than a change to working code on the critical path.

Extract it after the hackathon. Leave a one-line comment saying so.

## 4.4 G4 — copy only

```python
NO_SESSION_MESSAGE = (
    "Hi! I don't have a verification running for this number yet. "
    "Send me your resume as a PDF or Word document and I'll get started."
)
```

## 4.5 G6 — replace one line

At [whatsapp.py:234](api/routers/whatsapp.py#L234):

```python
reply = next_question.text if next_question else await _completion_summary(db, session)
```

```python
async def _completion_summary(db, session) -> str:
    """The last message of the demo. Never allowed to raise."""
    from api.engine import graph as graph_engine
    try:
        g = await graph_engine.build_candidate_graph(
            db, session.candidate_id, scope=TenantScope.of(session.tenant_id)
        )
        if g is None:
            return DONE_MESSAGE
        probed = sum(1 for d in g.dimension_profile if d.probed)
        return (
            "That's everything — thank you.\n\n"
            f"*Competence score: {g.competence_score}/100*\n"
            f"Status: {g.badge.value}\n"
            f"Evidence covered {probed} of 6 dimensions across "
            f"{len(g.claims)} claims.\n\n"
            "Your verified profile is ready and the recruiter can see it now."
        )
    except Exception:            # CLAUDE.md rule 5 — always a fallback
        log.exception("completion summary failed; sending the plain message")
        return DONE_MESSAGE
```

The `try` is not padding. This is the **last** message of the demo; a
traceback there loses the ending.

## 4.6 G1 / G2 — the frontend

**G1**, [ApplyButton.tsx:41](../ProofScreen_Next/components/candidate/jobs/ApplyButton.tsx#L41):

```ts
const startVerification = () => {
  if (whatsappUrl) { window.open(whatsappUrl, "_blank", "noopener"); return; }
  router.push(`/candidate/start?role_id=${encodeURIComponent(openingId)}`);
};
```

**Keep the `router.push` fallback.** It is what makes G1 reversible on demo
morning by unsetting one env var.

**G2**, both sites (§2.2): an `<a>` beside the code, prefilling the **bare
code** only.

```tsx
{process.env.NEXT_PUBLIC_WHATSAPP_NUMBER && (
  <a className="primary-button"
     href={`https://wa.me/${process.env.NEXT_PUBLIC_WHATSAPP_NUMBER.replace(/[^0-9]/g, "")}?text=${encodeURIComponent(code)}`}
     target="_blank" rel="noopener noreferrer">
    Send it on WhatsApp
  </a>
)}
```

---

# 5. What can be skipped

**Skip entirely:** the returning-candidate feature — history, profile reuse,
re-verification (§2.5; its live-session guard is **G8b**, which ships with G8) · the G6 profile link (§2.6) ·
authentication · `REQUIRE_API_KEY=true` · multi-tenancy beyond the named
`t_dev` intake · observability · DPDP/compliance · audit UI · replay UI ·
rate limiting.

**Cuttable if a day slips, in this order:**

1. **G6** — purely additive. The one-sentence `DONE_MESSAGE` still ends the
   interview cleanly.
2. **G1** — un-flipped, Apply routes to a *working* web intake. The demo gains
   a click and loses no capability.
3. Nothing else. **G8, G8b, G3, G4 and G7 are one indivisible unit.** G3
   without G8/G8b duplicates candidates, without G7 shows 40 s of silence, and
   without G4 the entry point is unreachable. G2 is not in the unit — it is
   the insurance against the unit slipping (§7.2).

---

# 6. Dependency graph

```
              ┌─────────────────────────────────────────────┐
              │ EXTERNAL — Day 1. Blocks everything live.    │
              │  Meta app + number approved                  │
              │  Static tunnel; webhook GET handshake green  │
              │  OPENAI_API_KEY funded, WA token live        │
              │  NEXT_PUBLIC_WHATSAPP_NUMBER set             │
              └───────────────┬─────────────────────────────┘
                              │
        ┌─────────────────────┼──────────────────────┬──────────────────┐
        ▼                     ▼                      ▼                  ▼
   ┌─────────┐         ┌──────────────┐      ┌──────────────┐   ┌─────────────┐
   │ G8      │         │ G2 wa.me +   │      │ §0 seeded    │   │ npm ci /    │
   │ dedupe  │         │ code (both   │      │ demo — 0 h   │   │ build       │
   │ 15 min  │         │ sites) 45 min│      │ ALREADY DONE │   └─────────────┘
   └────┬────┘         └──────┬───────┘      └──────┬───────┘
        │ MUST precede        │                     │
        │ live G3 testing     │ fallback tier 2     │ fallback tier 3
        ▼                     │                     │
   ┌───────────────────────────────────┐            │
   │ G3  document upload    4–5 h      │            │
   │  B1 parse_inbound  +3 lines       │            │
   │  B2 mime branch after download    │            │
   │  B3 mime→suffix map               │            │
   │  B4 TenantScope.of(t_dev)         │            │
   │  B5 start interview (duplicated)  │            │
   └──┬─────────┬──────────┬───────┬───┘            │
      │         │          │       │                │
      ▼         ▼          ▼       ▼                │
  ┌───────┐ ┌───────┐ ┌────────┐ ┌──────────┐       │
  │  G4   │ │  G7   │ │ G8b    │ │   G1     │◄──────┘  sequenced after G3
  │ 5 min │ │ 20 min│ │ guard  │ │ 20 min   │          by JUDGEMENT (§2.1),
  └───────┘ └───────┘ │ 10 min │ └────┬─────┘          not by code
  copy is    call      └────────┘      │
  FALSE      sites      failure         ▼
  before G3  must exist  G3 creates  ┌──────────────────┐
                                     │ G6 summary  1 h  │
                                     │ additive, CUTTABLE│
                                     └────────┬─────────┘
                                              │ SKIPPED
                                              ▼
                                     ┌──────────────────┐
                                     │ profile link —   │
                                     │ needs a config   │
                                     │ field + a public │
                                     │ Next deploy      │
                                     └──────────────────┘
```

**Critical path: Day 1 external → G8 → G3 → G1 → rehearsal.** Everything else
is off it.

---

# 7. Commit sequence — SHIPPED 2026-09-06

```
Commit 1  G2              9e044d9 (frontend)  wa.me deep link, both screens
Commit 2  G3 + G8 + G8b   d400749 (backend)   resume upload + both guards
Commit 3  G4              bdd7e7f (backend)   unknown-phone copy
Commit 4  G7              daedcab (backend)   two acknowledgements
Commit 5  G1              9b6320e (frontend)  Apply -> WhatsApp
Commit 6  G6              a68fdf3 (backend)   completion summary

DEFERRED: G5 returning-candidate feature (history, profile reuse).
```

**Backend 465 tests passing** (457 at the start; +8). **Frontend builds clean**,
24 routes, lint clean. **`seed.py --reset` still reproduces §0 exactly** —
Rohit 59/14, Priya 28/56, Rohit last under all three lenses.

`api/schemas.py`, `api/ingest/parse.py`, `api/routers/candidates.py`,
`api/config.py`, `api/tenancy.py` and everything in `api/engine/` are untouched,
as planned.

## 7.0 What is verified, and what is not

| Verified how | What |
|---|---|
| **Live, end to end** | opt-in deep link → webhook → `AWAITING_OPT_IN` → `ASKING` with a generated question; Apply prefill from an unknown number → the G4 copy asking for a resume |
| **Test suite, `download_media` stubbed** | document → candidate → session → first question; retried delivery onboards once; second upload over a live session re-sends the open question; image refused; audio still transcribed; both acks fire; completion summary matches the dashboard |
| **Direct** | a generated PDF through the mime→suffix mapping |
| **NOT verified — needs Meta** | a real `document` webhook from a real handset, and the real two-step media download |

That last row is the whole residual risk, and it is why Day 1 is Meta (§7.3).
`download_media` is the seam everything was tested through precisely because it
is the one thing a token is required for.

## 7.1 G8 is folded into G3, not shipped standalone — DECIDED

An earlier revision put G8 in its own commit ahead of G3. **That was wrong and
is reversed.**

Documents die at
[whatsapp_cloud.py:128](api/channels/whatsapp_cloud.py#L128) and `_handle` is
never invoked, so **the duplicate-delivery bug is not reachable until G3-B1
lands.** A standalone G8 commit ships dormant code that protects nothing, and
dormant code cannot be tested against the failure it exists to prevent.

So the document path is built as one coherent unit:

```
document arrives
  → _claim_once()              G8   claim BEFORE the 20 s _onboard
  → _resume_open_question()    G8b  never a second interview over a live one
  → download_media()           existing
  → mime detection             G3-B2  (check `data is None` FIRST — §2.3)
  → extract_text()             G3-B3  mime→suffix
  → _onboard(t_dev scope)      G3-B4
  → start the interview        G3-B5  duplicated, not extracted (§4.3)
```

Helper implementations are unchanged from the previous revision; only the
commit boundary moved. `_claim_once` and `_resume_open_question` land in the
same commit as the branch that calls them.

## 7.2 G2 is Commit 1 — the insurance, and it is off the critical path

G2 is frontend-only, a different owner's files, and touches nothing G3
touches. Shipping it first means that if G3 slips on its build day — the most
likely single slip in this plan, and per §2.3 only truly testable against a
live Meta token — you still have a **complete working demo**: web intake → tap
a button → WhatsApp opens with the code prefilled → interview → dashboard.

That is fallback tier 2 (§12), and it is the only thing that guarantees the
week cannot produce nothing.

## 7.3 Day 1 is Meta, not code — CONFIRMED

**The code is no longer the critical path. Meta is.** Every remaining task
depends on: real message → real webhook → real media download. Nothing in
Commits 2–6 can be verified without a live token (§2.3, the dry-run trap).

**Frontend build gate: CLOSED 2026-09-06.** `node_modules` was **absent** —
failure F9 was real, not hypothetical. `npm ci` → 366 packages, 0
vulnerabilities. `npm run build` → clean, 24 routes. Both files G2 touches
(`/candidate/start`, `/candidate/proof`) build.

# 8. Seven-day schedule

Every day ends green: `pytest -q` at **457**, and a working demo of *something*.

### Day 1 — external unblock. **No feature code.**

The only day that can silently cost the week.

- Meta: app live, number verified, permanent token, webhook URL saved, GET
  handshake echoing (`verify_webhook`, [whatsapp.py:60](api/routers/whatsapp.py#L60))
- **Static** tunnel domain — a rotating URL is failure F2
- `OPENAI_API_KEY` funded; `GET /api/dev/llm` reports `"mode": "live"`
- `npm ci` in `ProofScreen_Next`; `npm run build` clean
- Set `NEXT_PUBLIC_WHATSAPP_NUMBER`
- **Gate: a text from your handset reaches `_handle` and gets a reply.** Not
  true by end of day → escalate; do not start Day 2.

### Day 2 — G8 + G2

- G8 (§4.2's `_CLAIMED_DOCS`) — before anything is tested live
- G2 on **both** surfaces (§2.2), bare code only
- Manual: web intake → code → tap the button → first question arrives
- **Gate: the fallback demo path works end to end.**

### Day 3 — G3 + G4 + G8b. The one real build day.

- B1 → B5 in order. Test the **voice path first** after B1/B2 land — that is
  the regression that matters
- G4 copy and the G8b live-session guard in the same commit
- Manual, on a real handset: PDF · DOCX · a `.jpg` (expect
  `UNSUPPORTED_FILE_MESSAGE`) · a voice note **mid-interview** · the **same
  PDF twice, fast** (expect exactly one candidate) · a PDF **during** a live
  interview (expect the open question re-sent)
- **Gate: PDF → first question, on a real handset.** `pytest -q` = 457.

### Day 4 — G7 + live voice

- G7 two acks (§2.7)
- First real voice rehearsal: five voice answers end to end. **Write the turn
  latencies down** — they set your stage pacing
- Reserve the afternoon for whatever the handset reveals; this is the day
  surprises land
- **Gate: a full voice interview with no silence longer than an ack.**

### Day 5 — G1 + G6

- G1, keeping the intake fallback (§4.6)
- G6 without the profile link (§2.6). Use `d.probed`
- Full journey twice: Apply → WhatsApp → PDF → voice interview → summary →
  recruiter dashboard
- **Gate: the brief's flow, start to finish, twice.**

### Day 6 — harden + dress rehearsal

- **No new features.** Bug fixes and copy only
- §9 checklist, every line
- Two dress rehearsals: one clean, one where you break something deliberately
  and recover live
- Read §13 aloud, timed
- **Gate: two clean run-throughs and one recovered failure.**

### Day 7 — freeze

- Code freeze 09:00. Config only after that
- `/api/dev/reset` → `seed.py --reset` → verify §0 reproduces
- Print §11. Charge everything
- **Rehearse fallback tier 3** — presenting §0 alone, no live WhatsApp. If you
  cannot do that confidently, you are not ready.

---

# 9. Demo rehearsal checklist

Every line is pass/fail. No line is "probably fine".

### Environment
- [ ] `git log --oneline -1` matches the frozen commit
- [ ] `pytest -q` → **457 passed**
- [ ] `GET /health` → 200, `llm_mode: live`, `whatsapp_mode: live`
- [ ] `GET /api/dev/provenance` → a real `code_version`, not `unknown`
- [ ] `ENABLE_DEV_ENDPOINTS=true`, and the URL is **not public** —
      [`/api/dev/reset`](api/routers/dev.py#L428) is unauthenticated
- [ ] `NEXT_PUBLIC_WHATSAPP_NUMBER` set; `npm run build` clean
- [ ] Tunnel on the **static** domain; Meta shows that exact URL

### WhatsApp
- [ ] Webhook GET handshake re-verified **today**
- [ ] "hi" from the handset → the **G4** copy arrives
- [ ] **24-hour window open** — a message sent from the demo handset within
      the last 24 h (failure F4)
- [ ] Blue ticks appear (`mark_read` works ⇒ token is good)

### Document path
- [ ] PDF → ack #1 within 2 s → ack #2 with a claim count → first question
- [ ] DOCX → same
- [ ] Image → `UNSUPPORTED_FILE_MESSAGE`, no crash
- [ ] **Same PDF twice, fast → exactly one candidate** (G8)
- [ ] PDF **during** a live interview → open question re-sent, no second
      interview (**G8b**)

### Voice
- [ ] Voice note mid-interview transcribes (the B2 regression)
- [ ] Deliberately inaudible note → `VOICE_FAILED_MESSAGE`; typed answer works
- [ ] Turn latencies measured and written on the runbook

### Completion
- [ ] Summary carries score, badge, dimensions, claim count
- [ ] The number in WhatsApp **equals** the number on the dashboard
- [ ] `resume_score` is **not** in the candidate's message
- [ ] Candidate appears in the recruiter list within 5 s

### Recruiter
- [ ] `seed.py --reset` reproduces §0 exactly
- [ ] Rohit 59 / 14, contradiction visible
- [ ] Priya 28 / 56
- [ ] Role-lens switch re-ranks live across all three
- [ ] Evidence graph shows verbatim quotes

### Failure rehearsal
- [ ] Kill the tunnel mid-interview → recover, resume
- [ ] Unset `OPENAI_API_KEY` → fixture heuristics, **no traceback anywhere**
- [ ] Airplane-mode the handset mid-answer → reconnect, answer lands **once**

---

# 10. Failure matrix

| # | Failure | P | Impact | Detection | Response |
|---|---|---|---|---|---|
| F1 | Meta app/number not approved | med | **total** | Day 1 gate | Nothing else matters until a message round-trips. Escalate Day 1. |
| F2 | Tunnel URL rotated, webhook silently unregistered | high | total | §11 step 4 | Static domain; re-verify handshake as step 1 of the runbook |
| F3 | Venue wifi blocks the tunnel | med | total | §11 step 4 | **Phone hotspot as primary.** Rehearse on it |
| F4 | 24-hour window closed | **high** | fatal to live | no outbound arrives | §11 step 5 — most-forgotten item on this list |
| F5 | LLM latency spike, >40 s silence | med | severe | ack #2 late | G7 acks + narrate (§11). Warm cache (§2.7) |
| F6 | Whisper mis-transcribes on a noisy floor | med | moderate | wrong transcript in the reply | Hold the phone close; **type** the answer as tier-2 |
| F7 | **Meta retry duplicates the candidate** | **high** | severe | two questions arrive | **G8. Ship it Day 2.** |
| F8 | Rehearsal left a live session on the handset | high | severe | "already in progress" | **G8b** + `/reset` at T-30 |
| F9 | `node_modules` absent in the Next app | ~~med~~ | fatal | `npm run build` | **CLOSED 2026-09-06** — was absent; `npm ci` + build now green |
| F10 | Document arrives with an unmapped mime | low | moderate | `UNSUPPORTED_FILE_MESSAGE` | Rehearse with the **exact** demo file |
| F11 | Dry-run mode misreads a document as audio | med (dev only) | dev friction | `VOICE_FAILED_MESSAGE` locally | Known (§2.3). `data is None` check first; test live |
| F12 | `_begin_interview` duplication drifts from the opt-in path | low | moderate | tier-2 fallback breaks | Both paths walked in the Day 6 rehearsal |
| F13 | G1 flipped, G3 broken → no way in | low | **total** | Day 5 gate | Unset `NEXT_PUBLIC_WHATSAPP_NUMBER` → intake fallback (§4.6) |
| F14 | Completion summary raises on the last message | low | severe | no final message | `try/except → DONE_MESSAGE` (§4.5) |
| F15 | `t_dev` hardcode surfaces in a customer conversation | low | credibility | — | It is a **named** tenant. Do not claim multi-tenant intake |

---

# 11. Demo day runbook

### T-60 — before leaving

1. `docker compose up --build` (or the local uvicorn loop)
2. `POST /api/dev/reset` → `python seed.py --reset`
3. Verify §0's table on screen
4. Tunnel up; **re-verify the Meta webhook handshake** (F2)
5. **Send one message from the demo handset to the business number.** This
   opens the 24-hour window (F4). *The most-forgotten step on this page.*
6. Tabs open: recruiter ranked list · Rohit's graph · Priya's graph ·
   role-lens selector
7. Phone: WhatsApp open, chat cleared, **hotspot on**, mirroring live,
   brightness max, do-not-disturb on

### T-10 — warm the cache correctly

8. Upload **the exact resume you will demo** and let it produce a question.
9. `POST /api/dev/reset` → `python seed.py --reset`. **Do not restart the API
   process** — the LLM cache is process-local and `/reset` does not clear it
   ([llm.py:48](api/llm.py#L48), [dev.py:428](api/routers/dev.py#L428)), so
   claim extraction replays from cache.
   *Warms LLM #1 only. Question generation is `cache=False` by design
   ([question.py:775](api/engine/question.py#L775)) and stays live.*
10. `GET /health` → green. Deck on the §0 slide.

### During — narration over dead air

The acks give you the cue. While a model call runs:

> *"It's reading the resume now and pulling out the claims it thinks are
> checkable. That's the only place a model touches a number — from here on,
> scoring is arithmetic in Python."*

### After

11. Leave the dashboard on Rohit-vs-Priya, role lens visible
12. **Do not reset.** Questions come after the demo and the data answers them

---

# 12. Fallback strategy

| Tier | Trigger | Move | Prep cost |
|---|---|---|---|
| **1 — live** | everything works | Apply → WhatsApp → PDF → 2 voice answers → summary → dashboard | the whole build |
| **2 — WhatsApp degraded** | document path fails, or latency is unbearable | *"Let me show you one already in flight."* → the seeded Rohit/Priya comparison. **Do not debug on stage.** | G2, 45 min |
| **3 — no connectivity** | tunnel or venue network dead | Straight to §0 on the dashboard. It runs locally. The thesis needs no network. | **zero — done** |

**The rule: one retry, then drop a tier.** A second retry spends the room's
attention on your infrastructure instead of your idea.

Tier 3 is why §0 is the first section of this document. **The demo cannot
fail, only get shorter.**

---

# 13. Presenter script

Six minutes. Bracketed lines are actions.

### 0:00 — The problem (30 s)

> "Every resume you read this year was written with AI help. The strong
> candidates and the weak ones now produce the same document. Resume screening
> stopped working, and nobody has told the recruiters yet."

### 0:30 — The claim (30 s)

> "So we stopped treating the resume as evidence. We treat it as a list of
> **claims** — and then we verify them, one at a time, in a conversation on
> WhatsApp, in the candidate's own words."

### 1:00 — The journey *(live)*

*[browse openings, click Apply]*

> "The candidate finds a job and applies. No portal, no login, no 40-field
> form."

*[WhatsApp opens on the mirrored phone]*

> "It hands off to WhatsApp — where they already are."

*[send the resume PDF]*

> "They send their resume. That is the entire application."

*[ack #1 lands, then ack #2 with the claim count]*

> "It's reading it now. Three claims it thinks are checkable — and here's the
> first question, generated against the first one."

### 2:00 — The interview *(live: two answers, one by voice)*

*[reply with a voice note]*

> "They answer by voice, because typing on a phone is a barrier that has
> nothing to do with competence. It transcribes, extracts what it can
> **count** from the answer, and picks the next question from what's still
> missing."

*[second answer — ideally one that triggers a follow-up]*

> "Notice it didn't move on. That claim is under-evidenced, so it probed
> deeper instead of changing the subject. That's the difference between a
> questionnaire and an interview."

### 3:00 — The result *(live)*

*[completion summary lands]*

> "The candidate gets a real score with evidence behind it — not a rejection
> email six weeks later."

### 3:30 — The proof *(seeded data — this is the moment)*

*[switch to the recruiter dashboard]*

> "But here's what we actually built this to show."

*[open Rohit]*

> "Rohit. Resume score **59** — the best-written resume in the pile.
> Competence score **14**."

*[open his evidence graph]*

> "Not a judgement call. When we asked what he actually did, he contradicted
> himself — and every quote behind that number is verbatim from his own
> answers. Nothing paraphrased. Nothing invented."

*[open Priya]*

> "Priya. Resume **28**. Competence **56**. She writes a bad resume and does
> the job."

> "Same four candidates. Ranked one way by the document, the exact opposite
> way by the evidence."

### 5:00 — The lens

*[switch role profiles across all three]*

> "And competence isn't one number. Same evidence, three different openings —
> the ranking changes, because a Team Lead role and an Ops Excellence role
> weight different things. Rohit is last in all three."

### 5:30 — Close

> "The model never produces a score. It returns countable signals and quotes
> them; Python turns counts into numbers. That's why we can show you every
> quote behind every point — and it's why this survives the next generation of
> resume-writing AI."
