# P2-04 — Repair turn

Seven-section spec. Owner **A**, task 4 of 5. **Depends: P2-03** (uses the
`is_repair` column landed there).

**Migration impact: none** — P2-03's reset already added the column.

---

## 1. Task

When an inbound answer is a non-answer, ask once more instead of scoring it and
moving on — and **do not charge the interview budget** for that turn.

## 2. Current State

Measured:

- `evidence.is_non_answer(text)` already exists at `evidence.py:66`. Pure, no
  LLM: rejects anything under 12 canonical characters or matching `_NON_ANSWERS`.
  **Reuse it. Do not write a second one.**
- Today a non-answer flows straight through `submit_answer()` → a `Response`
  row → `_persist_evidence()` → signals ≈ 0, and `ask_next()` moves to the next
  probe. **The budgeted question is spent on "ok".**
- `session.questions_asked` is the budget counter, incremented at
  `orchestrator.py:749`, read by `plan_next(states, session.questions_asked)`
  (:721) and the `< settings.max_questions` gate (:966).
- **`order_index` currently means two things.** It is set to
  `order_index=session.questions_asked` (:745), so it is simultaneously
  *position in the transcript* and *budget consumed*. A turn that does not
  consume budget splits those meanings apart — this is the core design problem
  of the task.
- `ClaimState.stalled` is *`answers >= 2` and `last_answer_signals == 0`*, and
  `stalled` is what makes a claim `transfer_available`. A repair answer is an
  extra answer on the same claim, so naively counting it **pulls transfer probes
  forward**.
- `build_claim_states()` reads levels from the `questions` table, so a repair row
  sharing its parent's `probe_level` adds no new level — good, no planner change
  needed.

## 3. Files To Change

| File | Change |
|---|---|
| `api/engine/orchestrator.py` | repair branch in `submit_answer()`; `order_index` derivation; exclude repairs from the `answers` count |
| `api/engine/question.py` | `REPAIR_PROMPTS: dict[ProbeLevel, str]` |
| `api/config.py` | `repair_turn: bool = True` |
| `.env.example` | document the flag |
| `tests/test_policy.py` | budget, stall and cap tests |

Not `models.py` — the column exists. Not `schemas.py`.

## 4. Implementation Steps

1. **The repair question makes no model call.** A fixed, cohort-neutral template
   per probe level in `question.py`, naming what is missing:
   *"I need a bit more to go on — what specifically did you do, and what were the
   numbers?"* Rationale: there is nothing to word creatively, a model call costs
   latency against the +20% guardrail, and the candidate has just demonstrated
   low engagement. Deterministic is also cheaper to explain on stage.

2. **Budget: do not increment `questions_asked`.** That is the whole point of
   the task.

3. **Split the two meanings of `order_index`.** Derive it from a count of the
   session's existing question rows rather than from `questions_asked`:
   `order_index = <count of questions in session>`. Transcript order stays
   dense and unique; `questions_asked` stays the budget. `ix_questions_session_order`
   is non-unique so no constraint is at risk, and `_qa_rows()` / `_open_question()`
   keep ordering correctly.

4. **Exclude repairs from the stall signal.** `build_claim_states()` must not
   count a repair answer in `answers` or let it set `last_answer_signals`.
   Otherwise a candidate who says "ok" twice stalls a claim that was never
   properly probed, and TRANSFER fires early — R5 in the phase plan.

5. **One repair per parent question, hard.** If the repair answer is *also* a
   non-answer, accept it, score it as-is and move on. Without this cap a
   disengaged candidate loops forever inside one probe and the interview never
   terminates — the same class of bug as unbounded regeneration.

6. **The repair response is still stored and still scored.** It is a real answer
   from the candidate; suppressing it would lose evidence. Only the *budget* and
   the *stall count* are affected.

7. **`REPAIR_TURN=false` reproduces Phase 1 exactly**, the `TRANSFER_PROBE`
   precedent.

8. **De-duplication still applies.** A Meta retry of the non-answer must not
   produce two repair questions — the existing `provider_message_id` check in
   `whatsapp.py` covers it; assert it rather than assume it.

## 5. Tests

| Test | Asserts |
|---|---|
| `test_non_answer_issues_a_repair_question` | a repair row exists with `is_repair=True`, same claim and probe level |
| `test_repair_does_not_consume_budget` | `questions_asked` unchanged across the repair turn |
| `test_repair_makes_no_model_call` | `/api/dev/llm` count unchanged |
| `test_only_one_repair_per_question` | a second non-answer is accepted and scored, no second repair |
| `test_repair_answers_do_not_count_toward_stall` | claim with 2 repair answers is not `stalled`, so not `transfer_available` |
| `test_transfer_invariant_unchanged` | seed still yields **3** transfer probes, all Rohit, all `signals_found = 0` |
| `test_order_index_stays_dense_and_unique` | with repairs present, transcript order has no gaps or duplicates |
| `test_repair_flag_off_reproduces_phase_one` | `REPAIR_TURN=false`: competence 56/46/14/61 |
| `test_repair_response_is_still_scored` | the repair's answer produces evidence rows |
| `test_webhook_retry_does_not_double_repair` | replayed `provider_message_id` yields one repair |

## 6. Verification Commands

```bash
OPENAI_API_KEY="" DATABASE_URL="sqlite+aiosqlite:///:memory:" pytest -q tests/test_policy.py
OPENAI_API_KEY="" DATABASE_URL="sqlite+aiosqlite:///:memory:" pytest -q

python seed.py --reset      # expect 56 / 46 / 14 / 61 and 3 transfer probes
REPAIR_TURN=false python seed.py --reset   # identical

# the invariant, re-measured not assumed
python - <<'EOF'
# count TRANSFER questions and their signals_found across the seeded run
EOF

# end to end through the real webhook: answer "ok", expect a repair, not the next probe
```

## As built — 2026-09-05

| | Result |
|---|---|
| Tests | 290 → **298** |
| Budget | a repair leaves `questions_asked` **unchanged** |
| Model calls per repair | **0** |
| Transfer invariant | **3 probes, all Rohit, all `signals_found = 0`** — re-measured |
| Seed competence | 56 / 46 / 14 / 61 · three lens orderings unchanged |
| Suite under every flag | 298 green — default, `REPAIR_TURN=false`, `QUESTION_VALIDATION=false`, `TRANSFER_PROBE=false`, `ADAPTIVE_PROBING=false` |

**Measured on the evasive persona: 9 budgeted questions against the strong
persona's 12, across 14 turns versus 12.** That is the mechanism stated in one
line — fewer questions spent, more chances given.

**Two existing tests broke, and both were proxies rather than invariants.**
Neither was bent to pass:

- `test_evasive_candidate_gets_a_shorter_interview` asserted
  `len(weak_turns) < len(strong_turns)`. The invariant was always about
  **budget** — *"no point asking a twelfth question of someone who has said
  nothing for three"* — and turn count was a proxy that stopped being one. It
  now asserts both halves: fewer budgeted questions (9 < 12) **and** more turns
  (14 > 12), so if repairs ever stop firing the second assertion catches it.
- `test_a_stalled_claim_produces_a_transfer_question_about_another_claim`
  asserted one TRANSFER turn per claim. A repair sits at the same probe level as
  the question it repairs, so a transfer probe that drew a non-answer now shows
  two TRANSFER *turns*. That is one probe asked twice, not two probes —
  `levels_used` still records TRANSFER once, so `transfer_used` still spends the
  exemption exactly once. Repairs are excluded from the count rather than the
  invariant being weakened.

**`order_index` no longer means two things.** It was set from
`session.questions_asked`, making it simultaneously transcript position and
budget consumed. It is now a count of the session's questions, so
`questions_asked` stays the budget; a test asserts the transcript is dense and
unique with repairs interleaved.

**One observation, unexplained.** A single full-suite run failed once and did
not reproduce in eight subsequent runs across five flag configurations. No
cause identified; recorded rather than explained away.

## 7. Risks

| Risk | Mitigation |
|---|---|
| **Transfer probes fire earlier** because repair answers inflate the stall count (R5) | Step 4 excludes them, and `test_transfer_invariant_unchanged` re-measures the Phase 1 invariant rather than trusting it |
| **Interview never terminates** for a disengaged candidate | One repair per parent question, hard cap (step 5) |
| **`order_index` change breaks transcript ordering** anywhere it is read — `_qa_rows`, `_open_question`, `session_out`, the graph's `qa` list | Step 3 keeps it dense and unique; a dedicated test asserts that property with repairs interleaved |
| **A repair turn feels like an interrogation** on WhatsApp, raising abandonment — the guardrail says no increase in abandonment | One repair, neutral wording, and the answer is accepted whatever comes back. If abandonment rises, `REPAIR_TURN=false` is the immediate lever |
| `is_non_answer` is too aggressive — a short genuine answer ("31%") triggers repair | It is length-based (< 12 chars) plus a phrase list, and a bare metric *is* thin for a probe asking for scope. Add golden-set-style cases to `test_policy.py` if it misfires; do **not** loosen it silently |
| Repair questions counted in M6 as generated questions, distorting reject rate | `is_repair=True` excludes them from M6a–M6e in P2-05; they have their own M6f |
