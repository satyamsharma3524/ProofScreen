"""
TEMPORARY inspection harness. Traces ONE resume through the production
interview pipeline and prints every stage.

    python scripts/inspect_resume_pipeline.py resume_test/Some-Resume.pdf

WHAT THIS IS, AND WHAT IT IS NOT
--------------------------------
It is a PRINTER. Every value below comes from calling a production function or
reading a production object. There is no reimplemented logic here: no scoring,
no routing, no claim typing, no question wording. If a number is printed, some
function in `api/` returned it.

It reuses `scripts/demo_resume_flow.py` for the parts that drive the real
WhatsApp handler -- `_install_stubs`, `_deliver`, `CANNED` -- rather than
copying them, so the two harnesses cannot drift.

THE ONE SEAM is the same one `demo_resume_flow.py` documents:
`whatsapp_channel.download_media()`, which is the only thing in the path that
needs a Meta token. Everything else -- parse_inbound's document branch,
extract_text, classify_role, match_family, extract_claims, create_session,
ask_next, generate_question, validate, submit_answer, evidence, consistency,
scoring, finalize -- is production code making real model calls.

RAW MODEL JSON. `api.llm` caches every response by sha256 of
(model, temperature, schema, prompt) in `llm._cache`. Stages 1 and 3 snapshot
that dict before and after the call and print the NEW entry, which is the exact
bytes the provider returned. Nothing is intercepted and nothing is wrapped.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from api import llm  # noqa: E402
from api.config import settings  # noqa: E402
from api.db import SessionLocal, drop_all, init_models  # noqa: E402
from api.engine import extract as extract_engine  # noqa: E402
from api.engine import graph as graph_engine  # noqa: E402
from api.engine import orchestrator  # noqa: E402
from api.engine import question as question_engine  # noqa: E402
from api.engine import signals as signal_rubrics  # noqa: E402
from api.ingest.parse import extract_text  # noqa: E402
from api.models import Candidate, ChatSession, Claim, Question  # noqa: E402
from api.models import Response as ResponseRow  # noqa: E402
from api.routers import whatsapp as webhook  # noqa: E402
from api.schemas import Channel, ClaimExtraction, InboundMessage, ProbeLevel  # noqa: E402
from api.tenancy import TenantScope  # noqa: E402
from api import taxonomy  # noqa: E402

from scripts.demo_resume_flow import CANNED, _deliver, _install_stubs, _session_for  # noqa: E402

_MIME_FOR = {suffix: mime for mime, suffix in webhook._RESUME_SUFFIX.items()}
_RUN = uuid.uuid4().hex[:8]
_RULE = "=" * 50
_THIN = "-" * 50


def stage(name: str) -> None:
    print(f"\n{_RULE}\n{name}\n{_RULE}\n")


def block(label: str, body: str) -> None:
    print(f"{label}:\n{body}\n")


def path(where: str) -> None:
    print(f"Code path:\n{where}\n\n{_THIN}")


def new_cache_entries(before: set[str]) -> list[str]:
    """The raw provider responses added since `before`. Reads llm._cache."""
    return [raw for key, raw in llm._cache.items() if key not in before]


def pretty(raw: str) -> str:
    try:
        return json.dumps(json.loads(raw), indent=2, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        return raw


async def main(args: argparse.Namespace) -> int:
    resume_path = Path(args.resume).expanduser()
    if not resume_path.exists():
        print(f"no such file: {resume_path}")
        return 1
    mime = _MIME_FOR.get(resume_path.suffix.lower())
    if mime is None:
        print(f"unsupported: {resume_path.suffix!r}")
        return 1
    data = resume_path.read_bytes()

    print(f"resume     {resume_path}  ({len(data):,} bytes, {mime})")
    print(f"llm mode   {settings.llm_mode}  (requested model {settings.openai_model})")
    print(f"database   {settings.database_url}")
    print(
        "flags      "
        f"ROLE_CLASSIFIER={settings.role_classifier} "
        f"MAX_CLAIMS={settings.max_claims} MAX_QUESTIONS={settings.max_questions} "
        f"ADAPTIVE_PROBING={settings.adaptive_probing} "
        f"QUESTION_VALIDATION={settings.question_validation} "
        f"TRANSFER_PROBE={settings.transfer_probe} "
        f"REPAIR_TURN={settings.repair_turn}"
    )
    print(f"taxonomy   {taxonomy.taxonomy_version()} / hash {taxonomy.taxonomy_hash()}")
    print(f"prompts    {json.dumps(llm.prompt_versions())}")

    # ---------------------------------------------------------------- STAGE 0
    stage("STAGE 0 — INGEST (the WhatsApp document branch)")
    block("Inputs", f"  bytes    {len(data):,}\n  mime     {mime}\n  suffix   {resume_path.suffix.lower()}")
    resume_text = extract_text(f"resume{resume_path.suffix.lower()}", data)
    block("Outputs", f"  extracted {len(resume_text)} chars after normalise()\n\n"
                     + "\n".join(f"  | {line}" for line in resume_text.splitlines()))
    block(
        "Reasoning",
        "  `_try_resume_intake` tests the BODY before the mime: in dry-run\n"
        "  `download_media` defaults mime to audio/ogg, so a nil body must be\n"
        "  caught first or every document reads as a voice note. The mime then\n"
        "  maps through `_RESUME_SUFFIX` to a suffix, and `extract_text`\n"
        "  dispatches on that suffix -- PyMuPDF for .pdf -- then `normalise()`\n"
        "  collapses runs of whitespace and 3+ blank lines.",
    )
    path("api/routers/whatsapp.py::_try_resume_intake -> api/ingest/parse.py::extract_text/_from_pdf/normalise")

    trimmed = resume_text[: extract_engine.MAX_RESUME_CHARS]

    # ---------------------------------------------------------------- STAGE 1
    stage("STAGE 1 — ROLE CLASSIFIER (LLM #0), routing precedence rung 2")
    header = extract_engine.header_slice(trimmed)
    block(
        "Inputs",
        f"  settings.role_classifier   {settings.role_classifier}\n"
        f"  header_slice() length      {len(header)} chars "
        f"(MIN_HEADER_CHARS={extract_engine.MIN_HEADER_CHARS}, "
        f"HEADER_SLICE_CHARS={extract_engine.HEADER_SLICE_CHARS})\n\n"
        "  header_slice() output -- achievement bullets deliberately withheld:\n"
        + "\n".join(f"  | {line}" for line in header.splitlines()),
    )

    taxonomy_family = taxonomy.detect_family(trimmed)
    before = set(llm._cache)
    routed_by_classifier = await extract_engine.classify_role(trimmed, taxonomy_family)
    classifier_raw = new_cache_entries(before)

    if not settings.role_classifier:
        # OBSERVATION ONLY. The flag is production-default false, so rung 2 is
        # skipped and routing falls to rung 3. Flipping it here shows what the
        # classifier WOULD say; the routed family printed in STAGE 2 is the one
        # the pipeline actually used.
        settings.role_classifier = True
        before = set(llm._cache)
        observed = await extract_engine.classify_role(trimmed, taxonomy_family)
        classifier_raw = new_cache_entries(before)
        settings.role_classifier = False
        note = (
            f"  ROLE_CLASSIFIER is FALSE, so `classify_role` returned the taxonomy\n"
            f"  family unchanged: {routed_by_classifier!r}. Rung 2 did not run.\n\n"
            f"  OBSERVATION (flag flipped on, then restored -- NOT used for routing):\n"
            f"  classifier would route to: {observed!r}"
        )
    else:
        note = f"  classify_role() returned: {routed_by_classifier!r}"

    raw_note = (
        "\n\n  raw classifier response (api.llm._cache, exact provider bytes):\n"
        + "\n".join(f"  | {l}" for l in pretty(classifier_raw[0]).splitlines())
        if classifier_raw
        else "\n\n  (no new cache entry -- served from cache or not called)"
    )
    block("Outputs", note + raw_note)
    block(
        "Reasoning",
        "  `classify_role` sends ONLY `header_slice()` -- headline, title\n"
        "  history, summary and skills. Achievement bullets are withheld because\n"
        "  that is where the revenue/pipeline/GTM language lives, and that\n"
        "  language is what routes a product manager to `sales`.\n"
        "  `confidence` and `seniority` come back and are RECORDED AND NEVER\n"
        "  BRANCHED ON (CLAUDE.md rule 1). Certainty comes from the precedence\n"
        "  order, not from a number the model made up about itself.",
    )
    path("api/engine/extract.py::header_slice, classify_role  (prompt api/prompts/classify_role.txt)")

    # ---------------------------------------------------------------- STAGE 2
    stage("STAGE 2 — TAXONOMY ROUTING (deterministic, no model call)")
    match = taxonomy.match_family(trimmed)
    block("Inputs", f"  full resume text, {len(trimmed)} chars\n"
                    f"  taxonomy {taxonomy.taxonomy_version()} / {taxonomy.taxonomy_hash()}, "
                    f"{len(taxonomy.family_keys())} families")
    scores = "\n".join(
        f"    {k:<24} {v:.6f}{'   <-- winner' if k == match.family else ''}"
        for k, v in sorted(match.per_family_scores.items(), key=lambda kv: -kv[1])
    )
    block(
        "Outputs",
        f"  FamilyMatch.family            {match.family}\n"
        f"  FamilyMatch.confidence        {match.confidence:.6f}   (a MARGIN, not a probability)\n"
        f"  FamilyMatch.matched_terms     {list(match.matched_terms)}\n"
        f"  MARGIN_FLOOR                  {taxonomy.MARGIN_FLOOR}\n"
        f"  is_low_confidence(match)      {taxonomy.is_low_confidence(match)}\n"
        f"  MIN_TERMS                     {taxonomy.MIN_TERMS}\n\n"
        f"  per_family_scores (cosine over IDF-weighted keyword vectors):\n{scores}",
    )
    block(
        "Reasoning",
        "  `match_family` counts each keyword ONCE however often it occurs -- a\n"
        "  resume saying SQL eleven times is not eleven times a data resume, and\n"
        "  rewarding repetition makes the router trivially gameable by the same\n"
        "  keyword stuffing this product exists to see through. Each family's\n"
        "  IDF vector is L2-normalised so a family cannot win by owning a longer\n"
        "  keyword list. `confidence` is (top - runner_up) / top: it answers\n"
        "  'was this close?', not 'is this right?'.",
    )
    path("api/taxonomy.py::match_family, _matched, _term_pattern, _idf, _family_norms, is_low_confidence")

    # ---------------------------------------------------------------- STAGE 3
    stage("STAGE 3 — extract_claims() (LLM #1)")
    supplied = taxonomy.resolve_family(None)
    block(
        "Inputs",
        f"  resume_text        {len(trimmed)} chars (MAX_RESUME_CHARS={extract_engine.MAX_RESUME_CHARS})\n"
        f"  job_family arg     None  (no requisition -- rung 1 empty, supplied={supplied})\n"
        f"  limit              {settings.max_claims}  (MAX_CLAIMS)\n"
        f"  temperature        {settings.llm_temperature_extract}",
    )
    before = set(llm._cache)
    family, extracted = await extract_engine.extract_claims(resume_text, None)
    extract_raw = new_cache_entries(before)

    validated = ClaimExtraction(job_family=family, claims=list(extracted))
    raw_body = (
        "\n".join(f"  | {l}" for l in pretty(extract_raw[0]).splitlines())
        if extract_raw
        else "  (served from the process cache -- identical prompt already called)"
    )
    block(
        "Outputs",
        f"  routed family      {family}  ({taxonomy.family_label(family)})\n"
        f"  claims kept        {len(extracted)}\n\n"
        f"  EXACT RAW MODEL JSON (api.llm._cache, pre-validation):\n{raw_body}\n\n"
        f"  AFTER Python validation (ClaimExtraction.model_dump_json):\n"
        + "\n".join(f"  | {l}" for l in validated.model_dump_json(indent=2).splitlines()),
    )
    block(
        "Reasoning",
        "  ROUTING PRECEDENCE, decided in `extract_claims` and nowhere else:\n"
        "    1. the requisition's job_family, when the caller supplied a real one\n"
        "    2. the role classifier, on the TOP of the resume only   (LLM #0)\n"
        "    3. deterministic keyword detection over the whole resume\n"
        "    4. general\n"
        "  The classifier runs BEFORE the prompt is built, and that ordering is\n"
        "  the point: `claim_type_menu(routed)` decides which claim types the\n"
        "  model is allowed to find, so a family corrected AFTER extraction\n"
        "  would leave one cohort's claims wearing another's labels.\n"
        "  The model still returns a job_family; it is OBSERVED, NOT OBEYED.\n"
        "  Claims are then filtered in Python: verifiable=false or text < 15\n"
        "  chars is dropped, and one claim per type is kept -- breadth beats\n"
        "  depth, because an unprobed claim scores zero.",
    )
    path("api/engine/extract.py::extract_claims  (prompt api/prompts/extract_claims.txt)")

    print("\nThe EXACT rendered prompt sent to the provider for LLM #1:\n")
    rendered = llm.load_prompt(
        "extract_claims",
        resume_text=trimmed,
        max_claims=settings.max_claims,
        family_key=family,
        family_menu=extract_engine._family_menu(),
        claim_type_menu=taxonomy.claim_type_menu(family),
    )
    print("\n".join(f"  | {l}" for l in rendered.splitlines()))
    print(f"\n{_THIN}")

    # ---------------------------------------------------------------- STAGE 4
    stage("STAGE 4 — CLAIM TYPING (validated in Python, never trusted blindly)")
    weights = taxonomy.default_claim_weights(family)
    menu = "\n".join(
        f"    {k:<22} {cfg['label']:<38} weight {cfg['weight']:>5}  "
        f"probe_focus={taxonomy.probe_focus(family, k)}"
        for k, cfg in taxonomy.claim_types(family).items()
    )
    block("Inputs", f"  family {family}, claim-type menu offered to the model:\n{menu}")
    rows = []
    for i, claim in enumerate(extracted, 1):
        deterministic = taxonomy.classify_claim(claim.text, family)
        rows.append(
            f"  claim {i}\n"
            f"    text                  {claim.text}\n"
            f"    claim_type (kept)     {claim.claim_type}\n"
            f"    claim_type_label      {taxonomy.claim_type_label(family, claim.claim_type)}\n"
            f"    weight in family      {weights.get(claim.claim_type, 0.0)}\n"
            f"    metric                {claim.metric!r}\n"
            f"    _metric_of(text)      {extract_engine._metric_of(claim.text)!r}\n"
            f"    classify_claim(text)  {deterministic}"
            f"{'   (agrees)' if deterministic == claim.claim_type else '   (DISAGREES -- model key kept because it exists in this family)'}\n"
            f"    probe_focus           {taxonomy.probe_focus(family, claim.claim_type)}"
        )
    block("Outputs", "\n".join(rows))
    block(
        "Reasoning",
        "  `normalise_claim_type(family, key, text)` trusts the model's\n"
        "  claim_type ONLY if that key exists in this family; anything invented\n"
        "  is silently reclassified by `classify_claim`, which is pure keyword\n"
        "  hit-counting. The claim TYPE is what carries the recruiter's\n"
        "  importance weight, so an unclassified claim cannot be ranked.",
    )
    path("api/taxonomy.py::normalise_claim_type, classify_claim, default_claim_weights, probe_focus")

    # ---------------------------------------------------------------- STAGE 5
    stage("STAGE 5 — CLAIM ATTRIBUTION (role / company per claim)")
    block(
        "Inputs",
        "  api.schemas.ExtractedClaim fields: "
        + str(list(__import__("api.schemas", fromlist=["ExtractedClaim"]).ExtractedClaim.model_fields))
        + "\n  api.models.Claim columns:          "
        + str([c.name for c in Claim.__table__.columns]),
    )
    block(
        "Outputs",
        "  NOT AVAILABLE. There is no company or employer field anywhere on the\n"
        "  claim path: not on `ExtractedClaim`, not on the `claims` table, and\n"
        "  `api/prompts/extract_claims.txt` never asks for one. No production\n"
        "  code attributes a claim to a role or a company.",
    )
    block(
        "Reasoning",
        "  This is a real gap, not an omission in this trace. `extract.py`'s own\n"
        "  comment above `classify_role` records the consequence measured on six\n"
        "  PM resumes: 'Four of those six resumes produced claims from a job the\n"
        "  candidate left in 2021. The interview then asked about it.' The fix\n"
        "  shipped was to get the FAMILY right before extraction (rung 2), which\n"
        "  makes the wrong-job claim less likely -- it does not record which job\n"
        "  a claim came from, so the failure is still not detectable from stored\n"
        "  rows. Adding it means a field on the frozen `api/schemas.py`, which\n"
        "  CLAUDE.md rule 2 makes a conversation rather than a solo edit.",
    )
    path("api/schemas.py::ExtractedClaim · api/models.py::Claim · api/prompts/extract_claims.txt  (field absent in all three)")

    # ---------------------------------------------------------------- STAGE 6
    stage("STAGE 6 — create_session() via the real WhatsApp document handler")
    if args.fresh:
        await drop_all()
    await init_models()
    _install_stubs(data, mime)

    block(
        "Inputs",
        f"  InboundMessage(channel=whatsapp, media_id='media.{_RUN}',\n"
        f"                 external_id={args.phone.lstrip('+')!r},\n"
        f"                 profile_name={args.name!r},\n"
        f"                 provider_message_id='wamid.{_RUN}.doc')\n"
        f"  stubbed: whatsapp_channel.download_media / send_text / mark_read",
    )
    print("Outputs:\n")
    await _deliver(
        InboundMessage(
            channel=Channel.whatsapp,
            media_id=f"media.{_RUN}",
            external_id=args.phone.lstrip("+"),
            profile_name=args.name,
            provider_message_id=f"wamid.{_RUN}.doc",
        )
    )

    candidate, session = await _session_for(args.phone)
    if candidate is None or session is None:
        print("onboarding produced no candidate")
        return 1
    async with SessionLocal() as db:
        claims = (
            await db.execute(
                select(Claim).where(Claim.candidate_id == candidate.id)
                .order_by(Claim.order_index)
            )
        ).scalars().all()

    print(
        f"  candidate_id   {candidate.id}   name={candidate.name!r}  tenant={candidate.tenant_id}\n"
        f"  session_id     {session.id}   state={session.state}  channel={session.channel}\n"
        f"  job_family     {session.job_family}\n"
        f"  opt_in_code    {session.opt_in_code}   (unused -- the resume IS the opt-in)\n"
        f"  claims         {len(claims)}"
    )
    for claim in claims:
        print(f"    {claim.id}  order={claim.order_index}  type={claim.claim_type}  metric={claim.metric!r}")
    block(
        "\nReasoning",
        "  The document branch does NOT wait for an opt-in code: the candidate\n"
        "  messaged us unprompted with their resume, the 24-hour window is\n"
        "  already open, and an upload is a stronger consent signal than a code.\n"
        "  So AWAITING_OPT_IN is advanced straight to CLAIMS_READY and `ask_next`\n"
        "  is called in the same handler. A draft Evaluation is opened WITH the\n"
        "  interview, not after it (D6).",
    )
    path("api/routers/whatsapp.py::_handle -> _try_resume_intake -> api/routers/candidates.py::_onboard -> api/engine/orchestrator.py::create_session")

    # ---------------------------------------------------------------- STAGE 7
    stage("STAGE 7 — plan_next(): the question policy, pure and deterministic")
    async with SessionLocal() as db:
        session = await db.get(ChatSession, session.id)
        states = await orchestrator.build_claim_states(db, session)
        rows = []
        for s in states:
            rows.append(
                f"  {s.claim.id}  weight={s.weight:g}  type={s.claim.claim_type}\n"
                f"    levels_used={sorted(l.value for l in s.levels_used)}  "
                f"levels_left={[l.value for l in s.levels_left]}\n"
                f"    answers={s.answers}  score={s.score}  saturated={s.saturated}  "
                f"stalled={s.stalled}  exhausted={s.exhausted}\n"
                f"    transfer_available={s.transfer_available}  "
                f"weakest_dimension={s.weakest_dimension().value if s.weakest_dimension() else None}"
            )
    block("Inputs", f"  states (sorted heaviest claim first), index={session.questions_asked}\n"
                    + "\n".join(rows))
    block(
        "Outputs",
        "  the ladder, and which dimensions each rung is designed to elicit:\n"
        + "\n".join(
            f"    {lv.value:<12} -> {[d.value for d in signal_rubrics.dimensions_for_level(lv)]}"
            for lv in signal_rubrics.PROBE_ORDER
        )
        + f"\n\n  LADDER_ORDER (TRANSFER excluded -- offered only by the stall branch):\n"
          f"    {[l.value for l in signal_rubrics.LADDER_ORDER]}"
        + "\n\n  dimension -> earliest level that covers it (level_for_dimension):\n"
        + "\n".join(
            f"    {d.value:<20} -> {signal_rubrics.level_for_dimension(d).value}"
            for d in signal_rubrics.TARGETS
        ),
    )
    block(
        "Reasoning",
        "  Phase 1 BREADTH: one VALIDATION probe on every claim, heaviest first.\n"
        "  Nobody is deepened before every claim has been touched, because an\n"
        "  unprobed claim scores zero and would silently sink the candidate.\n"
        "  Phase 2 DEPTH: repeatedly take the heaviest claim that is not yet\n"
        "  saturated and ask the level covering its weakest un-probed dimension.\n"
        "  ADAPTIVE STOP: a claim stops at score >= 80, at five levels spent, or\n"
        "  when the last answer produced no new signals at all.",
    )
    path("api/engine/orchestrator.py::plan_next, build_claim_states, ClaimState · api/engine/signals.py::PROBE_LEVEL_DIMENSIONS, LADDER_ORDER, level_for_dimension")

    # ---------------------------------------------------------------- STAGE 8
    stage("STAGE 8 — generate_question() (LLM #2): the opening probe on every claim")
    block(
        "Inputs",
        f"  probe_level        VALIDATION (breadth phase, every claim)\n"
        f"  target_dimension   None (the breadth branch passes no gap hint)\n"
        f"  temperature        {settings.llm_temperature_question}\n"
        f"  validation         {settings.question_validation}  "
        f"(rules: {', '.join(question_engine.RULES) if hasattr(question_engine, 'RULES') else 'see question.validate()'})",
    )
    print("Outputs:\n")
    async with SessionLocal() as db:
        session = await db.get(ChatSession, session.id)
        states = await orchestrator.build_claim_states(db, session)
        prior = [(q.text, r.answer_text) for q, r in await orchestrator._qa_rows(db, session.id)]
    openings: dict[str, question_engine.QuestionAttempt] = {}
    for s in states:
        attempt = await question_engine.generate_question(
            s.claim.text,
            ProbeLevel.VALIDATION,
            claim_type=s.claim.claim_type,
            claim_metric=s.claim.metric,
            job_family=session.job_family,
            prior_qa=prior,
            target_dimension=None,
            transfer=None,
            other_claims=[o.claim.text for o in states if o.claim.id != s.claim.id],
            target_claim_text=None,
        )
        openings[s.claim.id] = attempt
        print(
            f"  {s.claim.id}  ({taxonomy.claim_type_label(session.job_family, s.claim.claim_type)}, "
            f"weight {s.weight:g})\n"
            f"    question    {attempt.question}\n"
            f"    probe_level {attempt.probe_level.value}\n"
            f"    source      {attempt.source}   attempts={attempt.attempts}\n"
            f"    violations  {list(attempt.violations)}\n"
            f"    dimensions  {[d.value for d in signal_rubrics.dimensions_for_level(attempt.probe_level)]}\n"
        )
    block(
        "Reasoning",
        "  planner -> model -> validate() -> ONE regeneration -> fallback.\n"
        "  `validate()` applies seven rules in PURE PYTHON. The model produces,\n"
        "  Python decides -- the same pattern as `enforce_verbatim()`.\n"
        "  The regeneration cap is one, written as two explicit calls rather than\n"
        "  a loop: a loop invites raising the constant.\n"
        "  The FALLBACK IS NEVER VALIDATED -- it is rendered `On \"<claim>\" —\n"
        "  <base>`, so it quotes the claim and trips `answer_leakage` by\n"
        "  construction. A validator able to reject it would leave no path at all.",
    )
    path("api/engine/question.py::generate_question, validate, fallback_question  (prompt api/prompts/generate_question.txt)")

    # ---------------------------------------------------------------- STAGE 9
    stage("STAGE 9 — CONTRADICTION SURFACE and TRANSFER PROBES available later")
    keys = taxonomy.fact_keys(session.job_family)
    block(
        "Inputs",
        f"  family {session.job_family}; the consistency engine tracks facts only\n"
        f"  on these keys ({len(keys)} of them), and only on the STABLE ones is a\n"
        f"  divergence a contradiction rather than a before/after:",
    )
    block(
        "Outputs",
        "\n".join(
            f"    {k:<24} {spec['label']:<34} kind={spec['kind']:<10} "
            f"stable={taxonomy.fact_is_stable(session.job_family, k)}"
            for k, spec in keys.items()
        )
        + "\n\n  Transfer probe each claim would receive IF it stalls "
          "(select_transfer is pure and deterministic):\n"
        + "\n".join(
            f"    {s.claim.id}  operator={orchestrator.select_transfer(s.claim, signal_rubrics.merge_signals(s.answer_signals), [o.claim for o in states]).operator.value}\n"
            f"      basis        {orchestrator.select_transfer(s.claim, signal_rubrics.merge_signals(s.answer_signals), [o.claim for o in states]).basis}\n"
            f"      other_problem {orchestrator.select_transfer(s.claim, signal_rubrics.merge_signals(s.answer_signals), [o.claim for o in states]).other_problem!r}"
            for s in states
        ),
    )
    block(
        "Reasoning",
        "  Consistency is SESSION-LEVEL and applied once, as a multiplier -- it\n"
        "  is a property of the whole interview, not of any claim, and counting\n"
        "  it inside a claim as well would penalise the same fact twice.\n"
        "  The stable/variable split is why the engine does not flag every\n"
        "  improvement a candidate describes as a contradiction.\n"
        "  `select_transfer` takes NO job_family parameter, deliberately: two\n"
        "  candidates with identical evidence in unrelated industries must get\n"
        "  the identical probe, or the mechanism is a scenario library in\n"
        "  disguise and every new cohort becomes an engineering ticket.",
    )
    path("api/taxonomy.py::fact_keys, fact_is_stable · api/engine/consistency.py::check_new_facts, compare · api/engine/orchestrator.py::select_transfer")

    # --------------------------------------------------------------- STAGE 10
    stage("STAGE 10 — THE ACTUAL INTERVIEW (real handler, canned answers)")
    block(
        "Inputs",
        "  answers cycled from scripts/demo_resume_flow.CANNED, delivered through\n"
        "  api/routers/whatsapp.py::_handle exactly as a candidate's WhatsApp\n"
        "  message would be. The SEQUENCE BELOW IS CONDITIONED ON THESE ANSWERS:\n"
        "  plan_next reads the evidence each answer produced, so different\n"
        "  answers give a different -- equally deterministic -- tree.",
    )
    print("Outputs:\n")
    turn = 0
    while turn < settings.max_questions * 2:
        async with SessionLocal() as db:
            session = await db.get(ChatSession, session.id)
            if session is None or session.state == "COMPLETE":
                break
        answer = CANNED[turn % len(CANNED)]
        turn += 1
        print(f"  candidate answer {turn}: {answer[:70]}...")
        await _deliver(
            InboundMessage(
                channel=Channel.whatsapp,
                text=answer,
                external_id=args.phone.lstrip("+"),
                profile_name=args.name,
                provider_message_id=f"wamid.{_RUN}.a{turn}",
            )
        )
    path("api/routers/whatsapp.py::_handle -> api/engine/orchestrator.py::submit_answer -> ask_next -> plan_next -> generate_question")

    # ---------------------------------------------------------------- RESULTS
    async with SessionLocal() as db:
        questions = (
            await db.execute(
                select(Question).where(Question.session_id == session.id)
                .order_by(Question.order_index)
            )
        ).scalars().all()
        responses = {
            r.question_id: r
            for r in (
                await db.execute(
                    select(ResponseRow).where(ResponseRow.session_id == session.id)
                )
            ).scalars().all()
        }
        claims_by_id = {c.id: c for c in claims}
        graph = await graph_engine.build_candidate_graph(
            db, candidate.id, scope=TenantScope.of(candidate.tenant_id)
        )

    stage("EXACT Question ROWS AS PERSISTED")
    for q in questions:
        print(json.dumps(
            {c.name: (v.isoformat() if hasattr(v, "isoformat") else v)
             for c in Question.__table__.columns
             for v in [getattr(q, c.name)]},
            indent=2, ensure_ascii=False,
        ))
        print()

    stage("FINAL QUESTION TREE")
    for claim in claims:
        label = taxonomy.claim_type_label(session.job_family, claim.claim_type)
        print(f"{claim.id}  [{claim.claim_type}] {label}")
        print(f"  {claim.text}")
        for q in questions:
            if q.claim_id != claim.id:
                continue
            dims = [d.value for d in signal_rubrics.dimensions_for_level(ProbeLevel(q.probe_level))]
            resp = responses.get(q.id)
            print(
                f"    Q{q.order_index + 1}  {q.probe_level:<12} "
                f"target={q.target_dimension or '—':<20} dims={dims}"
                f"  source={q.source} attempts={q.attempts}"
                f"{' REPAIR' if q.is_repair else ''}"
            )
            print(f"        {q.text}")
            if resp is not None:
                print(f"        -> signals_found={resp.signals_found}")
        print()

    stage("FINAL INTERVIEW PREVIEW")
    for i, claim in enumerate(claims, 1):
        asked = [q for q in questions if q.claim_id == claim.id]
        opening = openings.get(claim.id)
        explored = sorted({
            d for q in asked
            for d in signal_rubrics.dimensions_for_level(ProbeLevel(q.probe_level))
        }, key=lambda d: d.value)
        print(f"Claim {i}:")
        print(f"- Claim text     {claim.text}")
        print(f"- Company        NOT RECORDED — no such field exists (see STAGE 5)")
        print(f"- Claim type     {claim.claim_type} — "
              f"{taxonomy.claim_type_label(session.job_family, claim.claim_type)} "
              f"(weight {weights.get(claim.claim_type, 0.0)})")
        print(f"- Metric         {claim.metric!r}")
        print(f"- First question {asked[0].text if asked else (opening.question if opening else '—')}")
        print(f"- Probe focus    {taxonomy.probe_focus(session.job_family, claim.claim_type)}")
        print(f"- Dimensions explored {[d.value for d in explored]}")
        print()

    stage("FULL QUESTION FLOW")
    for q in questions:
        print(f"Q{q.order_index + 1}  [{q.probe_level}"
              f"{' · REPAIR' if q.is_repair else ''}"
              f"{' · target ' + q.target_dimension if q.target_dimension else ''}]")
        print(f"  {q.text}\n")

    if graph is not None:
        stage("RECRUITER VIEW (graph.build_candidate_graph)")
        print(f"  job_family_label     {graph.job_family_label}")
        print(f"  routing_confidence   {graph.routing_confidence}")
        print(f"  questions_asked      {graph.questions_asked}")
        print(f"  resume_score         {graph.resume_score}")
        print(f"  weighted_evidence    {graph.weighted_evidence_score}")
        print(f"  competence_score     {graph.competence_score}")
        print(f"  badge                {graph.badge.value}")
        print(f"  role_coverage        {graph.role_coverage}")
        print(f"  dimensions probed    "
              f"{sum(1 for d in graph.dimension_profile if d.probed)} of {len(graph.dimension_profile)}")
        for d in graph.dimension_profile:
            print(f"    {'x' if d.probed else '·'} {d.dimension.value:<20} {d.score:>3}  {d.basis}")
        print(f"  consistency          score={graph.consistency.score} "
              f"multiplier={graph.consistency.multiplier} "
              f"facts_tracked={graph.consistency.facts_tracked}")
        for c in graph.consistency.contradictions:
            print(f"    [{c.severity.value}] {c.fact_label or c.fact_key}: "
                  f"{c.earlier_value!r} -> {c.later_value!r}")

    print(f"\nllm cache stats: {llm.cache_stats()}")
    print(f"model_returned:  {llm.model_returned()}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("resume")
    parser.add_argument("--phone", default="+919810070042")
    parser.add_argument("--name", default="Pipeline Inspection")
    parser.add_argument("--fresh", action="store_true")
    raise SystemExit(asyncio.run(main(parser.parse_args())))
