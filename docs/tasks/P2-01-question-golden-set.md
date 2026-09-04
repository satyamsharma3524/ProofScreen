# P2-01 — Question golden set (defect corpus)

Seven-section implementation spec per `DEVELOPER_A_CONTRACT.md` §*Per-task
output*. Owner **A**, task 1 of 5. No dependencies.

**This task ships no production code.** It ships the measuring instrument, and
it lands before the thing it measures. `DEVELOPER_A_CONTRACT.md`: *"Write the
golden set, the fixture or the assertion before the code it judges. A test
authored afterwards describes the implementation instead of testing it."* That
rule is why P1-06 discovered substring matching (`hr` inside *through*) instead
of shipping the IDF weighting it had been specified to add.

---

## 1. Task

Author `tests/data/question_golden.json`: a **labelled defect corpus** of
interview questions, each with the planner context that produced it, a human
verdict, and the rule that verdict rests on.

It is deliberately **not** a corpus of good questions. Routing has one correct
answer per resume; a question does not. What *is* objectively decidable is
whether a specific question carries a specific defect — so the corpus labels
defects, and P2-02 is measured on precision and recall against those labels.

## 2. Current State

Measured, not assumed:

- `tests/data/routing_golden.json` exists — 64 entries, 60 labelled, 4
  deliberately ambiguous — and yields M5b = 98.3%. **This is the shape to
  copy**, including its `_note` header explaining that it was authored before
  the scorer and that a wrong entry is fixed in the entry, never by widening
  the taxonomy until it passes.
- There is **no** equivalent for questions. `tests/test_policy.py` asserts which
  claim and probe level the planner selects; nothing asserts anything about the
  question text.
- Question text today comes from one of three places: LLM #2
  (`question.generate_question`), `FALLBACK_QUESTIONS` (6 entries), or
  `TRANSFER_FALLBACKS` (2 `string.Template`s). The corpus must contain examples
  drawn from all three shapes, because all three reach a candidate.
- `PROBE_BRIEFS` show what each level is *for*, and the corpus's `accept`
  entries must be consistent with them — an `accept` question that contradicts
  its own probe brief is a wrong entry.

## 3. Files To Change

| File | Change |
|---|---|
| `tests/data/question_golden.json` | **New.** The corpus |
| `tests/test_questions.py` | **New.** Corpus integrity tests only in this task — no validator yet |

Nothing else. No production file is touched by P2-01.

## 4. Implementation Steps

1. **Write the `_note` header first**, stating: authored before the validator;
   a wrong entry is fixed in the entry, not by loosening a rule; `accept`
   entries exist to stop a reject-everything validator from scoring well.
2. **Entry shape**, exactly as briefed:
   ```json
   {
     "id": "q01",
     "context": {
       "claim": "Reduced average handle time from 480s to 310s across a 28-agent inbound voice process",
       "claim_type": "aht_control",
       "claim_metric": "480s -> 310s",
       "probe_level": "VALIDATION",
       "target_dimension": "SPECIFICITY",
       "prior_questions": [],
       "transfer_target_claim": null
     },
     "question": "So you cut AHT from 480s to 310s — how did you cut it from 480 to 310?",
     "verdict": "reject",
     "primary_rule": "answer_leakage",
     "rules": ["answer_leakage"],
     "why": "the question supplies both numbers the answer is supposed to provide"
   }
   ```
   `transfer_target_claim` is null except on TRANSFER entries, where it carries
   the second claim `select_transfer()` would have chosen. Rule 6 cannot be
   scored without it.
3. **Coverage matrix — every cell filled, ≥ 60 entries total:**

   | | accept | reject |
   |---|---|---|
   | VALIDATION | ≥ 3 | ≥ 3 |
   | OPERATIONAL | ≥ 3 | ≥ 3 |
   | INCIDENT | ≥ 3 | ≥ 3 |
   | DECISION | ≥ 3 | ≥ 3 |
   | OUTCOME | ≥ 3 | ≥ 3 |
   | TRANSFER | ≥ 3 | ≥ 3 |

   Plus ≥ 3 `reject` entries for **each** of the seven rules, and ≥ 6 Hinglish /
   code-switched entries split across both verdicts.
4. **Draw claims from at least three families** — `bpo_operations`,
   `product`, `software_engineering` — so the corpus cannot be satisfied by a
   validator that has learned call-centre vocabulary. Reuse claim text from
   `seed.py`'s personas and `routing_golden.json` where it fits; inventing a
   fourth vocabulary is authoring cost with no coverage gain.
5. **Author the adversarial pairs deliberately.** For each rule, include at
   least one `accept` entry that a naive implementation of that rule would
   reject. These are the entries that make M6c meaningful:
   - *anchoring vs leakage:* a question containing the claim's **words** but
     none of its **numerals** must be `accept`. Rules 1 and 7 pull in opposite
     directions and this pins the boundary.
   - *double-barrel vs the briefs:* `FALLBACK_QUESTIONS[DECISION]` is *"What did
     you decide to do about it, and what did you consider but decide against?"*
     — two clauses about **one** subject. It must be `accept`. A question
     joining **two** subjects ("how did you reduce AHT and improve CSAT?") must
     be `reject`.
   - *hypothetical on TRANSFER:* *"Suppose that had moved the number the wrong
     way instead…"* must be `accept` at TRANSFER and `reject` at OUTCOME. Same
     string, two verdicts, keyed only on `probe_level`.
   - *scope on TRANSFER:* a question referencing the planner's target claim is
     `accept`; one referencing a **third** claim is `reject`.
6. **Measure the duplicate-content threshold, do not guess it.** Author ≥ 6
   near-duplicate pairs of increasing similarity, compute content-word Jaccard
   over them, and record the observed separation in the `_note`. P2-02 takes its
   threshold from that measurement. A guessed 0.6 is exactly the mistake
   `MARGIN_FLOOR` avoided by measuring first.
7. **Never label from fluency.** No entry may be `reject` for grammar, spelling,
   register or politeness. CLAUDE.md rule 6, and the Hinglish entries are the
   test of it.

## 5. Tests

`tests/test_questions.py`, corpus integrity only:

| Test | Asserts |
|---|---|
| `test_golden_set_has_minimum_size` | ≥ 60 entries |
| `test_every_probe_level_appears_with_both_verdicts` | the 6×2 matrix above, no empty cell |
| `test_every_rule_has_at_least_three_reject_entries` | all seven rules represented |
| `test_accept_and_reject_are_both_substantial` | neither verdict below 35% of entries — a corpus that is 95% reject makes recall trivial |
| `test_transfer_entries_carry_a_target_claim` | rule 6 is scoreable |
| `test_hinglish_entries_exist_and_are_not_all_rejects` | ≥ 6 entries, both verdicts |
| `test_entry_ids_are_unique_and_stable` | ids are the citation handle in ledger rows |
| `test_no_entry_is_rejected_for_presentation` | no rule name is a presentation judgement; structural anti-bias guard |
| `test_families_represented` | ≥ 3 distinct `claim_type` families |

Every one of these fails against an empty or absent file, which is the
fail-first evidence for this task.

## 6. Verification Commands

```bash
OPENAI_API_KEY="" DATABASE_URL="sqlite+aiosqlite:///:memory:" pytest -q tests/test_questions.py

# coverage matrix, printed rather than asserted, for the ledger row
python - <<'EOF'
import json, collections
g = json.load(open("tests/data/question_golden.json"))["questions"]
print("entries:", len(g))
m = collections.Counter((e["context"]["probe_level"], e["verdict"]) for e in g)
for lvl in ("VALIDATION","OPERATIONAL","INCIDENT","DECISION","OUTCOME","TRANSFER"):
    print(f"  {lvl:12} accept={m[(lvl,'accept')]:2d}  reject={m[(lvl,'reject')]:2d}")
print("rules:", dict(collections.Counter(r for e in g for r in e["rules"])))
print("hinglish:", sum(1 for e in g if e.get("hinglish")))
EOF

# the measured Jaccard separation P2-02 will take its threshold from
python - <<'EOF'
# prints observed content-word Jaccard for every authored near-duplicate pair
EOF
```

## As built — 2026-09-05

| | Specified | Delivered |
|---|---|---|
| Entries | ≥ 60 | **73** (44 accept / 29 reject) |
| Verdict balance | both ≥ 35% | 60.3% / 39.7% |
| Rejects per rule | ≥ 3 | 3–6, all seven rules |
| Adversarial accepts per rule | ≥ 1 | **≥ 2**, all seven |
| Hinglish | ≥ 6 | 9 — **6 accept / 3 reject** |
| Families | ≥ 3 | bpo 32 · product 22 · swe 19 |
| Tests | — | 51 |

**Schema delta, approved in review:** `rule` (singular) became `primary_rule` +
`rules[]`, because defects genuinely co-occur (`q58` is `scope_drift` +
`unsupported_metric`). This adds **M6h `rule_attribution`**: of entries
correctly rejected, the % where `primary_rule` is among the fired violations.
Precision and recall alone answer *"did we reject the right question?"* and not
*"did we reject it for the intended reason?"* — without M6h a validator that
rejects correctly via the wrong rule looks green while the team tunes the wrong
rule. Invariant added: every reject entry carries `primary_rule`, and it is
present in `rules[]`.

**Rule 3 renamed** `double_barrel` → `multiple_fact_targets` before anything
persisted it. See P2-02.

**Three findings, all encoded as entries or tests rather than prose:**

1. **Aggressive stopword removal destroys rule 2.** Measured over the authored
   ladder: an aggressive list overlaps the duplicate and distinct bands by
   **−0.083** — no separating threshold exists. A minimal list separates at
   **+0.169** (distinct ≤ 0.231, duplicate ≥ 0.400). Threshold **0.37**, the
   midpoint above the highest borderline pair (0.333). Recorded as
   `rule_2_threshold`; a test fails if P2-02 drifts from it.
2. **A valid T1 transfer probe names two fact targets by construction** (`q63`),
   so rule 3 must not be evaluated on TRANSFER.
3. **The rendered fallback fails rule 1** (`q60`) — `On "<claim>" — <base>`
   quotes the claim including its figures. Evidence for the runtime bypass, tied
   to the live `FALLBACK_QUESTIONS[TRANSFER]` string by a test.

**Defect found in the corpus itself, by measuring it:** the first pass had 6
Hinglish entries and all 6 were accepts, which lets a validator satisfy the
coverage test by learning *code-switched ⇒ accept* — the same bias with the
opposite sign. Three Hinglish rejects added and the test strengthened to require
≥ 2.

## 7. Risks

| Risk | Mitigation |
|---|---|
| **The corpus encodes our current prompt's habits rather than real defects.** Author it from the defect taxonomy and the probe briefs, and it describes what we already do | Draw `reject` entries from the ChatGPT review's examples and from the *literature's* interviewer-mistake taxonomy, not from logs of our own output. Do not read live generated questions while authoring |
| **`accept` entries too easy, making M6c meaningless.** Every rule then passes trivially | Step 5 is the mitigation and it is the highest-value part of this task: each rule needs an `accept` entry that a naive implementation rejects |
| **Reject-heavy corpus inflates recall.** A 95%-reject corpus makes M6b easy and M6c unmeasurable | `test_accept_and_reject_are_both_substantial`, 35% floor both ways |
| **Rule 3 (double-barrel) may not be deterministically separable** from the two-clause phrasing the DECISION and OUTCOME briefs deliberately use | This is the reason P2-01 precedes P2-02. If the corpus shows no clean separation, **rule 3 is reported as unimplementable and dropped** rather than shipped as a coin flip. A dropped rule with a measurement beats a rule that fires at random |
| Hinglish entries authored by a non-speaker read as parody and test nothing | Draw phrasing from real WhatsApp register — short, transliterated, code-switched mid-sentence. Have a second reader check them before the corpus is used |
| The corpus becomes a frozen artifact nobody may fix | State in `_note`, as `routing_golden.json` does: a wrong entry is fixed **in the entry**, and the fix is recorded in the ledger row |
