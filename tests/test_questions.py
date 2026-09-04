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

from api.engine.question import FALLBACK_QUESTIONS, TRANSFER_FALLBACKS
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
