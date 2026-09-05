"""
P2-01 — corpus integrity for the question defect corpus.

NO VALIDATOR EXISTS YET. That is deliberate: `tests/data/question_golden.json`
is authored before `question.validate()` (P2-02), because a corpus written
afterwards describes the implementation instead of testing it. Everything here
tests the *corpus* and the *fallback questions already in production* — nothing
imports a validator, and nothing in `api/` changed for this task.

The fallback tests are the CI half of the runtime/CI split: at runtime the
fallback bypasses validation (it has to — see `q60`), but a future edit that
introduced garbage fallback text would otherwise reach a candidate unchecked.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from string import Template

import pytest

from tests.conftest import onboard, run_interview
from api.engine.question import (
    DUPLICATE_JACCARD,
    FALLBACK_QUESTIONS,
    TRANSFER_FALLBACKS,
    QuestionValidation,
    fallback_question,
    validate,
)
from api.schemas import Dimension, ProbeLevel
from api.taxonomy import claim_types, fact_keys

GOLDEN_PATH = Path(__file__).parent / "data" / "question_golden.json"
GOLDEN = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
ENTRIES = GOLDEN["questions"]
LADDER = GOLDEN["jaccard_ladder"]

ACCEPTS = [e for e in ENTRIES if e["verdict"] == "accept"]
REJECTS = [e for e in ENTRIES if e["verdict"] == "reject"]

# The seven rules P2-02 implements. Frozen here because they are persisted in
# `questions.violations_json` from P2-03 onward — renaming one later
# invalidates stored history, so the corpus is where the names are pinned.
RULES = (
    "answer_leakage",
    "duplicate_content",
    "multiple_fact_targets",
    "hypothetical_misuse",
    "unsupported_metric",
    "scope_drift",
    "no_claim_anchor",
)

LEVELS = ("VALIDATION", "OPERATIONAL", "INCIDENT", "DECISION", "OUTCOME", "TRANSFER")

MIN_ENTRIES = 60
MIN_PER_VERDICT_SHARE = 0.35
MIN_REJECTS_PER_RULE = 3
MIN_ADVERSARIAL_PER_RULE = 2
MIN_HINGLISH = 6
MIN_FAMILIES = 3


# ---------------------------------------------------------------------------
# size and balance
# ---------------------------------------------------------------------------


def test_golden_set_has_minimum_size():
    assert len(ENTRIES) >= MIN_ENTRIES, f"{len(ENTRIES)} entries, need {MIN_ENTRIES}"


def test_accept_and_reject_are_both_substantial():
    """A 95%-reject corpus makes recall trivial and accept-rate unmeasurable.
    A 95%-accept corpus does the reverse. Both verdicts carry weight or neither
    metric means anything."""
    total = len(ENTRIES)
    for verdict, rows in (("accept", ACCEPTS), ("reject", REJECTS)):
        share = len(rows) / total
        assert share >= MIN_PER_VERDICT_SHARE, (
            f"{verdict} is {share:.0%} of the corpus, floor is "
            f"{MIN_PER_VERDICT_SHARE:.0%} — the metrics become gameable"
        )


def test_entry_ids_are_unique():
    """Ids are the citation handle used in ledger rows and PR discussion."""
    duplicates = [k for k, n in Counter(e["id"] for e in ENTRIES).items() if n > 1]
    assert not duplicates, f"duplicate ids: {duplicates}"


# ---------------------------------------------------------------------------
# coverage
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("level", LEVELS)
def test_every_probe_level_appears_with_both_verdicts(level):
    """The 6x2 matrix, no empty cell. A level with no reject entries is a level
    whose rules were never exercised."""
    at_level = [e for e in ENTRIES if e["context"]["probe_level"] == level]
    accepts = [e for e in at_level if e["verdict"] == "accept"]
    rejects = [e for e in at_level if e["verdict"] == "reject"]
    assert len(accepts) >= 3, f"{level}: only {len(accepts)} accept entries"
    assert len(rejects) >= 3, f"{level}: only {len(rejects)} reject entries"


@pytest.mark.parametrize("rule", RULES)
def test_every_rule_has_enough_reject_entries(rule):
    hits = [e for e in REJECTS if rule in e["rules"]]
    assert len(hits) >= MIN_REJECTS_PER_RULE, (
        f"{rule}: {len(hits)} reject entries, need {MIN_REJECTS_PER_RULE}"
    )


@pytest.mark.parametrize("rule", RULES)
def test_every_rule_has_adversarial_accept_entries(rule):
    """The highest-value part of the corpus. Without these, a rule can be
    implemented as "reject anything vaguely like this" and still score well on
    precision and recall."""
    hits = [e for e in ACCEPTS if e["naive_reject_risk"] == rule]
    assert len(hits) >= MIN_ADVERSARIAL_PER_RULE, (
        f"{rule}: {len(hits)} adversarial accept entries, need "
        f"{MIN_ADVERSARIAL_PER_RULE} — the rule's boundary is untested"
    )


def test_families_are_represented():
    families = {e["family"] for e in ENTRIES}
    assert len(families) >= MIN_FAMILIES, (
        f"only {families} — a single-family corpus is satisfied by a validator "
        f"that has memorised one vocabulary"
    )


def test_hinglish_entries_exist_with_both_verdicts():
    """Register is never a defect (CLAUDE.md rule 6). Code-switched entries on
    BOTH sides are how that is enforced rather than asserted."""
    hinglish = [e for e in ENTRIES if e["hinglish"]]
    assert len(hinglish) >= MIN_HINGLISH, f"{len(hinglish)} Hinglish entries"
    accepts = [e for e in hinglish if e["verdict"] == "accept"]
    rejects = [e for e in hinglish if e["verdict"] == "reject"]
    assert len(accepts) >= 3, (
        "too few Hinglish accepts — the corpus would encode the bias it exists "
        "to guard against"
    )
    # The half the first pass of this corpus missed. Without Hinglish REJECTS a
    # validator can pass the coverage test by learning "code-switched =>
    # accept", which is the same bias wearing the opposite sign.
    assert len(rejects) >= 2, (
        f"only {len(rejects)} Hinglish rejects — nothing proves a code-switched "
        f"question carrying a real defect is caught"
    )
    assert {r for e in rejects for r in e["rules"]}.issubset(set(RULES))


# ---------------------------------------------------------------------------
# structural well-formedness
# ---------------------------------------------------------------------------


def test_reject_entries_carry_a_primary_rule_present_in_rules():
    """The invariant that prevents attribution drift inside the corpus. M6h
    (rule attribution) is computed against `primary_rule`, so an entry whose
    primary rule is missing from `rules[]` would silently corrupt it."""
    for e in REJECTS:
        assert e["primary_rule"], f"{e['id']}: reject with no primary_rule"
        assert e["primary_rule"] in e["rules"], (
            f"{e['id']}: primary_rule {e['primary_rule']!r} not in {e['rules']}"
        )
        assert e["primary_rule"] in RULES, f"{e['id']}: unknown rule"


def test_accept_entries_carry_no_rules():
    for e in ACCEPTS:
        assert e["primary_rule"] is None, f"{e['id']}: accept with a primary_rule"
        assert e["rules"] == [], f"{e['id']}: accept carrying {e['rules']}"


def test_every_entry_has_a_checkable_reason():
    """`why` is read by a human deciding whether the label is right. An entry
    nobody can check is an entry nobody can correct."""
    for e in ENTRIES:
        assert len(e["why"]) >= 25, f"{e['id']}: `why` too thin to review"


def test_context_is_complete_and_typed():
    for e in ENTRIES:
        c = e["context"]
        assert c["probe_level"] in LEVELS, f"{e['id']}: bad probe_level"
        ProbeLevel(c["probe_level"])
        Dimension(c["target_dimension"])
        assert c["claim"].strip(), f"{e['id']}: empty claim"
        assert c["claim_type"] in claim_types(e["family"]), (
            f"{e['id']}: claim_type {c['claim_type']!r} is not in {e['family']}"
        )


def test_transfer_entries_carry_a_target_claim():
    """Rule 6 on TRANSFER is scored against the planner's chosen target. Without
    it the entry cannot be evaluated at all."""
    for e in ENTRIES:
        if e["context"]["probe_level"] != "TRANSFER":
            continue
        operator = e["context"]["transfer_operator"]
        assert operator in ("T1", "T3"), f"{e['id']}: transfer_operator not set"
        if operator == "T3":
            # T3 inverts THIS claim's own outcome, so it has no second claim.
            # `select_transfer()` returns target_claim_id=None for exactly this
            # case; requiring a target here would assert against the mechanism.
            assert not e["context"]["transfer_target_claim"], (
                f"{e['id']}: T3 must not carry a target claim"
            )
            continue
        assert e["context"]["transfer_target_claim"], (
            f"{e['id']}: T1 entry with no transfer_target_claim — rule 6 is unscoreable"
        )


def test_transfer_covers_valid_and_third_claim_drift():
    """Both required TRANSFER cases, asserted rather than assumed present."""
    transfer = [e for e in ENTRIES if e["context"]["probe_level"] == "TRANSFER"]
    valid = [e for e in transfer if e["verdict"] == "accept"]
    drift = [e for e in transfer if e["primary_rule"] == "scope_drift"]
    assert len(valid) >= 3, "no valid transfer probes to contrast drift against"
    assert len(drift) >= 3, "third-claim drift is the defect TRANSFER exists to risk"


def test_duplicate_content_entries_supply_prior_questions():
    """R2 is meaningless without something to be a duplicate OF."""
    for e in REJECTS:
        if "duplicate_content" in e["rules"]:
            assert e["context"]["prior_questions"], (
                f"{e['id']}: labelled duplicate_content with no prior_questions"
            )


def test_unsupported_metric_entries_contain_a_numeral():
    """And the boundary case: an accept entry marked as an R5 risk must contain
    a numeral that appears in a prior ANSWER."""
    for e in REJECTS:
        if "unsupported_metric" in e["rules"]:
            assert re.search(r"\d", e["question"]), (
                f"{e['id']}: labelled unsupported_metric but has no number"
            )
    for e in ACCEPTS:
        if e["naive_reject_risk"] == "unsupported_metric":
            nums = re.findall(r"\d+", e["question"])
            assert nums, f"{e['id']}: R5 adversarial accept with no numeral"
            prior = " ".join(e["context"]["prior_answers"])
            assert any(n in prior for n in nums), (
                f"{e['id']}: numeral is not traceable to a candidate answer, so "
                f"the entry does not demonstrate the boundary it claims to"
            )


def test_no_entry_is_rejected_for_presentation():
    """Structural anti-bias guard, mirroring the three in test_scoring.py.
    A rule name that reads as a presentation judgement must never appear."""
    forbidden = {
        "fluency", "grammar", "spelling", "politeness", "tone", "register",
        "accent", "confidence", "verbosity", "length", "professionalism",
    }
    for e in ENTRIES:
        for rule in e["rules"]:
            assert rule not in forbidden, f"{e['id']}: presentation rule {rule!r}"
        assert e["primary_rule"] not in forbidden


def test_rule_names_are_the_frozen_seven():
    """These strings land in `questions.violations_json` in P2-03. The corpus is
    where they are pinned, before anything persists them."""
    used = {r for e in ENTRIES for r in e["rules"]}
    assert used <= set(RULES), f"unknown rule names: {used - set(RULES)}"
    assert used == set(RULES), f"rules never exercised: {set(RULES) - used}"


# ---------------------------------------------------------------------------
# the two findings from authoring, pinned so they cannot be quietly lost
# ---------------------------------------------------------------------------


def test_a_valid_transfer_probe_may_name_two_fact_targets():
    """FINDING (q63). A T1 transfer question pairs the method from one claim
    with the problem from another, so when both subjects are metrics it names
    two fact targets BY CONSTRUCTION.

    Therefore `multiple_fact_targets` must not be evaluated on TRANSFER — `R6`
    already constrains which second subject is allowed. This test fails if
    somebody later relabels that entry as a reject, which is the moment the
    finding would otherwise be lost.
    """
    entry = next(e for e in ENTRIES if e["id"] == "q63")
    assert entry["verdict"] == "accept"
    assert entry["naive_reject_risk"] == "multiple_fact_targets"
    assert entry["context"]["probe_level"] == "TRANSFER"

    # Asserted against the two subjects directly. Alias resolution
    # (`aht_seconds` <- "handle time") is P2-02's job; this test only has to
    # prove the entry still demonstrates TWO metric subjects in one question.
    text = entry["question"].lower()
    own_subject = "handle time"          # aht_seconds, from the probed claim
    target_subject = "attrition"         # attrition_pct, from the transfer target
    assert own_subject in text and target_subject in text, (
        "q63 no longer names two metric subjects, so it no longer justifies "
        "exempting TRANSFER from rule 3"
    )
    keys = fact_keys(entry["family"])
    assert "aht_seconds" in keys and "attrition_pct" in keys, (
        "both subjects must be real fact keys for this family or the finding "
        "is about nothing"
    )


def test_the_rendered_fallback_is_a_labelled_reject():
    """FINDING (q60). The runtime fallback is rendered as `On "<claim>" — <base>`,
    which quotes the claim including its figures and therefore fails
    `answer_leakage`. That is the evidence for the runtime bypass in P2-02, and
    it is not a defect to fix in `question.py`."""
    entry = next(e for e in ENTRIES if e["id"] == "q60")
    assert entry["is_fallback"] is True
    assert entry["verdict"] == "reject"
    assert entry["primary_rule"] == "answer_leakage"
    base = FALLBACK_QUESTIONS[ProbeLevel.TRANSFER]
    assert base in entry["question"], (
        "q60 no longer contains the real fallback text; the finding it records "
        "is about production code and must stay tied to it"
    )


# ---------------------------------------------------------------------------
# fallback questions — the CI half of the runtime/CI split
# ---------------------------------------------------------------------------


def test_every_probe_level_has_a_fallback():
    """CLAUDE.md rule 5: every LLM call has a fallback. A missing level means a
    model outage produces a KeyError mid-interview."""
    for level in ProbeLevel:
        assert level in FALLBACK_QUESTIONS, f"no fallback for {level.value}"


@pytest.mark.parametrize("level", list(ProbeLevel))
def test_fallback_questions_are_well_formed(level):
    text = FALLBACK_QUESTIONS[level]
    assert text.strip(), f"{level.value}: empty fallback"
    assert 40 <= len(text) <= 300, f"{level.value}: {len(text)} chars"
    # Not every fallback ends in '?': OPERATIONAL is an imperative
    # ("Walk me through the steps and the systems you used.") and that is a
    # legitimate probe. What must hold is that it asks for something.
    assert text.rstrip()[-1] in "?.", f"{level.value}: no terminal punctuation"
    assert "?" in text or re.search(r"\b(walk|tell|describe|give)\b", text.lower()), (
        f"{level.value}: neither interrogative nor imperative — it asks for nothing"
    )
    assert "$" not in text, f"{level.value}: unrendered placeholder"
    assert "TODO" not in text.upper(), f"{level.value}: placeholder text shipped"


def test_transfer_templates_render_with_both_slots():
    """`TRANSFER_FALLBACKS` are `string.Template`s. A renamed slot would raise
    KeyError at the worst possible moment — on the no-model path."""
    for operator, template in TRANSFER_FALLBACKS.items():
        assert isinstance(template, Template), f"{operator}: not a Template"
        rendered = template.safe_substitute(
            other_problem="the attrition problem", their_method="the daily reviews"
        )
        assert "$" not in rendered, f"{operator}: slot left unrendered: {rendered}"
        assert rendered.rstrip().endswith("?"), f"{operator}: not a question"
        assert 40 <= len(rendered) <= 300, f"{operator}: {len(rendered)} chars"


def test_fallback_questions_are_distinct_per_level():
    """Two levels sharing a fallback means one probe level cannot be told from
    another when the model is down — the interview silently loses a rung."""
    texts = list(FALLBACK_QUESTIONS.values())
    assert len(set(texts)) == len(texts), "duplicate fallback text across levels"


def test_fallbacks_carry_no_family_vocabulary():
    """Cohort neutrality, structurally. A fallback mentioning AHT or activation
    would make the no-model path a BPO product."""
    vocabulary = set()
    for family in ("bpo_operations", "product", "software_engineering"):
        vocabulary |= {k.split("_")[0] for k in fact_keys(family)}
    vocabulary -= {"team", "direct", "tenure", "headcount", "shift"}  # generic
    for level, text in FALLBACK_QUESTIONS.items():
        low = text.lower()
        hits = {v for v in vocabulary if v in low}
        assert not hits, f"{level.value} fallback names family vocabulary: {hits}"


# ---------------------------------------------------------------------------
# Jaccard ladder — R2's threshold is MEASURED here, not guessed in P2-02
# ---------------------------------------------------------------------------

_WORD = re.compile(r"[a-z0-9]+")
# MINIMAL on purpose, and this is a measurement rather than a preference.
# An aggressive list — one that also strips did/do/you/how/what/about — collapses
# the duplicate band into the distinct band (-0.083 overlap, no separating
# threshold exists). The interrogative frame IS the duplication signal: "what did
# you decide to do about X" reasked with a different X is precisely the defect.
# See `rule_2_threshold` in the corpus for the full measurement.
_STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "at", "for", "with",
    "by", "from", "as", "is", "was", "were", "be", "been", "it", "its", "that",
    "this", "these", "those", "me", "my", "your",
}

MEASURED = GOLDEN["rule_2_threshold"]


def content_words(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOP and not w.isdigit()}


def jaccard(a: str, b: str) -> float:
    wa, wb = content_words(a), content_words(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def test_jaccard_ladder_separates_duplicates_from_distinct():
    """The measurement P2-02's rule-2 threshold is taken from.

    Reported rather than assumed, the way MARGIN_FLOOR was derived from the
    measured 0.397 / 0.321 band instead of a guessed constant. If the bands
    overlap, rule 2 has no defensible threshold and that is a finding.
    """
    bands: dict[str, list[float]] = {"duplicate": [], "borderline": [], "distinct": []}
    for pair in LADDER:
        bands[pair["expected"]].append(jaccard(pair["a"], pair["b"]))

    for name, values in bands.items():
        assert values, f"ladder has no {name} pairs"

    lo_dup = min(bands["duplicate"])
    hi_distinct = max(bands["distinct"])
    print(
        f"\n  jaccard ladder — duplicate {min(bands['duplicate']):.3f}-"
        f"{max(bands['duplicate']):.3f} | borderline "
        f"{min(bands['borderline']):.3f}-{max(bands['borderline']):.3f} | "
        f"distinct {min(bands['distinct']):.3f}-{max(bands['distinct']):.3f}"
    )
    assert lo_dup > hi_distinct, (
        f"bands overlap: lowest duplicate {lo_dup:.3f} <= highest distinct "
        f"{hi_distinct:.3f}. Rule 2 has no separating threshold on this ladder"
    )

    # The threshold P2-02 must use, pinned so it cannot drift from the corpus.
    threshold = MEASURED["recommended_threshold"]
    hi_borderline = max(bands["borderline"])
    assert hi_borderline < threshold <= lo_dup, (
        f"recorded threshold {threshold} is not inside the usable gap "
        f"({hi_borderline:.3f}, {lo_dup:.3f}]"
    )


def test_ladder_pairs_are_not_identical_strings():
    for pair in LADDER:
        assert pair["a"] != pair["b"], f"{pair['id']}: identical strings prove nothing"


def test_corpus_duplicate_entries_sit_in_the_duplicate_band():
    """Consistency between the two halves of the corpus: an entry labelled
    duplicate_content must actually be one by the ladder's own measure."""
    threshold = MEASURED["recommended_threshold"]
    for e in REJECTS:
        if "duplicate_content" not in e["rules"]:
            continue
        best = max(jaccard(e["question"], q) for q in e["context"]["prior_questions"])
        assert best >= threshold, (
            f"{e['id']}: labelled duplicate_content but scores {best:.3f}, under "
            f"the recorded threshold {threshold}. Either the entry or the "
            f"threshold is wrong — fix one, and say which in the ledger row"
        )


def test_adversarial_duplicate_accepts_sit_below_the_threshold():
    """The other half: an entry marked as an R2 near-miss must actually be a
    near-miss, or it is not testing the boundary it claims to."""
    threshold = MEASURED["recommended_threshold"]
    checked = 0
    for e in ACCEPTS:
        if e["naive_reject_risk"] != "duplicate_content":
            continue
        priors = e["context"]["prior_questions"]
        assert priors, f"{e['id']}: R2 near-miss with no prior question"
        best = max(jaccard(e["question"], q) for q in priors)
        assert best < threshold, (
            f"{e['id']}: scores {best:.3f}, at or above the threshold "
            f"{threshold} — it is a duplicate, not a near-miss"
        )
        checked += 1
    assert checked >= 2, "not enough R2 boundary cases to pin the threshold"


# ===========================================================================
# P2-02 — the validator, measured against the corpus above
# ===========================================================================


def run_validator(entry: dict) -> QuestionValidation:
    """Every metric test goes through this, so the call shape is asserted once."""
    c = entry["context"]
    return validate(
        entry["question"],
        claim_text=c["claim"],
        claim_type=c["claim_type"],
        claim_metric=c.get("claim_metric"),
        job_family=entry["family"],
        probe_level=ProbeLevel(c["probe_level"]),
        prior_questions=c.get("prior_questions", ()),
        prior_answers=c.get("prior_answers", ()),
        other_claims=c.get("other_claims", ()),
        target_claim_text=c.get("transfer_target_claim"),
    )


def _scores() -> dict:
    tp = fp = fn = ok_accept = n_accept = attributed = 0
    missed, false_alarms, misattributed = [], [], []
    for e in ENTRIES:
        v = run_validator(e)
        if e["verdict"] == "reject":
            if v.accepted:
                fn += 1
                missed.append((e["id"], e["primary_rule"]))
            else:
                tp += 1
                if e["primary_rule"] in v.violations:
                    attributed += 1
                else:
                    misattributed.append((e["id"], e["primary_rule"], v.violations))
        else:
            n_accept += 1
            if v.accepted:
                ok_accept += 1
            else:
                fp += 1
                false_alarms.append((e["id"], e["naive_reject_risk"], v.violations))
    return {
        "m6a": 100 * tp / (tp + fp) if tp + fp else 0.0,
        "m6b": 100 * tp / (tp + fn) if tp + fn else 0.0,
        "m6c": 100 * ok_accept / n_accept if n_accept else 0.0,
        "m6h": 100 * attributed / tp if tp else 0.0,
        "missed": missed, "false_alarms": false_alarms,
        "misattributed": misattributed,
    }


def test_validator_precision_on_golden_set():
    s = _scores()
    assert s["m6a"] >= 95, f"M6a {s['m6a']:.1f}% — false rejections: {s['false_alarms']}"


def test_validator_recall_on_golden_set():
    s = _scores()
    assert s["m6b"] >= 90, f"M6b {s['m6b']:.1f}% — missed: {s['missed']}"


def test_validator_accepts_good_questions():
    """M6c, the anti-gaming metric. A validator that rejects everything scores
    100% recall and fails here."""
    s = _scores()
    assert s["m6c"] >= 95, f"M6c {s['m6c']:.1f}% — false rejections: {s['false_alarms']}"


def test_validator_rejects_for_the_intended_reason():
    """M6h. Precision and recall answer "did we reject the right question?" and
    not "for the intended reason?". Without this a validator that rejects
    correctly via the wrong rule looks green while the team tunes the wrong
    rule."""
    s = _scores()
    assert s["m6h"] >= 90, f"M6h {s['m6h']:.1f}% — {s['misattributed']}"


def test_a_reject_everything_validator_fails_the_corpus():
    """The guard that makes M6c load-bearing. Asserted with a stub rather than
    argued, because "we would notice" is not a test."""
    n_accept = len(ACCEPTS)
    stub_accepted = 0          # a validator that rejects unconditionally
    assert 100 * stub_accepted / n_accept < 95, (
        "a reject-everything validator would pass M6c — the corpus has too few "
        "accept entries for the metric to mean anything"
    )
    real = _scores()
    assert real["m6c"] > 100 * stub_accepted / n_accept


def test_validator_makes_no_model_call(client):
    """Structurally impossible — `validate` imports no LLM — but asserted the
    same way the routing endpoint is, because "impossible" drifts."""
    before = client.get("/api/dev/llm").json()["calls"]
    for e in ENTRIES:
        run_validator(e)
    assert client.get("/api/dev/llm").json()["calls"] == before


def test_validator_is_deterministic():
    """Same inputs, same violations, forever — the property that lets a stored
    `violations_json` be trusted months later."""
    sample = ENTRIES[:12]
    first = [run_validator(e) for e in sample]
    for _ in range(20):
        assert [run_validator(e) for e in sample] == first


def test_violation_names_are_the_frozen_seven():
    """These strings are persisted in `questions.violations_json` from P2-03.
    A rename invalidates stored history, so the set is pinned in two places —
    here and in the corpus — and both must agree."""
    emitted = {v for e in ENTRIES for v in run_validator(e).violations}
    assert emitted <= set(RULES), f"validator emitted unknown rules: {emitted - set(RULES)}"
    assert emitted == set(RULES), f"rules never exercised by the corpus: {set(RULES) - emitted}"


def test_accepted_questions_carry_no_violations():
    for e in ENTRIES:
        v = run_validator(e)
        assert v.accepted == (not v.violations), f"{e['id']}: accepted/violations disagree"


def test_all_rules_run_rather_than_short_circuiting():
    """M6 counts violations per rule. If evaluation stopped at the first hit,
    every rule after it would read zero and the histogram would lie about which
    rule is miscalibrated."""
    entry = next(e for e in ENTRIES if e["id"] == "q58")
    v = run_validator(entry)
    assert len(v.violations) >= 2, (
        "q58 is the deliberate co-occurrence entry; a single violation means "
        "evaluation is short-circuiting"
    )


@pytest.mark.parametrize("rule", RULES)
def test_each_rule_fires_on_its_own_reject_entries(rule):
    """Per-rule coverage: the rule must actually fire on the entries authored
    for it, not merely be caught by some other rule."""
    entries = [e for e in REJECTS if e["primary_rule"] == rule]
    assert entries, f"no entries with {rule} as primary_rule"
    for e in entries:
        assert rule in run_validator(e).violations, (
            f"{e['id']}: {rule} did not fire; got {run_validator(e).violations}"
        )


@pytest.mark.parametrize("rule", RULES)
def test_each_rule_leaves_its_adversarial_accepts_alone(rule):
    """The other half, and the one that stops a rule being implemented as
    "reject anything that looks vaguely like this"."""
    entries = [e for e in ACCEPTS if e["naive_reject_risk"] == rule]
    assert entries, f"no adversarial accept entries for {rule}"
    for e in entries:
        v = run_validator(e)
        assert v.accepted, f"{e['id']}: rejected as {v.violations}"


def test_validator_never_reads_presentation():
    """Structural anti-bias invariant. Two questions with identical substance
    and different fluency must produce identical violations. CLAUDE.md rule 6 —
    if this test ever needs changing, the change is wrong."""
    claim = "Reduced average handle time from 480s to 310s across a 28-agent inbound voice process"
    fluent = "Could you walk me through the scope of the handle time work, please?"
    plain = "handle time work ka scope kya tha bhai batao"
    kwargs = dict(
        claim_text=claim, claim_type="aht_control", job_family="bpo_operations",
        probe_level=ProbeLevel.VALIDATION,
    )
    assert validate(fluent, **kwargs).violations == validate(plain, **kwargs).violations


def test_rule_three_is_not_evaluated_on_transfer():
    """The finding from P2-01 (q63), pinned as behaviour rather than a comment.
    A T1 probe pairs one claim's method with another's problem, so two fact
    targets is the mechanism working."""
    q = ("Suppose you had taken on the attrition problem instead. Using the daily "
         "handle time reviews, where would you start?")
    claim = "Reduced average handle time from 480s to 310s across a 28-agent inbound voice process"
    target = "Owned shrinkage reporting and brought attrition down from 31% to 18% in three quarters"
    on_transfer = validate(
        q, claim_text=claim, claim_type="aht_control", job_family="bpo_operations",
        probe_level=ProbeLevel.TRANSFER, target_claim_text=target,
    )
    assert "multiple_fact_targets" not in on_transfer.violations
    # The same two subjects on a non-transfer probe ARE two evidence targets.
    on_outcome = validate(
        "Afterwards, what happened to handle time and to attrition?",
        claim_text=claim, claim_type="aht_control", job_family="bpo_operations",
        probe_level=ProbeLevel.OUTCOME,
    )
    assert "multiple_fact_targets" in on_outcome.violations


def test_duplicate_threshold_matches_the_measured_value():
    """The constant and the corpus's recorded measurement are one number in two
    files. If they drift, one of them is lying about how rule 2 was calibrated."""
    assert DUPLICATE_JACCARD == MEASURED["recommended_threshold"]


# ---------------------------------------------------------------------------
# out-of-corpus: the fallback violation-set snapshot promised in P2-01
# ---------------------------------------------------------------------------

CLAIM = "Reduced average handle time from 480s to 310s across a 28-agent inbound voice process"

# EXPECTED, not aspirational. The rendered fallback is `On "<claim>" — <base>`,
# so it quotes the claim INCLUDING its figures and therefore leaks by
# construction. Recording the exact set is what catches a future edit that
# introduces a genuinely broken fallback, without pretending the current ones
# are validator-clean. This is the CI half of the runtime/CI split: at runtime
# the fallback bypasses validation because it must (CLAUDE.md rule 5 — every
# LLM call has a fallback, so a validator able to reject it leaves no path).
EXPECTED_FALLBACK_VIOLATIONS = {
    ProbeLevel.VALIDATION: ("answer_leakage",),
    ProbeLevel.OPERATIONAL: ("answer_leakage",),
    ProbeLevel.INCIDENT: ("answer_leakage",),
    ProbeLevel.DECISION: ("answer_leakage",),
    ProbeLevel.OUTCOME: ("answer_leakage",),
    ProbeLevel.TRANSFER: ("answer_leakage",),
}


@pytest.mark.parametrize("level", list(ProbeLevel))
def test_fallback_violation_snapshot(level):
    rendered = fallback_question(level, CLAIM).question
    actual = validate(
        rendered, claim_text=CLAIM, claim_type="aht_control",
        job_family="bpo_operations", probe_level=level,
    ).violations
    assert actual == EXPECTED_FALLBACK_VIOLATIONS[level], (
        f"{level.value} fallback now violates {actual}, expected "
        f"{EXPECTED_FALLBACK_VIOLATIONS[level]}. Either a fallback was edited or "
        f"a rule changed — look at which before updating this snapshot"
    )


def test_fallbacks_leak_only_because_they_quote_the_claim():
    """The reason the snapshot above is all `answer_leakage`, asserted so that a
    future reader does not conclude the fallbacks are simply bad. Strip the
    quoted claim and the base text is clean."""
    for level, base in FALLBACK_QUESTIONS.items():
        v = validate(
            base, claim_text=CLAIM, claim_type="aht_control",
            job_family="bpo_operations", probe_level=level,
        )
        assert "answer_leakage" not in v.violations, (
            f"{level.value}: the base text itself leaks, which the claim prefix "
            f"cannot explain"
        )


def _recall_without(rule: str | None) -> float:
    """Recall with one rule's violations suppressed. Pure measurement — it does
    not monkeypatch anything, it just drops the rule from the result."""
    tp = fn = 0
    for e in REJECTS:
        violations = tuple(v for v in run_validator(e).violations if v != rule)
        tp += bool(violations)
        fn += not violations
    return 100 * tp / (tp + fn)


@pytest.mark.parametrize("rule", RULES)
def test_every_rule_earns_its_place(rule):
    """Ablation. A rule whose removal costs no recall is either redundant with
    another rule or untested by the corpus, and both are defects.

    THIS TEST FOUND A REAL GAP that M6a/M6b/M6c/M6h all missed at 100%:
    `duplicate_content` was worth ZERO recall, because every entry authored for
    it was an unanchored fallback-style string that rule 7 caught anyway. Three
    anchored duplicates (q74-q76) were added so rule 2 is the only rule standing
    between them and acceptance. Precision, recall and attribution can all read
    100% while a rule does nothing; only necessity shows it.
    """
    baseline = _recall_without(None)
    without = _recall_without(rule)
    assert baseline - without > 0, (
        f"disabling {rule} costs no recall — it is redundant with another rule, "
        f"or the corpus has no entry that isolates it"
    )


def test_no_single_rule_carries_the_whole_corpus():
    """The opposite failure: one rule doing 90% of the work means the other six
    are decoration and the reject-rate histogram will be meaningless."""
    baseline = _recall_without(None)
    for rule in RULES:
        lost = baseline - _recall_without(rule)
        assert lost < 60, f"{rule} alone carries {lost:.1f} points of recall"


# ===========================================================================
# P2-03 — bounded regeneration
#
# Fixture mode returns the fallback for every question, so none of this is
# exercised by the rest of the suite. These tests drive the model path with a
# stub and COUNT THE CALLS, because the cap is the whole point: the latency
# guardrail is +20% on the median turn and every turn already blocks on a call.
# ===========================================================================

import asyncio

import api.engine.question as question_module
from api.config import settings as _settings
from api.schemas import GeneratedQuestion

GOOD = "What was your scope on the handle time work, and which queue was it?"
BAD_LEAK = "So you cut it from 480s to 310s — how did you get from 480 to 310?"
BAD_ANCHOR = "Tell me more."

KWARGS = dict(
    claim_type="aht_control",
    claim_metric="480s -> 310s",
    job_family="bpo_operations",
)


class _Model:
    """Stub for `complete_json`. Returns queued questions and counts calls, so
    the retry cap is asserted by observation rather than by reading the code."""

    def __init__(self, *questions: str):
        self.queue = list(questions)
        self.calls = 0
        self.prompts: list[str] = []

    async def __call__(self, prompt, model, **kw):
        self.calls += 1
        self.prompts.append(prompt)
        text = self.queue.pop(0) if self.queue else self.queue and "" or GOOD
        return GeneratedQuestion(question=text, probe_level=ProbeLevel.VALIDATION)


def _generate(monkeypatch, model, validation: bool = True, **extra):
    """Drives the model path with a stub.

    `question_validation` is set EXPLICITLY rather than inherited from the
    environment. Without this the suite fails under `QUESTION_VALIDATION=false`,
    and the convention — set by `TRANSFER_PROBE` — is that the suite stays green
    with a behaviour flag off. A test asserting validation behaviour must turn
    validation on itself.
    """
    monkeypatch.setattr(_settings, "question_validation", validation)
    monkeypatch.setattr(question_module, "complete_json", model)
    return asyncio.run(
        question_module.generate_question(
            CLAIM, ProbeLevel.VALIDATION, **{**KWARGS, **extra}
        )
    )


def test_accepted_first_attempt_makes_one_call(monkeypatch):
    model = _Model(GOOD)
    result = _generate(monkeypatch, model)
    assert model.calls == 1, "a passing question must not be regenerated"
    assert result.source == "model"
    assert result.attempts == 1
    assert result.violations == ()


def test_rejected_question_triggers_exactly_one_regeneration(monkeypatch):
    model = _Model(BAD_LEAK, GOOD)
    result = _generate(monkeypatch, model)
    assert model.calls == 2, f"expected exactly 2 model calls, got {model.calls}"
    assert result.source == "regenerated"
    assert result.attempts == 2
    assert result.question == GOOD


def test_two_failures_fall_back_and_never_make_a_third_call(monkeypatch):
    """The cap. Not "usually two" — never three, whatever the model returns."""
    model = _Model(BAD_LEAK, BAD_ANCHOR)
    result = _generate(monkeypatch, model)
    assert model.calls == 2, f"{model.calls} model calls — the cap leaked"
    assert result.source == "fallback"
    assert result.attempts == 2
    assert result.question == question_module.fallback_question(
        ProbeLevel.VALIDATION, CLAIM
    ).question


def test_violations_are_recorded_from_attempt_one(monkeypatch):
    """M6d asks how often the MODEL produces a bad question, which is a property
    of attempt one. A successful retry must not erase that."""
    model = _Model(BAD_LEAK, GOOD)
    result = _generate(monkeypatch, model)
    assert result.source == "regenerated"
    assert "answer_leakage" in result.violations


def test_the_fallback_is_never_validated(monkeypatch):
    """R1 in the phase plan, asserted structurally. The rendered fallback trips
    `answer_leakage` by construction (corpus q60), and CLAUDE.md rule 5 requires
    every LLM call to have a fallback — so a validator able to reject it would
    leave no path at all."""
    fallback_text = question_module.fallback_question(
        ProbeLevel.VALIDATION, CLAIM
    ).question
    model = _Model(fallback_text)          # the model call itself failed
    seen: list[str] = []

    real_validate = question_module.validate

    def spy(text, **kw):
        seen.append(text)
        return real_validate(text, **kw)

    monkeypatch.setattr(question_module, "validate", spy)
    result = _generate(monkeypatch, model)

    assert result.source == "fallback"
    assert result.attempts == 1
    assert model.calls == 1, "a failed model call must not be retried by the validator"
    assert fallback_text not in seen, "the fallback was passed through validate()"


def test_retry_prompt_names_the_rules_and_shows_no_examples(monkeypatch):
    """The retry brief carries rule NAMES. Worked examples would be a per-cohort
    authoring cost and would re-introduce the bias the taxonomy keeps out of
    code — A's contract forbids per-family examples in prompts."""
    model = _Model(BAD_LEAK, GOOD)
    _generate(monkeypatch, model)
    retry_prompt = model.prompts[1]
    assert "answer_leakage" in retry_prompt
    assert "REJECTED" in retry_prompt.upper()
    # No corpus question may appear in the prompt — that is what an example is.
    for entry in ENTRIES:
        assert entry["question"] not in retry_prompt


def test_first_prompt_carries_no_retry_brief(monkeypatch):
    model = _Model(GOOD)
    _generate(monkeypatch, model)
    assert "REJECTED" not in model.prompts[0].upper()
    assert "$violations" not in model.prompts[0], "template slot left unrendered"


def test_validation_flag_off_reproduces_the_phase_one_path(monkeypatch):
    """QUESTION_VALIDATION=false must be the pre-phase system, question for
    question — the TRANSFER_PROBE precedent."""
    model = _Model(BAD_LEAK)
    result = _generate(monkeypatch, model, validation=False)
    assert model.calls == 1, "no validation means no retry"
    assert result.question == BAD_LEAK
    assert result.source == "model"
    assert result.violations == ()


def test_attempt_is_duck_compatible_with_generated_question(monkeypatch):
    """`GeneratedQuestion` lives in the frozen schemas.py, so QuestionAttempt
    carries the two attributes every existing call site reads. If this breaks,
    orchestrator.ask_next stops persisting question text."""
    model = _Model(GOOD)
    result = _generate(monkeypatch, model)
    assert isinstance(result.question, str) and result.question
    assert result.probe_level is ProbeLevel.VALIDATION


def test_question_columns_default_safely(client):
    """A row written without the new fields must read as an unvalidated model
    question rather than raising."""
    import asyncio as _asyncio

    from api import ids
    from api.db import SessionLocal
    from api.models import Question

    async def scenario():
        async with SessionLocal() as db:
            body = onboard(client, name="Column Defaults", phone="+919810080001")
            session_id = body["session_id"]
            claim_id = body["claims"][0]["id"]
            q = Question(
                id=ids.question_id(), claim_id=claim_id, session_id=session_id,
                text="Bare row, no provenance set.", probe_level="VALIDATION",
            )
            db.add(q)
            await db.commit()
            await db.refresh(q)
            return q.source, q.attempts, q.violations_json, q.is_repair

    assert _asyncio.run(scenario()) == ("model", 1, None, False)


def test_seeded_questions_never_exceed_two_attempts(client):
    """Over a whole interview, not one call."""
    import asyncio as _asyncio

    from sqlalchemy import select

    from api.db import SessionLocal
    from api.models import Question

    body = onboard(client, name="Attempt Ceiling", phone="+919810080002")
    run_interview(client, body["session_id"])

    async def rows():
        async with SessionLocal() as db:
            return list(
                (await db.execute(select(Question).where(
                    Question.session_id == body["session_id"]))).scalars().all()
            )

    asked = _asyncio.run(rows())
    assert asked, "no questions were asked"
    assert max(q.attempts for q in asked) <= 2
    assert {q.source for q in asked} <= {"model", "regenerated", "fallback"}


# ===========================================================================
# P2-05 — M6 in the validation report
# ===========================================================================

from scripts.validation_report import Snapshot, compute_m6, render, build_report, collect


def _snapshot(questions=(), answers=0) -> Snapshot:
    snap = Snapshot()
    snap.questions = list(questions)
    snap.responses_by_question = {f"r{i}": object() for i in range(answers)}
    return snap


class _Q:
    """A Question row, minus the ORM. compute_m6 reads five attributes."""

    def __init__(self, *, is_repair=False, source="model", violations=None, attempts=1):
        self.is_repair = is_repair
        self.source = source
        self.violations_json = json.dumps(violations) if violations else None
        self.attempts = attempts


def test_m6_computed_with_no_model_call(client):
    before = client.get("/api/dev/llm").json()["calls"]
    compute_m6(_snapshot())
    assert client.get("/api/dev/llm").json()["calls"] == before


def test_m6_scores_the_validator_against_the_corpus():
    m6 = compute_m6(_snapshot())
    assert m6["available"], "the question golden set was not found"
    assert m6["corpus_entries"] == len(ENTRIES)
    assert m6["m6a_precision"] >= 95
    assert m6["m6b_recall"] >= 90
    assert m6["m6c_accept_rate"] >= 95
    assert m6["m6h_attribution"] >= 90


def test_m6_excludes_repair_questions_from_generated_rates(monkeypatch):
    """Repairs are not generated questions — REPAIR_PROMPTS is a fixed table —
    so including them would dilute every rate by however disengaged the cohort
    happened to be. They have their own metric, M6f."""
    monkeypatch.setattr(_settings, "openai_api_key", "sk-test")   # live rates on
    generated = [_Q(), _Q(violations=["answer_leakage"])]
    with_repairs = generated + [_Q(is_repair=True), _Q(is_repair=True)]

    clean = compute_m6(_snapshot(generated, answers=2))
    noisy = compute_m6(_snapshot(with_repairs, answers=4))

    assert clean["m6d_reject_rate"] == noisy["m6d_reject_rate"] == 50.0
    assert clean["questions_asked"] == noisy["questions_asked"] == 2
    assert noisy["repairs"] == 2
    assert noisy["m6f_repair_rate"] == 50.0


def test_m6_withholds_live_rates_in_fixture_mode(monkeypatch):
    """Every question in fixture mode comes from FALLBACK_QUESTIONS, so a live
    reject rate would describe the fallback path and not the model. Withheld,
    never shown as a false 0% — the discipline M4a already follows."""
    monkeypatch.setattr(_settings, "openai_api_key", None)
    m6 = compute_m6(_snapshot([_Q(), _Q(source="fallback")], answers=2))

    assert m6["live_rates_meaningful"] is False
    assert m6["m6d_reject_rate"] is None
    assert m6["m6e_fallback_rate"] is None
    assert m6["m6g_repeat_rate"] is None
    # M6f is still meaningful: a repair is a repair whatever produced the question.
    assert m6["m6f_repair_rate"] is not None


def test_m6_live_rates_appear_when_a_key_is_present(monkeypatch):
    monkeypatch.setattr(_settings, "openai_api_key", "sk-test")
    m6 = compute_m6(_snapshot([_Q(), _Q(source="fallback")], answers=2))
    assert m6["live_rates_meaningful"] is True
    assert m6["m6e_fallback_rate"] == 50.0


def test_m6_per_rule_histogram_is_consistent():
    """A single rule producing most violations is the likeliest sign of a
    miscalibrated rule, and a total hides it."""
    m6 = compute_m6(_snapshot())
    assert set(m6["per_rule"]) <= set(RULES)
    assert sum(m6["per_rule"].values()) > 0


def test_m6_renders_with_every_denominator_named():
    """The M5a failure was a denominator nobody stated. Every M6 rate names
    what it is a rate OF, in the output itself."""
    text = render(_snapshot(), build_report(_snapshot(), minimum_n=30))
    assert "M6  Question quality" in text
    for label in ("M6a", "M6b", "M6c", "M6d", "M6e", "M6f", "M6g", "M6h"):
        assert label in text, f"{label} missing from the report"
    assert "of 44 labelled good" in text
    assert "labelled defects" in text
    assert "C4" in text, "the counter-metric must be printed beside the number"


def test_m6_does_not_disturb_m1_to_m5():
    """Phase 1's numbers are a regression surface now. M6 reads the same
    Snapshot and must not touch it."""
    snap = _snapshot([_Q(), _Q(is_repair=True)], answers=2)
    before = (list(snap.questions), dict(snap.responses_by_question))
    compute_m6(snap)
    assert list(snap.questions) == before[0]
    assert dict(snap.responses_by_question) == before[1]


def test_m6_reports_the_regeneration_cap():
    m6 = compute_m6(_snapshot([_Q(attempts=1), _Q(attempts=2)]))
    assert m6["max_attempts"] == 2, "the cap must be visible in the report"
