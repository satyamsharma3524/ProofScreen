# P2-03 — Bounded regeneration

Seven-section spec. Owner **A**, task 3 of 5. **Depends: P2-02.**

**Migration impact: schema change** (`questions` gains four columns) **+ fixture
regeneration.** One reset serves this task and P2-04.

---

## 1. Task

Wire `validate()` into `generate_question()` with a hard cap of **one**
regeneration, then fall back. Record the outcome on the `Question` row so P2-05
can compute a metric from stored data rather than from logs.

```
attempt 1 ──accepted──▶ ask it
    │
  rejected
    │
attempt 2 (retry prompt names the violated rules) ──accepted──▶ ask it
    │
  rejected
    │
FALLBACK_QUESTIONS[probe_level] ──▶ ask it        (never re-validated)
```

## 2. Current State

- `generate_question()` calls `complete_json(..., fallback=...)` once and
  returns whatever comes back. There is no retry anywhere on the question path.
- `FALLBACK_QUESTIONS` is reached only when the model call itself fails. After
  this task it is also the terminal state of two validation failures.
- `Question` stores `text · probe_level · target_dimension · order_index ·
  asked_at · answered`. **Nothing records how the text was produced**, so
  fallback rate and reject rate are not computable today at all.
- `PHASE_1_SUCCESS_METRICS.md` §G caps median turn latency at **+20%**. Every
  turn already blocks on a model call, so an unbounded retry loop is the live
  threat this task must not create.
- `settings` has no question-path flags. `TRANSFER_PROBE` is the precedent for
  a behaviour flag that reproduces the previous system exactly when off.

## 3. Files To Change

| File | Change |
|---|---|
| `api/engine/question.py` | retry flow inside `generate_question()`; retry brief naming violated rules |
| `api/models.py` | 4 new columns on `Question` — **B's file, restriction lifted, change announced** |
| `api/config.py` | `question_validation: bool = True` (off reproduces Phase 1 exactly) |
| `.env.example` | document the flag |
| `api/prompts/generate_question.txt` | one `$violations` slot, rule **names** only |
| `tests/test_questions.py` | call-count and recording tests |

## 4. Implementation Steps

1. **Schema, once** — `questions` gains, all nullable/defaulted so `create_all()`
   is enough and no backfill exists:

   | Column | Type | Meaning |
   |---|---|---|
   | `source` | `String(16)`, default `"model"` | `model` · `regenerated` · `fallback` |
   | `attempts` | `Integer`, default 1 | 1 or 2; never higher |
   | `violations_json` | `Text`, nullable | rules that fired on **attempt 1**, JSON list |
   | `is_repair` | `Boolean`, default `False` | unused here; landed now so P2-04 needs no second reset |

   `String` not a native enum — CLAUDE.md convention, because
   `create_all()` cannot add a value to a Postgres enum.

2. **Retry brief carries rule NAMES, never examples.** The prompt gains one
   `$violations` slot rendered as e.g. `answer_leakage, no_claim_anchor`.
   Per-family or per-defect worked examples in a prompt are forbidden by A's
   contract — they re-introduce cohort bias at config level and break the
   "cohort #101 costs zero Python edits" criterion. The arXiv 2507.02858 finding
   that a mistake-type taxonomy improves generated questions is satisfied by
   naming the taxonomy, not by illustrating it.

3. **The cap is structural, not a loop bound.** Write it as two explicit calls,
   not `for attempt in range(2)`. A loop invites someone to raise the constant;
   two calls make raising it a visible diff. This is the same reasoning that
   keeps `select_transfer()` out of a `planner.py`.

4. **The fallback is never validated.** Return it directly. R1 in the phase plan
   is the reason: three fallbacks would fail rules 4 and 7, CLAUDE.md rule 5
   requires every LLM call to have a fallback, and a validator able to reject
   the fallback leaves no path at all. Structural, not an exemption list.

5. **`violations_json` records attempt 1 only.** M6d is "how often does the
   model produce a bad question", which is a property of the first attempt. If
   attempt 2 also fails, `source` is `fallback` and that is the second fact
   worth storing.

6. **Flag off ⇒ Phase 1 exactly.** `QUESTION_VALIDATION=false` skips validate(),
   writes `source="model"`, `attempts=1`, `violations_json=NULL`. Asserted by
   re-running the seed and comparing competence 56/46/14/61.

7. **Regenerate the fixture once**, after the columns land.

## 5. Tests

| Test | Asserts |
|---|---|
| `test_rejected_question_triggers_exactly_one_regeneration` | LLM call count rises by **exactly 1**, via `/api/dev/llm` |
| `test_two_failures_fall_back` | `source == "fallback"`, text is a `FALLBACK_QUESTIONS` value |
| `test_fallback_is_never_validated` | monkeypatch `validate` to always reject; the fallback is still returned, and `validate` was not called with it |
| `test_accepted_first_attempt_makes_one_call` | no retry when the first attempt passes |
| `test_violations_are_recorded_from_attempt_one` | `violations_json` holds attempt 1's rules even when attempt 2 succeeds |
| `test_attempts_never_exceeds_two` | over the whole seeded run, `max(attempts) == 2` |
| `test_validation_flag_off_reproduces_phase_one` | `QUESTION_VALIDATION=false`: seed competence 56/46/14/61, no column populated |
| `test_regeneration_adds_no_second_model_call_on_transfer` | transfer path obeys the same cap |
| `test_question_columns_default_safely` | a row written without the new fields reads `source="model"`, `attempts=1`, `is_repair=False` |

## 6. Verification Commands

```bash
docker compose down -v && docker compose up --build -d       # schema change, no Alembic
docker compose exec api python seed.py

export DATABASE_URL="sqlite+aiosqlite:///./proofscreen.sqlite3"
python seed.py --reset && python scripts/dump_fixture.py && pytest -q

# the cap, measured rather than read
python - <<'EOF'
import asyncio, json
# assert max(attempts) == 2 and count sources across a seeded run
EOF

# flag off == Phase 1
QUESTION_VALIDATION=false python seed.py --reset   # expect competence 56 / 46 / 14 / 61
```

## 7. Risks

| Risk | Mitigation |
|---|---|
| **Latency.** One extra model call on rejected questions, and every turn already blocks on one | Cap of 1, structurally. Measure median turn latency before and after on the seeded run; +20% is the guardrail and the ledger row must carry the number |
| **The retry prompt becomes a dumping ground** for defect examples, re-introducing cohort bias | Rule names only. A structural test greps the rendered prompt for the golden set's claim strings and fails if any appear |
| **Schema change breaks Satyam's machine** mid-phase | Announce before landing; he runs `docker compose down -v`. `is_repair` ships now so P2-04 needs no second reset |
| **Regeneration masks a bad prompt.** If the base prompt is weak, retry hides it behind a second call | M6d is *reported, not targeted* (counter-metric C4). A rising reject rate is a signal to fix the base prompt, not to widen the rules |
| Fixture churn — regeneration changes ids and one quote (a known ID-length dependency, CLAUDE.md) | Regenerate once, at the end of the task, and diff the fixture for **substantive** fields only |
| Someone raises the cap to 3 "just for now" | Two explicit calls instead of a loop; `test_attempts_never_exceeds_two` fails loudly |
