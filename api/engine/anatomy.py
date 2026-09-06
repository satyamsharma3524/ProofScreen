"""
Claim anatomy — the decomposition the forensic generator plans against.

WHY THIS IS PURE PYTHON AND NOT A FOURTH LLM CALL. Extraction already reads the
resume once (`engine/extract.py`, LLM #1) and a claim is one sentence. Adding a
call to re-read that sentence would spend latency on every session for something
the sentence already states positionally. It would also make anatomy
non-deterministic, and the planner branches on it — a claim that decomposes
differently on two runs is a claim that gets a different interview.

WHAT THIS EXISTS TO PROTECT. The generator may name a metric and may never state
its value (CLAUDE.md rule 4's sibling: the figure IS the evidence, so handing it
back is handing back the answer). `claim.metric` today holds only the VALUE —
"41% -> 63%" — and the NAME lives inside the claim text. Splitting them is what
makes `ESTABLISH:METRIC_DEFINITION` expressible at all, and it is what keeps the
generated question on the passing side of `question.validate()`'s
`answer_leakage` rule without that rule being touched.

Nothing here is persisted. Anatomy is derived on demand from `claims.text` and
`claims.metric`, so there is no column to add, no backfill, and no second source
of truth to drift.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class Archetype(str, Enum):
    """The shape of a claim, which decides the order its moves are tried in.

    Derived from what the sentence CONTAINS, never from `claim_type` alone: the
    taxonomy has ~30 claim types across nine families and they answer "what kind
    of work is this", not "what can be asked about it".
    """

    METRIC_MOVE = "metric_move"   # a number was moved: "cut AHT from 480s to 430s"
    OWNERSHIP   = "ownership"     # a thing was held: "owned shrinkage and occupancy"
    BUILD       = "build"         # a thing was made: "built REST APIs on Postgres"
    PROCESS     = "process"       # a thing was run: "ran the chat support queue"
    VOLUME      = "volume"        # a count was handled: "ran 40 user interviews"


# A figure, matched exactly as `question._NUMERAL` matches it. The lookbehind
# keeps `P1` and `p95` out — a severity label and a percentile are not claimed
# figures, and treating them as such is the defect Phase 4A removed from the
# validator. The two regexes must agree or anatomy will hand the generator a
# token the validator then rejects it for using.
_NUMERAL = re.compile(r"(?<![A-Za-z0-9])\d+(?:[.,]\d+)?")

# "by rebuilding the first-run flow", "through script standardisation"
_MECHANISM = re.compile(r"\b(?:by|through|via|using)\s+(.+?)\s*$", re.I)

# Leading verbs. Stripped to reach the noun the sentence is actually about.
_LEAD_VERB = re.compile(
    r"^\s*(?:improved|increased|reduced|cut|grew|drove|raised|lowered|brought|"
    r"delivered|achieved|maintained|held|managed|owned|built|ran|led|handled|"
    r"processed|reviewed|cleared|integrated|migrated|deployed|designed|rebuilt|"
    r"redesigned|launched|shipped|created|introduced|automated|scaled|"
    r"optimi[sz]ed|streamlined|coordinated|supported|resolved|carried|sourced|"
    r"set\s+up|rolled\s+out|wrote|rewrote|tracked|monitored|instrumented)\b\s*",
    re.I,
)

_GERUND = re.compile(r"^\s*(?:re)?[a-z]+ing\b\s*", re.I)
_ARTICLE = re.compile(r"^\s*(?:the|a|an|our|their|its|my)\b\s*", re.I)
_TRAIL_PREP = re.compile(r"\s*\b(?:from|to|by|at|of|for|in|on|over|across|with|and)\s*$", re.I)

# Where a noun phrase stops. Everything after the first of these is another
# clause, not part of the subject.
_NP_STOP = re.compile(
    r"\s+(?:on|in|at|for|with|across|over|from|to|and|while|before|after|"
    r"during|through|by|that|which|improving|reducing|increasing|resulting|"
    r"driving|enabling|leading|helping|so)\b",
    re.I,
)

# People, not headcount. The WORDS are the evidence target for PERIPHERY:PEOPLE;
# any number attached to them is scope and is forbidden (see `scope`).
_PEOPLE = re.compile(
    r"\b(agents?|associates?|reps?|engineers?|analysts?|managers?|leads?|"
    r"stakeholders?|candidates?|hires?|advisors?|specialists?|executives?|"
    r"team(?:s)?|pods?|squads?|vendors?|clients?|customers?|underwriters?|"
    r"recruiters?|designers?|marketers?)\b",
    re.I,
)

# Named systems the candidate already put on the resume. Naming one back is not
# leakage — it is anchoring, and PERIPHERY:DEPENDENCY needs it.
_KNOWN_TOOLS = frozenset(
    "postgres postgresql kubernetes aws gcp azure redis kafka airflow dbt "
    "zendesk salesforce jira tableau looker excel sql python java react "
    "genesys avaya freshdesk hubspot amplitude mixpanel datadog grafana "
    "snowflake databricks naukri shine linkedin greenhouse lever workday "
    "sap oracle servicenow twilio stripe razorpay".split()
)

# A count of things is SCOPE, never a metric: "35 agents", "40 user interviews".
# Everything in here goes on the generator's forbidden list, because asking for
# it is the prohibition this architecture exists to enforce.
_COUNT_NOUN = re.compile(
    r"(?<![A-Za-z0-9])(\d+(?:[.,]\d+)?)\s*[-–]?\s*"
    r"([a-z]+(?:\s+[a-z]+)?)\b",
    re.I,
)

_UNIT_WORDS = frozenset(
    "seconds second sec secs minutes minute mins min hours hour hrs hr days day "
    "weeks week months month quarters quarter years year ms".split()
)


@dataclass(frozen=True)
class ClaimAnatomy:
    """What the generator is allowed to see, and what it must never say.

    `metric_value` and `scope` are carried so they can be WITHHELD. They are the
    forbidden list handed to the wording prompt; they are never interpolated
    into a question or a fallback.
    """

    mechanism: str = ""
    object: str = ""
    metric_name: str | None = None
    metric_value: str | None = None
    scope: tuple[str, ...] = field(default_factory=tuple)
    people: tuple[str, ...] = field(default_factory=tuple)
    dependencies: tuple[str, ...] = field(default_factory=tuple)
    archetype: Archetype = Archetype.PROCESS

    @property
    def forbidden(self) -> tuple[str, ...]:
        """Every literal the wording prompt must not reproduce.

        The claim's own figures plus every scope count. This is what keeps a
        generated question clear of `answer_leakage` without relaxing the rule.
        """
        out: list[str] = []
        if self.metric_value:
            out.append(self.metric_value)
            out.extend(sorted(_numerals(self.metric_value)))
        out.extend(self.scope)
        seen: set[str] = set()
        return tuple(x for x in out if x and not (x in seen or seen.add(x)))

    @property
    def has_metric(self) -> bool:
        return bool(self.metric_name)


def _numerals(text: str) -> set[str]:
    return {m.group(0).replace(",", "") for m in _NUMERAL.finditer(text or "")}


def _clean(text: str) -> str:
    text = _TRAIL_PREP.sub("", (text or "").strip().rstrip(".,;"))
    return _ARTICLE.sub("", text).strip()


def _defigure(text: str) -> str:
    """Strip every figure out of a phrase that will be spoken back.

    `object` and `mechanism` are interpolated into fallback questions and into
    the wording prompt, so a figure surviving here is a figure the generator
    hands the candidate — `answer_leakage` by construction, and the exact defect
    this layer exists to prevent. "team of 35 agents" must reach the prompt as
    "team", never as itself.

    The FIRST alphabetic segment wins when it is usable, because a resume
    sentence names the thing before it quantifies it. The longest segment is the
    fallback for phrases that open on a number ("40 user interviews").
    """
    if not text:
        return ""
    if not _NUMERAL.search(text):
        return _clean(text)
    segments = [_clean(seg.strip(" $£€@#-–/")) for seg in _NUMERAL.split(text)]
    segments = [seg for seg in segments if seg]
    if not segments:
        return ""
    if len(segments[0]) >= 3:
        return segments[0]
    return max(segments, key=len)


def _noun_phrase(text: str) -> str:
    """The subject of a fragment: strip the verb, stop at the next clause."""
    body = _LEAD_VERB.sub("", (text or "").strip())
    body = _GERUND.sub("", body)
    body = _ARTICLE.sub("", body)
    stop = _NP_STOP.search(body)
    if stop:
        body = body[: stop.start()]
    return _clean(body)


def _is_metric_value(raw: str) -> bool:
    """A before/after or a rate is a METRIC. A bare count of things is SCOPE.

    Deliberately conservative in one direction. Calling a metric "scope" only
    costs one un-asked measurement question; calling scope a "metric" produces
    "how was 35 agents measured?", which is the failure this whole layer exists
    to prevent.
    """
    if not raw:
        return False
    low = raw.lower()
    if "->" in low or "→" in low:
        return True
    if "%" in low:
        return True
    return False


def _scope_markers(claim_text: str, metric_raw: str | None) -> tuple[str, ...]:
    """Counts and durations, extracted precisely so they can be forbidden."""
    found: list[str] = []
    for source in (metric_raw or "", claim_text or ""):
        for match in _COUNT_NOUN.finditer(source):
            number, noun = match.group(1), match.group(2).strip().lower()
            head = noun.split()[0]
            if _PEOPLE.search(noun) or head in _UNIT_WORDS or noun.endswith("s"):
                found.append(match.group(0).strip())
                found.append(number)
    if metric_raw and not _is_metric_value(metric_raw):
        found.append(metric_raw)
        found.extend(sorted(_numerals(metric_raw)))
    seen: set[str] = set()
    return tuple(x for x in found if x and not (x in seen or seen.add(x)))


def _metric_name(claim_text: str, metric_raw: str | None) -> str | None:
    """The words immediately before the claim's first figure.

    "Grew activation from 41% to 63%..."  -> "activation"
    "Cut first response time from 9 hours" -> "first response time"
    "Held SLA attainment at 97%"           -> "SLA attainment"

    Positional rather than semantic on purpose: the resume sentence names the
    thing and then quantifies it, in every one of the nine job families.
    """
    if not _is_metric_value(metric_raw or ""):
        return None
    text = (claim_text or "").strip()
    first = _NUMERAL.search(text)
    head = text[: first.start()] if first else text
    head = _clean(_LEAD_VERB.sub("", head))
    # "activation from" -> "activation"; "CSAT scores in" -> "CSAT scores"
    head = _TRAIL_PREP.sub("", head).strip()
    if not head or len(head) > 60:
        return None
    # A leading count means we are looking at scope, not a metric name.
    if _NUMERAL.search(head):
        return None
    return head or None


def _people(claim_text: str) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for match in _PEOPLE.finditer(claim_text or ""):
        word = match.group(0).lower()
        if word not in seen:
            seen.add(word)
            out.append(word)
    return tuple(out)


def _dependencies(claim_text: str) -> tuple[str, ...]:
    """Named systems. Known tools by name, plus mid-sentence capitalisation.

    Mid-sentence only: the first word of a claim is capitalised because it is
    the first word, and "Managed" is not a dependency.
    """
    out: list[str] = []
    seen: set[str] = set()
    words = (claim_text or "").split()
    for index, raw in enumerate(words):
        word = raw.strip(".,;:()").strip()
        if not word:
            continue
        low = word.lower()
        capitalised = index > 0 and word[0].isupper() and not word.isupper()
        if low in _KNOWN_TOOLS or word.isupper() and len(word) > 2 or capitalised:
            if low in seen or low in _UNIT_WORDS:
                continue
            seen.add(low)
            out.append(word)
    return tuple(out)


def _archetype(claim_text: str, metric_name: str | None, scope: tuple[str, ...]) -> Archetype:
    low = (claim_text or "").lower()
    if metric_name:
        return Archetype.METRIC_MOVE
    if re.search(r"\b(built|build|deployed|migrated|integrated|created|set up|"
                 r"rolled out|launched|implemented|designed|rebuilt|automated)\b", low):
        return Archetype.BUILD
    if re.search(r"\b(owned|managed|led|responsible|accountable|carried)\b", low):
        return Archetype.OWNERSHIP
    if scope:
        return Archetype.VOLUME
    return Archetype.PROCESS


def analyse(claim_text: str, metric_raw: str | None = None) -> ClaimAnatomy:
    """Decompose one claim. Total function — never raises, never returns None.

    A claim it cannot read still yields a usable anatomy: `object` falls back to
    the claim's own noun phrase, and every family whose precondition is
    "always" stays available. Degrading to fewer moves is correct; failing is
    not, because the interview still has to ask something.
    """
    text = (claim_text or "").strip()

    mechanism_match = _MECHANISM.search(text)
    if mechanism_match:
        mechanism = _clean(mechanism_match.group(1))
        obj = _noun_phrase(mechanism_match.group(1))
        head = text[: mechanism_match.start()]
    else:
        mechanism = _clean(_LEAD_VERB.sub("", text))
        obj = _noun_phrase(text)
        head = text

    if not obj:
        obj = _noun_phrase(head) or _clean(head)

    # Both are spoken back to the candidate, so neither may carry a figure.
    obj = _defigure(obj) or "this work"
    mechanism = _defigure(mechanism) or obj

    metric_value = metric_raw if _is_metric_value(metric_raw or "") else None
    metric_name = _metric_name(text, metric_raw)
    scope = _scope_markers(text, metric_raw)

    return ClaimAnatomy(
        mechanism=mechanism,
        object=obj,
        metric_name=metric_name,
        metric_value=metric_value,
        scope=scope,
        people=_people(text),
        dependencies=_dependencies(text),
        archetype=_archetype(text, metric_name, scope),
    )
