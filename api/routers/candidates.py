"""Resume ingest. Owned by Dev A.

POST /api/candidates        multipart file upload  (PDF / DOCX / TXT / MD)
POST /api/candidates/text   json with resume_text  (additive: what the Next.js
                            candidate form and every test actually use)
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from api import ids
from api.db import get_db
from api.engine import orchestrator
from api.ingest.parse import UnsupportedResume, extract_text, normalise
from api.models import Candidate, Resume
from api.schemas import (
    CandidateCreateOut,
    CandidateTextIn,
    Channel,
    ClaimOut,
)

log = logging.getLogger("proofscreen.candidates")

router = APIRouter(prefix="/api/candidates", tags=["candidate"])


async def _onboard(
    db: AsyncSession,
    *,
    name: str,
    resume_text: str,
    filename: str | None = None,
    phone: str | None = None,
    email: str | None = None,
    role: str | None = None,
    job_description: str | None = None,
    channel: Channel = Channel.web,
) -> CandidateCreateOut:
    """Candidate + resume + claims + session + first question, in one commit path."""
    candidate = Candidate(
        id=ids.candidate_id(),
        name=name.strip() or "Unnamed candidate",
        phone=(phone or "").strip() or None,
        email=(email or "").strip() or None,
        role=(role or "").strip() or None,
    )
    resume = Resume(
        id=ids.resume_id(),
        candidate_id=candidate.id,
        raw_text=normalise(resume_text),
        filename=filename,
        job_description=(job_description or "").strip() or None,
    )
    db.add(candidate)
    db.add(resume)
    await db.commit()

    session, claims = await orchestrator.create_session(db, candidate, resume, channel)
    first = await orchestrator.ask_next(db, session)

    instructions = None
    if channel is Channel.whatsapp or candidate.phone:
        instructions = (
            f"Send the message  {session.join_code}  to our WhatsApp number to "
            f"start your verification."
        )

    log.info("onboarded %s (%s) with %d claims", candidate.name, candidate.id, len(claims))
    return CandidateCreateOut(
        candidate_id=candidate.id,
        session_id=session.id,
        claims=[
            ClaimOut(id=c.id, text=c.text, metric=c.metric, category=c.category)
            for c in claims
        ],
        join_code=session.join_code or "",
        first_question=first.text if first else None,
        whatsapp_instructions=instructions,
    )


@router.post("", response_model=CandidateCreateOut, status_code=status.HTTP_201_CREATED)
async def create_candidate(
    file: UploadFile = File(..., description="PDF, DOCX, TXT or MD resume"),
    name: str = Form(...),
    phone: str | None = Form(None),
    email: str | None = Form(None),
    role: str | None = Form(None),
    job_description: str | None = Form(None),
    channel: Channel = Form(Channel.web),
    db: AsyncSession = Depends(get_db),
) -> CandidateCreateOut:
    data = await file.read()
    try:
        resume_text = extract_text(file.filename or "resume", data)
    except UnsupportedResume as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    return await _onboard(
        db,
        name=name,
        resume_text=resume_text,
        filename=file.filename,
        phone=phone,
        email=email,
        role=role,
        job_description=job_description,
        channel=channel,
    )


@router.post("/text", response_model=CandidateCreateOut, status_code=status.HTTP_201_CREATED)
async def create_candidate_from_text(
    payload: CandidateTextIn,
    db: AsyncSession = Depends(get_db),
) -> CandidateCreateOut:
    if len(payload.resume_text.strip()) < 80:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "resume_text is too short to extract claims from"
        )
    return await _onboard(
        db,
        name=payload.name,
        resume_text=payload.resume_text,
        filename=None,
        phone=payload.phone,
        email=payload.email,
        role=payload.role,
        job_description=payload.job_description,
        channel=payload.channel,
    )
