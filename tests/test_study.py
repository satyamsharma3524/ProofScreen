"""P3-01/02/04 — the study harness.

These tests never touch the network. The harness's whole job is to run against a
live model, so what is testable here is everything AROUND that: the attempt->row
mapping that makes rejected questions exist at all, the blinding, and the
estimator that turns a stratified sample back into a population.

The estimator tests are the ones that matter. It is forty lines of arithmetic
that nobody will re-derive at review time, and getting it wrong produces numbers
that look completely reasonable and are wrong by twenty points.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.engine import question as question_engine  # noqa: E402
from api.schemas import ProbeLevel  # noqa: E402
from scripts import interview_study as study  # noqa: E402


def _generation(attempts, question, source, n_attempts=1):
    return study.Generation(
        attempts=[study.Attempt(q, ok, tuple(v)) for q, ok, v in attempts],
        result=question_engine.QuestionAttempt(
            question, ProbeLevel.VALIDATION, source, n_attempts, ()
        ),
        kwargs={},
    )


# ---------------------------------------------------------------------------
# the attempt -> row mapping  (plan §0 F1)
# ---------------------------------------------------------------------------


def test_an_unvalidated_fallback_is_one_row_and_is_never_an_accept():
    """`accepted_by_validator` must be BLANK, not False.

    Plan §0 F2. A fallback was not judged and rejected — it was never judged.
    Writing False here would make it a disagreement the moment a human accepts
    the question, and the study would report the validator making a call it
    never made.
    """
    rows = study._rows_for(_generation([], "On \"x\" — tell me more", "fallback"))
    assert len(rows) == 1
    assert rows[0]["validator_ran"] is False
    assert rows[0]["validation_result"] == "not_evaluated"
    assert rows[0]["accepted_by_validator"] == ""
    assert rows[0]["is_final"] is True


def test_an_accepted_first_attempt_is_one_row():
    rows = study._rows_for(_generation([("How many agents?", True, [])], "How many agents?", "model"))
    assert len(rows) == 1
    assert (rows[0]["validation_result"], rows[0]["is_final"]) == ("accept", True)
    assert rows[0]["source"] == "model"


def test_a_rejected_attempt_survives_as_its_own_row():
    """THE POINT OF THE WHOLE INSTRUMENT.

    `orchestrator.ask_next()` stores only the final text, so without this the
    rejected question exists nowhere and the reject stratum has nothing to
    review. The rejected text must be present, carry its rules, and NOT be
    marked final.
    """
    rows = study._rows_for(_generation(
        [("You cut AHT from 480 to 430, how?", False, ["answer_leakage"]),
         ("What did you change about the script?", True, [])],
        "What did you change about the script?", "regenerated", 2,
    ))
    assert len(rows) == 2
    first, second = rows
    assert first["generated_question"] == "You cut AHT from 480 to 430, how?"
    assert first["validation_result"] == "reject"
    assert first["primary_rule"] == "answer_leakage"
    assert first["is_final"] is False
    assert second["is_final"] is True and second["source"] == "regenerated"


def test_two_rejections_produce_three_rows_because_three_questions_were_generated():
    """Attempt 1, attempt 2, and the unvalidated fallback that actually got sent.

    Collapsing these would discard both rejects — precisely the rows the study
    exists to look at — and would also make M7e coverage read as if the fallback
    had been judged.
    """
    rows = study._rows_for(_generation(
        [("q1", False, ["scope_drift"]), ("q2", False, ["no_claim_anchor"])],
        "On \"claim\" — tell me more", "fallback", 2,
    ))
    assert len(rows) == 3
    assert [r["validation_result"] for r in rows] == ["reject", "reject", "not_evaluated"]
    assert [r["is_final"] for r in rows] == [False, False, True]
    assert [r["attempt_index"] for r in rows] == [1, 2, 3]


def test_attempt_index_is_dense_and_one_based():
    rows = study._rows_for(_generation(
        [("q1", False, ["scope_drift"]), ("q2", True, [])], "q2", "regenerated", 2))
    assert [r["attempt_index"] for r in rows] == [1, 2]


# ---------------------------------------------------------------------------
# the estimator  (plan §0 F3 — Decision 4)
# ---------------------------------------------------------------------------


def test_precision_is_base_rate_free():
    """Precision depends only on the reject stratum, so it is the one figure the
    brief's naive method gets right. Changing the population must not move it."""
    a = study.reweight(n_a=900, n_r=100, hr_a=2, s_a=50, hr_r=45, s_r=50)
    b = study.reweight(n_a=100, n_r=900, hr_a=2, s_a=50, hr_r=45, s_r=50)
    assert a["precision"] == b["precision"] == pytest.approx(0.90)


def test_recall_read_off_the_raw_sample_would_be_wrong_by_twenty_four_points():
    """The reason F3 is in the plan at all.

    Same sample either way. Read naively off the 50/50 table, recall is
    45/(45+2) = 95.7%. Reweighted to a population that is 90% accepts, it is
    71.4%. A study that published the first number would be reporting a
    validator that catches almost everything, when it misses more than a
    quarter.
    """
    naive = 45 / (45 + 2)
    assert naive == pytest.approx(0.957, abs=0.001)
    est = study.reweight(n_a=900, n_r=100, hr_a=2, s_a=50, hr_r=45, s_r=50)
    assert est["recall"] == pytest.approx(0.714, abs=0.001)
    assert naive - est["recall"] > 0.20


def test_the_cells_add_up_to_the_population():
    est = study.reweight(n_a=900, n_r=100, hr_a=2, s_a=50, hr_r=45, s_r=50)
    assert est["TP"] + est["FP"] + est["FN"] + est["TN"] == pytest.approx(1000)
    assert est["TP"] + est["FP"] == pytest.approx(100)     # every validator reject
    assert est["FN"] + est["TN"] == pytest.approx(900)     # every validator accept


def test_a_perfect_validator_scores_one_and_an_empty_sample_does_not_divide_by_zero():
    perfect = study.reweight(n_a=900, n_r=100, hr_a=0, s_a=50, hr_r=50, s_r=50)
    assert perfect["precision"] == perfect["recall"] == perfect["f1"] == 1.0
    empty = study.reweight(n_a=0, n_r=0, hr_a=0, s_a=0, hr_r=0, s_r=0)
    assert empty["precision"] == empty["recall"] == empty["accuracy"] == 0.0


def test_wilson_stays_inside_zero_and_one_at_the_boundary():
    """Why Wilson and not the normal approximation: at 50/50 the normal interval
    runs past 1.0 and the report prints `precision 100.0% (94%-106%)`."""
    low, high = study.wilson(50, 50)
    assert low > 0.9 and high == 1.0
    low, high = study.wilson(0, 50)
    assert low == 0.0 and high < 0.1
    assert study.wilson(0, 0) == (0.0, 1.0)


def test_wilson_narrows_as_n_grows():
    narrow = study.wilson(450, 500)
    wide = study.wilson(45, 50)
    assert (narrow[1] - narrow[0]) < (wide[1] - wide[0])


def test_kappa_is_one_on_agreement_and_about_zero_on_chance():
    labels = ["accept", "reject"] * 10
    assert study.cohens_kappa(labels, labels) == 1.0
    flipped = ["reject" if x == "accept" else "accept" for x in labels]
    assert study.cohens_kappa(labels, flipped) == pytest.approx(-1.0)
    assert study.cohens_kappa([], []) == 0.0


# ---------------------------------------------------------------------------
# blinding  (acceptance criteria 8 and 9)
# ---------------------------------------------------------------------------


def test_the_blind_file_exposes_nothing_the_validator_thought():
    """Asserted, not eyeballed — criterion 8 says so explicitly.

    `family` is absent on purpose as well as the verdict: `no_claim_anchor` on an
    HR question would be a tell, and a reviewer who can guess the stratum is not
    blind.
    """
    assert study.BLIND_FIELDS == [
        "row_id", "claim", "probe_level", "question", "human_verdict", "human_note"
    ]
    for leak in ("validation_result", "violations", "primary_rule", "source",
                 "accepted_by_validator", "attempt_index", "stratum", "family"):
        assert leak not in study.BLIND_FIELDS


def test_score_refuses_a_reviewed_file_that_leaked_the_answer(tmp_path, monkeypatch, capsys):
    """Criterion 9. A reviewer who could see the verdict was measuring their own
    anchoring, and the matrix would be a number about that instead."""
    reviewed = tmp_path / "reviewed.csv"
    with reviewed.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["row_id", "question", "human_verdict",
                                                "primary_rule"])
        writer.writeheader()
        writer.writerow({"row_id": "r0001", "question": "q", "human_verdict": "accept",
                         "primary_rule": "scope_drift"})
    for name in ("SAMPLE_KEY",):
        monkeypatch.setattr(study, name, tmp_path / ".sample_key.csv")
    (tmp_path / ".sample_key.csv").write_text("row_id\n")
    monkeypatch.setattr(study, "OUT_DIR", tmp_path)
    (tmp_path / ".population.json").write_text("{}")

    import asyncio
    args = type("A", (), {"reviewed": str(reviewed), "reviewer2": None})()
    assert asyncio.run(study.cmd_score(args)) == 2
    assert "REFUSING TO SCORE" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# the matrix
# ---------------------------------------------------------------------------


def test_tier_b_is_strided_so_a_pilot_spans_families():
    """Truncating would give a pilot six BPO resumes in a row — one family, and a
    cost estimate for nine."""
    small = study.build_matrix(repeats=0, tier_b_limit=6, base_seed=1)
    assert len(small) == 6
    assert len({s.family for s in small}) >= 5


def test_the_full_matrix_covers_every_labelled_family():
    specs = study.build_matrix(repeats=1, tier_b_limit=None, base_seed=1)
    tier_b = [s for s in specs if s.tier == "B"]
    assert len(tier_b) == 60
    assert len({s.family for s in tier_b}) == 9        # 8 families + general


def test_tier_a_carries_authored_answers_and_repeats_get_distinct_ids():
    specs = study.build_matrix(repeats=2, tier_b_limit=0, base_seed=1)
    assert len(specs) == 8
    assert all(s.answers for s in specs)
    assert len({s.interview_id for s in specs}) == 8


def test_importing_the_seed_personas_does_not_disable_the_model():
    """seed.py sets `settings.openai_api_key = None` at module scope — seeding
    must be free and offline. Importing it here without restoring the key would
    put the entire study into fixture mode SILENTLY, and every question would be
    a hard-coded fallback with no validator decision at all."""
    from api.config import settings

    settings.openai_api_key = "sk-not-a-real-key"
    try:
        study._load_seed_personas()
        assert settings.openai_api_key == "sk-not-a-real-key"
        assert settings.llm_enabled is True
    finally:
        settings.openai_api_key = ""


# ---------------------------------------------------------------------------
# guardrails the phase is accepted against
# ---------------------------------------------------------------------------


def test_the_study_never_asks_a_model_to_judge_a_question():
    """CLAUDE.md rule 1, at the phase level. The candidate simulator plays the
    CANDIDATE. Nothing in scoring may consult a model — a validator graded by a
    model would make question quality the model's opinion, which is the thing the
    architecture exists to prevent."""
    source = Path(study.__file__).read_text()
    scoring = source.split("# scoring", 1)[-1]
    body = source[source.index("async def cmd_score"):]
    assert "complete_json" not in body
    assert "_simulate_answer" not in body


def test_the_probe_levels_the_neutral_pool_answers_match_the_enum():
    assert set(study._NEUTRAL_ANSWERS) == {level.value for level in ProbeLevel}


# ---------------------------------------------------------------------------
# the generation buffer  (regression — cost $0.47 of pilot to find)
# ---------------------------------------------------------------------------


def test_a_generation_is_matched_by_text_not_by_being_last():
    """`orchestrator.submit_answer()` calls `ask_next()` itself, so question N+1
    is generated at the tail of turn N. Reading "the last generation" at the top
    of turn N+1 therefore reads the wrong one — or, if the buffer was cleared,
    nothing at all.

    The pilot reported M7e coverage of 14.8% while `questions.source` said 45
    model + 9 regenerated. That contradiction is the bug; this is the fix pinned.
    """
    study._generations.clear()
    study._consumed.clear()
    study._generations.extend([
        _generation([("first", True, [])], "first", "model"),
        _generation([("second", True, [])], "second", "model"),
        _generation([("third", True, [])], "third", "model"),
    ])
    # Asked out of order, exactly as the orchestrator's lookahead produces them.
    assert study._take_generation("second").result.question == "second"
    assert study._take_generation("first").result.question == "first"
    assert study._take_generation("third").result.question == "third"


def test_a_generation_is_consumed_once_so_a_repeated_fallback_is_not_double_counted():
    """Two claims can draw the identical fallback string. Without consumption the
    second question would be attributed to the first's generation and one real
    generation would be silently dropped from the dataset."""
    study._generations.clear()
    study._consumed.clear()
    study._generations.extend([
        _generation([], 'On "a" — tell me more', "fallback"),
        _generation([], 'On "a" — tell me more', "fallback"),
    ])
    first = study._take_generation('On "a" — tell me more')
    second = study._take_generation('On "a" — tell me more')
    assert first is not None and second is not None and first is not second
    assert study._take_generation('On "a" — tell me more') is None


def test_an_unmatched_question_returns_none_rather_than_the_wrong_generation():
    """A repair makes no model call, so nothing in the buffer produced it.
    Returning the nearest generation would file a deterministic fixed line as a
    validated model question."""
    study._generations.clear()
    study._consumed.clear()
    study._generations.append(_generation([("q", True, [])], "q", "model"))
    assert study._take_generation("On \"x\" — could you give me the steps?") is None
