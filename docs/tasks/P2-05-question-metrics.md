# P2-05 — M6 question metrics

Seven-section spec. Owner **A**, task 5 of 5. **Depends: P2-01 … P2-04.**

**Migration impact: none.** Reads columns landed in P2-03.

---

## 1. Task

Publish M6 in `scripts/validation_report.py`, computed from stored rows and the
golden set, with **zero model calls** — so that *"how often does the system
generate bad questions?"* is answered by arithmetic rather than by opinion.

## 2. Current State

- `scripts/validation_report.py` computes M1–M5 from stored rows, 0 model calls,
  and `GET /api/recruiter/validation` serves the **same** `build_report()` — one
  implementation, two surfaces, pinned by
  `test_validation_endpoint_matches_the_script`. M6 must join that structure,
  not sit beside it.
- `ValidationOut` / `ValidationCohort` live in the frozen `api/schemas.py`.
  **M6 must not require a schema edit** — the script's own renderer and the
  `compute_m5()`-style plain-dict pattern are the precedent (`compute_m1`,
  `compute_m2`, `compute_m5` all return plain dicts and only M4 flows through
  the Pydantic model).
- After P2-03 the `questions` table carries `source`, `attempts`,
  `violations_json`, `is_repair` — everything M6d–M6g needs.
- M5a's history is the cautionary precedent: it was reported floor-based for a
  phase because the threshold it named did not exist, and its denominator
  silently included 10 entries that *should* fail. **State every M6 denominator
  explicitly in the output.**

## 3. Files To Change

| File | Change |
|---|---|
| `scripts/validation_report.py` | `compute_m6()` + renderer block |
| `tests/test_questions.py` | metric tests + script/endpoint parity |

Not `api/schemas.py`. Not `api/routers/recruiter.py` — it already calls
`build_report()`.

## 4. Implementation Steps

1. **`compute_m6(snap) -> dict`**, plain dict like `compute_m5()`. Two sources,
   labelled separately in the output because they answer different questions:

   | | Metric | Source | Denominator, stated in output |
   |---|---|---|---|
   | M6a | validator precision | golden set | questions the validator rejected |
   | M6b | validator recall | golden set | entries labelled `reject` |
   | M6c | accept-rate on good questions | golden set | entries labelled `accept` |
   | M6d | live reject rate | `questions.violations_json` | non-repair questions asked |
   | M6e | fallback rate | `questions.source == "fallback"` | non-repair questions asked |
   | M6f | repair rate | `questions.is_repair` | answers received |
   | M6g | repeat rate | `duplicate_content` in `violations_json` | non-repair questions asked |

2. **Per-rule violation histogram.** Print counts per rule name, not just a
   total. A single rule producing 90% of rejections is the most likely sign of a
   miscalibrated rule, and a total hides it.

3. **Exclude repairs from M6a–M6e, M6g.** They are not generated questions;
   including them would dilute every rate. They have M6f.

4. **Label the golden-set metrics as golden-set metrics** in the output. M6a–M6c
   measure the *validator*; M6d–M6g measure the *system in operation*. Conflating
   them is how M5a came to mean two things.

5. **Fixture-mode caveat, printed.** With `OPENAI_API_KEY` empty every question
   comes from `FALLBACK_QUESTIONS`, so M6d/M6e are meaningless in fixture mode.
   Print the mode and suppress those two rather than showing a misleading 0% —
   the "withhold, never estimate" rule that M4a already follows.

6. **Verdict markers** matching the existing `_verdict()` helper: `OK` / `**`
   against the targets in the phase plan §6.

## 5. Tests

| Test | Asserts |
|---|---|
| `test_m6_computed_with_no_model_call` | `/api/dev/llm` count unchanged |
| `test_m6_appears_in_the_report_output` | all seven labels rendered |
| `test_m6_matches_between_script_and_endpoint` | field-for-field, the P1-12 pattern |
| `test_m6_excludes_repair_questions` | a session with repairs does not move M6d/M6e |
| `test_m6_withholds_live_rates_in_fixture_mode` | M6d/M6e reported as n/a, not 0% |
| `test_m6_per_rule_histogram_sums_to_total` | arithmetic consistency |
| `test_m6_denominators_are_printed` | every rate names its denominator |
| `test_m1_to_m5_unchanged_by_m6` | no Phase 1 number moved |

## 6. Verification Commands

```bash
OPENAI_API_KEY="" DATABASE_URL="sqlite+aiosqlite:///:memory:" pytest -q
python seed.py --reset && python scripts/validation_report.py     # M6 block renders
curl -s localhost:8000/api/recruiter/validation | python -m json.tool

# Phase 1 regression: no M1-M5 number may move
python scripts/validation_report.py > /tmp/after.txt && diff <(sed -n '/^M1/,/^M6/p' /tmp/before.txt) <(sed -n '/^M1/,/^M6/p' /tmp/after.txt)
```

## 7. Risks

| Risk | Mitigation |
|---|---|
| **M6d read as a quality score and driven to zero** by loosening rules, producing a validator that accepts everything | Counter-metric C4, printed beside the number: *a reject means the validator worked.* M6a–M6c on the labelled set are the goal |
| **Fixture mode makes M6d/M6e look perfect** — 0% reject because every question is a fallback | Step 5: withhold and print the mode. Same discipline as M4a's `insufficient data` |
| Two implementations of M6 drifting between script and endpoint | One `build_report()`, one parity test — the P1-12 pattern that already prevents this for M4 |
| Metric added that nothing reads, i.e. ceremony | Every M6 number appears in the rendered report and is asserted by a test. A number with no reader is deleted |
| Denominator ambiguity, the M5a failure repeating | Step 4 and `test_m6_denominators_are_printed` |
