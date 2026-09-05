"""
Rehearse the entire candidate journey locally, with no WhatsApp.

    python scripts/demo_resume_flow.py ~/Downloads/resume.pdf

WHY THIS EXISTS, WHEN THREE OTHER PATHS ALREADY RUN AN INTERVIEW
----------------------------------------------------------------
`POST /api/candidates` parses a resume, `POST /api/dev/simulate` runs a whole
interview, and `tests/conftest.run_interview` drives one through the dev
endpoints. None of the three touches the demo path:

  * they enter through the candidates router or `/api/dev/*`, so
    `_try_resume_intake` -- the function G3 added, and the one the demo depends
    on -- is never called;
  * `/api/dev/*` writes `Channel.simulated`, which the contract calls "never a
    real candidate";
  * the two onboarding acknowledgements and the completion summary live in the
    webhook handler, so none of them are exercised either.

So this drives `routers.whatsapp._handle` -- the real handler -- and stubs
exactly ONE function:

    whatsapp_channel.download_media()

That is the only thing in the path that needs a Meta token. Everything else is
production code: parse_inbound's document branch, _claim_once, the mime
detection, extract_text, _onboard, create_session, ask_next, submit_answer,
evidence extraction, consistency, scoring, finalize, and the G6 summary.

The one deliberate difference from production: `handle_message`'s try/except is
skipped, because it exists to send the candidate an apology and here we would
rather see the traceback.

THIS SCRIPT MAKES REAL MODEL CALLS when OPENAI_API_KEY is set, unlike seed.py
and scripts/replay.py which clear it. That is the point -- a rehearsal that
runs the heuristics is not a rehearsal of the demo.

    python scripts/demo_resume_flow.py resume.pdf                 # you answer
    python scripts/demo_resume_flow.py resume.pdf --auto          # canned
    python scripts/demo_resume_flow.py resume.pdf --fresh         # reset first
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from api.channels.whatsapp_cloud import whatsapp_channel  # noqa: E402
from api.config import settings  # noqa: E402
from api.db import SessionLocal, drop_all, init_models  # noqa: E402
from api.engine import graph as graph_engine  # noqa: E402
from api.models import Candidate, ChatSession, Claim, Question  # noqa: E402
from api.models import Response as ResponseRow  # noqa: E402
from api.routers import whatsapp as webhook  # noqa: E402
from api.schemas import Channel, InboundMessage  # noqa: E402
from api.tenancy import TenantScope  # noqa: E402

# Inverted from the production map, not retyped, so the two cannot drift.
_MIME_FOR = {suffix: mime for mime, suffix in webhook._RESUME_SUFFIX.items()}

# Enough of an answer to move a rubric. Cycled; --auto only.
CANNED = [
    "I owned it end to end. I ran the roadmap with the founders and engineering, "
    "and I was the one who decided what shipped each week.",
    "The number came from our Mixpanel funnel, measured weekly as activated users "
    "over installs. I reviewed it every Monday against the retention cohort.",
    "One release went badly. We shipped a checkout change on a Friday and "
    "conversion dropped about eight percent overnight, so I rolled it back "
    "myself on the Saturday morning and we shipped it again on the Tuesday "
    "behind a flag.",
    "We ran it in Mixpanel and Figma, with the tickets in Linear and the "
    "partner data in HubSpot. I pulled the funnel report before every standup.",
    "Afterwards conversion held at the new level for two quarters. Looking back "
    "I would have put it behind a flag the first time instead of the second.",
]

_OUTBOUND: list[str] = []


def _install_stubs(data: bytes, mime: str) -> None:
    """The ONE seam. `download_media` is what needs a Meta token; nothing else."""

    async def _download(media_id: str):
        return data, mime

    async def _send_text(to: str, text: str):
        _OUTBOUND.append(text)
        print(f"\n\033[36m┌─ WhatsApp → {to}\033[0m")
        for line in text.splitlines() or [""]:
            print(f"\033[36m│\033[0m {line}")
        print("\033[36m└─\033[0m")
        return True

    async def _mark_read(provider_message_id: str):
        return True

    whatsapp_channel.download_media = _download
    whatsapp_channel.send_text = _send_text
    whatsapp_channel.mark_read = _mark_read


async def _deliver(message: InboundMessage) -> None:
    """One inbound message through the production handler, in its own session.

    `_handle`, not `handle_message`: the wrapper's job is to apologise to the
    candidate on an exception, and in a rehearsal the traceback is worth more.
    """
    async with SessionLocal() as db:
        await webhook._handle(db, message)


async def _session_for(phone: str) -> tuple[Candidate | None, ChatSession | None]:
    async with SessionLocal() as db:
        candidate = (
            await db.execute(
                select(Candidate)
                .where(Candidate.phone == phone)
                .order_by(Candidate.created_at.desc(), Candidate.id)
            )
        ).scalars().first()
        if candidate is None:
            return None, None
        session = (
            await db.execute(
                select(ChatSession)
                .where(ChatSession.candidate_id == candidate.id)
                .order_by(ChatSession.started_at.desc(), ChatSession.id)
            )
        ).scalars().first()
        return candidate, session


async def _print_ids(candidate: Candidate, session: ChatSession) -> None:
    async with SessionLocal() as db:
        claims = (
            await db.execute(
                select(Claim).where(Claim.candidate_id == candidate.id)
                .order_by(Claim.order_index)
            )
        ).scalars().all()

    print("\n\033[1mCREATED\033[0m")
    print(f"  Candidate ID : {candidate.id}   ({candidate.name})")
    print(f"  Session ID   : {session.id}")
    print(f"  Job family   : {session.job_family}")
    print(f"  Opt-in code  : {session.opt_in_code}  (unused — the resume IS the opt-in)")
    print(f"  Claims       : {len(claims)}")
    for claim in claims:
        metric = f"  [{claim.metric}]" if claim.metric else ""
        print(f"    {claim.id}  {claim.claim_type:<18}{metric}")
        print(f"      {claim.text[:96]}")


async def _print_turn(session_id: str) -> None:
    """The planner's reasoning for the question just asked. Not sent to anyone —
    printed here because it is what makes the adaptive probing visible."""
    async with SessionLocal() as db:
        question = (
            await db.execute(
                select(Question).where(Question.session_id == session_id)
                .order_by(Question.order_index.desc())
            )
        ).scalars().first()
        if question is None:
            return
        print(
            f"\033[90m   ↳ {question.id} · claim {question.claim_id} · "
            f"probe {question.probe_level} · dim {question.target_dimension or '—'} · "
            f"source {question.source} (attempt {question.attempts})"
            f"{' · REPAIR' if question.is_repair else ''}\033[0m"
        )


async def _final_report(candidate_id: str, tenant_id: str) -> None:
    """The recruiter's view, via the exact function the dashboard calls."""
    async with SessionLocal() as db:
        graph = await graph_engine.build_candidate_graph(
            db, candidate_id, scope=TenantScope.of(tenant_id)
        )
        responses = (
            await db.execute(
                select(ResponseRow).join(
                    ChatSession, ChatSession.id == ResponseRow.session_id
                ).where(ChatSession.candidate_id == candidate_id)
            )
        ).scalars().all()

    if graph is None:
        print("no graph — nothing was scored")
        return

    print("\n" + "=" * 68)
    print("\033[1mRECRUITER VIEW\033[0m   graph.build_candidate_graph() — the dashboard's own call")
    print("=" * 68)
    print(f"  Candidate            {graph.candidate.name}  ({graph.candidate.id})")
    print(f"  Job family           {graph.job_family_label}  "
          f"(routing confidence {graph.routing_confidence:.3f})"
          if graph.routing_confidence is not None else
          f"  Job family           {graph.job_family_label}")
    print(f"  Questions asked      {graph.questions_asked}")
    print(f"  Responses stored     {len(responses)}")
    print()
    print(f"  \033[1mResume score         {graph.resume_score:>3}\033[0m   "
          f"keyword overlap — what a GenAI-optimised resume maximises")
    print(f"  Evidence score       {graph.weighted_evidence_score:>3}   before consistency")
    print(f"  \033[1mCompetence score     {graph.competence_score:>3}\033[0m   after consistency")
    print(f"  Badge                {graph.badge.value}")
    print(f"  Role coverage        {graph.role_coverage}")
    print()

    probed = [d for d in graph.dimension_profile if d.probed]
    print(f"  \033[1mDIMENSION COVERAGE\033[0m  {len(probed)} of {len(graph.dimension_profile)} probed")
    for dim in graph.dimension_profile:
        bar = "█" * round(dim.score / 5)
        flag = " " if dim.probed else "·"
        print(f"    {flag} {dim.dimension.value:<20} {dim.score:>3}  {bar}")

    print(f"\n  \033[1mCLAIMS\033[0m  {len(graph.claims)}")
    for claim in graph.claims:
        print(f"    {claim.claim_type_label} — score {claim.claim_score}, "
              f"{claim.probed_dimensions} dims probed, {len(claim.qa)} turns")
        print(f"      {claim.text[:88]}")

    consistency = graph.consistency
    print(f"\n  \033[1mCONSISTENCY\033[0m  score {consistency.score}, "
          f"multiplier {consistency.multiplier:.2f}, "
          f"{consistency.facts_tracked} facts tracked")
    if consistency.contradictions:
        for contradiction in consistency.contradictions:
            print(f"    \033[31m✗\033[0m {contradiction.summary}")
    else:
        print("    none")
    print("=" * 68)


async def run(args: argparse.Namespace) -> int:
    path = Path(args.resume).expanduser()
    if not path.exists():
        print(f"no such file: {path}")
        return 1
    mime = _MIME_FOR.get(path.suffix.lower())
    if mime is None:
        print(f"unsupported: {path.suffix!r}. Accepted: "
              f"{', '.join(sorted(_MIME_FOR))}")
        return 1

    if args.fresh:
        await drop_all()
    await init_models()

    data = path.read_bytes()
    _install_stubs(data, mime)

    print(f"\033[1mProofScreen — local candidate journey\033[0m")
    print(f"  resume    {path.name}  ({len(data):,} bytes, {mime})")
    print(f"  llm       {settings.llm_mode}  ({settings.openai_model})")
    print(f"  database  {settings.database_url}")
    print(f"  phone     {args.phone}")
    print("\n\033[90m--- the candidate sends their resume on WhatsApp ---\033[0m")

    await _deliver(
        InboundMessage(
            channel=Channel.whatsapp,
            media_id="media.LOCAL1",
            external_id=args.phone.lstrip("+"),
            profile_name=args.name,
            provider_message_id="wamid.LOCAL1",
        )
    )

    candidate, session = await _session_for(args.phone)
    if candidate is None or session is None:
        print("\nonboarding produced no candidate — see the output above")
        return 1
    await _print_ids(candidate, session)
    await _print_turn(session.id)

    turn = 0
    while turn < 40:
        _, session = await _session_for(args.phone)
        if session is None or session.state == "COMPLETE":
            break

        if args.auto:
            answer = CANNED[turn % len(CANNED)]
            print(f"\n\033[33mAnswer> \033[0m{answer}")
        else:
            try:
                answer = input("\n\033[33mAnswer> \033[0m").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n\nstopped. The session is still open; re-run to continue.")
                return 130
            if not answer:
                continue
            if answer in ("/quit", "/q"):
                print("stopped.")
                return 0

        turn += 1
        await _deliver(
            InboundMessage(
                channel=Channel.whatsapp,
                text=answer,
                external_id=args.phone.lstrip("+"),
                profile_name=args.name,
                provider_message_id=f"wamid.LOCALA{turn}",
            )
        )
        _, session = await _session_for(args.phone)
        if session is not None and session.state != "COMPLETE":
            await _print_turn(session.id)

    await _final_report(candidate.id, candidate.tenant_id)
    print(f"\nDashboard: GET /api/recruiter/candidates/{candidate.id}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("resume", help="path to a PDF, DOCX, TXT or MD resume")
    parser.add_argument("--phone", default="+919810070001")
    parser.add_argument("--name", default="Local Rehearsal")
    parser.add_argument("--auto", action="store_true", help="canned answers")
    parser.add_argument("--fresh", action="store_true", help="drop every table first")
    parser.add_argument("--verbose", action="store_true", help="show engine logs")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="\033[90m%(name)-26s %(message)s\033[0m",
    )
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
