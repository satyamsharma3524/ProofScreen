"""
LLM call #3 — (claim, question, answer) -> evidence nodes.  Owned by Dev B.

Two hard guarantees enforced here, not in the prompt:
  1. A node whose quote is not actually present in the answer is DROPPED.
     That is what makes "every term in the score points at a real quote" true
     rather than aspirational.
  2. The model never returns a number. claim_confidence comes from scoring.py.
"""

from __future__ import annotations

import logging
import re

from api.config import settings
from api.engine import scoring
from api.llm import complete_json, load_prompt
from api.schemas import (
    Dimension,
    EvidenceExtraction,
    EvidenceNode,
    RawEvidenceNode,
    ScoreRequest,
    ScoreResult,
    Verdict,
)

log = logging.getLogger("proofscreen.evidence")

QUOTE_MAX = 240

_NON_ANSWERS = (
    "i don't know", "i dont know", "no idea", "not sure", "cannot recall",
    "can't recall", "dont remember", "don't remember", "n/a", "na", "skip",
    "pass", "no comment", "nothing", "idk",
)

_WS = re.compile(r"\s+")


def _canon(text: str) -> str:
    return _WS.sub(" ", (text or "").lower()).strip()


def is_non_answer(text: str) -> bool:
    canon = _canon(text)
    if len(canon) < 12:
        return True
    return any(canon == n or canon.startswith(n + " ") or canon == n + "." for n in _NON_ANSWERS)


def _first_sentence(text: str, limit: int = QUOTE_MAX) -> str:
    clean = _WS.sub(" ", (text or "").strip())
    match = re.search(r"^(.{20,}?[.!?])(\s|$)", clean)
    candidate = match.group(1) if match else clean
    return candidate[:limit]


def _verbatim(quote: str, answer: str) -> str | None:
    """Return the quote if it really appears in the answer, else None.

    Whitespace and case are normalised — models reflow line breaks — but the
    words themselves must match. Anything else is a paraphrase, and a
    paraphrase is exactly the hallucination risk this product exists to kill.
    """
    q = _canon(quote)
    if not q:
        return None
    if q in _canon(answer):
        return quote.strip()[:QUOTE_MAX]
    return None


def unsupported_nodes(response_id: str, answer_text: str) -> list[EvidenceNode]:
    """Every dimension UNSUPPORTED — used for empty / evasive answers."""
    quote = _WS.sub(" ", (answer_text or "").strip())[:QUOTE_MAX]
    return [
        EvidenceNode(
            dimension=d,
            verdict=Verdict.UNSUPPORTED,
            quote=quote,
            source_response_id=response_id,
        )
        for d in scoring.DIMENSION_ORDER
    ]


def heuristic_extraction(answer_text: str) -> EvidenceExtraction:
    """Fixture-mode / last-resort evidence.

    Deliberately conservative: PARTIAL where the answer shows a signal, nothing
    where it does not. It is not pretending to be the model — it exists so the
    pipeline is demoable with no API key and so a dead LLM degrades instead of
    crashing.
    """
    if is_non_answer(answer_text):
        return EvidenceExtraction(
            nodes=[
                RawEvidenceNode(dimension=d, verdict=Verdict.UNSUPPORTED, quote="")
                for d in scoring.DIMENSION_ORDER
            ],
            rationale="Answer was empty or evasive; nothing was established.",
        )

    quote = _first_sentence(answer_text)
    nodes = [
        RawEvidenceNode(dimension=Dimension.OWNERSHIP, verdict=Verdict.PARTIAL, quote=quote)
    ]
    low = answer_text.lower()
    if any(c.isdigit() for c in answer_text):
        nodes.append(
            RawEvidenceNode(
                dimension=Dimension.SPECIFICITY, verdict=Verdict.PARTIAL, quote=quote
            )
        )
    if any(w in low for w in ("because", "root cause", "reason", "why", "driver", "caused")):
        nodes.append(
            RawEvidenceNode(dimension=Dimension.DEPTH, verdict=Verdict.PARTIAL, quote=quote)
        )
    if any(w in low for w in ("rollout", "rolled out", "monitor", "sla", "process",
                              "workflow", "runbook", "on-call", "deployed", "shipped")):
        nodes.append(
            RawEvidenceNode(
                dimension=Dimension.OPERATIONAL, verdict=Verdict.PARTIAL, quote=quote
            )
        )
    return EvidenceExtraction(
        nodes=nodes,
        rationale="Heuristic pass (LLM unavailable): signals present but unverified.",
    )


async def score_response(req: ScoreRequest) -> ScoreResult:
    """THE B-SIDE ENTRY POINT.  A calls exactly this and nothing else."""
    answer = (req.answer_text or "").strip()

    if is_non_answer(answer):
        nodes = unsupported_nodes(req.response_id, answer)
        return ScoreResult(
            nodes=nodes,
            claim_confidence=scoring.claim_confidence(nodes),
            rationale="Candidate did not answer the question, so nothing was verified.",
        )

    prompt = load_prompt(
        "extract_evidence",
        claim_text=req.claim.text,
        question_text=req.question_text,
        answer_text=answer,
    )

    extraction = await complete_json(
        prompt,
        EvidenceExtraction,
        temperature=settings.llm_temperature_extract,
        fallback=lambda: heuristic_extraction(answer),
    )

    nodes: list[EvidenceNode] = []
    seen: set[Dimension] = set()
    dropped = 0

    for raw in extraction.nodes:
        if raw.dimension in seen:
            continue

        if raw.verdict is Verdict.UNSUPPORTED:
            quote = ""                       # nothing to point at, by definition
        else:
            quote = _verbatim(raw.quote, answer) or ""
            if not quote:
                dropped += 1
                log.warning(
                    "dropped %s/%s node: quote not verbatim in answer",
                    raw.dimension.value, raw.verdict.value,
                )
                continue

        seen.add(raw.dimension)
        nodes.append(
            EvidenceNode(
                dimension=raw.dimension,
                verdict=raw.verdict,
                quote=quote,
                source_response_id=req.response_id,
            )
        )

    if not nodes:
        # Spec fallback: mark PARTIAL with the answer's first sentence, which is
        # by construction verbatim.
        log.error("no usable evidence nodes (dropped %d), falling back", dropped)
        nodes = [
            EvidenceNode(
                dimension=Dimension.OWNERSHIP,
                verdict=Verdict.PARTIAL,
                quote=_first_sentence(answer),
                source_response_id=req.response_id,
            )
        ]

    confidence = scoring.claim_confidence(nodes)
    rationale = (extraction.rationale or "").strip()[:280]
    if not rationale:
        rationale = f"{len(nodes)} dimension(s) evidenced from the candidate's answer."

    log.info(
        "claim %s -> %d nodes, confidence %.2f (dropped %d)",
        req.claim.id, len(nodes), confidence, dropped,
    )
    return ScoreResult(nodes=nodes, claim_confidence=confidence, rationale=rationale)
