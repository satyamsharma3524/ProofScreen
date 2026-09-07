# Demo Mode Validation — do the original issues still occur?

Validation only. Nothing in this document was implemented; every claim below
is backed by either a fresh code read or a real run captured this session.
Two real interviews were run end-to-end through `/api/dev/sessions` against
`resume_test/Yogendra.pdf` — the same resume and claim set the original
transcript (Firebase/Zoom SDK, "I don't know" candidate) exposed the problems
on — one with the same adversarial answer pattern as that transcript, one
with a strong, engaged candidate, specifically to see whether disabling
EXCLUSION/PERTURB costs a good-faith candidate anything. Raw logs:
`/tmp/issueA_claims.py`, session scratchpad's `issueD_strong_run.py`.

---

## Issue A — Weak Claim Selection

**Status: Partially Fixed — by code that already existed, not by Demo Mode.**

Ran `extract_claims()` fresh against `Yogendra.pdf` twice today. Both times,
the "Integrated third-party libraries such as Google Maps, Firebase, and Zoom
SDK" claim was **excluded** from the final 3, exactly as in the original
transcript.

**Correction to a prior assumption from this session:** the delegated
summary of `LIVE_INTERVIEW_QUALITY_AUDIT.md` described its P2 fix ("rank
claims by weight, not document order, before the one-per-type cap") as an
unimplemented proposal. It is not — `api/engine/extract.py:656-679` already
implements it, comment and all ("F4/P2 ... Weight, then a metric beating no
metric, then document position as the final tiebreak"). That audit doc was
evidently acted on after it was written. So the *coarse* version of Issue A
(weakest claim of a type always wins by appearing first) is fixed.

**What's still broken is narrower and precise.** Two claims tie for the
`tech_depth` slot — this Firebase/Zoom one, and "Write a test cases for
every pages by using Jest and Enzyme." Both are `tech_depth` (same weight,
15), and **neither carries a metric**, so the existing tiebreak chain
(`-weight, not metric, position`) collapses to its last resort — raw
document position — and Jest/Enzyme simply appears one bullet earlier in
the resume. The fix already shipped solved "worst beats best," not "two
equally-unweighted claims, pick the more specific one."

- **How often:** structural, not occasional — fires deterministically any
  time 2+ same-type claims both lack a metric. Reproduced 2/2 fresh runs on
  this resume.
- **Severe enough to hurt the demo:** Low-Medium. The 3 claims that *do*
  survive are still reasonable (confirmed in the Issue D run below — they
  produced claim scores of 68/49/23+ with 4-6 of 6 dimensions populated).
  This is a missed *better* moment ("who's worked with Firebase" is a
  punchier demo beat), not a broken interview.
- **Demo Mode mitigate it:** No, by design — Demo Mode never touches
  extraction or ranking (per this task's own constraint), and the fresh runs
  confirm the selection is identical with or without it.
- **Small patch available:** Yes. Add one more tiebreak criterion *before*
  falling to position: prefer the claim whose text names more distinct
  capitalized/proper-noun tokens (a cheap regex count over the claim text
  itself — "Google Maps, Firebase, and Zoom SDK" has three; "Jest and
  Enzyme" has two but is a thinner sentence overall). This is one more key
  in the existing sort tuple at `extract.py:668`, not a ranking redesign.
- **Estimated effort:** Small — a ~10-line helper plus one sort-key entry,
  30-60 minutes including a check against the weight assertions
  `tests/conftest.py` documents as load-bearing.

---

## Issue B — Early Abstraction

**Status: Still Broken — confirmed live, and the mechanism is more specific
than the original bad example.**

Ran the Issue D strong-candidate interview and read the turn-by-turn
`INTERVIEW SNAPSHOT` logs directly (not inferred). Turn 3:

```
claim=cl_cc7bfb (performance_work, "Optimized performance and reduced app load time.")
archetype=process, reason="opening move on a process claim", move=AUTHORITY
```

`PROCESS` archetype's ladder opens on `OPERATING_CONTEXT` (concrete: "what
was the first thing you checked"), not `AUTHORITY`. What actually happened:
claim 1 (`BUILD` archetype) had already spent `OPERATING_CONTEXT` in turn 1,
and `_rotate_session_fresh` — an *existing* mechanism that skips a move
already used elsewhere this session, specifically to stop two same-archetype
claims opening on identical wording — rotated claim 2 past its own intended
opener and landed on `AUTHORITY` instead. The actual sent question: *"On the
work where you optimized performance, what decisions could you make on your
own, and what needed approval from others?"* — asked before a single word
was established about what the optimization work even was. That is exactly
the bad-example pattern, just caused by cross-claim rotation rather than the
claim's own archetype.

Separately, by ladder design (not rotation), `VOLUME` archetype opens
*directly* on `AUTHORITY` with zero exceptions — the canonical worst case.
Measured across the 19 real claims extracted from 10 resumes earlier this
session: `VOLUME` is 11% of real claims (2/19) — including one genuinely
strong claim ("owning all architecture, prioritisation, and offer
mechanics decisions... scaled Pync to ₹40L+ monthly GMV") that should almost
certainly have been `OWNERSHIP` archetype and wasn't, because the archetype
regex matches `\bowned\b` but not `\bowning\b` — a verb-inflection gap, not
a judgment call.

**Does answer-threading already fix this?** Partially. In the same run,
turn 4 (the threaded follow-up after the AUTHORITY question) landed on
*"What happened with the release?"* — concrete, because the candidate's
answer happened to contain an entity ("release"). So threading recovers
concreteness *after* an abstract question, when the candidate engages. It
does nothing for the question that was already sent, and nothing at all if
the candidate doesn't name an entity in reply (the exact adversarial
pattern in Issue C).

**A Demo Mode interaction worth naming:** disabling EXCLUSION/PERTURB
shrinks the move pool every archetype's ladder draws from, which makes a
session-fresh rotation collision *more* likely to land on something further
down the ladder — including AUTHORITY. Reducing move variety to simplify
the demo has a small, real side effect of making this specific failure
slightly more likely, not less.

- **How often:** the rotation-collision case needs 2+ same-or-similar
  archetype claims in one session (common — `BUILD` and `PROCESS` are 48%
  of real claims combined) and is timing-dependent, so not every session
  hits it, but it reproduced on the very first strong-candidate run tried.
  The `VOLUME`-opens-on-`AUTHORITY` case is unconditional whenever the
  archetype fires (~11% of claims, likely undercounted given the "owning"
  regex gap).
- **Severe enough to hurt the demo:** Medium. It produced a real, sendable
  question that a stronger opener would have avoided, on a resume with no
  unusual phrasing. Not a crash, but a visibly awkward moment if that
  particular claim is the one a judge reads closely.
- **Demo Mode mitigate it:** No — makes the rotation variant marginally
  *more* likely, for the reason above.
- **Small patch available:** Two options, in order of how minimal they are:
  1. **Trivial:** re-order `VOLUME`'s ladder to open on `OPERATING_CONTEXT`
     instead of `AUTHORITY` (one tuple edit, `question.py:1153`). Kills the
     unconditional worst case outright.
  2. **Small:** also fix the archetype verb regex (`anatomy.py:301`) to
     match `own(?:ed|ing)`, `manag(?:ed|ing)`, `led|leading`, etc., so
     claims like the Pync example classify as `OWNERSHIP` (opens on
     `OWNERSHIP_BOUNDARY`, concrete) instead of falling through to `VOLUME`.
  3. **Optional, more involved, skip unless there's time:** bias
     `_rotate_session_fresh` to prefer a same-concreteness alternative
     over "whatever's next in ladder order" when a collision forces a
     rotation — this is the one that fixes the rotation case specifically,
     but touches the rotation helper itself rather than a single ladder
     entry.
- **Estimated effort:** #1 and #2 combined: ~20 minutes plus a test-suite
  run. #3: 30-45 minutes, and it's the only one that touches shared
  planner-selection logic rather than static data.

---

## Issue C — Thin Answers Consuming Budget

**Status: Partially Fixed.** Tested the four named examples directly against
both live mechanisms:

| Answer | `is_non_answer` (repair) | `detect_thread_entity` (threading) | Outcome |
|---|---|---|---|
| "I did independently." | **False** | **None** | **Falls through both — consumes its full turn, gets scored, nothing recovers it** |
| "Mostly me." | True | — | Repair fires correctly |
| "We used APIs." | False | `api` | Threading fires → "Which API was that?" |
| "Documentation." | False | `documentation` | Threading fires → "Which documentation did you check?" |

Three of the four named examples are already handled — two by the existing
repair mechanism, two by the new threading mechanism, both confirmed live.
The one gap, "I did independently.", is not new: it's the same limitation
CLAUDE.md already documents from the Phase 3 study (*"`is_non_answer()`
wants a canned phrase or <12 chars and no realistic candidate writes
either"*) — this session didn't introduce it and Demo Mode doesn't touch
`is_non_answer()` at all, so it's exactly as broken as before.

**Repair logic correctness** (asked explicitly): confirmed twice this
session — the demo-mode smoke test and a real transcript both show exactly
one repair per claim, no loops, non-answer accepted and the claim moved past
after the cap. Working as designed, including the newer per-claim (not
per-probe-level) version.

**Does threading recover useful evidence?** Yes, demonstrated live in the
Issue D run — an "API" mention led to a follow-up that pulled a real,
specific blocker out of the candidate ("blocked... waiting on the backend
team to expose a new pagination field"). But it's a one-shot recovery, not
a guarantee: under the demo's 2-question-per-claim cap, a threaded follow-up
is always that claim's *last* question, so a thin reply to the thread itself
ends that claim's evidence-gathering exactly as it would have without
threading.

- **Small patch proposed** (as invited, not a new subsystem): extend
  `is_non_answer()` with one more structural check, reusing the *same*
  keyword list threading already has — an answer with no thread-entity
  keyword AND under ~5 words counts as thin, alongside the existing <12-char
  and canned-phrase checks. No new phrase list, no new pipeline.
- **Risk to flag honestly:** this could false-positive on a genuinely
  informative one-word answer that happens to name an entity not on the
  fixed list (e.g., a bare tool name like "Genesys."). Needs a check against
  a few real answers before shipping, not just the four named examples.
- **Estimated effort:** Small — a few lines in `evidence.py`'s
  `is_non_answer()`, 15-20 minutes, plus deliberately checking it against a
  handful of real short-but-useful answers before trusting it.

---

## Issue D — Transfer/Perturb Removal Impact

**Status: Fixed / Not Needed — confirmed empirically, not just by config.**

Two full interviews run end-to-end, both against `Yogendra.pdf`:

- **Adversarial** (last session's transcript-style "I don't know" pattern,
  rerun fresh under Demo Mode): completed cleanly at exactly 6 questions,
  `badge=unverified`, honest low score. No PERTURB/TRANSFER fired
  (`transfer_questions=0`).
- **Strong, engaged candidate** (this session, real answers): completed
  cleanly at exactly 6 questions. Claim scores 68 / 49 / 23+, with 4-6 of 6
  dimensions populated **per claim, in just 2 questions each**. Genuinely
  rich evidence, achieved without ever reaching EXCLUSION or PERTURB.

**Completion rate: 100% in both runs.** **Evidence quality for an engaged
candidate: strong**, and produced with fewer questions than the old ladder
would have spent reaching the same claims. **Are advanced moves needed for
this demo:** evidence says no — both are structurally near-unreachable
under the 2-question cap on their own:

- `EXCLUSION` sits at ladder position 3 for `BUILD`/`PROCESS` (48% of real
  claims) — already unreachable under a 2-question cap with or without the
  explicit disable. It matters only for `METRIC_MOVE` claims (21% of real
  claims), where it's position 2 — there, disabling it is a real, small,
  probably-fine change (that slot becomes `FAILURE` instead).
- `PERTURB` is the one place this validation found something worth flagging
  precisely: its stall-triggered branch (`plan_next_forensic` step 4,
  `orchestrator.py:1850`) has **no awareness of the per-claim cap at all** —
  it checks `saturated`/`dear_stalled`/`moves_used`, never `demo_capped`.
  Traced through the code: if `transfer_probe` had been left at its old
  default, a claim already at its 2-question cap with `dear_stalled=True`
  could still receive a **3rd** question through this branch, silently
  breaking requirement #2's hard cap. Flipping `transfer_probe` off wasn't
  redundant with the cap — it was load-bearing for the cap actually holding.
  Good news: it does hold, confirmed in both runs (`answers` never exceeded
  2 for any claim in either transcript).
- Separately, the original (pre-Demo-Mode) transcript already showed PERTURB
  actively hurting a stalled claim by escalating to the hardest move exactly
  when the candidate had already produced nothing — so removing it isn't
  just neutral for the demo, it removes a documented failure mode.

- **Recommended action:** none — keep both disabled as shipped. Re-enabling
  either is not warranted for this scope; nothing measured shows a cost to
  a good-faith candidate, and the adversarial case is measurably safer
  without PERTURB.
- **Estimated effort:** N/A — validation only.

---

## Issue E — Recruiter Verdict Layer (design, not implemented)

Every input this needs already exists on `EvaluationOut`
(`api/schemas.py:675+`) and the `final scoring` log line already computed
each run this session: `competence_score`, `role_coverage`, a
`dimension_breakdown` (6 dimensions, 0-100 each), and a `claim_breakdown`
(per claim: score, `probed_dimensions`). A verdict layer is a pure function
over numbers that already exist — no new extraction, scoring, ranking, or
planner call.

**Proposed shape:**

```python
def recruiter_verdict(evaluation: EvaluationOut) -> Verdict:
    # thresholds below are placeholders for product sign-off, not a
    # measured calibration
    if evaluation.competence_score >= 65 and evaluation.role_coverage >= 70:
        label = "Strong Match"
    elif evaluation.competence_score <= 30 or evaluation.role_coverage <= 35:
        label = "Weak Match"
    else:
        label = "Moderate Match"
    reasons = _deterministic_reasons(evaluation)  # e.g. "Ownership on X was
        # never established (0 of 6 dimensions probed)"; "Weakest evidence:
        # Causal Reasoning across the interview" -- string-templated from
        # claim_breakdown / dimension_breakdown, nothing inferred
    return Verdict(label=label, reasons=reasons)
```

- Where it lives: a new small pure module (e.g. `api/engine/verdict.py`),
  computed at read time from an already-serialized `EvaluationOut` — not
  persisted, so it's free to iterate on and carries zero risk to stored
  evaluations. A persisted version later is a Phase-4-style optional
  field addition if wanted, not required for the demo.
- What it explicitly does NOT touch: extraction, scoring, ranking, or the
  planner — confirmed by construction, since its only input is data the
  scoring pipeline has already finished computing.
- Open question for the user, not an engineering one: the three threshold
  numbers above are placeholders. Worth a quick pass against a few real
  evaluations (the ones already run this session, or the Phase 3 corpus)
  before trusting them on stage.
- **Estimated effort:** Small — the function itself is ~40-60 lines; add a
  response field or a tiny new endpoint to expose it. Roughly half a day
  including picking real thresholds and hand-checking them against 3-4 real
  evaluations rather than shipping the placeholders blind.

---

## Summary table

| Issue | Status | Demo Mode mitigate? | Small patch? | Effort |
|---|---|---|---|---|
| A — weak claim selection | Partially Fixed (coarse case already fixed; a narrower tiebreak gap remains) | No — out of scope by design | Yes | Small (~30-60 min) |
| B — early abstraction | Still Broken (confirmed live) | No — slightly worsens it | Yes, two small ones | Small (~20-65 min) |
| C — thin answers | Partially Fixed (3 of 4 examples handled) | Threading helps; doesn't fully mitigate | Yes | Small (~15-20 min) |
| D — advanced move removal | Fixed / not needed | N/A (this *is* Demo Mode) | N/A | None — no action |
| E — recruiter verdict | New feature, design only | N/A | N/A | Small (~half day) |
