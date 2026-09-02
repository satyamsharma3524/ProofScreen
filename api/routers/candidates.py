"""
Resume ingest. Owned by Dev A.

POST /api/candidates        multipart resume (PDF / DOCX / TXT / MD)
POST /api/candidates/text   the same with resume_text as JSON

A phone number is required: WhatsApp is the only candidate channel, so a
candidate without one cannot be interviewed.

The response carries an `opt_in_code`. WhatsApp Business API does not let us
free-form message someone who has not messaged us first, so the candidate
sends that code to the business number, which both binds their phone to the
session and opens the 24-hour window every subsequent question rides on. If an
approved template is configured we also push a first-contact message here.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from api import ids
from api.channels.whatsapp_cloud import normalise_phone, whatsapp_channel
from api.config import settings
from api.db import get_db
from api.engine import orchestrator
from api.ingest.parse import UnsupportedResume, extract_text, normalise
from api.models import Candidate, Resume, utcnow
from api.schemas import (
    CandidateCreateOut,
    CandidateTextIn,
    Channel,
    ClaimOut,
    SessionState,
)
from api.taxonomy import claim_type_label, default_claim_weights, family_label, resolve_family

log = logging.getLogger("proofscreen.candidates")

router = APIRouter(prefix="/api/candidates", tags=["candidate"])


async def _onboard(
    db: AsyncSession,
    *,
    name: str,
    phone: str,
    resume_text: str,
    filename: str | None = None,
    email: str | None = None,
    role: str | None = None,
    job_family: str | None = None,
    role_id: str | None = None,
    job_description: str | None = None,
) -> CandidateCreateOut:
    normalised = normalise_phone(phone)
    if not normalised:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "a valid phone number is required — WhatsApp is the candidate channel",
        )

    candidate = Candidate(
        id=ids.candidate_id(),
        name=name.strip() or "Unnamed candidate",
        phone=normalised,
        email=(email or "").strip() or None,
        role=(role or "").strip() or None,
        job_family=resolve_family(job_family) if job_family else "general",
        role_id=role_id,
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

    session, claims = await orchestrator.create_session(
        db, candidate, resume, Channel.whatsapp
    )
    weights = default_claim_weights(session.job_family)

    outreach_sent = False
    outreach_note: str | None = None
    if settings.whatsapp_template_name and settings.whatsapp_enabled:
        outreach_sent = await whatsapp_channel.send_template(
            normalised, [candidate.name.split()[0], session.opt_in_code or ""]
        )
        if outreach_sent:
            session.last_outbound_at = utcnow()
            await db.commit()
        outreach_note = (
            "Template message sent." if outreach_sent
            else "Template send failed — the candidate can still opt in manually."
        )
    elif not settings.whatsapp_enabled:
        outreach_note = "WhatsApp is in dry-run: no outbound message was sent."
    else:
        outreach_note = (
            "No approved template configured, so the candidate must message the "
            "business number first."
        )

    log.info(
        "onboarded %s (%s) — %s, %d claims",
        candidate.name, candidate.id, session.job_family, len(claims),
    )
    return CandidateCreateOut(
        candidate_id=candidate.id,
        session_id=session.id,
        job_family=session.job_family,
        job_family_label=family_label(session.job_family),
        claims=[
            ClaimOut(
                id=c.id,
                text=c.text,
                claim_type=c.claim_type,
                claim_type_label=claim_type_label(session.job_family, c.claim_type),
                metric=c.metric,
                weight=float(weights.get(c.claim_type, 0.0)),
            )
            for c in claims
        ],
        state=SessionState(session.state),
        opt_in_code=session.opt_in_code or "",
        whatsapp_instructions=(
            f"Send the message  {session.opt_in_code}  to our WhatsApp business "
            f"number to start the verification."
        ),
        outreach_sent=outreach_sent,
        outreach_note=outreach_note,
    )


@router.post("", response_model=CandidateCreateOut, status_code=status.HTTP_201_CREATED)
async def create_candidate(
    file: UploadFile = File(..., description="PDF, DOCX, TXT or MD resume"),
    name: str = Form(...),
    phone: str = Form(..., description="E.164, e.g. +919812345678"),
    email: str | None = Form(None),
    role: str | None = Form(None),
    job_family: str | None = Form(None),
    role_id: str | None = Form(None),
    job_description: str | None = Form(None),
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
        phone=phone,
        resume_text=resume_text,
        filename=file.filename,
        email=email,
        role=role,
        job_family=job_family,
        role_id=role_id,
        job_description=job_description,
    )


@router.post(
    "/text", response_model=CandidateCreateOut, status_code=status.HTTP_201_CREATED
)
async def create_candidate_from_text(
    payload: CandidateTextIn, db: AsyncSession = Depends(get_db)
) -> CandidateCreateOut:
    if len(payload.resume_text.strip()) < 80:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "resume_text is too short to extract claims from"
        )
    return await _onboard(
        db,
        name=payload.name,
        phone=payload.phone,
        resume_text=payload.resume_text,
        email=payload.email,
        role=payload.role,
        job_family=payload.job_family,
        role_id=payload.role_id,
        job_description=payload.job_description,
    )
