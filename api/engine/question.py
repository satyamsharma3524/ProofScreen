"""
ARTIFACT 3 — question generation.  LLM call #2.

The POLICY decides which claim and which probe level (engine/orchestrator.py).
The model only chooses the wording. If it is slow, down or off, the
hand-written fallback for that level is used and the candidate notices nothing.

Every fallback is anchored to the claim text, because a candidate reading
"Tell me about a specific time this went wrong" on WhatsApp has no idea which
of their three resume lines "this" refers to.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from enum import Enum
from string import Template
from typing import NamedTuple, Sequence

from pydantic import BaseModel

from api.config import settings
from api.llm import complete_json, load_prompt
from api.schemas import Dimension, GeneratedQuestion, ProbeLevel
from api.taxonomy import claim_type_label, fact_keys, family_label

log = logging.getLogger("proofscreen.question")

_WS = re.compile(r"\s+")


# ---------------------------------------------------------------------------
# the planner -> wording contract for a TRANSFER probe
#
# `select_transfer()` lives in engine/orchestrator.py, beside the rest of the
# policy — Python decides WHAT to ask. Its output type lives HERE, next to the
# wording that consumes it, because orchestrator imports question and never the
# other way round; defining it there would be an import cycle, and defining it
# in schemas.py would touch the frozen file a second time.
#
# Note what the spec does NOT carry: a job family. A transfer question is built
# from the candidate's own words, so the mechanism costs nothing per cohort.
# ---------------------------------------------------------------------------


class TransferOperator(str, Enum):
    """The perturbation applied to the candidate's own reasoning. T2, T4 and T5
    are designed in docs/TRANSFER_DESIGN_AUDIT.md §3 and deliberately not built."""

    T1 = "T1"      # substitute the problem: their method, their OTHER claim
    T3 = "T3"      # invert the outcome: the number moved against them


@dataclass(frozen=True)
class TransferSpec:
    """Every slot is the candidate's own language, lifted from stored signals.

    `basis` is why this operator and target were chosen. It is for the log and
    the dashboard, never for the prompt — the model does not need to know how
    the planner decided.
    """

    operator: TransferOperator
    their_method: str
    other_problem: str = ""
    target_claim_id: str | None = None
    basis: str = ""


# What each probe level is for, injected into the prompt so the model asks at
# the right depth instead of rephrasing the same question five times.
PROBE_BRIEFS: dict[ProbeLevel, str] = {
    ProbeLevel.VALIDATION: (
        "VALIDATION — establish that they actually held this scope. Ask for the "
        "shape of it: how many, how long, who else was involved, what the "
        "numbers were. This is the opening question about this claim."
    ),
    ProbeLevel.OPERATIONAL: (
        "OPERATIONAL — find out how the work ran day to day. Ask for the "
        "mechanics: the steps, the cadence, the systems they worked in, what "
        "they looked at each morning."
    ),
    ProbeLevel.INCIDENT: (
        "INCIDENT — get one specific episode. Ask about a particular time it "
        "went wrong, or the hardest week. Real practitioners produce concrete "
        "detail here; people who did not do the work produce generalities."
    ),
    ProbeLevel.DECISION: (
        "DECISION — find the judgement they exercised. Ask what they decided, "
        "what they considered and rejected, and why they chose as they did."
    ),
    ProbeLevel.OUTCOME: (
        "OUTCOME — close the loop. Ask what happened afterwards, how they knew "
        "it worked, which number moved, and what they would do differently."
    ),
    ProbeLevel.TRANSFER: (
        "TRANSFER — pose a problem the candidate has NOT solved and ask them to "
        "reason about it with the method they already described. A memorised "
        "resume can be recited; it cannot be transferred. This is the one probe "
        "level where a hypothetical is the point.\n"
        "Ask only for the reasoning: where they would start, what they would "
        "look at, what would rule a cause out. Do NOT ask for numbers, tools or "
        "results — this did not happen, so there are none, and asking invites "
        "invention."
    ),
}

# The concrete substitution, appended to the TRANSFER brief once the planner
# has chosen an operator. One template per operator; the only domain content in
# either is the candidate's own words.
TRANSFER_INSTRUCTIONS: dict[TransferOperator, Template] = {
    TransferOperator.T1: Template(
        "Hold their method constant and swap the subject.\n"
        "  Their method: $their_method\n"
        "  What to swap in, taken from another claim on their own resume: "
        "$other_problem\n"
        "Ask how they would approach the second subject using the first "
        "method. Do not tell them how the second one actually turned out — "
        "they claimed it elsewhere, and the point is the reasoning they would "
        "apply, not the result they already reported."
    ),
    TransferOperator.T3: Template(
        "Invert the outcome they reported.\n"
        "  What they did: $their_method\n"
        "Ask them to reason about the same action having moved the number "
        "against them instead of for them: first hypothesis, and what would "
        "rule it out."
    ),
}

FALLBACK_QUESTIONS: dict[ProbeLevel, str] = {
    ProbeLevel.VALIDATION: (
        "Tell me more about this — what exactly was your scope, and what were "
        "the numbers?"
    ),
    ProbeLevel.OPERATIONAL: (
        "How did this work day to day? Walk me through the steps and the "
        "systems you used."
    ),
    ProbeLevel.INCIDENT: (
        "Tell me about one specific time this went wrong. What happened that "
        "week?"
    ),
    ProbeLevel.DECISION: (
        "What did you decide to do about it, and what did you consider but "
        "decide against?"
    ),
    ProbeLevel.OUTCOME: (
        "What happened afterwards? How did you know it worked, and which "
        "number moved?"
    ),
    # Used only when the planner could not build a spec. Still poses a
    # situation the candidate has not described — the inversion needs nothing
    # but the claim it is anchored to.
    ProbeLevel.TRANSFER: (
        "Suppose that had moved the number the wrong way instead. What would "
        "you check first, and what would rule a cause out?"
    ),
}

# The offline transfer question. A template rather than a fixed sentence,
# because the substance has to come from the candidate's own claims — a
# hand-written scenario would be a per-cohort authoring cost, which is the
# failure mode docs/TRANSFER_DESIGN_AUDIT.md §5 exists to prevent.
TRANSFER_FALLBACKS: dict[TransferOperator, Template] = {
    # "taken on", not "solved" or "moved": the slot holds another claim's
    # subject, which may be a metric, a system or a team, and the wording has
    # to fit all three without knowing which it got.
    TransferOperator.T1: Template(
        "Suppose you had taken on $other_problem instead. Using "
        "$their_method, where would you start?"
    ),
    TransferOperator.T3: Template(
        "Suppose $their_method had made things worse instead of better. "
        "What is your first hypothesis, and what would rule it out?"
    ),
}

# When the policy wants a specific dimension covered, nudge the wording.
GAP_HINTS: dict[Dimension, str] = {
    Dimension.SPECIFICITY: (
        "The answers so far have been short on concrete figures. Word the "
        "question so a number, a headcount or a timeframe is the natural answer."
    ),
    Dimension.PROCESS: (
        "The answers so far have not described how the work actually ran. Word "
        "the question so the natural answer is a sequence of steps."
    ),
    Dimension.METRIC_OWNERSHIP: (
        "The candidate has named metrics without defining them. Word the "
        "question so they have to say how the metric was captured or calculated "
        "in their own operation — not as a definition quiz."
    ),
    Dimension.CAUSAL_REASONING: (
        "The answers so far state outcomes without causes. Word the question so "
        "the natural answer connects a cause, an action and a result."
    ),
    Dimension.AUTHENTICITY: (
        "The answers so far have been general. Word the question so only a "
        "specific remembered episode can answer it."
    ),
    Dimension.TOOL_FAMILIARITY: (
        "The candidate has named tools without describing use. Word the question "
        "so they have to say what they actually did inside the system."
    ),
}


# ---------------------------------------------------------------------------
# P2-02 — question validation
#
# The same pattern as `evidence.enforce_verbatim()`: the model produces, Python
# decides whether to accept it. NO LLM CALL IN THIS SECTION, ever — a validator
# that asked a model whether a question was good would make question quality the
# model's opinion, which is the thing rule 1 of CLAUDE.md exists to prevent.
#
# Seven rules. Each names ONE defect: two rules firing on the same defect would
# corrupt the per-rule reject counts that M6 is computed from.
#
# The corpus at tests/data/question_golden.json was authored BEFORE this code
# and is what these thresholds are measured against.
# ---------------------------------------------------------------------------


class QuestionAttempt(NamedTuple):
    """What `generate_question()` produced, and how it got there.

    `GeneratedQuestion` lives in the frozen `api/schemas.py` and stays the LLM's
    RESPONSE model; this is the function's return type, so the validation
    outcome can reach the `questions` row without touching that file. It carries
    `question` and `probe_level` under the same names, so the existing call
    sites keep working unchanged.

    `source` and `violations` are persisted (`questions.source`,
    `questions.violations_json`) and counted in M6, so their string values are
    stable vocabulary, not display text.
    """

    question: str
    probe_level: ProbeLevel
    source: str                       # "model" | "regenerated" | "fallback"
    attempts: int                     # 1 or 2, never higher
    violations: tuple[str, ...]       # what attempt 1 tripped, for M6d
    # Forensic provenance. Defaulted so every existing positional construction
    # above keeps working untouched; `move` is what the second attempt CHANGED.
    move: str = ""
    target_signal: str = ""
    reasoning: str = ""


class QuestionValidation(NamedTuple):
    """Why a generated question was accepted or rejected.

    A NamedTuple here rather than in `api/schemas.py`, which is frozen — the
    same call `FamilyMatch` made in P1-06. `violations` names are STABLE
    STRINGS: from P2-03 they are persisted in `questions.violations_json` and
    counted per-rule in M6, so renaming one invalidates stored history.
    """

    accepted: bool
    violations: tuple[str, ...]


# Rule 2 only. MEASURED over the authored ladder in the corpus, and the
# measurement inverted the obvious choice: an aggressive stopword list — one
# that also strips did/do/you/how/what/about — collapses the duplicate band into
# the distinct band (-0.083 overlap, no separating threshold exists at all).
# The interrogative FRAME is the duplication signal: "what did you decide to do
# about X" reasked with a different X is precisely the defect. A minimal list
# separates at +0.169 (distinct <= 0.231, duplicate >= 0.400).
_STOP_PHRASING = frozenset(
    "the a an and or of to in on at for with by from as is was were be been it "
    "its that this these those me my your".split()
)

# Rules 6 and 7 use a BROADER list, and the difference is semantic rather than a
# fudge. Rule 2 asks "is this the same question rephrased", where the frame is
# the evidence. Rules 6 and 7 ask "does this name the right subject", where the
# frame is noise — a question sharing only "did" and "you" with a claim has not
# named anything.
_STOP_SUBJECT = _STOP_PHRASING | frozenset(
    "what how why who when where which do does did you yours i we our us they "
    "them but so if then than about into out up down over there here more most "
    "much many other another some any all each been have has had can could "
    "would should will shall may might must not no nor own same such only just "
    "very get got make made take took give gave go went come came look looked "
    "tell told say said work worked run ran use used".split()
)

# Duplicate threshold, measured. Midpoint of the usable gap between the highest
# BORDERLINE pair (0.333) and the lowest duplicate pair (0.400).
# D7 — the question policy, versioned. Stamped on every evaluation.
#
# `qpol_2` is the Phase 2 shape — `planner -> model -> validate -> one
# regeneration -> fallback` — which changes which questions a candidate is
# actually asked and therefore what evidence exists to score.
#
# READ THIS BEFORE COMPARING TWO EVALUATIONS. The constant was introduced in
# P4-D7, which lands AFTER commit 761959e ("P4A: two validator changes"). So
# `qpol_2` denotes the validator INCLUDING those two rule refinements, not the
# Phase 2 exit validator. Nothing was stamped before the constant existed, so
# nothing is mislabelled — but do not read `qpol_2` as "unchanged since Phase 2
# exit". The next behavioural change to `validate()` is `qpol_3`.
#
# `qpol_3` is the FORENSIC shape: `planner -> claim anatomy + evidence ledger ->
# move-specific prompt -> validate -> RE-TARGET (a different move, not a reworded
# draft) -> anatomy-built fallback`. It changes which questions a candidate is
# asked more completely than any previous bump, so evaluations either side of it
# are not comparable question-for-question. `validate()` itself is byte-identical
# to qpol_2 — what changed is everything that decides what reaches it.
#
# BUMP IT WHEN A RULE'S BEHAVIOUR CHANGES. Not for a comment, not for a
# refactor. And it is NOT an invitation to tune `DUPLICATE_JACCARD` below
# during Phase 3's study — that is counter-metric C7, the one move that makes
# a study worthless while making it look successful.
QUESTION_POLICY_VERSION = "qpol_3"

DUPLICATE_JACCARD = 0.37

# `agar` is Hindi for "if" and is how a code-switched conditional is actually
# posed on WhatsApp. Including it is completing an existing rule's marker list
# for the language this product operates in — NOT a judgement about register,
# which no rule here may make. Found by the golden set: q73 ("Agar activation
# gir jaata to aap kya karte?") is a textbook hypothetical and an English-only
# pattern list missed it entirely.
_HYPOTHETICAL = re.compile(
    r"(?<!\w)(suppose|imagine|hypothetically|what would you|"
    r"if you were|if you had to|had you been|agar)(?!\w)",
    re.IGNORECASE,
)
# PHASE 4A, from Phase 3 finding 3. A run of digits is a FIGURE only when a
# letter does not run straight into it. Without the lookbehind, `P1` yields 1 and
# `p95` yields 95, so `answer_leakage` blocked a question for "leaking" a
# severity label the claim also used — measured on the study's r0023 and r0067,
# and `p95` was already being stripped as a modifier in `_LABEL_MODIFIERS` two
# screens down, so the file disagreed with itself.
#
# The boundary is on the LEFT ONLY. `480s`, `900ms`, `1.2M` and `78%` are real
# figures with a unit or a symbol attached, and excluding a trailing letter would
# drop every one of them.
# The lookbehind excludes a preceding DIGIT as well as a letter, and the digit
# is not redundant: with a letters-only guard, `p95` merely fails to match at the
# 9 and the engine advances one character and matches the 5. Measured — the first
# version of this fix turned `p95` into {'5'} instead of {}.
_NUMERAL = re.compile(r"(?<![A-Za-z0-9])\d+(?:[.,]\d+)?")
_TOKEN = re.compile(r"[a-z0-9]+")

# Unit suffixes stripped when deriving a fact key's stem: `aht_seconds` -> `aht`,
# `csat_pct` -> `csat`. Kept as data rather than a regex so a PM editing the
# taxonomy can see what the resolver will do with a new key.
_UNIT_SUFFIXES = ("_pct", "_seconds", "_ms", "_count", "_per_day",
                  "_per_second", "_per_week", "_managed", "_months")

# Leading modifiers dropped from a fact-key LABEL so "Average handle time" also
# resolves from "handle time", which is what a question actually says.
# Percentile and statistical prefixes count as modifiers too: a question says
# "latency", not "p95 latency". Without this, `p95_latency_ms` resolved from
# neither and rule 3 missed a two-metric question on the golden set.
_LABEL_MODIFIERS = ("average", "total", "overall", "median", "mean", "monthly",
                    "weekly", "p50", "p95", "p99")


def _stem(word: str) -> str:
    """Crude, auditable, and deliberately not a stemmer library.

    Rules 6 and 7 intersect word SETS, so `users` vs `user` and `interviewed`
    vs `interviews` must not read as different subjects — that is the same
    defect class `taxonomy._INFLECTION` exists for, and it cost 9 false
    rejections on the golden set before this existed. A real stemmer is a
    dependency and a source of surprises; this list is readable by whoever
    edits the taxonomy.
    """
    for suffix, keep in (("ies", 3), ("ers", 4), ("ing", 4), ("ed", 3),
                         ("es", 3), ("er", 4), ("s", 3)):
        if word.endswith(suffix) and len(word) - len(suffix) >= keep - len(suffix) + 1:
            trimmed = word[: -len(suffix)]
            if len(trimmed) >= 3:
                return trimmed + ("y" if suffix == "ies" else "")
    return word


def _words(text: str, stop: frozenset[str], stem: bool = False) -> set[str]:
    """Content words. Numerals are dropped — they are rules 1 and 5's business,
    and letting them count as shared content would make a question that only
    echoes a figure look properly anchored."""
    out = {
        w for w in _TOKEN.findall((text or "").lower())
        if w not in stop and not w.isdigit()
    }
    return {_stem(w) for w in out} if stem else out


def _jaccard(a: str, b: str, discount: "set[str] | None" = None) -> float:
    """Overlap between two questions, optionally ignoring a shared vocabulary.

    `discount` is rule 2's business: the claim's own words are words BOTH
    questions are required to contain (rule 7), so counting them as duplication
    evidence penalises the anchoring the validator elsewhere demands. Absent, the
    behaviour is unchanged — which is what the corpus and the measured jaccard
    ladder are calibrated against.
    """
    wa, wb = _words(a, _STOP_PHRASING), _words(b, _STOP_PHRASING)
    if not wa or not wb:
        return 0.0
    shared = wa & wb
    if discount:
        # DISCOUNT THE NUMERATOR ONLY. Removing the claim's words from both SETS
        # is the obvious version and it is wrong: when the claim words are what
        # DISTINGUISHES two questions, stripping them collapses the remainder to
        # near-identity and the score goes UP. Measured — that version turned
        # three accepts into rejects on the study data.
        #
        # Subtracting from the shared set alone is monotone non-increasing, so
        # this can only ever forgive a pair, never newly condemn one. For a rule
        # already sitting at 38.5% precision, "cannot create a new false reject"
        # is the property worth having.
        shared = shared - discount
    return len(shared) / len(wa | wb)


def _numerals(text: str) -> set[str]:
    return {m.group(0).replace(",", "") for m in _NUMERAL.finditer(text or "")}


@lru_cache(maxsize=32)
def _fact_aliases(family_key: str | None) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Surface forms that resolve to each fact key, derived from the taxonomy.

    Derived, never hand-listed: the vocabulary is config, so a new cohort costs
    one taxonomy entry and zero Python edits. That is the criterion the whole
    architecture is judged on.
    """
    out: list[tuple[str, tuple[str, ...]]] = []
    for key, spec in fact_keys(family_key).items():
        aliases = {key.replace("_", " ")}
        stem = key
        for suffix in _UNIT_SUFFIXES:
            if stem.endswith(suffix):
                stem = stem[: -len(suffix)]
                break
        aliases.add(stem.replace("_", " "))
        label = (spec.get("label") or "").lower().strip()
        if label:
            aliases.add(label)
            head, _, rest = label.partition(" ")
            if head in _LABEL_MODIFIERS and rest:
                aliases.add(rest)
            # "Uptime / availability" carries two names for one key.
            for part in re.split(r"[/,]", label):
                part = part.strip()
                if part:
                    aliases.add(part)
        out.append((key, tuple(sorted(a for a in aliases if len(a) >= 3))))
    return tuple(out)


def _named_fact_keys(text: str, family_key: str | None) -> set[str]:
    """Which fact keys this question names, however it spells them.

    Word-boundary matched with an optional plural, NOT substring — naked
    substring matching is the defect P1-06 measured out of `taxonomy.py`, where
    `hr` inside *through* gave every resume an HR point. `sla` must not fire on
    "slap", while `incident` must still fire on "incidents".
    """
    low = (text or "").lower()
    found: set[str] = set()
    for key, aliases in _fact_aliases(family_key):
        for alias in aliases:
            pattern = r"(?<!\w)" + r"\s+".join(re.escape(w) for w in alias.split())
            if re.search(pattern + r"(?:s|es)?(?!\w)", low):
                found.add(key)
                break
    return found


def validate(
    question: str,
    *,
    claim_text: str,
    probe_level: ProbeLevel,
    claim_type: str | None = None,
    claim_metric: str | None = None,
    job_family: str | None = None,
    prior_questions: "Sequence[str]" = (),
    prior_answers: "Sequence[str]" = (),
    other_claims: "Sequence[str]" = (),
    target_claim_text: str | None = None,
) -> QuestionValidation:
    """Is this a question worth asking? Pure, deterministic, no model call.

    EVERY RULE RUNS. `violations` collects all of them rather than returning the
    first: M6 counts violations per rule, and short-circuiting would bias every
    rule after the first toward zero and make the histogram lie about which rule
    is miscalibrated.

    NOTHING HERE READS PRESENTATION. No fluency, grammar, spelling, register,
    politeness or length-as-quality — those are bias vectors, and their absence
    is a product decision rather than an oversight (CLAUDE.md rule 6). The
    corpus carries Hinglish entries on BOTH sides to keep it that way.
    """
    text = (question or "").strip()
    violations: list[str] = []

    claim_numerals = _numerals(claim_text) | _numerals(claim_metric or "")
    answer_numerals = set()
    for answer in prior_answers:
        answer_numerals |= _numerals(answer)
    question_numerals = _numerals(text)

    # 1 — answer leakage. A figure the claim already states is a figure the
    # candidate no longer has to produce, and producing it is the evidence.
    if question_numerals & claim_numerals:
        violations.append("answer_leakage")

    # 5 — unsupported metric. The other half of the same idea: a numeral from
    # neither the claim nor the candidate's own words was invented here.
    if question_numerals - claim_numerals - answer_numerals:
        violations.append("unsupported_metric")

    # 2 — duplicate content, DISCOUNTING THE CLAIM'S OWN WORDS.
    #
    # PHASE 4A, and the first design of this fix was wrong, so both are recorded.
    #
    # Phase 3 finding 2 read eight false rejects — all the shape "How did you
    # measure the success of X?" — and concluded the rule was penalising a reused
    # interrogative frame ACROSS DIFFERENT CLAIMS. So the first fix compared only
    # priors belonging to the same claim. It fixed nothing and cost two true
    # rejects, because the diagnosis was wrong: measured over all 519 study rows,
    # **every one of the eight triggers was SAME-CLAIM and not one was
    # cross-claim.** The eight questions sat in eight different interviews and
    # were never compared to each other at all — they only looked alike to a human
    # reading the sample. Claim-id gating never changed a single verdict in the
    # whole dataset, so it is not here.
    #
    # What is actually happening is a CONFLICT BETWEEN TWO RULES. Rule 7 requires
    # a question to share subject words with its claim — that is what being
    # anchored means. Rule 2 then counts those same shared words as evidence of
    # duplication. The probe ladder walks one claim through five levels, so every
    # question after the first is compared against a sibling that must, by rule 7,
    # repeat the claim's vocabulary. **The better anchored a question is, the more
    # likely rule 2 calls it a repeat.**
    #
    #   "How many chat support tickets did you handle daily?"          (prior)
    #   "How did you measure success in managing the chat support queue?"
    #   claim: "Ran the chat support queue."          -> 0.385, tripped
    #
    # Not counting the claim's own words AS SHARED EVIDENCE leaves the frame and
    # the specific ask, which is what rule 2 was always trying to compare:
    # 0.385 -> 0.231, passes. A genuine reask shares the frame AND the ask, so it
    # still trips at 0.875. See `_jaccard` for why the discount applies to the
    # numerator only.
    #
    # THE THRESHOLD IS UNCHANGED at 0.37. Moving it against the sample that
    # measured it is counter-metric C7; this changes what is compared, not where
    # the line sits.
    claim_words = _words(claim_text, _STOP_PHRASING)
    if any(_jaccard(text, prior, discount=claim_words) >= DUPLICATE_JACCARD
           for prior in prior_questions):
        violations.append("duplicate_content")

    # 3 — multiple fact targets. NOT EVALUATED ON TRANSFER: a valid T1 probe
    # pairs the method from one claim with the problem from another, so when
    # both subjects are metrics it names two fact targets BY CONSTRUCTION
    # (corpus q63). Rule 6 already constrains which second subject is allowed,
    # and two rules on one boundary corrupts the reject-rate metric.
    if probe_level is not ProbeLevel.TRANSFER:
        if len(_named_fact_keys(text, job_family)) >= 2:
            violations.append("multiple_fact_targets")

    # 4 — hypothetical misuse. TRANSFER is the one probe level that is
    # deliberately situational; everywhere else the ladder asks what they DID.
    if probe_level is not ProbeLevel.TRANSFER and _HYPOTHETICAL.search(text):
        violations.append("hypothetical_misuse")

    subject = _words(text, _STOP_SUBJECT, stem=True)
    claim_subject = _words(claim_text, _STOP_SUBJECT, stem=True)
    label_subject = (
        _words(claim_type_label(job_family, claim_type), _STOP_SUBJECT, stem=True)
        if claim_type
        else set()
    )

    # What a question is allowed to anchor to. The claim and its type label are
    # the obvious two. The LAST ANSWER is the third and it is not a loophole:
    # this is a WhatsApp thread, and "you mentioned it jumped to 520 seconds —
    # what did you do?" is anchored by any reasonable reading. Scope is rule 6's
    # job, not rule 7's.
    anchors = claim_subject | label_subject
    if prior_answers:
        anchors |= _words(prior_answers[-1], _STOP_SUBJECT, stem=True)
    if probe_level is ProbeLevel.TRANSFER and target_claim_text:
        # A transfer probe legitimately spans two claims, so naming either one
        # anchors it. Which second claim is permitted stays rule 6's business.
        anchors |= _words(target_claim_text, _STOP_SUBJECT, stem=True)

    # 6 — scope drift.
    if probe_level is ProbeLevel.TRANSFER:
        # A transfer probe is SUPPOSED to leave the claim; what it may not do is
        # leave it for a claim the planner did not choose.
        if target_claim_text and not (subject & _words(target_claim_text, _STOP_SUBJECT, stem=True)):
            violations.append("scope_drift")
    else:
        if not (subject & claim_subject):
            for other in other_claims:
                if len(subject & _words(other, _STOP_SUBJECT, stem=True)) >= 2:
                    violations.append("scope_drift")
                    break

    # 7 — no claim anchor. The candidate has to know which of their three
    # resume lines "this" refers to.
    if not (subject & anchors):
        violations.append("no_claim_anchor")

    return QuestionValidation(not violations, tuple(violations))


def _short(text: str, limit: int = 90) -> str:
    clean = _WS.sub(" ", text or "").strip()
    return clean if len(clean) <= limit else clean[: limit - 3].rstrip() + "..."


def fallback_question(
    probe_level: ProbeLevel,
    claim_text: str | None = None,
    *,
    transfer: TransferSpec | None = None,
) -> GeneratedQuestion:
    if probe_level is ProbeLevel.TRANSFER and transfer is not None:
        base = TRANSFER_FALLBACKS[transfer.operator].substitute(
            their_method=transfer.their_method,
            other_problem=transfer.other_problem,
        )
    else:
        base = FALLBACK_QUESTIONS[probe_level]
    if not claim_text:
        return GeneratedQuestion(question=base, probe_level=probe_level)
    return GeneratedQuestion(
        question=f'On "{_short(claim_text)}" — {base}', probe_level=probe_level
    )


# P2-04 — what to send when an answer was not an answer.
#
# NO MODEL CALL. There is nothing to word creatively: the candidate has just
# said "ok", a model call costs latency against the +20% guardrail, and a fixed
# line is easier to defend on stage than a generated one. Cohort-neutral by
# construction — no family vocabulary, and the claim is prefixed by
# `repair_question()` exactly as the fallbacks are.
REPAIR_PROMPTS: dict[ProbeLevel, str] = {
    ProbeLevel.VALIDATION: (
        "I need a bit more to go on — what was your actual scope here, and what "
        "were the numbers?"
    ),
    ProbeLevel.OPERATIONAL: (
        "Could you give me the steps? What did you actually do, in what order?"
    ),
    ProbeLevel.INCIDENT: (
        "Can you think of one specific occasion? What happened, and when?"
    ),
    ProbeLevel.DECISION: (
        "What did you decide, and what else could you have done instead?"
    ),
    ProbeLevel.OUTCOME: (
        "What happened in the end, and how did you know?"
    ),
    ProbeLevel.TRANSFER: (
        "Take a guess — what would you check first, and how would you know "
        "that wasn't the problem?"
    ),
}


FAMILY_REPAIR_PROMPTS: dict[str, str] = {
    "sales": "Walk me through one specific deal or account strategy from lead to close.",
    "customer_support": "Walk me through one specific customer case or escalation and how you resolved it.",
    "banking_operations": "Walk me through one specific transaction or audit check from intake to clearance.",
    "software_engineering": "Walk me through the actual setup steps, system architecture, or code you implemented.",
    "recruiting_hr": "Walk me through one specific hiring pipeline or onboarding process you executed.",
    "operations_logistics": "Walk me through your operational workflow and what you checked daily.",
    "product_management": "Walk me through how you defined the product requirements and launched it.",
}


def repair_question(
    probe_level: ProbeLevel,
    claim_text: str | None = None,
    job_family: str | None = None,
) -> str:
    """One more go at the SAME probe. Deterministic, no model call.

    Anchored to the claim for the same reason the fallbacks are. Family-aware
    for operational repair prompts so domain candidates receive natural prompts.
    """
    family_prompt = FAMILY_REPAIR_PROMPTS.get((job_family or "").lower())
    base = family_prompt if (family_prompt and probe_level == ProbeLevel.OPERATIONAL) else REPAIR_PROMPTS[probe_level]
    return f'On "{_short(claim_text)}" — {base}' if claim_text else base


# Hackathon demo -- lightweight answer threading. Pure keyword match, no
# model call, no new extraction pipeline: the same "fixed line is easier to
# defend on stage than a generated one" reasoning as REPAIR_PROMPTS above,
# just triggered by an entity in the candidate's own last answer instead of a
# non-answer. Order matters -- it is match PRIORITY, first hit wins, so a
# more specific word ("approval") is checked before a more generic one that
# might co-occur in the same sentence ("manager").
THREAD_ENTITY_ORDER: tuple[str, ...] = (
    "approval", "documentation", "metric", "dashboard", "ticket", "jira",
    "release", "api", "customer", "report", "sdk", "library", "service",
    "bug", "meeting", "team", "manager",
)

THREAD_ENTITY_QUESTIONS: dict[str, str] = {
    "approval": "What specific criteria or threshold was required before getting that approval?",
    "documentation": "What specific specification or edge case in that documentation guided your approach?",
    "metric": "What baseline threshold was that metric measured against, and how did you verify it?",
    "dashboard": "What specific anomaly on that dashboard triggered your technical intervention?",
    "ticket": "What boundary of responsibility did you own versus the escalation team on that ticket?",
    "jira": "What specific requirement or constraint in that Jira ticket defined your scope?",
    "release": "What rollback guardrail or validation check did you run for that release?",
    "api": "What payload constraint, rate limit, or latency threshold did that API impose on your architecture?",
    "customer": "What specific constraint or operational bottleneck did the customer present?",
    "report": "What root cause did that report reveal, and what action did you take on it?",
    "sdk": "What technical limitation in that SDK did you have to architect around?",
    "library": "What trade-off made you select that library over a custom implementation?",
    "service": "What dependency or failure mode of that service impacted your design?",
    "bug": "What root cause did you diagnose for that bug, and how did you fix it?",
    "meeting": "What technical trade-off or boundary decision was agreed upon in that meeting?",
    "team": "What interface boundary or handoff contract did you establish with that team?",
    "manager": "What decision authority did you hold versus what required your manager's sign-off?",
}


def detect_thread_entity(answer_text: str, exclude: "Sequence[str]" = ()) -> str | None:
    """First entity this answer names, in priority order, or None.

    Word-boundary, case-insensitive substring match against a fixed list --
    deliberately not a model call and not a new signal-extraction path. Skips
    anything already threaded on this claim (`exclude`) so a claim never asks
    about the same entity twice.
    """
    text = answer_text or ""
    skip = {e.lower() for e in exclude}
    for entity in THREAD_ENTITY_ORDER:
        if entity in skip:
            continue
        # Trailing `s?` for the common plural (tickets, reports, managers) --
        # not a real stemmer, just enough for the demo's fixed word list.
        if re.search(rf"\b{re.escape(entity)}s?\b", text, re.IGNORECASE):
            return entity
    return None


def thread_followup_question(entity: str) -> str:
    return THREAD_ENTITY_QUESTIONS[entity]


def _retry_brief(violations: tuple[str, ...]) -> str:
    """What to tell the model on the second attempt.

    RULE NAMES AND A ONE-LINE DEFINITION. Never worked examples: a per-defect
    example is a per-cohort authoring cost and re-introduces the bias the
    taxonomy exists to keep out of code — A's contract forbids per-family
    examples in prompts for exactly this reason. The evidence that naming the
    mistake types is enough is arXiv 2507.02858, where guided generation beat
    human-authored questions; the guidance there is a taxonomy, not a gallery.
    """
    if not violations:
        return ""
    lines = "\n".join(f"  - {v}: {_RETRY_HINTS[v]}" for v in violations if v in _RETRY_HINTS)
    if not lines:
        return ""
    return (
        "\nYOUR PREVIOUS ATTEMPT WAS REJECTED. Fix these and ask again:\n"
        f"{lines}\n"
    )


# One line each, phrased as an instruction rather than an illustration.
_RETRY_HINTS: dict[str, str] = {
    "answer_leakage": "do not state any figure the claim already gives — ask for it",
    "duplicate_content": "this repeats an earlier question; ask something new",
    "multiple_fact_targets": "ask about ONE metric, not two",
    "hypothetical_misuse": "ask what they actually did, not what they would do",
    "unsupported_metric": "do not invent numbers the candidate never mentioned",
    "scope_drift": "stay on the claim being probed",
    "no_claim_anchor": "name the specific work being asked about",
}


def _brief_for(probe_level: ProbeLevel, transfer: TransferSpec | None) -> str:
    """The probe brief, plus the concrete substitution when there is one.

    The planner has already chosen the operator, the method and the problem.
    All that is left for the model is the wording — so the brief hands it the
    slots filled in and nothing else. `transfer.basis` is deliberately withheld:
    how the planner decided is for the log and the dashboard, and telling the
    model about the selection logic invites it to second-guess the selection.
    """
    brief = PROBE_BRIEFS[probe_level]
    if probe_level is not ProbeLevel.TRANSFER or transfer is None:
        return brief
    instruction = TRANSFER_INSTRUCTIONS[transfer.operator].substitute(
        their_method=transfer.their_method,
        other_problem=transfer.other_problem,
    )
    return f"{brief}\n\n{instruction}"


def _format_prior(prior_qa: list[tuple[str, str]]) -> str:
    if not prior_qa:
        return "(nothing yet — this is the first question of the session)"
    return "\n\n".join(f"Q: {q}\nA: {a[:500]}" for q, a in prior_qa[-5:])


async def generate_question(
    claim_text: str,
    probe_level: ProbeLevel,
    *,
    claim_type: str | None = None,
    claim_metric: str | None = None,
    job_family: str = "general",
    prior_qa: list[tuple[str, str]] | None = None,
    target_dimension: Dimension | None = None,
    transfer: TransferSpec | None = None,
    other_claims: "Sequence[str]" = (),
    target_claim_text: str | None = None,
) -> QuestionAttempt:
    """`transfer` is required for a TRANSFER probe and ignored for every other
    level. It is the planner's choice of what to ask; this function still only
    chooses how to say it. No prompt-file change was needed: the template
    already interpolates `$probe_level_brief`, and its no-hypotheticals rule
    already carves out "UNLESS the probe brief above explicitly asks for one".
    """
    fallback = fallback_question(probe_level, claim_text, transfer=transfer)
    prior_questions = [q for q, _ in (prior_qa or [])]
    prior_answers = [a for _, a in (prior_qa or [])]

    def render(violations: tuple[str, ...]) -> str:
        return load_prompt(
            "generate_question",
            claim_text=claim_text,
            claim_type_label=claim_type_label(job_family, claim_type),
            claim_metric=claim_metric or "none stated",
            family_label=family_label(job_family),
            probe_level=probe_level.value,
            probe_level_brief=_brief_for(probe_level, transfer),
            prior_qa=_format_prior(prior_qa or []),
            gap_hint=GAP_HINTS.get(target_dimension, "") if target_dimension else "",
            violations=_retry_brief(violations),
        )

    async def ask(violations: tuple[str, ...] = ()) -> tuple[str, bool]:
        """One model call. Returns (text, came_from_fallback)."""
        result = await complete_json(
            render(violations),
            GeneratedQuestion,
            temperature=settings.llm_temperature_question,
            fallback=lambda: fallback,
            # Wording is non-deterministic on purpose; caching would make every
            # follow-up on a repeated claim identical.
            cache=False,
        )
        text = (result.question or "").strip()
        if text == fallback.question:
            return text, True
        if len(text) < 12:
            log.warning("model returned an unusable question, using fallback")
            return fallback.question, True
        return text, False

    def check(text: str) -> QuestionValidation:
        return validate(
            text,
            claim_text=claim_text,
            claim_type=claim_type,
            claim_metric=claim_metric,
            job_family=job_family,
            probe_level=probe_level,
            prior_questions=prior_questions,
            prior_answers=prior_answers,
            other_claims=other_claims or (),
            target_claim_text=target_claim_text,
        )

    claim_ref = claim_text[:60]

    # --- attempt 1 ----------------------------------------------------------
    text, from_fallback = await ask()
    if from_fallback:
        log.info(
            "generation attempt 1/1 claim=%r probe_level=%s draft=%r source=fallback "
            "(model call failed or returned an unusable question)",
            claim_ref, probe_level.value, text,
        )
        # THE FALLBACK IS NEVER VALIDATED, and this is structural rather than an
        # exemption list. It is rendered as `On "<claim>" — <base>`, so it quotes
        # the claim including its figures and trips `answer_leakage` by
        # construction (corpus q60). CLAUDE.md rule 5 requires every LLM call to
        # have a fallback, so a validator able to reject it would leave no path
        # at all.
        return QuestionAttempt(text, probe_level, "fallback", 1, ())

    if not settings.question_validation:
        log.info(
            "generation attempt 1/1 claim=%r probe_level=%s draft=%r source=model "
            "(QUESTION_VALIDATION=false, not checked)",
            claim_ref, probe_level.value, text,
        )
        return QuestionAttempt(text, probe_level, "model", 1, ())

    first = check(text)
    log.info(
        "generation attempt 1/2 claim=%r probe_level=%s draft=%r validator=%s violations=%s",
        claim_ref, probe_level.value, text,
        "passed" if first.accepted else "failed", list(first.violations),
    )
    if first.accepted:
        return QuestionAttempt(text, probe_level, "model", 1, ())

    log.info("question rejected (%s), regenerating once", ", ".join(first.violations))

    # --- attempt 2, and there is no attempt 3 -------------------------------
    # Written as a second explicit call rather than `for attempt in range(N)`.
    # A loop invites someone to raise the constant; two calls make raising it a
    # visible diff. Same reasoning that keeps `select_transfer()` out of a
    # `planner.py`. The ceiling is the +20% median-turn-latency guardrail in
    # PHASE_1_SUCCESS_METRICS.md — every turn already blocks on a model call.
    retry_text, retry_from_fallback = await ask(first.violations)
    if retry_from_fallback:
        log.info(
            "generation attempt 2/2 claim=%r probe_level=%s previous=%r draft=%r "
            "source=fallback (regeneration call failed or returned an unusable question)",
            claim_ref, probe_level.value, text, retry_text,
        )
        return QuestionAttempt(retry_text, probe_level, "fallback", 2, first.violations)

    retry_check = check(retry_text)
    log.info(
        "generation attempt 2/2 claim=%r probe_level=%s previous=%r draft=%r "
        "validator=%s violations=%s",
        claim_ref, probe_level.value, text, retry_text,
        "passed" if retry_check.accepted else "failed", list(retry_check.violations),
    )
    if retry_check.accepted:
        return QuestionAttempt(retry_text, probe_level, "regenerated", 2, first.violations)

    # Two strikes. The fallback is thin but it is anchored, cohort-neutral and
    # never wrong about the probe level.
    log.info("regenerated question also rejected, using fallback")
    return QuestionAttempt(fallback.question, probe_level, "fallback", 2, first.violations)


# ===========================================================================
# FORENSIC GENERATION
#
# The objective is authorship verification: did this person do the work, or did
# they write it down. Everything above this line is the probe-level generator,
# which asks what a claim CONTAINS. Everything below asks what only its author
# could know.
#
# The probe-level enums are not deleted — `questions.probe_level` and
# `evidence.probe_level` are NOT NULL and the evidence graph keys off them — but
# they no longer DECIDE anything. A move is chosen, and its probe level is
# derived from it for storage (`MOVE_PROBE_LEVEL`).
#
# NO NEW MODEL CALL, NO NEW TABLE. Anatomy is derived in Python
# (`engine/anatomy.py`); the ledger is the `AnswerSignals` this session already
# stored on `responses.signals_json`, which `build_claim_states` already parses.
# ===========================================================================

from api.engine import anatomy as claim_anatomy
from api.engine.anatomy import Archetype, ClaimAnatomy


class Family(str, Enum):
    ESTABLISH = "ESTABLISH"   # anchor the claim in their own operating language
    PERIPHERY = "PERIPHERY"   # leave the headline: failure, exclusion, people
    SEAM      = "SEAM"        # cross two facts they have already stated
    TRANSFER  = "TRANSFER"    # their world, exactly one variable changed


class Move(str, Enum):
    """One move, one ask, one target.

    Nine of them rather than five families with four asks each, because a brief
    carrying several asks is a menu and the model orders the cheapest item —
    which is how a four-ask OUTCOME brief came to ask "how did you measure it"
    and nothing else.
    """

    METRIC_DEFINITION = "METRIC_DEFINITION"   # ESTABLISH
    OWNERSHIP_BOUNDARY = "OWNERSHIP_BOUNDARY"  # ESTABLISH
    OPERATING_CONTEXT = "OPERATING_CONTEXT"   # ESTABLISH
    FAILURE = "FAILURE"                       # PERIPHERY
    EXCLUSION = "EXCLUSION"                   # PERIPHERY
    DEPENDENCY = "DEPENDENCY"                 # PERIPHERY
    PEOPLE = "PEOPLE"                         # PERIPHERY
    AUTHORITY = "AUTHORITY"                   # PERIPHERY
    COHERENCE = "COHERENCE"                   # SEAM
    PERTURB = "PERTURB"                       # TRANSFER


MOVE_FAMILY: dict[Move, Family] = {
    Move.METRIC_DEFINITION: Family.ESTABLISH,
    Move.OWNERSHIP_BOUNDARY: Family.ESTABLISH,
    Move.OPERATING_CONTEXT: Family.ESTABLISH,
    Move.FAILURE: Family.PERIPHERY,
    Move.EXCLUSION: Family.PERIPHERY,
    Move.DEPENDENCY: Family.PERIPHERY,
    Move.PEOPLE: Family.PERIPHERY,
    Move.AUTHORITY: Family.PERIPHERY,
    Move.COHERENCE: Family.SEAM,
    Move.PERTURB: Family.TRANSFER,
}

# Candidate-Level Interview Model (docs/QUESTION_EVAL_HARNESS_AND_LEVEL_MODEL.md
# Phase 1). Moves absent from this dict are unrestricted at every seniority --
# only the three moves real logs implicated (authority questions reading
# unnatural on juniors, exclusion/perturbation assuming a scope a junior was
# never given) are gated at all. A seniority NOT in the set is blocked, which
# is what makes `level_appropriate` return False for unknown seniority below:
# there is no junior entry because junior never unlocks any of these three.
LEVEL_RESTRICTED: dict[Move, frozenset[str]] = {
    Move.AUTHORITY: frozenset({"mid", "senior"}),
    Move.EXCLUSION: frozenset({"senior"}),
    Move.PERTURB: frozenset({"senior"}),
}


def level_appropriate(move: Move, seniority: str | None) -> bool:
    """Is `move` allowed for a candidate at this seniority?

    Unknown seniority (`None` -- classifier off, header too thin, or a value
    it returned that `extract._normalise_seniority` didn't recognise) must
    read exactly like today's behaviour for these three moves: all three are
    unconditionally disabled already (see the demo_mode filter in
    `ClaimState.forensic_moves_left`), so "unknown" stays disabled rather than
    defaulting open.
    """
    allowed = LEVEL_RESTRICTED.get(move)
    if allowed is None:
        return True
    if seniority is None:
        return False
    return seniority in allowed


# Compatibility only. The evidence graph and `claim_scores.probed_dimensions`
# read `probe_level`, so every question still stores one — but nothing plans
# with it. Chosen so the dimensions a move actually elicits are the dimensions
# its recorded level claims to have probed.
MOVE_PROBE_LEVEL: dict[Move, ProbeLevel] = {
    Move.METRIC_DEFINITION: ProbeLevel.OUTCOME,      # METRIC_OWNERSHIP
    Move.OWNERSHIP_BOUNDARY: ProbeLevel.VALIDATION,  # SPECIFICITY
    Move.OPERATING_CONTEXT: ProbeLevel.OPERATIONAL,  # PROCESS, TOOL_FAMILIARITY
    Move.FAILURE: ProbeLevel.INCIDENT,               # AUTHENTICITY
    Move.EXCLUSION: ProbeLevel.DECISION,             # CAUSAL_REASONING
    Move.DEPENDENCY: ProbeLevel.OPERATIONAL,         # TOOL_FAMILIARITY
    Move.PEOPLE: ProbeLevel.INCIDENT,                # AUTHENTICITY, SPECIFICITY
    Move.AUTHORITY: ProbeLevel.DECISION,             # CAUSAL_REASONING
    Move.COHERENCE: ProbeLevel.OUTCOME,              # CAUSAL_REASONING
    Move.PERTURB: ProbeLevel.TRANSFER,
}

# Which rubric dimensions a move actually elicits, keyed by Move.value so a
# caller that only has the stored string (`questions.move`, possibly
# comma-joined after a re-target) never needs the enum itself.
#
# This is what MOVE_PROBE_LEVEL's trailing comments above already state as
# intent, made into a real table. It exists because MOVE_PROBE_LEVEL is a
# many-to-one COMPATIBILITY label for storage/replay (COHERENCE and
# METRIC_DEFINITION both record "OUTCOME"; FAILURE and PEOPLE both record
# "INCIDENT"; EXCLUSION and AUTHORITY both record "DECISION") — crediting
# probed dimensions from the stored probe_level, as `signals.score_claim` did
# before this table existed, credits a move for whatever its unrelated
# co-mapped sibling covers. `engine/signals.py` reads this directly (see
# `moves_used` on `score_claim`) instead of `PROBE_LEVEL_DIMENSIONS` whenever
# a move is on record, which is the decoupling FORENSIC_GENERATOR_DESIGN.md
# §6 specifies and that was not carried into the shipped code.
MOVE_DIMENSIONS: dict[str, tuple[Dimension, ...]] = {
    Move.METRIC_DEFINITION.value: (Dimension.METRIC_OWNERSHIP, Dimension.KNOWLEDGE),
    Move.OWNERSHIP_BOUNDARY.value: (Dimension.OWNERSHIP, Dimension.SPECIFICITY),
    Move.OPERATING_CONTEXT.value: (Dimension.PROCESS, Dimension.TOOL_FAMILIARITY, Dimension.EXECUTION),
    Move.FAILURE.value: (Dimension.AUTHENTICITY, Dimension.PROBLEM_SOLVING),
    Move.EXCLUSION.value: (Dimension.JUDGMENT, Dimension.CAUSAL_REASONING),
    Move.DEPENDENCY.value: (Dimension.TOOL_FAMILIARITY, Dimension.PROBLEM_SOLVING),
    Move.PEOPLE.value: (Dimension.AUTHENTICITY, Dimension.SPECIFICITY, Dimension.OWNERSHIP),
    Move.AUTHORITY.value: (Dimension.CAUSAL_REASONING, Dimension.JUDGMENT),
    Move.COHERENCE.value: (Dimension.CAUSAL_REASONING, Dimension.KNOWLEDGE),
    Move.PERTURB.value: (Dimension.CAUSAL_REASONING, Dimension.PROCESS, Dimension.ADAPTABILITY),
    # EvidenceCategory planner string keys
    "ownership": (Dimension.OWNERSHIP,),
    "process": (Dimension.PROCESS, Dimension.EXECUTION),
    "metric_definition": (Dimension.METRIC_OWNERSHIP, Dimension.KNOWLEDGE),
    "decision": (Dimension.JUDGMENT, Dimension.CAUSAL_REASONING),
    "dependency": (Dimension.TOOL_FAMILIARITY, Dimension.PROBLEM_SOLVING),
    "incident": (Dimension.AUTHENTICITY, Dimension.PROBLEM_SOLVING),
    "constraint": (Dimension.JUDGMENT, Dimension.PROBLEM_SOLVING),
    "causal_chain": (Dimension.CAUSAL_REASONING,),
    "artifact": (Dimension.SPECIFICITY,),
    "cross_claim_link": (Dimension.ADAPTABILITY,),
}

# One ask each. Never two. The `target` is what the question is hunting, and it
# is shown to the model separately so the ask and the quarry cannot blur.
MOVE_BRIEFS: dict[Move, tuple[str, str]] = {
    Move.METRIC_DEFINITION: (
        "Ask how the metric was DERIVED — who or what was counted, over what "
        "window, against what baseline, and where the figure was read from. "
        "Never ask what the value was. The value is on the resume; the "
        "derivation is not.",
        "how the number was produced, in their own operating language",
    ),
    Move.OWNERSHIP_BOUNDARY: (
        "Ask what part of this THEY personally handled, or what happened "
        "once their part was done and it moved on. This is a contribution "
        "question, not an org-chart question — never ask who approved it, "
        "who signed off, or what authority they had; those invite a name or "
        "a shrug, not a description of the work. 'What part did you build?' "
        "or 'what happened after your part was finished?' is right; 'who "
        "reviewed your work' or 'what could you decide independently' is "
        "wrong, even phrased gently. A plain, complete answer ('I built X, "
        "then it went to the release team') is exactly the target -- it "
        "does not need a tradeoff or a decision in it to count.",
        "the specific piece that was theirs, described as work not rank",
    ),
    Move.OPERATING_CONTEXT: (
        "Ask what they were LOOKING AT while doing this — the dashboard, log, "
        "telemetry alert, metric, ticket, report, or system that told them something needed "
        "attention. Ask for the first thing they checked, not the routine. Do NOT phrase as 'on your screen'.",
        "the concrete artefact or telemetry source they worked from day to day",
    ),
    Move.FAILURE: (
        "Ask about one specific occasion this did not go the way they "
        "expected. Frame it so that 'it broke' is a completely acceptable "
        "answer — a question with only one good answer collects only that "
        "answer, from everyone.",
        "a specific remembered episode with its incidental detail",
    ),
    Move.EXCLUSION: (
        "Ask what they deliberately did NOT change, cover, include or fix, and "
        "what made it stay that way. Every real piece of work has a leftover, "
        "and the reason is usually specific and boring.",
        "the deliberate omission and the constraint behind it",
    ),
    Move.DEPENDENCY: (
        "Ask for the specific MOMENT a dependency mattered — what they were "
        "blocked on, what they couldn't do until something else was ready, "
        "or what changed once it was. Never lead with 'who did you rely on' "
        "or 'who did you coordinate with' alone — that names a team and "
        "stops there. Ask for the moment the dependency bit, not the org "
        "chart.",
        "the moment a dependency actually blocked or changed the work",
    ),
    Move.PEOPLE: (
        "Ask about a specific person or role in this work — who pushed back, "
        "who they escalated to, who noticed first. A role is enough; never ask "
        "for a name, and never for a headcount.",
        "a named role in the loop and what they did",
    ),
    Move.AUTHORITY: (
        "Ask what they could decide on their own here and what had to go "
        "somewhere else. Authority boundaries are precise, memorable, and "
        "specific to one organisation.",
        "their decision rights and the escalation path",
    ),
    Move.COHERENCE: (
        "The candidate has already stated the two facts below. Put them "
        "against each other and ask how they hold together. Introduce NO new "
        "subject matter — every noun in your question must come from those two "
        "facts or from the claim. The question must be unanswerable by "
        "repeating either fact.",
        "whether two things they have said actually cohere",
    ),
    Move.PERTURB: (
        "Change exactly ONE thing in the world they have just described, and "
        "ask them to reason about it. Ask only where they would start and what "
        "would rule a cause out. Do NOT ask for numbers, tools or results — "
        "this did not happen, so there are none, and asking invites invention. "
        "Never a generic hypothetical, never a role-play.",
        "reasoning that a memorised resume cannot supply",
    ),
}

# The order moves are tried in, per claim shape. First entry is the opening
# question for that claim.
#
# METRIC_MOVE opens on METRIC_DEFINITION rather than on context: a quantified
# claim earns its measurement question first, because the metric is the
# falsifiable part and everything downstream is worth less if it is undefined.
#
# VOLUME opens on AUTHORITY because the count itself — the N — is exactly what
# must not be asked. The forensic content of a volume claim is the boundary of
# what the person was allowed to decide.
ARCHETYPE_LADDER: dict[Archetype, tuple[Move, ...]] = {
    Archetype.METRIC_MOVE: (
        Move.METRIC_DEFINITION, Move.EXCLUSION, Move.FAILURE,
        Move.COHERENCE, Move.DEPENDENCY, Move.PERTURB,
    ),
    Archetype.OWNERSHIP: (
        # OPERATING_CONTEXT opens even an OWNERSHIP-archetype claim now --
        # measured this session: "what decisions were solely yours" as a
        # claim's FIRST question, with zero grounding, is a senior-sounding
        # question a junior candidate can find genuinely hard to answer
        # despite having done the work. AUTHORITY itself is removed under
        # demo_mode (see forensic_moves_left()); OWNERSHIP_BOUNDARY is kept,
        # reworded, and now asked second, after some concrete detail exists.
        Move.OPERATING_CONTEXT, Move.OWNERSHIP_BOUNDARY, Move.AUTHORITY, Move.FAILURE,
        Move.PEOPLE, Move.COHERENCE, Move.PERTURB,
    ),
    Archetype.BUILD: (
        Move.OPERATING_CONTEXT, Move.DEPENDENCY, Move.FAILURE,
        Move.EXCLUSION, Move.COHERENCE, Move.PERTURB,
    ),
    Archetype.PROCESS: (
        Move.OPERATING_CONTEXT, Move.AUTHORITY, Move.FAILURE,
        Move.EXCLUSION, Move.COHERENCE, Move.PERTURB,
    ),
    Archetype.VOLUME: (
        Move.AUTHORITY, Move.OPERATING_CONTEXT, Move.FAILURE,
        Move.PEOPLE, Move.COHERENCE, Move.PERTURB,
    ),
}


# ---------------------------------------------------------------------------
# the evidence ledger
#
# NO NEW STORAGE. This is `AnswerSignals` — already extracted by LLM #3, already
# persisted on `responses.signals_json`, already parsed and grouped per claim by
# `orchestrator.build_claim_states` into `ClaimState.answer_signals`. The only
# thing that was missing is that nobody handed it to the generator.
# ---------------------------------------------------------------------------

CHEAP, MID, DEAR = "CHEAP", "MID", "DEAR"


class LedgerFact(NamedTuple):
    """One thing the candidate has established, with what it cost them to say.

    `cost` is computed from STRUCTURE, never judged at runtime: a metric
    definition either carries `how_measured` or it does not. That is what makes
    "expensive for an impostor" a measurement rather than an opinion.
    """

    kind: str
    text: str
    quote: str
    cost: str
    answer_ix: int

    @property
    def is_dear(self) -> bool:
        return self.cost == DEAR


def build_ledger(answer_signals: "Sequence[object]") -> tuple[LedgerFact, ...]:
    """Flatten this claim's answers into costed facts, oldest first.

    `answer_ix` is list position, which is the answer's order in the interview.
    SEAM needs two facts from DIFFERENT answers — a pair inside one answer tests
    nothing, because the candidate already reconciled them as they spoke.
    """
    out: list[LedgerFact] = []
    for index, sig in enumerate(answer_signals or ()):
        for item in getattr(sig, "incident_markers", ()) or ():
            out.append(LedgerFact("incident", item.detail, item.quote, DEAR, index))
        for item in getattr(sig, "causal_links", ()) or ():
            text = " -> ".join(p for p in (item.cause, item.action, item.outcome) if p)
            out.append(LedgerFact(
                "causal", text, item.quote,
                DEAR if item.is_complete else MID, index,
            ))
        for item in getattr(sig, "metric_definitions", ()) or ():
            out.append(LedgerFact(
                "metric", f"{item.metric}: {item.how_measured}" if item.how_measured else item.metric,
                item.quote, DEAR if item.how_measured else CHEAP, index,
            ))
        for item in getattr(sig, "tools", ()) or ():
            out.append(LedgerFact(
                "tool", f"{item.tool} ({item.usage})" if item.usage else item.tool,
                item.quote, MID if item.usage else CHEAP, index,
            ))
        for item in getattr(sig, "quantities", ()) or ():
            out.append(LedgerFact(
                "quantity", f"{item.value} {item.refers_to}".strip(), item.quote,
                MID if item.refers_to else CHEAP, index,
            ))
        for item in getattr(sig, "process_steps", ()) or ():
            out.append(LedgerFact("step", item.step, item.quote, MID, index))
        for item in getattr(sig, "entities", ()) or ():
            out.append(LedgerFact("entity", f"{item.entity} ({item.kind})", item.quote, MID, index))
    return tuple(out)


def dear_count(ledger: "Sequence[LedgerFact]") -> int:
    return sum(1 for f in ledger if f.is_dear)


def seam_pair(ledger: "Sequence[LedgerFact]") -> tuple[LedgerFact, LedgerFact] | None:
    """Two facts worth putting against each other, chosen in PYTHON.

    Requirements, in order of what makes a seam work at all:
      - different answers   — a pair the candidate stated in one breath is one
                              thought, and testing it tests nothing
      - both MID or DEAR    — two cheap facts have nothing to hold together
      - shared referent     — otherwise the question is two questions

    Preferred shapes first: a causal link against the metric it claims to have
    moved is the seam a fabricated claim fails, because real systems have
    counter-moving numbers and an invented one improves in every direction.
    """
    usable = [f for f in ledger if f.cost in (MID, DEAR)]
    if len(usable) < 2:
        return None

    def words(text: str) -> set[str]:
        return {w for w in _TOKEN.findall((text or "").lower()) if len(w) > 3}

    ranked: list[tuple[int, LedgerFact, LedgerFact]] = []
    for i, a in enumerate(usable):
        for b in usable[i + 1:]:
            if a.answer_ix == b.answer_ix:
                continue
            wa, wb = words(a.text), words(b.text)
            if not (wa & wb):
                continue
            # Two statements of the SAME fact are not a seam. A candidate who
            # repeats "about 12 endpoints" in two answers has not said two
            # things, and asking how they fit together is incoherent.
            if wa <= wb or wb <= wa:
                continue
            kinds = {a.kind, b.kind}
            if kinds == {"causal", "metric"}:
                rank = 0
            elif kinds == {"metric"}:
                rank = 1
            elif kinds == {"incident", "causal"}:
                rank = 2
            elif "causal" in kinds or "incident" in kinds:
                rank = 3
            else:
                rank = 4
            ranked.append((rank, a, b))
    if not ranked:
        return None
    ranked.sort(key=lambda r: r[0])
    return ranked[0][1], ranked[0][2]


# ---------------------------------------------------------------------------
# hard prohibitions
#
# The shapes measured to yield the least hard-to-invent evidence. These are
# checked in PYTHON after generation, not left to the prompt: the prompt already
# forbids them and a prompt is a request, not a guarantee.
# ---------------------------------------------------------------------------

_PROHIBITED = re.compile(
    r"(?<!\w)(?:"
    r"how\s+(?:long|many|much|often|big|large)"
    r"|what\s+year|which\s+year|what\s+month"
    r"|team\s+size|head\s?count"
    r"|over\s+what\s+(?:period|timeframe)"
    r"|for\s+how\s+long"
    r"|what\s+was\s+the\s+(?:percentage|exact\s+number|total|headcount)"
    r"|how\s+frequently"
    r")(?!\w)",
    re.IGNORECASE,
)


def violates_prohibition(
    text: str, ledger: "Sequence[LedgerFact]" = ()
) -> bool:
    """Is this one of the banned shapes, and did the candidate not open the door?

    The exception is narrow and literal: a duration or a count may be REFERRED
    to once the candidate has volunteered it, because at that point it is their
    fact and not our fishing. It is established by a ledger quantity whose
    subject the question actually names.
    """
    match = _PROHIBITED.search(text or "")
    if not match:
        return False
    subject = _words(text, _STOP_SUBJECT, stem=True)
    for fact in ledger or ():
        if fact.kind != "quantity":
            continue
        if subject & _words(fact.text, _STOP_SUBJECT, stem=True):
            return False        # they raised it; referring back is allowed
    return True


def move_available(
    move: Move, anatomy: ClaimAnatomy, ledger: "Sequence[LedgerFact]"
) -> bool:
    """Can this move be asked at all against this claim, right now?

    Preconditions are what stop the planner selecting a move the claim cannot
    support — which is how a generator ends up producing a generic question and
    calling it a probe.
    """
    if move is Move.METRIC_DEFINITION:
        return anatomy.has_metric
    if move is Move.EXCLUSION:
        return bool(anatomy.object) and anatomy.object != "this work"
    if move is Move.COHERENCE:
        return seam_pair(ledger) is not None
    if move is Move.PERTURB:
        # Deliberately NOT gated on the ledger having produced anything. A claim
        # that stalled produced nothing expensive to invent, and that is exactly
        # when a perturbation is worth its question: the answers stopped saying
        # what they did, so ask about something they did not do. Gating on
        # MID/DEAR facts would withhold the probe from precisely the candidate
        # it was designed for.
        return bool(anatomy.object) and anatomy.object != "this work"
    return True


# ---------------------------------------------------------------------------
# targeted fallbacks
#
# CLAUDE.md rule 5 requires every model call to have one. These are real
# forensic questions rather than degraded generic ones, because anatomy gives
# Python enough to build a specific question without a model.
#
# They interpolate `object`, `mechanism`, `metric_name` and ledger QUOTES only —
# never `metric_value`, never `scope`. `anatomy._defigure()` guarantees the
# first three carry no figure, so unlike the probe-level fallbacks these do not
# trip `answer_leakage` and do not need an exemption from validation.
# ---------------------------------------------------------------------------

def _the(phrase: str) -> str:
    """Give a bare noun phrase its article so the fallback reads as speech.

    Skipped for a phrase that already has a determiner and for a proper noun
    ("REST APIs", "Postgres") — "the REST APIs" is worse than "REST APIs", and
    the fallbacks are read aloud on WhatsApp.
    """
    text = (phrase or "").strip()
    if not text:
        return "this work"
    if _ARTICLED.match(text):
        return text
    if text[0].isupper():
        return text
    return f"the {text}"


_ARTICLED = re.compile(r"^(?:the|a|an|our|their|its|my|your|this|these)\b", re.I)


_PERTURB_SCALE = "PERTURB_SCALE"   # fallback variant key, never a Move

MOVE_FALLBACKS: dict[object, Template] = {
    Move.METRIC_DEFINITION: Template(
        "You mentioned $metric_name. How was $metric_name actually worked out — "
        "what counted and what did not?"
    ),
    Move.OWNERSHIP_BOUNDARY: Template(
        "On $object — what part did you personally handle, and what happened "
        "once it left your hands?"
    ),
    Move.OPERATING_CONTEXT: Template(
        "When you were working on $object, what did you look at first?"
    ),
    Move.FAILURE: Template(
        "Tell me about a time $object did not go the way you expected. "
        "What happened?"
    ),
    Move.EXCLUSION: Template(
        "Which part of $object did you leave alone, and what made you leave it?"
    ),
    Move.DEPENDENCY: Template(
        "Who or what did you have to rely on most while working on $object?"
    ),
    Move.PEOPLE: Template(
        "Who else was close to $object, and what did they do when it went wrong?"
    ),
    Move.AUTHORITY: Template(
        "On $object, what could you decide yourself and what had to go to "
        "someone else?"
    ),
    Move.COHERENCE: Template(
        "You said $fact_a, and also $fact_b. How did those two fit together?"
    ),
    # Two forms. Substituting another line of the candidate's OWN resume is
    # still "one variable inside their world", and it is the stronger probe: a
    # memorised claim can be recited, but it cannot be applied to a different
    # subject. The scale form is used when the resume offers nothing to swap in.
    Move.PERTURB: Template(
        "Suppose you had taken on $other_subject instead, with the same "
        "approach you used on $object. Where would you start?"
    ),
    _PERTURB_SCALE: Template(
        "Suppose $object had suddenly got much harder. What would you check "
        "first, and what would rule a cause out?"
    ),
}


def forensic_fallback(
    move: Move,
    anatomy: ClaimAnatomy,
    ledger: "Sequence[LedgerFact]" = (),
    other_subjects: "Sequence[str]" = (),
) -> str:
    """Deterministic, no model call, never a figure."""
    obj = anatomy.object or "this work"
    pair = seam_pair(ledger) if move is Move.COHERENCE else None
    if move is Move.COHERENCE and pair is None:
        move = Move.FAILURE                      # nothing to cross; ask beside it
    key: object = move
    other = next((o for o in other_subjects if o and o != obj), "")
    if move is Move.PERTURB and not other:
        key = _PERTURB_SCALE
    template = MOVE_FALLBACKS[key]
    return _WS.sub(" ", template.safe_substitute(
        object=_the(obj),
        mechanism=_the(anatomy.mechanism or obj),
        metric_name=anatomy.metric_name or obj,
        other_subject=_the(other) if other else "",
        fact_a=_short(pair[0].quote or pair[0].text, 60) if pair else "",
        fact_b=_short(pair[1].quote or pair[1].text, 60) if pair else "",
    )).strip()


def _ledger_summary(ledger: "Sequence[LedgerFact]", limit: int = 12) -> str:
    """What the candidate has already established, in their own words.

    Newest first — the last answer is the one a follow-up must not re-ask. The
    quote is included because SEAM must build only from what was actually said.
    """
    if not ledger:
        return "(nothing yet — this is the first question about this claim)"
    lines = [
        f"  [{f.cost}] {f.kind}: {_short(f.text, 90)}"
        + (f'  — they said: "{_short(f.quote, 90)}"' if f.quote else "")
        for f in list(ledger)[::-1][:limit]
    ]
    return "\n".join(lines)


_ORIENTATION_FIRST = (
    "This is the FIRST question about this claim -- the candidate has no "
    "context yet. Open with one short reminder of which piece of work you "
    "mean, 5-12 words, before the question itself -- \"You mentioned "
    "<fragment>.\" or \"On the work where you <fragment>,\". Use only what's "
    "already given above, never a number or duration. This reminder is "
    "exempt from the word count in RULES below; the question that follows "
    "it is not."
)
_ORIENTATION_LATER = (
    "The candidate has already been asked about this claim and has that "
    "context from an earlier question. Do NOT add a reminder sentence -- "
    "open directly with the question itself."
)


def _orientation_note(is_first_question: bool) -> str:
    """Python decides whether a reminder is due, the model is not asked to.

    A live check (`/tmp/check_orientation.py`, this session) showed the model
    reproduces the SAME reminder sentence whether or not the prompt told it
    evidence was already established for this claim -- the same "brief
    carrying more than one ask" failure `MOVE_BRIEFS`'s docstring already
    documents (question.py:914-917), just in a different clause. Handing it
    a single precomputed sentence instead of a condition to evaluate is the
    fix, matching the pattern `$claim_graph_context` already uses below.
    """
    return _ORIENTATION_FIRST if is_first_question else _ORIENTATION_LATER


def _forensic_prompt(
    claim_text: str,
    move: Move,
    anatomy: ClaimAnatomy,
    ledger: "Sequence[LedgerFact]",
    other_subjects: "Sequence[str]" = (),
) -> str:
    brief, target = MOVE_BRIEFS[move]
    if move is Move.PERTURB and other_subjects:
        swappable = ", ".join(f'"{o}"' for o in other_subjects if o)
        if swappable:
            brief = (
                f"{brief}\n"
                f"  You may swap in one of these, taken from another line of "
                f"their OWN resume: {swappable}. Substituting a subject they "
                f"claimed elsewhere is still their world, and it is the "
                f"stronger probe — a recited claim cannot be applied to a "
                f"different subject."
            )
    if move is Move.COHERENCE:
        pair = seam_pair(ledger)
        if pair:
            brief = (
                f"{brief}\n"
                f'  FACT ONE: {pair[0].text}   — they said: "{pair[0].quote}"\n'
                f'  FACT TWO: {pair[1].text}   — they said: "{pair[1].quote}"'
            )
    forbidden = ", ".join(f'"{f}"' for f in anatomy.forbidden) or "(no figures in this claim)"
    return load_prompt(
        "forensic_question",
        claim_text=claim_text,
        mechanism=anatomy.mechanism or "(not stated)",
        object=anatomy.object or "(not stated)",
        metric_name=anatomy.metric_name or "(this claim names no metric — do not invent one)",
        move_name=f"{MOVE_FAMILY[move].value}:{move.value}",
        move_brief=brief,
        target=target,
        ledger=_ledger_summary(ledger),
        orientation_note=_orientation_note(not ledger),
        forbidden=forbidden,
    )


class ForensicQuestion(BaseModel):
    """LLM #2's forensic response.

    Engine-local rather than in `api/schemas.py`, which is frozen — the same
    call `FamilyMatch` and `TransferSpec` already make.

    `reasoning` is prose and is NEVER parsed for a rating, a confidence or a
    score. It is stored so a question's separation argument is auditable: a
    question whose reasoning cannot name what a copier would fail to produce has
    been phrased, not designed. CLAUDE.md rule 1 is untouched — nothing here
    becomes a number.
    """

    question: str
    target_signal: str = ""
    reasoning: str = ""


async def generate_forensic_question(
    claim_text: str,
    move: Move,
    *,
    anatomy: ClaimAnatomy,
    ledger: "Sequence[LedgerFact]" = (),
    alt_moves: "Sequence[Move]" = (),
    claim_type: str | None = None,
    claim_metric: str | None = None,
    job_family: str = "general",
    prior_questions: "Sequence[str]" = (),
    prior_answers: "Sequence[str]" = (),
    other_claims: "Sequence[str]" = (),
) -> QuestionAttempt:
    """Two attempts, and THE SECOND ONE CHANGES THE TARGET, NOT THE WORDING.

    This is the one behavioural difference that matters most. The probe-level
    generator told a rejected model which rules it tripped and asked again, and
    19% of those regenerations satisfied the validator by deleting the offending
    token — "how long did you manage the team of 35 agents?" became "how long
    did you manage the team of agents?", which is compliant, ungrammatical and
    no more use than the original.

    Handing the model a DIFFERENT MOVE makes that impossible: attempt two is a
    different question hunting a different detail, not a patch of attempt one.
    The rejected draft is never shown to the model, and no violation names are
    ever fed back.

    `validate()` is called unchanged. Nothing here relaxes a rule; the prompt
    and `anatomy.forbidden` are what keep the output on its passing side.
    """
    probe_level = MOVE_PROBE_LEVEL[move]
    # Subjects from the candidate's other claims, decomposed the same way so
    # they carry no figures either.
    other_subjects = tuple(
        claim_anatomy.analyse(text).object for text in (other_claims or ())
    )

    def check(text: str, for_move: Move) -> tuple[bool, tuple[str, ...]]:
        """Python decides. Prohibitions first, then the untouched validator."""
        if violates_prohibition(text, ledger):
            return False, ("prohibited_shape",)
        result = validate(
            text,
            claim_text=claim_text,
            claim_type=claim_type,
            claim_metric=claim_metric,
            job_family=job_family,
            probe_level=MOVE_PROBE_LEVEL[for_move],
            prior_questions=list(prior_questions),
            prior_answers=list(prior_answers),
            other_claims=list(other_claims),
        )
        return result.accepted, result.violations

    async def ask(for_move: Move) -> ForensicQuestion | None:
        """One model call. None => it failed or returned something unusable."""
        sentinel = ForensicQuestion(question="")
        result = await complete_json(
            _forensic_prompt(claim_text, for_move, anatomy, ledger, other_subjects),
            ForensicQuestion,
            temperature=settings.llm_temperature_question,
            # Rule 5: a fallback always exists. The empty sentinel means "the
            # model did not answer", and the caller renders the Python fallback
            # — which is a real forensic question, not a degraded one.
            fallback=lambda: sentinel,
            cache=False,
        )
        text = (result.question or "").strip()
        if len(text) < 12:
            return None
        return ForensicQuestion(
            question=text,
            target_signal=(result.target_signal or "").strip()[:200],
            reasoning=(result.reasoning or "").strip()[:400],
        )

    claim_ref = claim_text[:60]

    # --- attempt 1 ----------------------------------------------------------
    first = await ask(move)
    if first is not None:
        accepted, violations = check(first.question, move)
        log.info(
            "forensic attempt 1/2 claim=%r move=%s draft=%r verdict=%s violations=%s",
            claim_ref, move.value, first.question,
            "passed" if accepted else "failed", list(violations),
        )
        if accepted:
            return QuestionAttempt(
                first.question, probe_level, "model", 1, (),
                move.value, first.target_signal, first.reasoning,
            )
        first_violations = violations
    else:
        log.info("forensic attempt 1/2 claim=%r move=%s — no usable model output",
                 claim_ref, move.value)
        first_violations = ("model_unavailable",)

    # --- attempt 2: a DIFFERENT MOVE, not a repair of attempt 1 -------------
    retarget = next(
        (m for m in alt_moves if m is not move and move_available(m, anatomy, ledger)),
        None,
    )
    if retarget is not None:
        second = await ask(retarget)
        if second is not None:
            accepted, violations = check(second.question, retarget)
            log.info(
                "forensic attempt 2/2 claim=%r move=%s (re-targeted from %s) "
                "draft=%r verdict=%s violations=%s",
                claim_ref, retarget.value, move.value, second.question,
                "passed" if accepted else "failed", list(violations),
            )
            if accepted:
                return QuestionAttempt(
                    second.question, MOVE_PROBE_LEVEL[retarget], "regenerated", 2,
                    first_violations, retarget.value,
                    second.target_signal, second.reasoning,
                )

    # --- fallback -----------------------------------------------------------
    # Anatomy-built, figure-free and cohort-neutral. Unlike the probe-level
    # fallbacks it is not exempt from validation by necessity — it simply passes.
    text = forensic_fallback(move, anatomy, ledger, other_subjects)
    log.info("forensic fallback claim=%r move=%s question=%r",
             claim_ref, move.value, text)
    return QuestionAttempt(
        text, probe_level, "fallback", 2, first_violations,
        move.value, MOVE_BRIEFS[move][1], "python fallback: model unavailable or rejected twice",
    )


# ===========================================================================
# v2 — evidence-category question generation (api/prompts/v2_forensic_question.txt)
#
# Wires the EvidenceCategory planner (api/engine/v2_evidence_planner.py) to its
# own prompt, alongside the Move path above rather than in place of it. Same
# shape as generate_forensic_question: two attempts, the second retargets to a
# different category rather than rewording the first draft; same response
# schema (ForensicQuestion); same validate(). Gated behind
# `EVIDENCE_PLANNER_V2` in orchestrator.py, off by default — the Move path is
# unchanged and is what ships without it.
#
# Deferred on purpose: CROSS_CLAIM_LINK. It needs `claim_graph.txt` run as a
# real LLM call and its local claim ids reconciled against the actual `Claim`
# rows, which is a second extraction pipeline in its own right. The orchestrator
# never offers it as a target for now, so `linked_claim_text` stays None and
# the prompt's LINKED CLAIM section always renders its "none" branch — which is
# the behaviour the prompt itself already specifies for every other target.
# ===========================================================================

from api.engine import v2_evidence_planner as evidence_planner

# Storage-compatibility label only, same role as MOVE_PROBE_LEVEL above:
# `questions.probe_level` is NOT NULL and the evidence graph keys off it, so an
# EvidenceCategory question still records one. Categories with no direct
# analogue take the nearest family match (CONSTRAINT -> EXCLUSION's DECISION,
# ARTIFACT -> OWNERSHIP_BOUNDARY's VALIDATION, CROSS_CLAIM_LINK -> PERTURB's
# TRANSFER, on the same reasoning MOVE_PROBE_LEVEL used for each).
EVIDENCE_PROBE_LEVEL: dict["evidence_planner.EvidenceCategory", ProbeLevel] = {
    evidence_planner.EvidenceCategory.OWNERSHIP: ProbeLevel.VALIDATION,
    evidence_planner.EvidenceCategory.PROCESS: ProbeLevel.OPERATIONAL,
    evidence_planner.EvidenceCategory.METRIC_DEFINITION: ProbeLevel.OUTCOME,
    evidence_planner.EvidenceCategory.DECISION: ProbeLevel.DECISION,
    evidence_planner.EvidenceCategory.DEPENDENCY: ProbeLevel.OPERATIONAL,
    evidence_planner.EvidenceCategory.INCIDENT: ProbeLevel.INCIDENT,
    evidence_planner.EvidenceCategory.CONSTRAINT: ProbeLevel.DECISION,
    evidence_planner.EvidenceCategory.CAUSAL_CHAIN: ProbeLevel.OUTCOME,
    evidence_planner.EvidenceCategory.ARTIFACT: ProbeLevel.VALIDATION,
    evidence_planner.EvidenceCategory.CROSS_CLAIM_LINK: ProbeLevel.TRANSFER,
}


def _known_evidence_summary(
    coverage: "dict[evidence_planner.EvidenceCategory, evidence_planner.CoverageState]",
    ledger: "Sequence[LedgerFact]",
) -> str:
    """`$known_evidence` — coverage per category, then the actual established
    facts with their quotes. The category line alone cannot satisfy the
    prompt's own ANCHORING requirement (it needs a specific person, tool,
    system or event, not a category label), so this reuses `_ledger_summary`,
    the same renderer the Move path already uses for its `$ledger` slot.
    """
    lines = [
        f"  {category.value}: {state.value}"
        for category, state in coverage.items()
        if state is not evidence_planner.CoverageState.MISSING
    ]
    header = "\n".join(lines) if lines else "  (nothing established yet)"
    return f"{header}\n\n{_ledger_summary(ledger)}"


def _evidence_fallback(category: "evidence_planner.EvidenceCategory", claim_text: str) -> str:
    """Generic and deliberately unvalidated — the same pattern CLAUDE.md
    documents for the probe-level fallback: it quotes the claim, trips
    `answer_leakage` by construction, and exists so a path always exists even
    when the model is unavailable or rejected twice (rule 5).
    """
    topic = category.value.lower().replace("_", " ")
    return f'On "{claim_text}" — tell me more about the {topic} involved.'


def _evidence_prompt(
    claim_text: str,
    category: "evidence_planner.EvidenceCategory",
    anatomy: ClaimAnatomy,
    coverage: "dict[evidence_planner.EvidenceCategory, evidence_planner.CoverageState]",
    ledger: "Sequence[LedgerFact]",
    linked_claim_text: str | None,
) -> str:
    forbidden = ", ".join(f'"{f}"' for f in anatomy.forbidden) or "(no figures in this claim)"
    is_first_question = all(
        state is evidence_planner.CoverageState.MISSING for state in coverage.values()
    )
    return load_prompt(
        "v2_forensic_question",
        claim_text=claim_text,
        mechanism=anatomy.mechanism or "(not stated)",
        object=anatomy.object or "(not stated)",
        metric_name=anatomy.metric_name or "(this claim names no metric — do not invent one)",
        target_evidence=category.value,
        known_evidence=_known_evidence_summary(coverage, ledger),
        claim_graph_context=(
            f"Linked claim: {linked_claim_text}" if linked_claim_text
            else "(none — no linked claim for this target)"
        ),
        orientation_note=_orientation_note(is_first_question),
        forbidden=forbidden,
    )


async def generate_evidence_question(
    claim_text: str,
    category: "evidence_planner.EvidenceCategory",
    *,
    anatomy: ClaimAnatomy,
    coverage: "dict[evidence_planner.EvidenceCategory, evidence_planner.CoverageState]",
    ledger: "Sequence[LedgerFact]" = (),
    alt_categories: "Sequence[evidence_planner.EvidenceCategory]" = (),
    linked_claim_text: str | None = None,
    claim_type: str | None = None,
    claim_metric: str | None = None,
    job_family: str = "general",
    prior_questions: "Sequence[str]" = (),
    prior_answers: "Sequence[str]" = (),
    other_claims: "Sequence[str]" = (),
) -> QuestionAttempt:
    """Same two-attempt/retarget/fallback shape as generate_forensic_question.

    `alt_categories` is expected pre-filtered by the caller (the orchestrator's
    planner already excludes established, unavailable and just-touched
    categories when it builds this list) — unlike the Move path, nothing here
    re-checks a precondition before offering a retarget.
    """
    probe_level = EVIDENCE_PROBE_LEVEL[category]

    def check(text: str, for_category: "evidence_planner.EvidenceCategory") -> tuple[bool, tuple[str, ...]]:
        if violates_prohibition(text, ledger):
            return False, ("prohibited_shape",)
        result = validate(
            text,
            claim_text=claim_text,
            claim_type=claim_type,
            claim_metric=claim_metric,
            job_family=job_family,
            probe_level=EVIDENCE_PROBE_LEVEL[for_category],
            prior_questions=list(prior_questions),
            prior_answers=list(prior_answers),
            other_claims=list(other_claims),
        )
        return result.accepted, result.violations

    async def ask(for_category: "evidence_planner.EvidenceCategory") -> ForensicQuestion | None:
        sentinel = ForensicQuestion(question="")
        result = await complete_json(
            _evidence_prompt(claim_text, for_category, anatomy, coverage, ledger, linked_claim_text),
            ForensicQuestion,
            temperature=settings.llm_temperature_question,
            fallback=lambda: sentinel,
            cache=False,
        )
        text = (result.question or "").strip()
        if len(text) < 12:
            return None
        return ForensicQuestion(
            question=text,
            target_signal=(result.target_signal or "").strip()[:200],
            reasoning=(result.reasoning or "").strip()[:400],
        )

    claim_ref = claim_text[:60]

    # --- attempt 1 ------------------------------------------------------
    first = await ask(category)
    if first is not None:
        accepted, violations = check(first.question, category)
        log.info(
            "evidence attempt 1/2 claim=%r category=%s draft=%r verdict=%s violations=%s",
            claim_ref, category.value, first.question,
            "passed" if accepted else "failed", list(violations),
        )
        if accepted:
            return QuestionAttempt(
                first.question, probe_level, "model", 1, (),
                category.value, first.target_signal, first.reasoning,
            )
        first_violations = violations
    else:
        log.info("evidence attempt 1/2 claim=%r category=%s — no usable model output",
                 claim_ref, category.value)
        first_violations = ("model_unavailable",)

    # --- attempt 2: a DIFFERENT CATEGORY, not a repair of attempt 1 -----
    retarget = next((c for c in alt_categories if c is not category), None)
    if retarget is not None:
        second = await ask(retarget)
        if second is not None:
            accepted, violations = check(second.question, retarget)
            log.info(
                "evidence attempt 2/2 claim=%r category=%s (re-targeted from %s) "
                "draft=%r verdict=%s violations=%s",
                claim_ref, retarget.value, category.value, second.question,
                "passed" if accepted else "failed", list(violations),
            )
            if accepted:
                return QuestionAttempt(
                    second.question, EVIDENCE_PROBE_LEVEL[retarget], "regenerated", 2,
                    first_violations, retarget.value,
                    second.target_signal, second.reasoning,
                )

    # --- fallback ---------------------------------------------------------
    text = _evidence_fallback(category, claim_text)
    log.info("evidence fallback claim=%r category=%s question=%r",
             claim_ref, category.value, text)
    return QuestionAttempt(
        text, probe_level, "fallback", 2, first_violations,
        category.value, "", "python fallback: model unavailable or rejected twice",
    )


# ---------------------------------------------------------------------------
# live question-quality logging (settings.live_question_quality_log)
#
# Offline-only in every other respect: this NEVER gates, NEVER changes what
# was already sent (the question is on its way to the candidate before this
# is even scheduled), and its result is NEVER persisted or read by anything
# that scores a candidate -- it exists to be read from the log stream by a
# human, the same as the `planner level=` line. The judge model call itself
# runs as a background task from orchestrator.ask_next(), never awaited
# inline, so it cannot add latency to a live turn even if the judge call is
# slow. See docs/QUESTION_EVAL_HARNESS_AND_LEVEL_MODEL.md Part A for the
# offline, batch version of the same rubric (scripts/question_quality_harness.py).
#
# The prompt is inline, not a api/prompts/*.txt file: that directory is
# glob-discovered into provenance.prompt_versions(), so a prompt that has no
# influence on any evaluation would otherwise start silently changing every
# evaluation_version minted from here on -- exactly what
# test_every_versioned_input_has_a_value exists to catch.
LIVE_QUALITY_AXES = (
    "clarity", "specificity", "naturalness", "single_focus",
    "answerability", "evidence_yield", "relevance_to_claim",
)


class LiveQuestionQualityScore(BaseModel):
    clarity: int
    specificity: int
    naturalness: int
    single_focus: int
    answerability: int
    evidence_yield: int
    relevance_to_claim: int


_LIVE_QUALITY_PROMPT = """You are auditing the QUALITY of a question an \
automated recruiting system just generated, NOT judging the candidate. Score \
the QUESTION only.

THE CLAIM THIS QUESTION IS PROBING
$claim

THE MOVE IT WAS TARGETING
$move

THE GENERATED QUESTION
$question

Score each axis 1 (worst) to 5 (best):

- clarity: unambiguous and easy to parse on first read?
- specificity: targets something concrete, not a vague generality?
- naturalness: would a real interviewer actually phrase it this way out loud?
- single_focus: asks exactly one thing, not several bundled together?
- answerability: could a real candidate who did this work actually answer it?
- evidence_yield: is a strong answer likely to produce verifiable,
  hard-to-invent detail?
- relevance_to_claim: clearly follows from the claim above, not a generic
  question that could apply to any claim?

Return JSON:
{"clarity": 1-5, "specificity": 1-5, "naturalness": 1-5, "single_focus": 1-5, \
"answerability": 1-5, "evidence_yield": 1-5, "relevance_to_claim": 1-5}"""


def _live_quality_fallback() -> LiveQuestionQualityScore:
    return LiveQuestionQualityScore(**{axis: 0 for axis in LIVE_QUALITY_AXES})


async def log_question_quality(
    *, session_id: str, question_id: str, claim_text: str, move: str, question_text: str,
) -> None:
    """Fire-and-forget: judge one already-sent question and log the 7 axes.

    Never raises into the caller -- a background task's exception would
    otherwise vanish into asyncio's default handler (or, worse, be logged as
    an unhandled-task-exception traceback that looks like a real bug). CLAUDE.md
    rule 5 is satisfied by `_live_quality_fallback` the same as any other
    `complete_json` call; the try/except below is *additional*, for the parts
    of this function that are not the model call itself.
    """
    try:
        prompt = Template(_LIVE_QUALITY_PROMPT).safe_substitute(
            claim=claim_text, move=move, question=question_text,
        )
        score = await complete_json(
            prompt,
            LiveQuestionQualityScore,
            temperature=0.0,
            fallback=_live_quality_fallback,
            cache=False,
        )
        log.info(
            "question quality session=%s question=%s move=%s scores=%s",
            session_id, question_id, move,
            {axis: getattr(score, axis) for axis in LIVE_QUALITY_AXES},
        )
    except Exception:  # noqa: BLE001
        log.exception(
            "question quality judge failed session=%s question=%s (logging only, "
            "no interview impact)", session_id, question_id,
        )
