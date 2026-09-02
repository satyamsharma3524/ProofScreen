"""
ProofScreen API — FastAPI application.

Backend only. The recruiter dashboard and candidate UI are a separate Next.js
app, so this process serves JSON and nothing else: no StaticFiles mount, CORS
open per the build decision.

Read the OpenAPI schema at /docs (Swagger) or /openapi.json — that schema IS
the contract between this service and the Next.js app.
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
from api.routers import candidates, channel, dev, recruiter, sessions
from api.schemas import HealthOut

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)-28s %(message)s",
)
log = logging.getLogger("proofscreen")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # No Alembic by design: create_all is the whole migration story.
    await init_models()
    log.info(
        "ProofScreen up — llm=%s model=%s adaptive=%s max_questions=%d twilio=%s",
        settings.llm_mode,
        settings.openai_model,
        settings.adaptive_followups,
        settings.max_questions,
        "live" if settings.twilio_enabled else "dry-run",
    )
    if not settings.llm_enabled:
        log.warning(
            "OPENAI_API_KEY is not set — running in FIXTURE MODE. "
            "Claims, questions and evidence come from deterministic heuristics."
        )
    yield
    await engine.dispose()


app = FastAPI(
    title="ProofScreen API",
    version="0.1.0",
    summary="Evidence-graph competence verification for resumes.",
    description=(
        "Resume in, evidence graph out.\n\n"
        "The LLM produces evidence nodes with enum verdicts. It never produces "
        "a number — `claim_confidence` and `competence_score` are arithmetic "
        "over those verdicts (see `api/engine/scoring.py`), and every term in "
        "the score points at a verbatim quote from the candidate's own answer."
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
app.include_router(channel.router)
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
        adaptive_followups=settings.adaptive_followups,
        max_questions=settings.max_questions,
    )
