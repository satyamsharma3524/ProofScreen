"""
D9 — tenant isolation.

The point of this file is stated once, here: *"filter by tenant_id" scattered
through dozens of endpoints is not an architecture.* So these tests do not
sample a couple of endpoints and declare the boundary sound. They assert the
STRUCTURE — every owned table has the column, every route that touches tenant
data declares the dependency, the trusted path is exactly one line — and then
walk the recruiter and dev surfaces end to end with two tenants holding
deliberately identical data.

A cross-tenant id must return 404, never 403. 403 confirms the row exists,
which in a hiring product tells tenant A that a named person applied to
tenant B.
"""

from __future__ import annotations

import asyncio
import pathlib

import pytest
from sqlalchemy import select

from api.config import settings
from api.db import SessionLocal
from api.models import (
    DEVELOPMENT_TENANT_ID,
    Base,
    Candidate,
    CandidateOutcome,
    ChatSession,
    Claim,
    ClaimScore,
    ContradictionRow,
    Evidence,
    JobRole,
    Profile,
    Question,
    Response,
    Resume,
    SessionFact,
)
from tests.conftest import RESUME, STRONG_ANSWERS

OWNED_MODELS = [
    JobRole, Candidate, Resume, ChatSession, Claim, Question, Response,
    Evidence, ClaimScore, SessionFact, ContradictionRow, Profile,
    CandidateOutcome,
]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def provision(client, slug: str) -> dict:
    resp = client.post("/api/dev/tenants", json={"slug": slug, "name": slug.title()})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return {"id": body["id"], "headers": {"X-API-Key": body["api_key"]}}


def onboard_as(client, headers: dict, name: str, phone: str) -> dict:
    resp = client.post(
        "/api/candidates/text",
        json={"resume_text": RESUME, "name": name, "phone": phone,
              "role": "Support Team Lead"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def interview_as(client, headers: dict, session_id: str) -> None:
    assert client.post(
        f"/api/dev/sessions/{session_id}/start", headers=headers
    ).status_code == 200
    for index in range(20):
        state = client.get(f"/api/sessions/{session_id}", headers=headers).json()
        if not state["next_question"]:
            break
        body = client.post(
            f"/api/dev/sessions/{session_id}/answer",
            json={"text": STRONG_ANSWERS[index % len(STRONG_ANSWERS)]},
            headers=headers,
        ).json()
        if body["done"]:
            break


@pytest.fixture(scope="module")
def two_tenants(client):
    """Two tenants with deliberately IDENTICAL candidate data.

    Identical on purpose: if isolation only appeared to work because the rows
    differed, this fixture would hide it. Same resume, same answers, same role
    weights — the tenant is the only variable.
    """
    a = provision(client, "isolation-a")
    b = provision(client, "isolation-b")
    for side, phone in ((a, "+919810050001"), (b, "+919810050002")):
        body = onboard_as(client, side["headers"], "Identical Twin", phone)
        side["candidate_id"] = body["candidate_id"]
        side["session_id"] = body["session_id"]
        interview_as(client, side["headers"], side["session_id"])
        side["role_id"] = client.post(
            "/api/recruiter/roles",
            json={"title": "Ops Lens", "job_family": "bpo_operations",
                  "claim_weights": {"team_handling": 70, "csat_improvement": 30}},
            headers=side["headers"],
        ).json()["id"]
    return a, b


# ---------------------------------------------------------------------------
# structure
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model", OWNED_MODELS, ids=lambda m: m.__tablename__)
def test_every_owned_table_carries_a_non_null_indexed_tenant_id(model):
    """The column, its nullability, its index and its foreign key.

    Nullability is the load-bearing assertion. A nullable tenant_id is a row
    that belongs to nobody: `scoped()` would exclude it from every query
    forever, which is data loss that looks exactly like isolation working.
    """
    column = model.__table__.columns["tenant_id"]
    assert column.nullable is False, f"{model.__tablename__}.tenant_id is nullable"
    assert any(
        fk.column.table.name == "tenants" for fk in column.foreign_keys
    ), f"{model.__tablename__}.tenant_id is not a foreign key to tenants"
    indexed = column.index or any(
        "tenant_id" in [c.name for c in ix.columns] for ix in model.__table__.indexes
    )
    assert indexed, f"{model.__tablename__}.tenant_id is not indexed"


def test_the_tenant_tables_exist(client):
    assert "tenants" in Base.metadata.tables
    assert "api_keys" in Base.metadata.tables


def test_no_route_that_touches_tenant_data_forgets_the_dependency(client):
    """The anti-checklist test.

    An endpoint can only bypass ownership by not depending on `current_tenant`,
    so this walks every registered route and asserts the dependency is there,
    against an explicit allowlist of routes that touch no tenant data. A new
    recruiter endpoint without it fails here — which is the merge gate the plan
    asks for, expressed as a test rather than as a review convention.
    """
    from api.main import app
    from api.tenancy import current_tenant

    exempt = {
        "/", "/api/health", "/openapi.json", "/docs", "/docs/oauth2-redirect",
        "/redoc",
        "/api/webhooks/whatsapp",     # the trusted path; no tenant exists yet
        "/api/dev/fixture",           # a static JSON file on disk
        "/api/dev/detect",            # a pure function of text and the taxonomy
        "/api/dev/llm",               # process-level counters
        "/api/dev/reset",             # drops every tenant; scoping is meaningless
        "/api/dev/tenants",           # creates the tenant; there is none to scope by
        "/api/dev/provenance",        # process-level version stamp
        "/api/recruiter/taxonomy",    # read-only view of a JSON file
    }

    missing = []
    for route in app.routes:
        path = getattr(route, "path", None)
        dependant = getattr(route, "dependant", None)
        if path is None or dependant is None or path in exempt:
            continue
        if current_tenant not in {d.call for d in dependant.dependencies}:
            missing.append(f"{sorted(route.methods)} {path}")
    assert not missing, (
        "these routes touch tenant data without Depends(current_tenant): "
        + ", ".join(missing)
    )


def test_the_system_scope_is_used_in_exactly_one_place():
    """A grep, as a test. The trusted path must stay small and stay named.

    Walks the AST rather than the text, so a docstring explaining the bypass
    does not count as one. `scripts/` is out of scope deliberately: a support
    CLI reading its own database is not a tenant, and it argues that at its own
    callsite. This is about the SERVING code.
    """
    import ast

    hits = []
    for path in sorted(pathlib.Path("api").rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "system"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "TenantScope"
            ):
                hits.append(f"{path}:{node.lineno}")
    assert len(hits) == 1, (
        f"the cross-tenant trusted path grew; every use needs review: {hits}"
    )
    assert hits[0].startswith("api/routers/whatsapp.py")


# ---------------------------------------------------------------------------
# the development tenant
# ---------------------------------------------------------------------------


def test_requests_without_a_key_are_the_development_tenant_not_everybody(client):
    """The demo path. A missing key is a NAMED tenant, never a global view."""
    from api.models import Tenant

    async def scenario():
        async with SessionLocal() as db:
            return await db.get(Tenant, DEVELOPMENT_TENANT_ID)

    tenant = asyncio.run(scenario())
    assert tenant is not None and tenant.slug == "dev"

    body = onboard_as(client, {}, "Unkeyed Candidate", "+919810051001")
    assert client.get(
        f"/api/recruiter/candidates/{body['candidate_id']}"
    ).status_code == 200


def test_a_tenant_scoped_pipeline_writes_no_development_tenant_rows(client):
    """The column default exists for Phase 3's frozen study script. Nothing in
    `api/` may rely on it — a production write that forgot its tenant would
    land in `t_dev` and be invisible to its real owner.

    So: drive a whole interview under a fresh tenant, then read back every row
    it produced and assert each one carries that tenant.
    """
    side = provision(client, "no-default-leak")
    body = onboard_as(client, side["headers"], "Leak Check", "+919810051002")
    interview_as(client, side["headers"], body["session_id"])
    assert client.post(
        f"/api/recruiter/candidates/{body['candidate_id']}/outcome",
        json={"decision": "shortlisted"},
        headers=side["headers"],
    ).status_code == 201

    async def scenario():
        async with SessionLocal() as db:
            async def rows(model, clause):
                return (await db.execute(select(model).where(clause))).scalars().all()

            candidate = await db.get(Candidate, body["candidate_id"])
            session = await db.get(ChatSession, body["session_id"])
            claims = await rows(Claim, Claim.candidate_id == candidate.id)
            claim_ids = [c.id for c in claims]
            return [
                candidate,
                session,
                *claims,
                *await rows(Resume, Resume.candidate_id == candidate.id),
                *await rows(Question, Question.session_id == session.id),
                *await rows(Response, Response.session_id == session.id),
                *await rows(Evidence, Evidence.claim_id.in_(claim_ids)),
                *await rows(ClaimScore, ClaimScore.claim_id.in_(claim_ids)),
                *await rows(SessionFact, SessionFact.session_id == session.id),
                *await rows(
                    ContradictionRow, ContradictionRow.session_id == session.id
                ),
                *await rows(Profile, Profile.candidate_id == candidate.id),
                *await rows(
                    CandidateOutcome, CandidateOutcome.candidate_id == candidate.id
                ),
            ]

    found = asyncio.run(scenario())
    assert len(found) > 15, "the pipeline wrote almost nothing; this proves little"
    stray = [f"{type(r).__name__}:{r.id}" for r in found if r.tenant_id != side["id"]]
    assert not stray, f"rows fell back to the development tenant: {stray}"


# ---------------------------------------------------------------------------
# the boundary
# ---------------------------------------------------------------------------


def test_tenant_a_cannot_read_tenant_b_evaluation_surface(client, two_tenants):
    """Graph, ranked list and session state — all three."""
    a, b = two_tenants

    cross = client.get(
        f"/api/recruiter/candidates/{b['candidate_id']}", headers=a["headers"]
    )
    assert cross.status_code == 404
    assert cross.json()["detail"] == "candidate not found"

    own = client.get(
        f"/api/recruiter/candidates/{a['candidate_id']}", headers=a["headers"]
    )
    assert own.status_code == 200
    assert own.json()["competence_score"] > 0

    listed = client.get("/api/recruiter/candidates", headers=a["headers"]).json()
    ids_seen = {row["id"] for row in listed["candidates"]}
    assert a["candidate_id"] in ids_seen
    assert b["candidate_id"] not in ids_seen

    assert client.get(
        f"/api/sessions/{b['session_id']}", headers=a["headers"]
    ).status_code == 404


def test_tenant_a_cannot_reach_tenant_b_evidence_through_the_dev_tools(
    client, two_tenants
):
    """The dev endpoints are the widest surface in the app and the easiest to
    forget. Both session routes must refuse a foreign session — the second one
    is a WRITE into another customer's interview."""
    a, b = two_tenants

    assert client.post(
        f"/api/dev/sessions/{b['session_id']}/start", headers=a["headers"]
    ).status_code == 404
    assert client.post(
        f"/api/dev/sessions/{b['session_id']}/answer",
        json={"text": "trying to write into someone else's interview"},
        headers=a["headers"],
    ).status_code == 404


def test_tenant_a_cannot_update_tenant_b_records(client, two_tenants):
    """Recording a decision against another customer's candidate would corrupt
    the one table the product's central claim is falsified against."""
    a, b = two_tenants

    assert client.post(
        f"/api/recruiter/candidates/{b['candidate_id']}/outcome",
        json={"decision": "rejected"},
        headers=a["headers"],
    ).status_code == 404
    assert client.get(
        f"/api/recruiter/candidates/{b['candidate_id']}/outcomes",
        headers=a["headers"],
    ).status_code == 404


def test_tenant_a_cannot_borrow_tenant_b_lens(client, two_tenants):
    """A role is only a weight profile — arguably harmless to read. It is still
    not theirs, and `scored_for` echoing a foreign role's title would disclose
    what another customer calls their jobs."""
    a, b = two_tenants

    roles = client.get("/api/recruiter/roles", headers=a["headers"]).json()
    assert {r["id"] for r in roles} == {a["role_id"]}

    ranked = client.get(
        f"/api/recruiter/candidates?role_id={b['role_id']}", headers=a["headers"]
    ).json()
    assert ranked["scored_for"] is None, "another tenant's lens was applied"

    graph = client.get(
        f"/api/recruiter/candidates/{a['candidate_id']}?role_id={b['role_id']}",
        headers=a["headers"],
    ).json()
    assert graph["scored_for"] is None

    assert client.post(
        f"/api/recruiter/candidates/{a['candidate_id']}/outcome",
        json={"decision": "rejected", "role_id": b["role_id"]},
        headers=a["headers"],
    ).status_code == 404

    assert client.post(
        "/api/candidates/text",
        json={"resume_text": RESUME, "name": "Borrowed Lens",
              "phone": "+919810051010", "role_id": b["role_id"]},
        headers=a["headers"],
    ).status_code == 404


def test_a_cross_tenant_id_is_indistinguishable_from_a_missing_one(
    client, two_tenants
):
    """No existence leak. The 404 for someone else's candidate must be
    byte-identical to the 404 for a candidate nobody ever created."""
    a, b = two_tenants

    theirs = client.get(
        f"/api/recruiter/candidates/{b['candidate_id']}", headers=a["headers"]
    )
    nobody = client.get(
        "/api/recruiter/candidates/c_neverexisted", headers=a["headers"]
    )
    assert theirs.status_code == nobody.status_code == 404
    assert theirs.json() == nobody.json()


def test_the_validation_report_does_not_pool_tenants(client, two_tenants):
    """M4a over another customer's hiring decisions would disclose their
    pipeline. PRODUCTION_READINESS 4 calls that a decision, not a default."""
    a, b = two_tenants
    assert client.post(
        f"/api/recruiter/candidates/{b['candidate_id']}/outcome",
        json={"decision": "hired"},
        headers=b["headers"],
    ).status_code == 201
    report = client.get("/api/recruiter/validation", headers=a["headers"]).json()
    assert report["overall"]["n_decided"] == 0, (
        "tenant A's validation report counted tenant B's decisions"
    )


# ---------------------------------------------------------------------------
# credentials
# ---------------------------------------------------------------------------


def test_an_unknown_key_is_401_in_every_mode(client):
    resp = client.get("/api/recruiter/candidates", headers={"X-API-Key": "psk_nope"})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "invalid API key"


def test_missing_context_fails_closed_when_a_key_is_required(client, monkeypatch):
    """With REQUIRE_API_KEY on, no key is 401 — not the development tenant,
    and certainly not everything."""
    monkeypatch.setattr(settings, "require_api_key", True)
    resp = client.get("/api/recruiter/candidates")
    assert resp.status_code == 401
    assert "X-API-Key" in resp.json()["detail"]

    side = provision(client, "fail-closed-check")
    assert client.get(
        "/api/recruiter/candidates", headers=side["headers"]
    ).status_code == 200


def test_the_raw_api_key_is_never_stored(client):
    """A database dump must disclose no credential."""
    from api.models import ApiKey
    from api.tenancy import hash_key

    resp = client.post("/api/dev/tenants", json={"slug": "key-storage", "name": "K"})
    raw = resp.json()["api_key"]
    assert raw.startswith("psk_")

    async def scenario():
        async with SessionLocal() as db:
            return (await db.execute(select(ApiKey))).scalars().all()

    rows = asyncio.run(scenario())
    stored = {r.key_hash for r in rows}
    assert raw not in stored
    assert hash_key(raw) in stored
    assert all(len(r.key_hash) == 64 for r in rows)


def test_a_duplicate_tenant_slug_is_refused(client):
    client.post("/api/dev/tenants", json={"slug": "dupe", "name": "One"})
    assert client.post(
        "/api/dev/tenants", json={"slug": "dupe", "name": "Two"}
    ).status_code == 409


# ---------------------------------------------------------------------------
# the enforcement primitive itself
# ---------------------------------------------------------------------------


def test_a_scope_with_no_tenant_raises_rather_than_returning_everything():
    """The single most important behaviour in api/tenancy.py.

    If `require()` returned None instead of raising, `scoped()` would build
    `WHERE tenant_id IS NULL`, match nothing, and look like it worked — right
    up to `get_owned`, which would then match everything.
    """
    from api.tenancy import TenantContextMissing, TenantScope, scoped

    empty = TenantScope()
    with pytest.raises(TenantContextMissing):
        empty.require()
    with pytest.raises(TenantContextMissing):
        scoped(select(Candidate), Candidate, empty)
    with pytest.raises(ValueError):
        TenantScope.system("")          # a bypass must state its reason


def test_scoped_actually_narrows_the_query():
    """Assert the SQL, not the intention."""
    from api.tenancy import TenantScope, scoped

    sql = str(scoped(select(Candidate), Candidate, TenantScope.of("t_abc")))
    assert "WHERE candidates.tenant_id = " in sql
    # A system scope adds no predicate at all. Checked on the WHERE clause,
    # not the whole statement: `tenant_id` is in the SELECT list either way.
    assert "WHERE" not in str(
        scoped(select(Candidate), Candidate, TenantScope.system("test"))
    )


def test_the_schema_guard_finds_a_missing_column(client):
    """`create_all()` cannot add a column, so a pre-Phase-4 database has to be
    told to reset rather than failing on the first query.

    Two assertions: the guard is clean against the CURRENT schema, and it
    actually detects an absence rather than always returning [].
    """
    from api.db import _REQUIRED_COLUMNS, _check_columns, verify_schema

    assert ("candidates", "tenant_id") in _REQUIRED_COLUMNS
    assert asyncio.run(verify_schema()) == []

    class StaleInspector:
        def get_table_names(self):
            return ["candidates"]

        def get_columns(self, table):
            return [{"name": "id"}, {"name": "name"}]

    import sqlalchemy

    real = sqlalchemy.inspect
    sqlalchemy.inspect = lambda _conn: StaleInspector()
    try:
        assert _check_columns(None) == ["candidates.tenant_id"]
    finally:
        sqlalchemy.inspect = real
