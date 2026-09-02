"""
LLM call #3 — one answer -> evidence signals, facts and contradictions.
Owned by Dev B.  THE SEAM: A calls score_response() and nothing else.

Three guarantees enforced HERE, in Python, not requested in the prompt:

  1. VERBATIM. Any signal whose quote is not literally present in the answer is
     DROPPED. That is what makes "every point in the score traces to something
     the candidate actually said" true rather than aspirational.

  2. NO MODEL SCORES. The model returns counts; engine/signals.py turns counts
     into 0-100 via published rubrics. Nothing numeric the model emits reaches
     a score — the only numbers we take from it are quantities and facts the
     CANDIDATE stated, each of which must survive rule 1.

  3. CONTROLLED FACT KEYS. Facts are kept only on taxonomy keys. An open key
     space would let the model invent a fresh key per answer and thereby never
     contradict itself.
"""

from __future__ import annotations

import logging
import re

from api.config import settings
from api.engine import consistency, scoring, signals as signal_rubrics
from api.llm import complete_json, load_prompt
from api.schemas import (
    AnswerSignals,
    CausalLink,
    Contradiction,
    Dimension,
    EvidenceNode,
    ExtractedFact,
    IncidentMarker,
    MetricDefinition,
    NamedEntity,
    ProbeLevel,
    ProcessStep,
    Quantity,
    ScoreRequest,
    ScoreResult,
    ToolMention,
)
from api.taxonomy import fact_keys, family_vocabulary, is_known_fact_key

log = logging.getLogger("proofscreen.evidence")

QUOTE_MAX = 240

_NON_ANSWERS = (
    "i don't know", "i dont know", "no idea", "not sure", "cannot recall",
    "can't recall", "cant recall", "dont remember", "don't remember", "n/a",
    "na", "skip", "pass", "no comment", "nothing", "idk", "as mentioned",
    "same as above", "it was a while ago", "i forgot",
)

_WS = re.compile(r"\s+")


def _canon(text: str | None) -> str:
    return _WS.sub(" ", (text or "").lower()).strip()


def is_non_answer(text: str) -> bool:
    canon = _canon(text)
    if len(canon) < 12:
        return True
    return any(
        canon == n or canon.startswith(n + " ") or canon in (n + ".", n + "!")
        for n in _NON_ANSWERS
    )


def _verbatim(quote: str, answer: str) -> str | None:
    """The quote, if it truly appears in the answer. Whitespace and case are
    normalised because models reflow line breaks; the words must match."""
    q = _canon(quote)
    if not q or len(q) < 3:
        return None
    return quote.strip()[:QUOTE_MAX] if q in _canon(answer) else None


# ---------------------------------------------------------------------------
# heuristic signal extraction — fixture mode and last-resort fallback
#
# Deliberately conservative. It exists so the product demos with no API key and
# so a dead model degrades instead of crashing. It must never look BETTER than
# the real extraction, or the fallback becomes the product.
# ---------------------------------------------------------------------------

_UNIT = r"(?:%|percent|ms|seconds?|secs?|minutes?|mins?|hours?|hrs?|days?|weeks?|months?|years?|lakh|cr|crore|bn|k|m|x)"
_QTY = re.compile(rf"(?<![A-Za-z\d])(\d+(?:[.,]\d+)?\s*{_UNIT}?)", re.IGNORECASE)
_SENT = re.compile(r"(?<=[.!?])\s+|\n+")
_CAUSAL_MARKERS = (
    "because", "since", "so that", " so ", "therefore", "which led to",
    "resulted in", "as a result", "due to", "that is why", "which meant",
    "the reason", "root cause",
)
_OUTCOME_MARKERS = (
    "dropped", "fell", "rose", "improved", "increased", "reduced", "went up",
    "went down", "came down", "halved", "doubled", "moved to", "ended at",
    "reached", "recovered", "stabilised", "stabilized",
)
_STEP_MARKERS = (
    "we ", "i ", "then ", "first ", "next ", "after that", "every ", "daily",
    "weekly", "monthly", "each ",
)
_INCIDENT_MARKERS = (
    "one day", "that week", "the week", "last month", "that month", "one of my",
    "a client", "the client", "my manager", "our vp", "before month-end",
    "month end", "during peak", "on a saturday", "that quarter", "once ",
    "there was a time", "i remember", "the day", "that night", "shift",
)
_USAGE_MARKERS = (
    "used it to", "pulled", "tracked", "logged", "tagged", "configured", "built",
    "ran", "set up", "created", "monitored", "exported", "reported", "dashboard",
    "queried", "raised", "assigned",
)
_MEASURE_MARKERS = (
    "measured", "calculated", "survey", "captured", "tracked", "computed",
    "formula", "percentage of", "average of", "sampled", "audited", "scored",
)

_TOOL_VOCAB = (
    "zendesk", "freshdesk", "salesforce", "genesys", "avaya", "ozonetel",
    "intercom", "jira", "servicenow", "hubspot", "zoho", "leadsquared",
    "tableau", "power bi", "looker", "excel", "sql", "python", "sap",
    "finacle", "flexcube", "temenos", "darwinbox", "workday", "successfactors",
    "greenhouse", "keka", "naukri", "linkedin", "kubernetes", "kafka", "redis",
    "postgres", "mysql", "mongodb", "terraform", "docker", "airflow", "dbt",
    "snowflake", "bigquery", "redshift", "grafana", "datadog", "splunk",
)


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT.split(text or "") if s.strip()]


def heuristic_signals(answer: str, job_family: str = "general") -> AnswerSignals:
    """Regex-and-vocabulary extraction. Quotes are real spans of the answer."""
    sig = AnswerSignals(summary="Heuristic extraction (model unavailable).")
    if is_non_answer(answer):
        return AnswerSignals(summary="Answer was empty or evasive.")

    sentences = _sentences(answer)
    low_answer = answer.lower()

    for sentence in sentences:
        low = sentence.lower()

        for match in _QTY.finditer(sentence):
            value = match.group(1).strip()
            if not any(c.isdigit() for c in value):
                continue
            window = sentence[max(0, match.start() - 40) : match.end() + 40]
            sig.quantities.append(
                Quantity(value=value[:60], refers_to=_WS.sub(" ", window)[:80],
                         quote=sentence[:QUOTE_MAX])
            )

        if any(low.startswith(m.strip()) or m in low for m in _STEP_MARKERS) and len(low) > 25:
            if any(v in low for v in ("ed ", "ing ", "review", "track", "train",
                                      "call", "audit", "plan", "assign", "check")):
                sig.process_steps.append(
                    ProcessStep(step=_WS.sub(" ", sentence)[:160], quote=sentence[:QUOTE_MAX])
                )

        if any(m in low for m in _CAUSAL_MARKERS):
            has_outcome = any(m in low for m in _OUTCOME_MARKERS)
            sig.causal_links.append(
                CausalLink(
                    cause=_WS.sub(" ", sentence)[:160],
                    action=_WS.sub(" ", sentence)[:160],
                    # Only a stated outcome completes a chain — no inference.
                    outcome=_WS.sub(" ", sentence)[:160] if has_outcome else None,
                    quote=sentence[:QUOTE_MAX],
                )
            )

        if any(m in low for m in _INCIDENT_MARKERS) and len(low) > 20:
            sig.incident_markers.append(
                IncidentMarker(detail=_WS.sub(" ", sentence)[:200], quote=sentence[:QUOTE_MAX])
            )

    for tool in _TOOL_VOCAB:
        if tool in low_answer:
            host = next((s for s in sentences if tool in s.lower()), answer)
            described = any(m in host.lower() for m in _USAGE_MARKERS)
            sig.tools.append(
                ToolMention(
                    tool=tool[:80],
                    usage=_WS.sub(" ", host)[:160] if described else None,
                    quote=host[:QUOTE_MAX],
                )
            )

    for key, spec in fact_keys(job_family).items():
        label = spec["label"].lower()
        head = label.split()[0]
        if len(head) < 3 or head not in low_answer:
            continue
        host = next((s for s in sentences if head in s.lower()), None)
        if host is None:
            continue
        described = any(m in host.lower() for m in _MEASURE_MARKERS)
        sig.metric_definitions.append(
            MetricDefinition(
                metric=spec["label"][:80],
                how_measured=_WS.sub(" ", host)[:200] if described else None,
                quote=host[:QUOTE_MAX],
            )
        )
        number = _QTY.search(host)
        if number:
            raw = number.group(1)
            try:
                sig.facts.append(
                    ExtractedFact(
                        key=key,
                        value_num=float(re.sub(r"[^\d.]", "", raw) or 0) or None,
                        unit=(re.sub(r"[\d.,\s]", "", raw) or None),
                        quote=host[:QUOTE_MAX],
                    )
                )
            except ValueError:
                pass

    for word in family_vocabulary(job_family):
        if len(word) > 4 and word in low_answer:
            host = next((s for s in sentences if word in s.lower()), answer)
            sig.entities.append(
                NamedEntity(entity=word[:100], kind="process", quote=host[:QUOTE_MAX])
            )
            if len(sig.entities) >= 4:
                break

    return sig


# ---------------------------------------------------------------------------
# verbatim enforcement
# ---------------------------------------------------------------------------


def enforce_verbatim(sig: AnswerSignals, answer: str) -> tuple[AnswerSignals, int]:
    """Drop every signal whose quote is not literally in the answer."""
    clean = AnswerSignals(summary=sig.summary[:280])
    dropped = 0

    def keep(item, bucket: str) -> None:
        nonlocal dropped
        quote = _verbatim(item.quote, answer)
        if quote is None:
            dropped += 1
            return
        item.quote = quote
        getattr(clean, bucket).append(item)

    for q in sig.quantities:
        keep(q, "quantities")
    for st in sig.process_steps:
        keep(st, "process_steps")
    for cl in sig.causal_links:
        keep(cl, "causal_links")
    for tl in sig.tools:
        keep(tl, "tools")
    for md in sig.metric_definitions:
        keep(md, "metric_definitions")
    for im in sig.incident_markers:
        keep(im, "incident_markers")
    for en in sig.entities:
        keep(en, "entities")
    for ft in sig.facts:
        keep(ft, "facts")

    return clean, dropped


# ---------------------------------------------------------------------------
# the B-side entry point
# ---------------------------------------------------------------------------


def _nodes_from(
    dimension_scores: dict[Dimension, "object"],
    response_id: str,
    probe_level: ProbeLevel,
) -> list[EvidenceNode]:
    targeted = set(signal_rubrics.dimensions_for_level(probe_level))
    nodes: list[EvidenceNode] = []
    for dimension, entry in dimension_scores.items():
        # Store a row when we asked about it, or when the candidate volunteered
        # evidence for it anyway. Silent zeros on un-asked dimensions would
        # clutter the graph without telling the recruiter anything.
        if entry.score > 0 or dimension in targeted:
            nodes.append(
                EvidenceNode(
                    dimension=dimension,
                    score=entry.score,
                    basis=entry.basis,
                    quotes=entry.quotes,
                    source_response_id=response_id,
                    probe_level=probe_level,
                )
            )
    return nodes


async def score_response(req: ScoreRequest) -> ScoreResult:
    """Extract signals from one answer, score it, and check it for contradictions."""
    answer = (req.answer_text or "").strip()
    family = req.job_family or "general"

    if is_non_answer(answer):
        empty = AnswerSignals(summary="Candidate did not answer the question.")
        dimension_scores = signal_rubrics.score_answer(empty, family)
        return ScoreResult(
            signals=empty,
            nodes=_nodes_from(dimension_scores, req.response_id, req.probe_level),
            facts=[],
            contradictions=[],
            answer_score=0,
            summary="Candidate did not answer, so nothing was established.",
            signals_found=0,
        )

    prompt = load_prompt(
        "extract_signals",
        claim_text=req.claim.text,
        question_text=req.question_text,
        probe_level=req.probe_level.value,
        answer_text=answer,
        fact_key_menu="\n".join(
            f"                     {k} — {v['label']} ({v['kind']})"
            for k, v in fact_keys(family).items()
        ),
    )

    raw = await complete_json(
        prompt,
        AnswerSignals,
        temperature=settings.llm_temperature_extract,
        fallback=lambda: heuristic_signals(answer, family),
    )

    sig, dropped = enforce_verbatim(raw, answer)
    if dropped:
        log.warning(
            "dropped %d signal(s) on %s: quote not verbatim in the answer",
            dropped, req.response_id,
        )

    # Facts: taxonomy keys only, then compare against session memory.
    candidate_facts = [f for f in sig.facts if is_known_fact_key(family, f.key)]
    kept_facts, contradictions = consistency.check_new_facts(
        candidate_facts, req.known_facts, response_id=req.response_id, job_family=family
    )
    sig.facts = kept_facts

    dimension_scores = signal_rubrics.score_answer(sig, family)
    answer_score = scoring.claim_score(
        dimension_scores,
        family,
        voice_effort=req.voice.effort_score if req.voice else None,
        voice_weight=settings.voice_weight,
    )

    summary = (sig.summary or "").strip()[:280]
    if not summary:
        summary = (
            f"{signal_rubrics.total_signals(sig)} evidence signal(s) extracted "
            f"from this answer."
        )

    log.info(
        "%s / %s -> %d signals, answer_score %d, %d contradiction(s)",
        req.claim.id, req.probe_level.value,
        signal_rubrics.total_signals(sig), answer_score, len(contradictions),
    )

    return ScoreResult(
        signals=sig,
        nodes=_nodes_from(dimension_scores, req.response_id, req.probe_level),
        facts=kept_facts,
        contradictions=contradictions,
        answer_score=answer_score,
        summary=summary,
        signals_found=signal_rubrics.total_signals(sig),
        quotes_dropped=dropped,
    )


def signals_of(result_json: str | None) -> AnswerSignals:
    """Rehydrate stored signals for claim-level rescoring."""
    if not result_json:
        return AnswerSignals()
    try:
        return AnswerSignals.model_validate_json(result_json)
    except Exception:  # noqa: BLE001
        return AnswerSignals()
