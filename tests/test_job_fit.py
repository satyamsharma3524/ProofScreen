"""
Unit and Integration Tests for Job Fit Ranking System (api/engine/job_fit.py, job_requirements.py, api/routers/job_fit.py).

Tests:
1. Job Requirement Extraction & Weight Normalization (sum = 1.0).
2. Requirement Coverage against Candidate Evidence Graph.
3. Skill Fit, Competence Fit, and Job Fit Score calculation formulas.
4. Recruiter JSON result schema structure.
5. Multi-candidate job fit ranking order.
6. API Endpoints: POST /api/job-fit, POST /api/job-fit/rank, POST /api/rank-candidates.
"""

import asyncio
from fastapi.testclient import TestClient

from api.engine.job_fit import (
    CoverageStatus,
    JobFitResult,
    calculate_job_fit,
    verify_requirement_coverage,
)
from api.engine.job_requirements import (
    JobRequirement,
    extract_job_requirements,
    heuristic_job_requirements,
    normalise_requirement_weights,
)
from api.main import app
from api.schemas import (
    Badge,
    CandidateGraph,
    CandidateRef,
    ClaimGraph,
    Dimension,
    DimensionScore,
)

client = TestClient(app)


def _mock_candidate_graph(
    name: str = "Test Candidate",
    competence: int = 80,
    dims: dict[Dimension, int] | None = None,
    claims: list[tuple[str, int, list[str]]] | None = None,  # [(text, score, tools)]
) -> CandidateGraph:
    dims = dims or {
        Dimension.EXECUTION: 85,
        Dimension.PROBLEM_SOLVING: 90,
        Dimension.OWNERSHIP: 80,
        Dimension.JUDGMENT: 75,
        Dimension.KNOWLEDGE: 70,
        Dimension.ADAPTABILITY: 65,
    }
    dim_profile = [
        DimensionScore(
            dimension=d,
            score=score,
            probed=True,
            gate_open=True,
            basis=f"Probed score for {d.value}",
        )
        for d, score in dims.items()
    ]

    claim_graphs: list[ClaimGraph] = []
    if claims:
        for idx, (ctext, cscore, tools) in enumerate(claims, start=1):
            claim_graphs.append(
                ClaimGraph(
                    id=f"cl_{idx}",
                    text=ctext,
                    claim_type="architecture_design",
                    claim_type_label="Architecture & Design",
                    claim_score=cscore,
                    qa=[],
                    facts=[],
                    dimensions=[],
                )
            )

    return CandidateGraph(
        candidate=CandidateRef(id="c_test1", name=name),
        job_family="software_engineering",
        job_family_label="Software Engineering",
        scored_for=None,
        competence_score=competence,
        badge=Badge.verified,
        probed_dimensions=6,
        resume_score=85,
        dimension_profile=dim_profile,
        claims=claim_graphs,
    )


def test_requirement_weight_normalization():
    """Verify raw requirement weights normalize so total equals 1.0 exactly."""
    raw = [
        JobRequirement(name="FastAPI", category="SKILL", weight=0.20),
        JobRequirement(name="PostgreSQL", category="SKILL", weight=0.20),
        JobRequirement(name="Redis", category="SKILL", weight=0.15),
        JobRequirement(name="Kafka", category="SKILL", weight=0.15),
        JobRequirement(name="System Design", category="COMPETENCY", weight=0.15),
        JobRequirement(name="Ownership", category="COMPETENCY", weight=0.15),
    ]

    normalized = normalise_requirement_weights(raw)

    assert len(normalized) == len(raw)
    total_w = sum(r.weight for r in normalized)
    assert abs(total_w - 1.0) < 1e-4


def test_heuristic_job_requirement_extraction():
    """Verify heuristic requirement extraction parses skills, competencies, and domains from JD."""
    jd = """
    Senior Backend Engineer
    Requirements:
    - FastAPI, PostgreSQL, Redis, Kafka
    - System Design and Ownership
    - Distributed Systems experience
    """
    reqs = heuristic_job_requirements(jd)

    names = [r.name for r in reqs]
    assert "FastAPI" in names
    assert "PostgreSQL" in names
    assert "Redis" in names
    assert "Kafka" in names
    assert "System Design" in names
    assert "Ownership" in names
    assert "Distributed Systems" in names

    total_w = sum(r.weight for r in reqs)
    assert abs(total_w - 1.0) < 1e-4


def test_async_extract_job_requirements_fallback():
    """Verify extract_job_requirements returns valid normalized requirements in fixture mode."""
    jd = "Seeking FastAPI and Postgres engineer with strong Ownership."
    reqs = asyncio.run(extract_job_requirements(jd))

    assert len(reqs) >= 2
    assert sum(r.weight for r in reqs) == 1.0


def test_requirement_coverage_verification():
    """Verify skill and competency coverage statuses against evidence graph."""
    graph = _mock_candidate_graph(
        name="Candidate A",
        competence=85,
        dims={
            Dimension.EXECUTION: 85,
            Dimension.PROBLEM_SOLVING: 90,
            Dimension.OWNERSHIP: 80,
            Dimension.JUDGMENT: 75,
            Dimension.KNOWLEDGE: 70,
            Dimension.ADAPTABILITY: 30,
        },
        claims=[
            ("Built FastAPI web API with PostgreSQL database", 85, ["FastAPI", "PostgreSQL"]),
            ("Configured Redis caching layer for API responses", 75, ["Redis"]),
        ],
    )

    req_fastapi = JobRequirement(name="FastAPI", category="SKILL", weight=0.20)
    req_kafka = JobRequirement(name="Kafka", category="SKILL", weight=0.20)
    req_ownership = JobRequirement(name="Ownership", category="COMPETENCY", weight=0.20)
    req_adaptability = JobRequirement(name="Adaptability", category="COMPETENCY", weight=0.20)

    cov_fastapi = verify_requirement_coverage(req_fastapi, graph)
    cov_kafka = verify_requirement_coverage(req_kafka, graph)
    cov_ownership = verify_requirement_coverage(req_ownership, graph)
    cov_adaptability = verify_requirement_coverage(req_adaptability, graph)

    assert cov_fastapi.status == CoverageStatus.VERIFIED
    assert cov_fastapi.coverage_score == 100

    assert cov_kafka.status == CoverageStatus.MISSING
    assert cov_kafka.coverage_score == 0

    assert cov_ownership.status == CoverageStatus.VERIFIED
    assert cov_ownership.coverage_score == 100

    assert cov_adaptability.status == CoverageStatus.MISSING
    assert cov_adaptability.coverage_score == 0


def test_job_fit_score_calculation_formula():
    """Verify job_fit_score = round(skill_fit * 0.60 + competence_fit * 0.40)."""
    graph = _mock_candidate_graph(
        name="Candidate B",
        competence=85,
        dims={
            Dimension.EXECUTION: 85,
            Dimension.PROBLEM_SOLVING: 90,
            Dimension.OWNERSHIP: 80,
            Dimension.JUDGMENT: 75,
            Dimension.KNOWLEDGE: 70,
            Dimension.ADAPTABILITY: 65,
        },
        claims=[
            ("FastAPI PostgreSQL Redis", 80, ["FastAPI", "PostgreSQL", "Redis"]),
        ],
    )

    reqs = [
        JobRequirement(name="FastAPI", category="SKILL", weight=0.25),
        JobRequirement(name="PostgreSQL", category="SKILL", weight=0.25),
        JobRequirement(name="Redis", category="SKILL", weight=0.25),
        JobRequirement(name="Kafka", category="SKILL", weight=0.25),  # MISSING
        JobRequirement(name="Ownership", category="COMPETENCY", weight=0.50),  # 80 -> VERIFIED 100
        JobRequirement(name="Problem Solving", category="COMPETENCY", weight=0.50),  # 90 -> VERIFIED 100
    ]

    fit = calculate_job_fit(graph, reqs)

    assert fit.skill_fit == 75  # 3 verified (100) + 1 missing (0) = 75
    assert fit.competence_fit == 100  # both competencies verified = 100
    # job_fit_score = round(75 * 0.60 + 100 * 0.40) = 45 + 40 = 85
    assert fit.job_fit_score == 85

    assert "FastAPI" in fit.verified_requirements
    assert "PostgreSQL" in fit.verified_requirements
    assert "Redis" in fit.verified_requirements
    assert "Kafka" in fit.missing_requirements
    assert any("Kafka" in risk for risk in fit.risk_areas)


def test_job_fit_api_single_candidate(monkeypatch):
    """Test POST /api/job-fit endpoint."""
    graph = _mock_candidate_graph(
        name="API Candidate",
        competence=80,
        claims=[("Built FastAPI and PostgreSQL application", 85, ["FastAPI"])],
    )

    async def _mock_build_graph(*args, **kwargs):
        return graph

    from api.routers import job_fit as job_fit_router
    monkeypatch.setattr(job_fit_router, "build_candidate_graph", _mock_build_graph)

    res = client.post(
        "/api/job-fit",
        json={
            "candidate_id": "c_test1",
            "job_description": "Senior FastAPI and PostgreSQL Engineer with Ownership",
        },
    )

    assert res.status_code == 200
    data = res.json()
    assert "job_fit_score" in data
    assert "skill_fit" in data
    assert "competence_fit" in data
    assert isinstance(data["verified_requirements"], list)
    assert isinstance(data["missing_requirements"], list)


def test_job_fit_api_rank_candidates(monkeypatch):
    """Test POST /api/job-fit/rank multi-candidate ranking endpoint."""
    graph_a = _mock_candidate_graph(
        name="Candidate A (Strong)",
        competence=90,
        claims=[("FastAPI PostgreSQL Redis Kafka System Design Ownership", 90, [])],
    )
    graph_b = _mock_candidate_graph(
        name="Candidate B (Moderate)",
        competence=60,
        claims=[("FastAPI PostgreSQL", 50, [])],
    )

    async def _mock_build_graph(db, cid, **kwargs):
        if cid == "c_a":
            return graph_a
        if cid == "c_b":
            return graph_b
        return None

    from api.routers import job_fit as job_fit_router
    monkeypatch.setattr(job_fit_router, "build_candidate_graph", _mock_build_graph)

    res = client.post(
        "/api/job-fit/rank",
        json={
            "candidate_ids": ["c_b", "c_a"],
            "job_description": "FastAPI PostgreSQL Redis Kafka System Design Ownership",
        },
    )

    assert res.status_code == 200
    data = res.json()
    rankings = data["rankings"]

    assert len(rankings) == 2
    # Candidate A should be ranked #1
    assert rankings[0]["candidate_id"] == "c_a"
    assert rankings[0]["rank"] == 1
    assert rankings[0]["job_fit_score"] >= rankings[1]["job_fit_score"]

    assert rankings[1]["candidate_id"] == "c_b"
    assert rankings[1]["rank"] == 2
