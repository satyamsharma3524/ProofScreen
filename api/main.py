"""
ProofScreen API — evidence-graph competence verification.

Backend only. The recruiter dashboard is a separate Next.js app, so this
process serves JSON and nothing else.

THE ONE-PARAGRAPH PITCH, FOR ANYONE READING THIS FILE FIRST
-----------------------------------------------------------
A resume is a list of claims. ProofScreen extracts them, probes each one over
WhatsApp through five levels (validate, operational, incident, decision,
outcome), and extracts COUNTABLE SIGNALS from the answers — quantities,
process steps, complete cause-action-outcome chains, tools with described
usage, specific remembered incidents — each quoted verbatim. Published rubrics
in engine/signals.py turn those counts into six dimension scores. Role weights
turn dimension scores into a ranking. A deterministic fact-memory catches
contradictions between answers and multiplies the whole thing down.

The model never produces a score. Not once. Every number a recruiter sees is
arithmetic over counted, quoted evidence — which is the only honest answer to
"how do we know this isn't the AI's opinion?"
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text as sql_text

from api.config import settings
from api.db import engine, init_models
from api.llm import LLMContractError
from api.routers import candidates, dev, recruiter, sessions, whatsapp
from api.schemas import HealthOut
from api.taxonomy import family_keys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)-28s %(message)s",
)
log = logging.getLogger("proofscreen")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_models()          # no Alembic by design
    log.info(
        "ProofScreen up — llm=%s model=%s whatsapp=%s max_questions=%d families=%d",
        settings.llm_mode, settings.openai_model, settings.whatsapp_mode,
        settings.max_questions, len(family_keys()),
    )
    if not settings.llm_enabled:
        log.warning(
            "OPENAI_API_KEY not set — FIXTURE MODE. Claims, questions and signal "
            "extraction come from deterministic heuristics; scoring is unchanged."
        )
    if not settings.whatsapp_enabled:
        log.warning(
            "WhatsApp Cloud API not configured — outbound messages are dry-run. "
            "Set WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID to go live."
        )
    yield
    await engine.dispose()


app = FastAPI(
    title="ProofScreen API",
    version="2.0.0",
    summary="Turns resume claims into a scored, quotable evidence graph.",
    description=(
        "Resume in, evidence graph out.\n\n"
        "**The model never produces a score.** It extracts countable signals and "
        "quotes them verbatim; `api/engine/signals.py` turns counts into six "
        "dimension scores via published rubrics, `api/engine/scoring.py` applies "
        "role weights, and `api/engine/consistency.py` catches contradictions "
        "between answers deterministically.\n\n"
        "Pass `role_id` to any recruiter endpoint to re-rank identical evidence "
        "under a different recruiter's priorities."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    # Wildcard origins and credentials are mutually exclusive in the CORS spec.
    allow_credentials=settings.cors_origin_list != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(candidates.router)
app.include_router(sessions.router)
app.include_router(whatsapp.router)
app.include_router(recruiter.router)
app.include_router(dev.router)


@app.exception_handler(LLMContractError)
async def llm_contract_error_handler(request: Request, exc: LLMContractError):
    """The demo must never show a stack trace."""
    log.error("LLM contract error on %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=503,
        content={
            "detail": "The language model could not be reached. Please retry.",
            "error": "llm_unavailable",
        },
    )


@app.get("/", tags=["meta"])
async def root() -> dict:
    return {
        "service": "proofscreen-api",
        "version": "2.0.0",
        "docs": "/docs",
        "openapi": "/openapi.json",
        "health": "/api/health",
    }


@app.get("/api/health", response_model=HealthOut, tags=["meta"])
async def health() -> HealthOut:
    database = "ok"
    try:
        async with engine.connect() as conn:
            await conn.execute(sql_text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        database = f"error: {type(exc).__name__}"

    return HealthOut(
        status="ok" if database == "ok" else "degraded",
        database=database,
        llm_mode=settings.llm_mode,
        model=settings.openai_model if settings.llm_enabled else None,
        whatsapp=settings.whatsapp_mode,
        max_questions=settings.max_questions,
        job_families=len(family_keys()),
    )
