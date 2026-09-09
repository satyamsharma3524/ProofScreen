"""
Phase 1 — Job Requirement Extraction.  Owned by Dev A.

Parses Job Description (JD) text into normalized JobRequirement objects:
- Category: SKILL, COMPETENCY, DOMAIN
- Normalized Weights: sum to 1.0

Uses LLM when settings.llm_enabled is True; otherwise uses a deterministic heuristic.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pydantic import BaseModel, Field

from api.config import settings
from api.llm import complete_json, load_prompt

log = logging.getLogger("proofscreen.job_requirements")

VALID_CATEGORIES = {"SKILL", "COMPETENCY", "DOMAIN"}


@dataclass
class JobRequirement:
    name: str
    category: str       # "SKILL", "COMPETENCY", "DOMAIN"
    weight: float       # normalized 0.0 to 1.0


class ExtractedRequirementSchema(BaseModel):
    name: str
    category: str
    weight: float = Field(default=0.15, ge=0.01, le=1.0)


class JobRequirementsPayload(BaseModel):
    requirements: list[ExtractedRequirementSchema] = Field(default_factory=list)


def normalise_requirement_weights(requirements: list[JobRequirement]) -> list[JobRequirement]:
    """Rescale requirement weights so they sum exactly to 1.0, absorbing rounding remainder."""
    if not requirements:
        return []

    total_raw = sum(max(0.001, r.weight) for r in requirements)
    if total_raw <= 0:
        equal_weight = 1.0 / len(requirements)
        return [
            JobRequirement(name=r.name, category=r.category, weight=round(equal_weight, 4))
            for r in requirements
        ]

    normalized: list[JobRequirement] = []
    accumulated = 0.0

    for i, r in enumerate(requirements):
        if i == len(requirements) - 1:
            # Last element absorbs rounding remainder so sum is exactly 1.0
            final_w = max(0.001, round(1.0 - accumulated, 4))
            normalized.append(JobRequirement(name=r.name, category=r.category, weight=final_w))
        else:
            w = round(max(0.001, r.weight) / total_raw, 4)
            accumulated += w
            normalized.append(JobRequirement(name=r.name, category=r.category, weight=w))

    return normalized


def heuristic_job_requirements(jd_text: str) -> list[JobRequirement]:
    """Deterministic requirement extractor for offline / fixture mode."""
    if not jd_text or not jd_text.strip():
        return [
            JobRequirement(name="General Competence", category="COMPETENCY", weight=0.50),
            JobRequirement(name="Execution", category="COMPETENCY", weight=0.50),
        ]

    text_lower = jd_text.lower()
    found: list[tuple[str, str, float]] = []  # (name, category, initial_weight)

    # Hard skills / technologies
    known_skills = [
        ("fastapi", "FastAPI", "SKILL", 0.20),
        ("postgresql", "PostgreSQL", "SKILL", 0.20),
        ("postgres", "PostgreSQL", "SKILL", 0.20),
        ("redis", "Redis", "SKILL", 0.15),
        ("kafka", "Kafka", "SKILL", 0.15),
        ("python", "Python", "SKILL", 0.15),
        ("docker", "Docker", "SKILL", 0.15),
        ("kubernetes", "Kubernetes", "SKILL", 0.15),
        ("react", "React", "SKILL", 0.15),
        ("typescript", "TypeScript", "SKILL", 0.15),
        ("aws", "AWS", "SKILL", 0.15),
        ("sql", "SQL", "SKILL", 0.15),
    ]

    seen_names: set[str] = set()
    for keyword, canon_name, cat, init_w in known_skills:
        if keyword in text_lower and canon_name not in seen_names:
            found.append((canon_name, cat, init_w))
            seen_names.add(canon_name)

    # Competencies
    known_competencies = [
        ("system design", "System Design", "COMPETENCY", 0.15),
        ("architecture", "System Design", "COMPETENCY", 0.15),
        ("ownership", "Ownership", "COMPETENCY", 0.15),
        ("problem solving", "Problem Solving", "COMPETENCY", 0.15),
        ("troubleshooting", "Problem Solving", "COMPETENCY", 0.15),
        ("execution", "Execution", "COMPETENCY", 0.15),
        ("judgment", "Judgment", "COMPETENCY", 0.15),
        ("adaptability", "Adaptability", "COMPETENCY", 0.15),
    ]

    for keyword, canon_name, cat, init_w in known_competencies:
        if keyword in text_lower and canon_name not in seen_names:
            found.append((canon_name, cat, init_w))
            seen_names.add(canon_name)

    # Domains
    known_domains = [
        ("distributed systems", "Distributed Systems", "DOMAIN", 0.15),
        ("fintech", "Fintech", "DOMAIN", 0.15),
        ("e-commerce", "E-commerce", "DOMAIN", 0.15),
        ("bpo", "BPO Operations", "DOMAIN", 0.15),
        ("backend", "Backend Engineering", "DOMAIN", 0.15),
    ]

    for keyword, canon_name, cat, init_w in known_domains:
        if keyword in text_lower and canon_name not in seen_names:
            found.append((canon_name, cat, init_w))
            seen_names.add(canon_name)

    if not found:
        # Fallback if no keywords matched
        return normalise_requirement_weights([
            JobRequirement(name="Core Technology", category="SKILL", weight=0.40),
            JobRequirement(name="Problem Solving", category="COMPETENCY", weight=0.30),
            JobRequirement(name="Ownership", category="COMPETENCY", weight=0.30),
        ])

    reqs = [
        JobRequirement(name=name, category=cat, weight=w)
        for name, cat, w in found
    ]
    return normalise_requirement_weights(reqs)


async def extract_job_requirements(jd_text: str) -> list[JobRequirement]:
    """Extract job requirements from JD text using LLM or deterministic fallback."""
    if not jd_text or not jd_text.strip():
        return heuristic_job_requirements(jd_text)

    if not settings.llm_enabled:
        log.info("fixture mode: using heuristic job requirement extraction")
        return heuristic_job_requirements(jd_text)

    fallback_reqs = heuristic_job_requirements(jd_text)
    fallback_payload = JobRequirementsPayload(
        requirements=[
            ExtractedRequirementSchema(name=r.name, category=r.category, weight=r.weight)
            for r in fallback_reqs
        ]
    )

    try:
        prompt_tmpl = load_prompt("extract_job_requirements.txt")
        prompt = prompt_tmpl.substitute(jd_text=jd_text.strip())

        res = await complete_json(
            prompt=prompt,
            schema=JobRequirementsPayload,
            fallback=fallback_payload,
            temperature=0.0,
        )

        parsed: list[JobRequirement] = []
        for req in res.requirements:
            cat = req.category.upper().strip()
            if cat not in VALID_CATEGORIES:
                cat = "SKILL"
            name = req.name.strip()
            if name:
                parsed.append(JobRequirement(name=name, category=cat, weight=float(req.weight)))

        if not parsed:
            return fallback_reqs

        return normalise_requirement_weights(parsed)

    except Exception as exc:  # noqa: BLE001
        log.error("extract_job_requirements failed: %s", exc)
        return fallback_reqs
