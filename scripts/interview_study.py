"""
P3-01 / P3-02 / P3-04 — the Real Interview Validation Study harness.

    python scripts/interview_study.py generate --limit 2      # costed pilot
    python scripts/interview_study.py generate                # full run
    python scripts/interview_study.py sample                  # blind review file
    python scripts/interview_study.py score                   # matrix + disagreements

WHAT THIS IS FOR
----------------
`tests/data/question_golden.json` reads 100% on M6a/M6b/M6c/M6h. That makes it
a REGRESSION DETECTOR: it was authored by the same person who wrote the rules,
so it can tell you `validate()` got worse and cannot tell you whether it is
good. This harness runs the real pipeline against a real model and asks a blind
human whether the validator's calls were right.

Design in docs/PHASE_3_VALIDATION_STUDY.md. Three things from it are load-bearing
here and easy to undo by accident:

1. **`api/` IS NOT MODIFIED BY THIS PHASE.** Acceptance criterion 1 is
   `git diff --stat api/` empty. Everything below is instrumentation wrapped
   AROUND production code from outside it — `_spy_on_validator()` and
   `_count_tokens()` monkeypatch at the module boundary and restore on exit.
   If something here starts wanting an `api/` edit, the design was wrong: stop
   and raise it, do not edit.

2. **The rejected question text is never persisted** (plan §0 F1).
   `orchestrator.ask_next()` stores the FINAL text; `QuestionAttempt` carries
   attempt-1's violations but not attempt-1's words. So every validator REJECT
   is a question that exists nowhere. That is why this file instruments
   `validate()` — it is called once per attempt with that attempt's exact text
   — instead of reading the `questions` table. One row per generated ATTEMPT,
   not per persisted question.

3. **A fallback is not an accept** (plan §0 F2). Two paths return
   `source="fallback"` and neither was validated, by design. Those rows carry
   `validation_result="not_evaluated"` and a BLANK `accepted_by_validator` —
   never `false`. They are excluded from the confusion matrix and reported as
   M7e coverage. Scoring them as accepts would report agreement on a call the
   validator was never asked to make.

THE MODEL IS STILL NEVER THE JUDGE. The candidate simulator plays the
CANDIDATE. `validate()` stays pure Python and is the thing under test; nothing
in `score` asks a model anything. CLAUDE.md rule 1 is untouched.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import math
import os
import random
import sys
from collections import Counter, defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Overridable so a later phase can run the same three commands over its own
# directory without a second copy of this file. Defaults to Phase 3's, which is
# where the committed study lives.
OUT_DIR = Path(os.environ.get("STUDY_DIR") or (ROOT / "studies" / "phase3"))

# Set BEFORE api.config is imported anywhere, exactly as tests/conftest.py does.
# A file rather than :memory: so `interview_id` joins to a real `sessions.id`
# afterwards and the run stays inspectable (acceptance criterion 6).
OUT_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{OUT_DIR / 'study.sqlite3'}")
os.environ.setdefault("ADAPTIVE_PROBING", "true")
os.environ.setdefault("TRANSFER_PROBE", "true")
os.environ.setdefault("QUESTION_VALIDATION", "true")
os.environ.setdefault("REPAIR_TURN", "true")
os.environ.setdefault("SCORE_INLINE", "true")

from pydantic import BaseModel  # noqa: E402

from api import ids  # noqa: E402
from api.config import settings  # noqa: E402
from api.db import SessionLocal, drop_all  # noqa: E402
from api.engine import orchestrator  # noqa: E402
from api.engine import question as question_engine  # noqa: E402
from api.ingest.parse import normalise  # noqa: E402
from api.llm import complete_json  # noqa: E402
from api.models import Candidate, Resume  # noqa: E402
from api.schemas import Channel  # noqa: E402

DATASET = OUT_DIR / os.environ.get("STUDY_DATASET", "real_question_dataset.csv")
SAMPLE = OUT_DIR / "human_review_sample.csv"
SAMPLE_KEY = OUT_DIR / ".sample_key.csv"
MATRIX = OUT_DIR / "confusion_matrix.md"
DISAGREEMENTS = OUT_DIR / "validator_disagreements.md"

# Hard stop well above `max_questions`, because repair turns are off-budget and
# so do not count against it. 20 is the same guard tests/conftest uses.
MAX_TURNS = 20


# ---------------------------------------------------------------------------
# cost accounting  (plan §0 C-i — "cost is a constraint, not a footnote")
# ---------------------------------------------------------------------------

# USD per 1M tokens. Hard-coded and therefore going stale: these are list prices
# as of 2026-09, and the dollar figure is an ESTIMATE for sizing a run, never an
# invoice. The token counts beside it are measured and exact.
PRICES: dict[str, tuple[float, float]] = {
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
}


@dataclass
class Usage:
    by_model: dict[str, list[int]] = field(default_factory=lambda: defaultdict(lambda: [0, 0, 0]))

    def add(self, model: str, prompt: int, completion: int) -> None:
        row = self.by_model[model]
        row[0] += 1
        row[1] += prompt
        row[2] += completion

    @property
    def calls(self) -> int:
        return sum(r[0] for r in self.by_model.values())

    def dollars(self) -> float:
        total = 0.0
        for model, (_calls, pin, pout) in self.by_model.items():
            rate_in, rate_out = PRICES.get(model, PRICES["gpt-4o"])
            total += pin / 1e6 * rate_in + pout / 1e6 * rate_out
        return total

    def report(self) -> str:
        lines = [f"{'model':<16}{'calls':>8}{'in':>12}{'out':>10}{'USD':>10}"]
        for model, (calls, pin, pout) in sorted(self.by_model.items()):
            rate_in, rate_out = PRICES.get(model, PRICES["gpt-4o"])
            cost = pin / 1e6 * rate_in + pout / 1e6 * rate_out
            lines.append(f"{model:<16}{calls:>8}{pin:>12,}{pout:>10,}{cost:>10.4f}")
        lines.append(f"{'TOTAL':<16}{self.calls:>8}{'':>12}{'':>10}{self.dollars():>10.4f}")
        return "\n".join("  " + line for line in lines)


USAGE = Usage()


def _count_tokens() -> None:
    """Wrap the OpenAI client's create() to record usage.

    Wrapping the CLIENT rather than `api.llm._raw_completion` is deliberate:
    `_raw_completion` returns only the message content and throws the `usage`
    block away, so counting there would mean estimating tokens from string
    length. This reads the number the bill is computed from.
    """
    if not settings.llm_enabled:
        return
    from api import llm

    client = llm._get_client()
    original = client.chat.completions.create

    async def counted(**kwargs):
        resp = await original(**kwargs)
        usage = getattr(resp, "usage", None)
        if usage is not None:
            USAGE.add(kwargs.get("model", "?"), usage.prompt_tokens, usage.completion_tokens)
        return resp

    client.chat.completions.create = counted


@contextmanager
def _model(name: str | None):
    """Run a block against a different model.

    Used for ONE thing: the candidate simulator is not under test, so it runs on
    the cheap model while question generation — which IS under test — stays on
    production's. Safe because interviews run strictly serially; if this file
    ever grows concurrency, this has to go first.
    """
    if not name or name == settings.openai_model:
        yield
        return
    previous = settings.openai_model
    settings.openai_model = name
    try:
        yield
    finally:
        settings.openai_model = previous


# ---------------------------------------------------------------------------
# the validator instrument  (plan §0 F1, Decision 2)
# ---------------------------------------------------------------------------


@dataclass
class Attempt:
    """One call to `validate()`, with the exact text that was judged."""

    question: str
    accepted: bool
    violations: tuple[str, ...]


@dataclass
class Generation:
    """One `generate_question()` call: its attempts, and what came out."""

    attempts: list[Attempt]
    result: object          # question_engine.QuestionAttempt
    kwargs: dict


_pending: list[Attempt] = []
_generations: list[Generation] = []
_consumed: set[int] = set()


def _take_generation(question_text: str) -> Generation | None:
    """The generation that produced this question, consumed once.

    WHY THIS IS NOT "the last generation".  `orchestrator.submit_answer()` calls
    `ask_next()` itself (orchestrator.py:1047), so the NEXT question is generated
    at the tail of the PREVIOUS turn. A driver that clears the buffer at the top
    of each turn therefore throws away every generation but the first, and
    `ask_next()` then returns the already-open question without generating
    anything — so 45 of 61 rows fell through to the database branch and read
    `validator_ran=False` on questions the validator had in fact judged.

    Measured, not reasoned: the $0.47 pilot reported M7e coverage of 14.8% while
    `questions.source` said 45 model + 9 regenerated. That contradiction is what
    exposed it, and it is why the plan puts a costed pilot before the full run.

    Matching on text and consuming keeps it correct whatever order the
    orchestrator generates in.
    """
    for index, generation in enumerate(_generations):
        if index not in _consumed and generation.result.question == question_text:
            _consumed.add(index)
            return generation
    return None


@contextmanager
def _spy_on_validator():
    """Record every validator decision and every generation, then put it back.

    Patches at the MODULE level. `generate_question()` calls the module-global
    `validate` through its local `check()` closure, and `orchestrator` calls
    `question_engine.generate_question` as a module attribute — both resolve at
    call time, so both see the wrapper. Neither is imported by value anywhere,
    which is the property this depends on.
    """
    real_validate = question_engine.validate
    real_generate = question_engine.generate_question

    def spy_validate(question, **kwargs):
        result = real_validate(question, **kwargs)
        _pending.append(Attempt(question, result.accepted, tuple(result.violations)))
        return result

    async def spy_generate(*args, **kwargs):
        _pending.clear()
        result = await real_generate(*args, **kwargs)
        _generations.append(Generation(list(_pending), result, dict(kwargs)))
        _pending.clear()
        return result

    question_engine.validate = spy_validate
    question_engine.generate_question = spy_generate
    try:
        yield
    finally:
        question_engine.validate = real_validate
        question_engine.generate_question = real_generate


def _rows_for(gen: Generation) -> list[dict]:
    """Turn one generation into one row per question it produced.

    `attempt_index` is the position among questions produced for this planner
    slot; `is_final` marks the one actually sent. The two are different because
    a twice-rejected generation produces THREE texts — attempt 1, attempt 2, and
    the unvalidated fallback that got asked — and all three are questions the
    system generated. Collapsing them would discard exactly the rows the study
    exists to look at.
    """
    result = gen.result
    rows: list[dict] = []
    for index, attempt in enumerate(gen.attempts, start=1):
        rows.append(
            {
                "attempt_index": index,
                "generated_question": attempt.question,
                "validator_ran": True,
                "validation_result": "accept" if attempt.accepted else "reject",
                "accepted_by_validator": attempt.accepted,
                "violations": "|".join(attempt.violations),
                "primary_rule": attempt.violations[0] if attempt.violations else "",
                "source": "",
                "is_final": False,
            }
        )
    # Did the text that was actually asked appear among the validated attempts?
    asked = result.question
    for row in rows:
        if row["generated_question"] == asked:
            row["is_final"] = True
            row["source"] = result.source
    if not any(r["is_final"] for r in rows):
        # A fallback, or validation disabled: generated, asked, never judged.
        rows.append(
            {
                "attempt_index": len(rows) + 1,
                "generated_question": asked,
                "validator_ran": False,
                "validation_result": "not_evaluated",
                "accepted_by_validator": "",
                "violations": "",
                "primary_rule": "",
                "source": result.source,
                "is_final": True,
            }
        )
    return rows


# ---------------------------------------------------------------------------
# the candidate simulator  (Decision 3)
# ---------------------------------------------------------------------------


class SimulatedAnswer(BaseModel):
    answer: str


# NOT in api/prompts/. This is a study instrument, not production, and putting
# it there would be an `api/` edit (acceptance criterion 1).
#
# The instruction is "answer in character from this resume", NOT "answer well"
# or "answer evasively". Steering the candidate toward a quality band would make
# the question stream a function of my steering rather than of the pipeline. The
# one nudge is the last line, and it is a fidelity instruction: a real candidate
# whose resume does not support the question gets vague, and a simulator that
# never does that would mean no claim ever stalls, so TRANSFER and the repair
# turn would never fire.
_SIMULATOR_PROMPT = """You are playing a job candidate answering an interview question over WhatsApp.

THEIR RESUME
$resume

THE CONVERSATION SO FAR
$prior

THE QUESTION JUST ASKED
$question

Reply as this candidate would, in first person, 2-5 sentences, plain WhatsApp
register. Stay consistent with the resume and with anything you already said.
Invent concrete specifics where the resume supports them.

If the resume does not really support an answer to this question, be vague and
move on, the way a real person does. Do not announce that you are being vague.

Return JSON: {"answer": "..."}"""


async def _simulate_answer(resume: str, prior: list[tuple[str, str]], question: str, model: str) -> str:
    from string import Template

    prompt = Template(_SIMULATOR_PROMPT).safe_substitute(
        resume=resume[:2000],
        prior="\n\n".join(f"Q: {q}\nA: {a}" for q, a in prior[-4:]) or "(nothing yet)",
        question=question,
    )
    with _model(model):
        result = await complete_json(
            prompt,
            SimulatedAnswer,
            temperature=0.7,
            # CLAUDE.md rule 5 — every call has a fallback. A non-answer is the
            # honest one: if the simulator is down, the candidate said nothing.
            fallback=lambda: SimulatedAnswer(answer="I don't remember the details."),
            cache=False,
        )
    return (result.answer or "").strip() or "I don't remember the details."


# A family-neutral pool, one per probe level. Used by --no-simulator, which is
# the zero-model-cost run. Bland ON PURPOSE: this is the option the plan warns
# understates the generator, and it exists so a run is possible with no budget
# at all, not because it is as good.
_NEUTRAL_ANSWERS = {
    "VALIDATION": "It was about twenty of them, over roughly six months, and I owned it end to end.",
    "OPERATIONAL": "Every morning I pulled the report, went through the exceptions, then handed the summary to my manager.",
    "INCIDENT": "There was one week where it all went wrong at once and I had to stay late to clear the backlog.",
    "DECISION": "I decided to fix the process rather than add headcount, because headcount would have taken too long.",
    "OUTCOME": "It improved over the next quarter and we held it there. I would start measuring earlier next time.",
    "TRANSFER": "I would start by looking at where the numbers diverge, then rule out the obvious causes one at a time.",
}


# ---------------------------------------------------------------------------
# the interview matrix  (plan §3)
# ---------------------------------------------------------------------------


@dataclass
class Spec:
    interview_id: str
    tier: str
    persona: str
    family: str
    resume: str
    jd: str | None
    answers: dict[str, list[str]] | None      # Tier A only
    run_seed: int


def _load_seed_personas() -> list[dict]:
    """Import seed.py's personas WITHOUT letting it disable the model.

    `seed.py` sets `settings.openai_api_key = None` at module scope, on purpose
    — seeding must be free, instant and offline. Importing it here would put
    this whole study into fixture mode, silently, and every question would be a
    hard-coded fallback. So the key is saved and restored around the import.

    Re-declaring the four personas here instead would be a drifting copy of
    seed.py, which is worse: the day someone edits Priya's answers, this study
    would quietly stop testing the same candidate the demo shows.
    """
    saved = settings.openai_api_key
    try:
        import seed as seed_module
        return list(seed_module.SEEDS)
    finally:
        settings.openai_api_key = saved


def build_matrix(repeats: int, tier_b_limit: int | None, base_seed: int) -> list[Spec]:
    specs: list[Spec] = []

    # Tier A — authored answers, realistic multi-turn threads. Rohit is why this
    # tier is not optional: he stalls, so TRANSFER and the repair turn fire, and
    # acceptance criteria 5 needs at least one of each.
    for repeat in range(repeats):
        for person in _load_seed_personas():
            key = person["name"].split()[0].lower()
            specs.append(
                Spec(
                    interview_id=f"A-{key}-r{repeat + 1}",
                    tier="A",
                    persona=person["name"],
                    family=person.get("job_family", "bpo_operations"),
                    resume=person["resume"],
                    jd=person.get("jd"),
                    answers={k: list(v) for k, v in person["answers"].items()},
                    run_seed=base_seed + repeat,
                )
            )

    # Tier B — family breadth. 60 labelled resumes across 8 families + general.
    golden = json.loads((ROOT / "tests" / "data" / "routing_golden.json").read_text())
    labelled = [r for r in golden["resumes"] if r.get("family")]
    if tier_b_limit is not None:
        if tier_b_limit <= 0:
            labelled = []
        else:
            # Stride rather than truncate: a pilot must not be six BPO resumes
            # in a row, or it measures one family and reports a cost for nine.
            step = max(1, len(labelled) // tier_b_limit)
            labelled = labelled[::step][:tier_b_limit]
    for entry in labelled:
        specs.append(
            Spec(
                interview_id=f"B-{entry['id']}",
                tier="B",
                persona=entry["id"],
                family=entry["family"],
                resume=entry["text"],
                jd=None,
                answers=None,
                run_seed=base_seed,
            )
        )
    return specs


# ---------------------------------------------------------------------------
# generate
# ---------------------------------------------------------------------------

FIELDS = [
    "interview_id", "run_seed", "tier", "persona", "family", "answer_fidelity",
    "claim_id", "claim", "claim_type", "claim_metric",
    "probe_level", "target_dimension", "order_index", "attempt_index",
    "generated_question",
    "validator_ran", "validation_result", "accepted_by_validator",
    "violations", "primary_rule",
    "source", "attempts", "is_repair", "is_final",
    "model", "temperature",
]


async def _run_interview(db, spec: Spec, simulator_model: str | None) -> list[dict]:
    from api.models import Claim

    rng = random.Random(spec.run_seed)
    candidate = Candidate(
        id=ids.candidate_id(),
        name=spec.persona,
        role="study",
        phone=f"+9199{rng.randrange(10**8):08d}",
        email=f"{spec.interview_id.lower()}@study.invalid",
        job_family=spec.family,
    )
    resume = Resume(
        id=ids.resume_id(),
        candidate_id=candidate.id,
        raw_text=normalise(spec.resume),
        filename=f"{spec.interview_id}.pdf",
        job_description=spec.jd or settings.default_job_description,
    )
    db.add(candidate)
    db.add(resume)
    await db.commit()

    _generations.clear()
    _consumed.clear()
    session, claims = await orchestrator.create_session(db, candidate, resume, Channel.simulated)
    claim_by_id = {c.id: c for c in claims}
    pools = {k: list(v) for k, v in (spec.answers or {}).items()}
    used: Counter = Counter()

    fidelity = "authored" if spec.answers else ("simulated" if simulator_model else "neutral")
    rows: list[dict] = []
    seen: set[str] = set()
    prior: list[tuple[str, str]] = []

    for _turn in range(MAX_TURNS):
        question = await orchestrator.ask_next(db, session)
        if question is None:
            break

        claim = claim_by_id.get(question.claim_id) or await db.get(Claim, question.claim_id)
        base = {
            "interview_id": session.id,
            "run_seed": spec.run_seed,
            "tier": spec.tier,
            "persona": spec.persona,
            "family": spec.family,
            "answer_fidelity": fidelity,
            "claim_id": question.claim_id,
            "claim": claim.text if claim else "",
            "claim_type": claim.claim_type if claim else "",
            "claim_metric": (claim.metric if claim else "") or "",
            "probe_level": question.probe_level,
            "target_dimension": question.target_dimension or "",
            "order_index": question.order_index,
            "attempts": question.attempts,
            "is_repair": question.is_repair,
            "model": settings.openai_model,
            "temperature": settings.llm_temperature_question,
        }

        if question.id not in seen:
            seen.add(question.id)
            generation = None if question.is_repair else _take_generation(question.text)
            if generation is None:
                # A repair makes no model call and is never validated — it is a
                # fixed line by design. It is still a question that was asked,
                # so it is in the dataset, marked not_evaluated.
                rows.append({**base, **{
                    "attempt_index": 1,
                    "generated_question": question.text,
                    "validator_ran": False,
                    "validation_result": "not_evaluated",
                    "accepted_by_validator": "",
                    "violations": "",
                    "primary_rule": "",
                    "source": question.source,
                    "is_final": True,
                }})
            else:
                for row in _rows_for(generation):
                    rows.append({**base, **row})

        if pools:
            claim_type = claim.claim_type if claim else ""
            pool = pools.get(claim_type) or ["I don't remember the details."]
            answer = pool[min(used[claim_type], len(pool) - 1)]
            used[claim_type] += 1
        elif simulator_model:
            answer = await _simulate_answer(spec.resume, prior, question.text, simulator_model)
        else:
            answer = _NEUTRAL_ANSWERS.get(question.probe_level, _NEUTRAL_ANSWERS["VALIDATION"])

        prior.append((question.text, answer))
        await orchestrator.submit_answer(db, session, text=answer, channel=Channel.simulated)
        await db.refresh(session)
        if session.completed_at is not None:
            break

    await db.refresh(session)
    if session.completed_at is None:
        await orchestrator.finalize(db, session)
    return rows


async def cmd_generate(args: argparse.Namespace) -> int:
    if DATASET.exists() and not args.force and not args.resume:
        print(f"{DATASET} exists. Use --force to overwrite or --resume to continue.")
        return 1

    mode = settings.llm_mode
    if mode == "fixture":
        print(
            "\n  !! FIXTURE MODE — THIS IS A PLUMBING SMOKE TEST, NOT A STUDY.\n"
            "     With no OPENAI_API_KEY, complete_json() returns the fallback,\n"
            "     generate_question() takes the from_fallback branch and validate()\n"
            "     is NEVER CALLED. Every row will read source=fallback and carry no\n"
            "     validator decision. Do not compute a confusion matrix from it.\n"
        )

    simulator = None if args.no_simulator else args.simulator_model
    specs = build_matrix(args.repeats, args.limit, args.run_seed)

    done: set[str] = set()
    existing: list[dict] = []
    if args.resume and DATASET.exists():
        with DATASET.open(newline="", encoding="utf-8") as fh:
            existing = list(csv.DictReader(fh))
        done = {r["persona"] + "|" + r["run_seed"] for r in existing}
        print(f"  resuming: {len(existing)} rows, {len(done)} interviews already done")

    print(f"  mode={mode} model={settings.openai_model} simulator={simulator or 'off'}")
    print(f"  interviews={len(specs)} (tier A {sum(1 for s in specs if s.tier=='A')}, "
          f"tier B {sum(1 for s in specs if s.tier=='B')})\n")

    if not args.resume:
        await drop_all()
    rows: list[dict] = list(existing)

    failures = 0
    with _spy_on_validator():
        _count_tokens()
        for index, spec in enumerate(specs, start=1):
            if spec.persona + "|" + str(spec.run_seed) in done:
                continue
            # ONE SESSION PER INTERVIEW, not one for the run. Interviews are
            # independent, and a shared session makes them anything but: a single
            # IntegrityError leaves the session in "transaction has been rolled
            # back" and EVERY interview after it fails on the same dead statement.
            # Measured — a pilot did exactly that, failed 4 of 6 and wrote zero
            # rows after paying for 21 model calls.
            async with SessionLocal() as db:
                try:
                    produced = await _run_interview(db, spec, simulator)
                except Exception as exc:  # noqa: BLE001
                    # Roll back explicitly. Without it the failure outlives the
                    # `async with`, because the connection is pooled.
                    await db.rollback()
                    failures += 1
                    print(f"  [{index}/{len(specs)}] {spec.interview_id:<22} "
                          f"FAILED ({type(exc).__name__}): {str(exc).splitlines()[0][:110]}")
                    continue
            rows.extend(produced)
            _write(DATASET, rows)      # flush per interview: survivable
            print(f"  [{index}/{len(specs)}] {spec.interview_id:<22} "
                  f"{len(produced):>3} rows   ${USAGE.dollars():.4f}")

    if failures:
        print(f"\n  {failures} of {len(specs)} interviews FAILED and are absent from "
              f"the dataset. That is a coverage fact, not a rounding error — it is "
              f"reported here and in the plan's execution log, never quietly dropped.")

    print(f"\n  wrote {len(rows)} rows -> {DATASET}")
    print(USAGE.report() if USAGE.calls else "  (no model calls — fixture mode)")
    _summarise(rows)
    return 0


def _write(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _truthy(value) -> bool:
    return str(value).strip().lower() in ("true", "1", "yes")


def m7e(rows: list[dict]) -> float:
    """% of generated questions that received a validator decision.

    Both sides are ROWS. See the note in `_summarise` for the version that was
    not, and what it cost."""
    if not rows:
        return 0.0
    return 100.0 * sum(1 for r in rows if _truthy(r["validator_ran"])) / len(rows)


def _summarise(rows: list[dict]) -> None:
    """The numbers acceptance criteria 5 and 7 are read off."""
    if not rows:
        return
    ran = [r for r in rows if _truthy(r["validator_ran"])]
    final = [r for r in rows if _truthy(r["is_final"])]
    # M7e = generated questions that got a validator DECISION, over generated
    # questions. Rows both sides. An earlier version put DISTINCT question texts
    # over ALL rows, which is not a proportion of anything — the numerator
    # de-duplicated and the denominator did not, so repeated fallback text
    # silently deflated it. It read 90.0% where the real figure was 93.6%, and
    # M7e has a 90% acceptance floor, so the bug was one repeated string away
    # from failing the phase on a number that was never computed.
    coverage = 100.0 * len(ran) / max(1, len(rows))
    print(f"\n  rows {len(rows)}  |  validator ran on {len(ran)}  |  M7e coverage {coverage:.1f}%")
    print(f"  families {len({r['family'] for r in rows})}  "
          f"probe levels {sorted({r['probe_level'] for r in rows})}")
    print(f"  accepts {sum(1 for r in ran if _truthy(r['accepted_by_validator']))}  "
          f"rejects {sum(1 for r in ran if not _truthy(r['accepted_by_validator']))}")
    print(f"  repairs {sum(1 for r in rows if _truthy(r['is_repair']))}  "
          f"regenerated attempts {sum(1 for r in rows if int(r['attempt_index']) > 1)}")
    sources = Counter(r["source"] for r in final)
    print(f"  asked-question sources {dict(sources)}")
    rules = Counter(r["primary_rule"] for r in ran if r["primary_rule"])
    print(f"  primary_rule histogram {dict(rules) or '{}'}")


# ---------------------------------------------------------------------------
# sample  (P3-02 — Decision 4)
# ---------------------------------------------------------------------------

BLIND_FIELDS = ["row_id", "claim", "probe_level", "question", "human_verdict", "human_note"]


async def cmd_sample(args: argparse.Namespace) -> int:
    if not DATASET.exists():
        print(f"{DATASET} not found. Run `generate` first.")
        return 1
    with DATASET.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    judged = [r for r in rows if _truthy(r["validator_ran"])]
    accepts = [r for r in judged if _truthy(r["accepted_by_validator"])]
    rejects = [r for r in judged if not _truthy(r["accepted_by_validator"])]

    rng = random.Random(args.seed)
    take_a = rng.sample(accepts, min(args.n, len(accepts)))
    take_r = rng.sample(rejects, min(args.n, len(rejects)))
    print(f"  population: {len(accepts)} accepts, {len(rejects)} rejects")
    print(f"  sampled   : {len(take_a)} accepts, {len(take_r)} rejects")
    if len(take_r) < args.n:
        print(f"  NOTE: fewer than {args.n} rejects exist. `score` widens every "
              f"interval to match and says so.")
    if len(take_r) < 20:
        # Phrased about the SAMPLE, not the population: with --n 8 the reviewer
        # chose a small stratum, and telling them "under 20 rejects exist" when
        # 18 do would be the harness reporting a fact it has not established.
        print(f"  WARNING: only {len(take_r)} rejects will be reviewed. Precision is "
              f"still reported; its interval will be very wide and recall wider. "
              f"`score` says so rather than printing a number that looks precise.")

    picked = take_a + take_r
    rng.shuffle(picked)

    blind, key = [], []
    for index, row in enumerate(picked, start=1):
        row_id = f"r{index:04d}"
        # THE BLIND FILE CARRIES NOTHING THE VALIDATOR THOUGHT. Not the verdict,
        # not the violations, not the source, not the attempt number, not even
        # the family — `no_claim_anchor` on an HR question would be a tell.
        blind.append({
            "row_id": row_id,
            "claim": row["claim"],
            "probe_level": row["probe_level"],
            "question": row["generated_question"],
            "human_verdict": "",
            "human_note": "",
        })
        key.append({
            "row_id": row_id,
            "interview_id": row["interview_id"],
            # Required to address a dataset row uniquely — see the note in
            # `cmd_score`. Without it the key cannot join back at all.
            "order_index": row["order_index"],
            "attempt_index": row["attempt_index"],
            "stratum": "accept" if _truthy(row["accepted_by_validator"]) else "reject",
            "validation_result": row["validation_result"],
            "violations": row["violations"],
            "primary_rule": row["primary_rule"],
            "family": row["family"],
            "tier": row["tier"],
            "source": row["source"],
        })

    with SAMPLE.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=BLIND_FIELDS)
        writer.writeheader()
        writer.writerows(blind)
    with SAMPLE_KEY.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(key[0]))
        writer.writeheader()
        writer.writerows(key)

    # Population counts travel with the key: `score` needs N_A and N_R to
    # reweight, and reading them from a dataset that has since been regenerated
    # would silently mis-weight the whole matrix.
    (OUT_DIR / ".population.json").write_text(json.dumps({
        "accepts": len(accepts), "rejects": len(rejects),
        "judged": len(judged), "rows": len(rows),
        "sample_seed": args.seed,
    }, indent=2))

    print(f"\n  {SAMPLE}  <- label human_verdict as `accept` or `reject`")
    print(f"  {SAMPLE_KEY}  (sealed — do not open before labelling)")
    print(f"\n  For kappa: copy the file, have a second reviewer label the first "
          f"{args.overlap} rows, and pass it to `score --reviewer2`.")
    return 0


# ---------------------------------------------------------------------------
# score  (P3-04 — plan §0 F3, Decision 4 + 5)
# ---------------------------------------------------------------------------


def reweight(n_a: int, n_r: int, hr_a: int, s_a: int, hr_r: int, s_r: int) -> dict:
    """Population estimates from a stratified sample. Plan §0 F3.

    The brief's method — sample 50 accepts and 50 rejects, build a 2x2, read off
    precision and recall — is wrong for any population where the two strata are
    not equally common. If the live reject rate is 8%, a 50/50 sample
    over-represents rejects about 11x, and recall and accuracy read off that
    table are simply not the population's. This is the correction.

    POSITIVE = the validator REJECTS. That is the discriminative act and the one
    that costs something (a regeneration).

        n_a, n_r   population counts of validator accepts / rejects
        hr_a, s_a  of s_a SAMPLED accepts, hr_a that the human rejected
        hr_r, s_r  of s_r SAMPLED rejects, hr_r that the human also rejected

    Precision comes out base-rate free — it is a property of the reject stratum
    alone, which is why it is the one figure the naive method gets right by
    accident. Recall and accuracy need the population weights.
    """
    r_R = hr_r / s_r if s_r else 0.0
    r_A = hr_a / s_a if s_a else 0.0
    TP, FP = n_r * r_R, n_r * (1 - r_R)
    FN, TN = n_a * r_A, n_a * (1 - r_A)
    precision = r_R
    recall = TP / (TP + FN) if (TP + FN) else 0.0
    accuracy = (TP + TN) / (n_a + n_r) if (n_a + n_r) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {"r_R": r_R, "r_A": r_A, "TP": TP, "FP": FP, "FN": FN, "TN": TN,
            "precision": precision, "recall": recall, "accuracy": accuracy, "f1": f1}


def wilson(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval. Chosen over normal-approximation because at n=50
    with a proportion near 0 or 1 the normal interval leaves the [0,1] range and
    prints things like `precision 0.98 (0.94-1.02)`."""
    if total == 0:
        return (0.0, 1.0)
    p = successes / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    spread = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return (max(0.0, centre - spread), min(1.0, centre + spread))


def cohens_kappa(a: list[str], b: list[str]) -> float:
    n = len(a)
    if n == 0:
        return 0.0
    observed = sum(1 for x, y in zip(a, b) if x == y) / n
    labels = set(a) | set(b)
    expected = sum((a.count(l) / n) * (b.count(l) / n) for l in labels)
    return 1.0 if expected == 1 else (observed - expected) / (1 - expected)


def _pct(value: float) -> str:
    return f"{100 * value:.1f}%"


async def cmd_score(args: argparse.Namespace) -> int:
    reviewed = Path(args.reviewed)
    for path in (reviewed, SAMPLE_KEY, OUT_DIR / ".population.json"):
        if not path.exists():
            print(f"missing: {path}")
            return 1

    with reviewed.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    # Acceptance criterion 9. A reviewed file carrying a validator column means
    # the reviewer could see the answer, and every number below would be a
    # measurement of anchoring rather than of the validator.
    leaked = {"validation_result", "violations", "primary_rule", "source",
              "accepted_by_validator", "attempt_index", "stratum"} & set(rows[0])
    if leaked:
        print(f"REFUSING TO SCORE: the reviewed file exposes {sorted(leaked)}.")
        print("The review was not blind, so the confusion matrix would not mean anything.")
        return 2

    with SAMPLE_KEY.open(newline="", encoding="utf-8") as fh:
        key = {r["row_id"]: r for r in csv.DictReader(fh)}
    population = json.loads((OUT_DIR / ".population.json").read_text())
    with DATASET.open(newline="", encoding="utf-8") as fh:
        # (interview_id, attempt_index) IS NOT UNIQUE — measured, 136 distinct
        # keys across 519 rows. `attempt_index` counts attempts within ONE
        # planner slot and restarts at 1 for every question, so every row of a
        # 12-question interview collided. `order_index` is what makes it unique.
        # The confusion matrix never used this index (it keys on `row_id`), so no
        # published number moved; the auto-generated disagreement listing did,
        # and would have quoted the wrong question against the right verdict.
        dataset = {(r["interview_id"], r["order_index"], r["attempt_index"]): r
                   for r in csv.DictReader(fh)}

    labels: dict[str, str] = {}
    for row in rows:
        verdict = (row.get("human_verdict") or "").strip().lower()
        if verdict in ("accept", "reject"):
            labels[row["row_id"]] = verdict
    unlabelled = len(rows) - len(labels)

    strata = {"accept": [0, 0], "reject": [0, 0]}     # [human_rejects, n]
    for row_id, human in labels.items():
        stratum = key[row_id]["stratum"]
        strata[stratum][1] += 1
        if human == "reject":
            strata[stratum][0] += 1

    n_a, n_r = population["accepts"], population["rejects"]
    hr_r, s_r = strata["reject"]        # of sampled validator-rejects, human also rejected
    hr_a, s_a = strata["accept"]        # of sampled validator-accepts, human rejected

    est = reweight(n_a, n_r, hr_a, s_a, hr_r, s_r)
    r_R, r_A = est["r_R"], est["r_A"]
    TP, FP, FN, TN = est["TP"], est["FP"], est["FN"], est["TN"]
    precision, recall = est["precision"], est["recall"]
    accuracy, f1 = est["accuracy"], est["f1"]

    kappa, overlap_n = None, 0
    if args.reviewer2:
        with Path(args.reviewer2).open(newline="", encoding="utf-8") as fh:
            second = {r["row_id"]: (r.get("human_verdict") or "").strip().lower()
                      for r in csv.DictReader(fh)}
        shared = [rid for rid in labels if second.get(rid) in ("accept", "reject")]
        overlap_n = len(shared)
        if overlap_n:
            kappa = cohens_kappa([labels[r] for r in shared], [second[r] for r in shared])

    _write_matrix(precision, recall, accuracy, f1, r_R, r_A, s_r, s_a, hr_r, hr_a,
                  n_a, n_r, population, kappa, overlap_n, unlabelled, TP, FP, FN, TN)
    _write_disagreements(labels, key, dataset)
    print(f"  wrote {MATRIX}\n  wrote {DISAGREEMENTS}")
    print(f"\n  precision {_pct(precision)}  recall {_pct(recall)}  "
          f"accuracy {_pct(accuracy)}  F1 {_pct(f1)}")
    if kappa is not None:
        print(f"  kappa {kappa:.2f} over {overlap_n} items"
              + ("   <-- LOW, published with a warning" if kappa < 0.6 else ""))
    return 0


def _write_matrix(precision, recall, accuracy, f1, r_R, r_A, s_r, s_a, hr_r, hr_a,
                  n_a, n_r, population, kappa, overlap_n, unlabelled,
                  TP, FP, FN, TN) -> None:
    p_lo, p_hi = wilson(hr_r, s_r)
    a_lo, a_hi = wilson(hr_a, s_a)
    warn = []
    if kappa is not None and kappa < 0.6:
        warn.append(
            f"> **REVIEWER AGREEMENT IS LOW — kappa = {kappa:.2f} over {overlap_n} items.**\n"
            "> Every figure below is published anyway (plan Decision 5): metrics are\n"
            "> never suppressed, they are labelled. But at this kappa the two reviewers\n"
            "> disagree often enough that the ground truth itself is noisy, so read\n"
            "> these as indicative and weight `validator_disagreements.md` more heavily\n"
            "> than the point estimates.\n")
    if s_r < 20:
        warn.append(
            f"> **ONLY {s_r} REJECTS WERE REVIEWED.** Precision is reported; recall and\n"
            "> accuracy depend on it and are correspondingly wide. Do not read the\n"
            "> point estimates as separated from each other.\n")
    if unlabelled:
        warn.append(f"> **{unlabelled} sampled rows carry no human verdict** and are excluded.\n")

    MATRIX.write_text(f"""# Phase 3 — Confusion matrix

`question.validate()` against a blind human, over questions generated by the
real pipeline. Method: `docs/PHASE_3_VALIDATION_STUDY.md` §0 F3.

**Positive = the validator REJECTS.** That is the discriminative act and the one
with an operational consequence — a reject costs a regeneration.

{"".join(warn)}
## Population

| | count |
|---|---|
| Rows in dataset | {population['rows']} |
| Rows the validator judged | {population['judged']} |
| Validator accepts (N_A) | {n_a} |
| Validator rejects (N_R) | {n_r} |
| Live reject rate (M7h) | {_pct(n_r / max(1, n_a + n_r))} |

## Raw sample — NOT the population

Stratified 50/50, so this table over-represents rejects by roughly
{(n_a / max(1, n_r)) if n_r else 0:.1f}x. **Do not read precision/recall off it.**

| | human reject | human accept | n |
|---|---|---|---|
| **validator reject** | {hr_r} | {s_r - hr_r} | {s_r} |
| **validator accept** | {hr_a} | {s_a - hr_a} | {s_a} |

- `r_R` = {_pct(r_R)} of sampled rejects the human also rejected — 95% CI [{_pct(p_lo)}, {_pct(p_hi)}]
- `r_A` = {_pct(r_A)} of sampled accepts the human rejected — 95% CI [{_pct(a_lo)}, {_pct(a_hi)}]

## Reweighted to the population — read these

| | human reject | human accept |
|---|---|---|
| **validator reject** | TP {TP:.0f} | FP {FP:.0f} |
| **validator accept** | FN {FN:.0f} | TN {TN:.0f} |

| Metric | Value | 95% CI |
|---|---|---|
| **M7a Precision** | {_pct(precision)} | [{_pct(p_lo)}, {_pct(p_hi)}] |
| **M7b Recall** | {_pct(recall)} | derived from both strata |
| **M7c Accuracy** | {_pct(accuracy)} | derived from both strata |
| **M7d F1** | {_pct(f1)} | derived |
| **M7g Reviewer kappa** | {f'{kappa:.2f} (n={overlap_n})' if kappa is not None else 'not measured'} | — |

Precision is base-rate free and read directly from the reject stratum. Recall
and accuracy are reweighted by N_A and N_R; at n={s_a}/{s_r} per stratum their
intervals are wide, and the plan (§0 C-ii) deliberately does not narrow them
further. **The finding is in `validator_disagreements.md`.**
""", encoding="utf-8")


# The ten root causes, as briefed. Seven rule names plus three the rules cannot
# express. Every disagreement gets exactly one.
ROOT_CAUSES = [
    "answer_leakage", "multiple_fact_targets", "duplicate_content",
    "hypothetical_misuse", "unsupported_metric", "scope_drift", "no_claim_anchor",
    "threshold_issue", "transfer_issue", "human_ambiguity",
]


def _write_disagreements(labels, key, dataset) -> None:
    """Every disagreement, quoted, with one root cause each.

    THE ROOT CAUSE IS PRE-FILLED, NOT DECIDED. A false reject is filed under the
    rule that fired, because that rule is what has to be answered for. A false
    ACCEPT has no rule to blame, so it is left `unclassified` for a human to
    file — guessing there would be the study inventing its own findings.
    """
    groups: dict[str, list] = defaultdict(list)
    for row_id, human in labels.items():
        entry = key[row_id]
        validator = "reject" if entry["stratum"] == "reject" else "accept"
        if validator == human:
            continue
        row = dataset.get(
            (entry["interview_id"], entry["order_index"], entry["attempt_index"]), {}
        )
        cause = entry["primary_rule"] if validator == "reject" else "unclassified"
        groups[cause or "unclassified"].append((row_id, entry, row, validator, human))

    total = sum(len(v) for v in groups.values())
    out = [
        "# Phase 3 — Validator disagreements\n",
        "Every case where the blind human and `validate()` disagreed. This is the",
        "deliverable the plan (§0 C-ii) says carries the finding — one example of the",
        "validator rejecting a question a human would ask teaches more than any",
        "confidence interval.\n",
        f"**{total} disagreements.**\n",
        "Root cause for a FALSE REJECT is the rule that fired — that rule is what has",
        "to answer for it. A FALSE ACCEPT has no rule to blame and is filed",
        "`unclassified` for a human to assign from the taxonomy below. The harness",
        "does not guess: a study that invents its own findings is not a study.\n",
        "Taxonomy: `" + "` · `".join(ROOT_CAUSES) + "`\n",
        "## Counts by root cause\n",
        "| root cause | n |", "|---|---|",
    ]
    for cause, items in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        out.append(f"| `{cause}` | {len(items)} |")
    out.append("")

    for cause, items in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        out.append(f"\n## {cause} ({len(items)})\n")
        for row_id, entry, row, validator, human in items:
            out.append(f"### {row_id} — validator **{validator}**, human **{human}**\n")
            out.append(f"- **Claim:** {row.get('claim', '(not found)')}")
            out.append(f"- **Question:** {row.get('generated_question', '(not found)')}")
            out.append(f"- **Probe level:** {row.get('probe_level', '?')}  ·  "
                       f"**Family:** {entry['family']}  ·  **Tier:** {entry['tier']}")
            out.append(f"- **Rules fired:** `{entry['violations'] or 'none'}`")
            out.append("- **Assessment:** _(fill in)_\n")

    DISAGREEMENTS.write_text("\n".join(out), encoding="utf-8")


# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    subparsers = parser.add_subparsers(dest="command", required=True)

    gen = subparsers.add_parser("generate", help="drive real interviews, write the dataset")
    gen.add_argument("--limit", type=int, default=None,
                     help="cap Tier B interviews (strided, not truncated). Use for a costed pilot")
    gen.add_argument("--repeats", type=int, default=1, help="Tier A repeats")
    gen.add_argument("--run-seed", type=int, default=20260905)
    gen.add_argument("--simulator-model", default="gpt-4o-mini",
                     help="model for the CANDIDATE, which is not under test. "
                          "Question generation always uses settings.openai_model")
    gen.add_argument("--no-simulator", action="store_true",
                     help="family-neutral answer pool instead; zero simulator cost, lower fidelity")
    gen.add_argument("--force", action="store_true")
    gen.add_argument("--resume", action="store_true")

    smp = subparsers.add_parser("sample", help="blind review file + sealed key")
    smp.add_argument("--n", type=int, default=50, help="per stratum")
    smp.add_argument("--seed", type=int, default=7)
    smp.add_argument("--overlap", type=int, default=20)

    sc = subparsers.add_parser("score", help="confusion matrix + disagreements")
    sc.add_argument("--reviewed", default=str(SAMPLE))
    sc.add_argument("--reviewer2", default=None)

    args = parser.parse_args()
    handlers = {"generate": cmd_generate, "sample": cmd_sample, "score": cmd_score}
    return asyncio.run(handlers[args.command](args))


if __name__ == "__main__":
    raise SystemExit(main())
