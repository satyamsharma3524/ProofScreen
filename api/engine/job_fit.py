"""
Job Fit Engine & Requirement Coverage Verification.  Owned by Dev A.

Verifies Job Requirements against Candidate Evidence Graph:
- SKILL / DOMAIN requirements checked against evidence graph tools, facts & claims
- COMPETENCY requirements mapped to candidate dimension scores
- Computes skill_fit (60%) + competence_fit (40%) = job_fit_score
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Sequence
from pydantic import BaseModel, Field

from api.engine.job_requirements import JobRequirement
from api.schemas import CandidateGraph, Dimension

log = logging.getLogger("proofscreen.job_fit")


class CoverageStatus(str, Enum):
    VERIFIED = "VERIFIED"
    PARTIAL = "PARTIAL"
    MISSING = "MISSING"


COMPETENCY_MAP: dict[str, list[Dimension]] = {
    "ownership": [Dimension.OWNERSHIP],
    "problem solving": [Dimension.PROBLEM_SOLVING],
    "execution": [Dimension.EXECUTION],
    "judgment": [Dimension.JUDGMENT],
    "knowledge": [Dimension.KNOWLEDGE],
    "adaptability": [Dimension.ADAPTABILITY],
    "system design": [Dimension.KNOWLEDGE, Dimension.JUDGMENT],
    "troubleshooting": [Dimension.PROBLEM_SOLVING, Dimension.EXECUTION],
    "leadership": [Dimension.OWNERSHIP, Dimension.JUDGMENT],
}


class RequirementCoverageDetail(BaseModel):
    name: str
    category: str
    weight: float
    status: CoverageStatus
    coverage_score: int          # 100 for VERIFIED, 50 for PARTIAL, 0 for MISSING
    evidence_note: str


class JobFitResult(BaseModel):
    job_fit_score: int = Field(..., ge=0, le=100, description="Final job fit score (0-100)")
    skill_fit: int = Field(..., ge=0, le=100, description="Skill/Domain fit score (0-100)")
    competence_fit: int = Field(..., ge=0, le=100, description="Competence fit score (0-100)")
    verified_requirements: list[str] = Field(default_factory=list)
    missing_requirements: list[str] = Field(default_factory=list)
    strongest_dimensions: list[str] = Field(default_factory=list)
    risk_areas: list[str] = Field(default_factory=list)
    requirement_details: list[RequirementCoverageDetail] = Field(default_factory=list)


class CandidateJobFitRanking(BaseModel):
    rank: int
    candidate_id: str
    candidate_name: str
    job_fit_score: int
    skill_fit: int
    competence_fit: int
    verified_requirements_count: int
    total_requirements_count: int
    badge: str
    details: JobFitResult


def _map_competency_to_dimensions(competency_name: str) -> list[Dimension]:
    key = competency_name.lower().strip()
    if key in COMPETENCY_MAP:
        return COMPETENCY_MAP[key]

    for mapped_key, dims in COMPETENCY_MAP.items():
        if mapped_key in key or key in mapped_key:
            return dims

    return [Dimension.EXECUTION, Dimension.PROBLEM_SOLVING]


def verify_requirement_coverage(
    req: JobRequirement,
    graph: CandidateGraph,
) -> RequirementCoverageDetail:
    """Verifies a single JobRequirement against the Candidate's Evidence Graph."""
    req_name_lower = req.name.lower().strip()
    cat = req.category.upper()

    # Case A: COMPETENCY Category
    if cat == "COMPETENCY":
        dims = _map_competency_to_dimensions(req.name)
        dim_scores: list[int] = []
        dim_names: list[str] = []

        dim_profile_map = {d.dimension: d for d in graph.dimension_profile}

        for dim in dims:
            dim_names.append(dim.value)
            if dim in dim_profile_map:
                dp = dim_profile_map[dim]
                dim_scores.append(dp.score if dp.probed or dp.gate_open else 0)
            else:
                dim_scores.append(0)

        avg_dim_score = int(sum(dim_scores) / len(dim_scores)) if dim_scores else 0

        if avg_dim_score >= 60:
            status = CoverageStatus.VERIFIED
            cov_score = 100
            note = f"Verified evidence across {', '.join(dim_names)} (dim score: {avg_dim_score})"
        elif avg_dim_score >= 35:
            status = CoverageStatus.PARTIAL
            cov_score = 65
            note = f"Partial evidence across {', '.join(dim_names)} (dim score: {avg_dim_score})"
        else:
            status = CoverageStatus.MISSING
            cov_score = 20
            note = f"Limited probed evidence across {', '.join(dim_names)} (dim score: {avg_dim_score})"

        return RequirementCoverageDetail(
            name=req.name,
            category=req.category,
            weight=req.weight,
            status=status,
            coverage_score=cov_score,
            evidence_note=note,
        )

    # Case B: SKILL or DOMAIN Category
    # Check Evidence Graph claims, QA turns, and extracted tools/facts
    found_verified = False
    found_partial = False
    matching_claim_titles: list[str] = []

    for claim_graph in graph.claims:
        claim_text_val = getattr(claim_graph, "text", None) or getattr(claim_graph, "claim_text", "")
        claim_text_lower = claim_text_val.lower()
        has_text_mention = req_name_lower in claim_text_lower

        # Check QA turns and facts in this claim
        has_qa_mention = False
        for qa in claim_graph.qa:
            if req_name_lower in (qa.answer or "").lower() or req_name_lower in (qa.question or "").lower():
                has_qa_mention = True
                break

        claim_score = claim_graph.claim_score or 0

        if (has_text_mention or has_qa_mention) and claim_score >= 50:
            found_verified = True
            matching_claim_titles.append(claim_text_val[:50])
        elif (has_text_mention or has_qa_mention) and claim_score >= 25:
            found_partial = True
            matching_claim_titles.append(claim_text_val[:50])
        elif has_text_mention or has_qa_mention:
            found_partial = True

    if found_verified:
        status = CoverageStatus.VERIFIED
        cov_score = 100
        note = f"Verified evidence in claim: '{matching_claim_titles[0]}...'"
    elif found_partial:
        status = CoverageStatus.PARTIAL
        cov_score = 65
        note = f"Mentioned in claim evidence with moderate depth"
    else:
        status = CoverageStatus.MISSING
        cov_score = 20
        note = f"Unprobed / unverified in current interview claims for {req.name}"

    return RequirementCoverageDetail(
        name=req.name,
        category=req.category,
        weight=req.weight,
        status=status,
        coverage_score=cov_score,
        evidence_note=note,
    )


def calculate_job_fit(
    graph: CandidateGraph,
    requirements: Sequence[JobRequirement],
) -> JobFitResult:
    """Calculates Job Fit Score, Skill Fit, Competence Fit, and recruiter explanations."""
    if not requirements:
        # Fallback if no requirements extracted
        raw_comp = graph.competence_score
        scaled_comp = max(20, min(98, round(20 + 0.80 * raw_comp)))
        return JobFitResult(
            job_fit_score=scaled_comp,
            skill_fit=scaled_comp,
            competence_fit=scaled_comp,
            verified_requirements=["General Competence"],
            missing_requirements=[],
            strongest_dimensions=[
                d.dimension.value.title() for d in sorted(graph.dimension_profile, key=lambda x: x.score, reverse=True)[:2]
            ],
            risk_areas=[],
            requirement_details=[],
        )

    coverage_details: list[RequirementCoverageDetail] = [
        verify_requirement_coverage(req, graph) for req in requirements
    ]

    skill_reqs = [c for c in coverage_details if c.category.upper() in ("SKILL", "DOMAIN")]
    comp_reqs = [c for c in coverage_details if c.category.upper() == "COMPETENCY"]

    # Calculate skill_fit
    if skill_reqs:
        skill_weight_sum = sum(c.weight for c in skill_reqs)
        if skill_weight_sum > 0:
            raw_skill_fit = int(sum(c.coverage_score * c.weight for c in skill_reqs) / skill_weight_sum)
        else:
            raw_skill_fit = int(sum(c.coverage_score for c in skill_reqs) / len(skill_reqs))
    else:
        raw_skill_fit = 100

    # Calculate competence_fit
    if comp_reqs:
        comp_weight_sum = sum(c.weight for c in comp_reqs)
        if comp_weight_sum > 0:
            raw_comp_fit = int(sum(c.coverage_score * c.weight for c in comp_reqs) / comp_weight_sum)
        else:
            raw_comp_fit = int(sum(c.coverage_score for c in comp_reqs) / len(comp_reqs))
    else:
        raw_comp_fit = graph.competence_score

    # Hackathon Calibration: Hard minimum floor at 20, raw score 25 maps to ~40
    skill_fit = max(20, min(98, round(20 + 0.80 * raw_skill_fit)))
    competence_fit = max(20, min(98, round(20 + 0.80 * raw_comp_fit)))

    # Final formula: job_fit_score = skill_fit * 0.60 + competence_fit * 0.40
    job_fit_score = max(20, min(98, round(skill_fit * 0.60 + competence_fit * 0.40)))

    # Summary lists for recruiter UI
    verified_reqs = [c.name for c in coverage_details if c.status == CoverageStatus.VERIFIED]
    missing_reqs = [c.name for c in coverage_details if c.status == CoverageStatus.MISSING]

    # Strongest dimensions from candidate graph
    sorted_dims = sorted(graph.dimension_profile, key=lambda d: d.score, reverse=True)
    strongest_dims = [d.dimension.value.title() for d in sorted_dims if d.score >= 40][:2]
    if not strongest_dims and sorted_dims:
        strongest_dims = [sorted_dims[0].dimension.value.title()]

    # Risk areas
    risk_areas: list[str] = []
    for c in coverage_details:
        if c.status == CoverageStatus.MISSING:
            risk_areas.append(f"Unprobed requirement: {c.name}")
        elif c.status == CoverageStatus.PARTIAL:
            risk_areas.append(f"Limited depth in {c.name}")

    low_dims = [d for d in graph.dimension_profile if d.score < 35 and d.probed]
    for ld in low_dims:
        risk_areas.append(f"Lower score in {ld.dimension.value.title()} ({ld.score}/100)")

    return JobFitResult(
        job_fit_score=job_fit_score,
        skill_fit=skill_fit,
        competence_fit=competence_fit,
        verified_requirements=verified_reqs,
        missing_requirements=missing_reqs,
        strongest_dimensions=strongest_dims,
        risk_areas=risk_areas[:4],  # top risk items
        requirement_details=coverage_details,
    )
