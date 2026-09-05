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
# BUMP IT WHEN A RULE'S BEHAVIOUR CHANGES. Not for a comment, not for a
# refactor. And it is NOT an invitation to tune `DUPLICATE_JACCARD` below
# during Phase 3's study — that is counter-metric C7, the one move that makes
# a study worthless while making it look successful.
QUESTION_POLICY_VERSION = "qpol_2"

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
        "What was the call you made, and what did you turn down to make it?"
    ),
    ProbeLevel.OUTCOME: (
        "What happened in the end, and how did you know?"
    ),
    ProbeLevel.TRANSFER: (
        "Take a guess — what would you look at first, and what would rule it out?"
    ),
}


def repair_question(probe_level: ProbeLevel, claim_text: str | None = None) -> str:
    """One more go at the SAME probe. Deterministic, no model call.

    Anchored to the claim for the same reason the fallbacks are: a candidate
    reading "could you give me the steps?" on WhatsApp has no idea which of
    their three resume lines it refers to.
    """
    base = REPAIR_PROMPTS[probe_level]
    return f'On "{_short(claim_text)}" — {base}' if claim_text else base


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

    # --- attempt 1 ----------------------------------------------------------
    text, from_fallback = await ask()
    if from_fallback:
        # THE FALLBACK IS NEVER VALIDATED, and this is structural rather than an
        # exemption list. It is rendered as `On "<claim>" — <base>`, so it quotes
        # the claim including its figures and trips `answer_leakage` by
        # construction (corpus q60). CLAUDE.md rule 5 requires every LLM call to
        # have a fallback, so a validator able to reject it would leave no path
        # at all.
        return QuestionAttempt(text, probe_level, "fallback", 1, ())

    if not settings.question_validation:
        return QuestionAttempt(text, probe_level, "model", 1, ())

    first = check(text)
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
        return QuestionAttempt(retry_text, probe_level, "fallback", 2, first.violations)

    if check(retry_text).accepted:
        return QuestionAttempt(retry_text, probe_level, "regenerated", 2, first.violations)

    # Two strikes. The fallback is thin but it is anchored, cohort-neutral and
    # never wrong about the probe level.
    log.info("regenerated question also rejected, using fallback")
    return QuestionAttempt(fallback.question, probe_level, "fallback", 2, first.violations)
