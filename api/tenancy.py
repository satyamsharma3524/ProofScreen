"""
D9 — the tenant ownership boundary.  Shared file; changes are announced.

THE ARCHITECTURE, IN ONE LINE

    tenant_id -> TenantScope -> scoped() / get_owned() -> rows

`filter by tenant_id` scattered through dozens of endpoints is not an
architecture, it is a checklist — and the failure mode of a checklist is the
one endpoint nobody ticked. So no handler in this codebase writes
`where(Model.tenant_id == ...)` itself. Handlers obtain a `TenantScope` from
`Depends(current_tenant)` and hand it to the two functions below, which are the
only place the predicate is written.

FAIL CLOSED. `TenantScope.require()` raises `TenantContextMissing` when there is
no tenant and no explicit system grant. A scope that cannot name its tenant
never produces an unfiltered query; it produces an exception.

THE TRUSTED PATH IS EXPLICIT AND GREPPABLE. Exactly one real flow legitimately
crosses tenants: an inbound WhatsApp message. One business number serves every
customer, so a message carries no tenant until the opt-in code or the phone
number resolves a session — and the session is what supplies the tenant for
everything written afterwards. That flow says `TenantScope.system(reason=...)`
out loud. `grep -rn "TenantScope.system" api/` lists every bypass in the
product; there are two, and both name their reason.

WHAT THIS IS NOT. It is not authentication. There are no users, no roles, no
sessions, no rotation and no expiry — a tenant holds one shared API key, which
is the minimum needed to answer "whose data is this request allowed to see?".
Building OAuth here would be inventing a subsystem the repository has no
foundation for, which D9 explicitly forbids.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import settings
from api.db import get_db
from api.models import (
    DEVELOPMENT_TENANT_ID,
    DEVELOPMENT_TENANT_NAME,
    DEVELOPMENT_TENANT_SLUG,
    ApiKey,
    Tenant,
)

log = logging.getLogger("proofscreen.tenancy")

API_KEY_HEADER = "X-API-Key"

__all__ = [
    "API_KEY_HEADER",
    "DEVELOPMENT_TENANT_ID",
    "TenantContextMissing",
    "TenantScope",
    "current_tenant",
    "get_owned",
    "hash_key",
    "scoped",
]


class TenantContextMissing(RuntimeError):
    """A tenant-scoped query was attempted with no tenant and no system grant."""


@dataclass(frozen=True)
class TenantScope:
    """Who this unit of work is allowed to touch. Immutable on purpose."""

    tenant_id: str | None = None
    is_system: bool = False
    reason: str = ""

    @classmethod
    def of(cls, tenant_id: str) -> "TenantScope":
        return cls(tenant_id=tenant_id)

    @classmethod
    def system(cls, reason: str) -> "TenantScope":
        """The trusted path. `reason` is mandatory and appears in logs.

        Only for work that genuinely has no tenant to be scoped to yet — the
        WhatsApp webhook resolving an inbound message, and seeding.
        """
        if not reason:
            raise ValueError("a system scope must state its reason")
        return cls(tenant_id=None, is_system=True, reason=reason)

    def require(self) -> str:
        """The tenant id, or an exception. Never a silent None."""
        if self.tenant_id:
            return self.tenant_id
        if self.is_system:
            raise TenantContextMissing(
                f"system scope ({self.reason}) has no tenant_id; a write needs "
                f"one — derive it from the row you resolved"
            )
        raise TenantContextMissing("no tenant context for a tenant-scoped operation")

    def owns(self, row: object | None) -> bool:
        if row is None:
            return False
        if self.is_system:
            return True
        return getattr(row, "tenant_id", None) == self.require()


def scoped(stmt, model, scope: TenantScope):
    """Add the tenant predicate to a select. The ONLY place it is written."""
    if scope.is_system:
        return stmt
    return stmt.where(model.tenant_id == scope.require())


async def get_owned(db: AsyncSession, model, pk: str | None, scope: TenantScope):
    """Primary-key fetch that returns None for another tenant's row.

    None, not an exception, so callers raise their own 404. A cross-tenant id
    must be indistinguishable from a nonexistent one — 403 would confirm the
    row exists, which is a disclosure in a hiring product.
    """
    if not pk:
        return None
    row = await db.get(model, pk)
    return row if scope.owns(row) else None


def hash_key(raw: str) -> str:
    """sha256 hex. The raw key is never written anywhere."""
    return hashlib.sha256(raw.strip().encode("utf-8")).hexdigest()


async def tenant_for_key(db: AsyncSession, raw: str) -> Tenant | None:
    row = (
        await db.execute(
            select(ApiKey).where(
                ApiKey.key_hash == hash_key(raw), ApiKey.revoked.is_(False)
            )
        )
    ).scalars().first()
    return await db.get(Tenant, row.tenant_id) if row else None


async def current_tenant(
    x_api_key: str | None = Header(default=None, alias=API_KEY_HEADER),
    db: AsyncSession = Depends(get_db),
) -> TenantScope:
    """FastAPI dependency. Every recruiter route and every dev route that
    touches tenant data depends on this.

    Resolution, in order:

      1. `X-API-Key` matches a live key  -> that key's tenant.
      2. `X-API-Key` present but unknown -> 401. Always, in every mode.
      3. No header, REQUIRE_API_KEY=false -> the DEVELOPMENT tenant, named.
      4. No header, REQUIRE_API_KEY=true  -> 401.

    Step 3 is what keeps the demo and the 332-test suite working unchanged. It
    is a named tenant, not a bypass: requests without a key see `t_dev`'s rows
    and nobody else's, which is why the isolation tests can create a second
    tenant and get a real boundary out of a system with no login screen.
    """
    if x_api_key:
        tenant = await tenant_for_key(db, x_api_key)
        if tenant is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid API key")
        return TenantScope.of(tenant.id)

    if settings.require_api_key:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, f"{API_KEY_HEADER} header is required"
        )
    return TenantScope.of(DEVELOPMENT_TENANT_ID)


async def ensure_development_tenant(conn) -> None:
    """Create `t_dev` if it is not there. Called from init_models and drop_all.

    Runs on a raw connection rather than an ORM session because both callers
    already hold one, and because this must happen before any FK to `tenants`
    can be satisfied — including the ones `scripts/interview_study.py` creates
    by writing a Candidate with the column default.
    """
    from sqlalchemy import insert

    existing = (
        await conn.execute(
            select(Tenant.id).where(Tenant.id == DEVELOPMENT_TENANT_ID)
        )
    ).first()
    if existing:
        return
    await conn.execute(
        insert(Tenant).values(
            id=DEVELOPMENT_TENANT_ID,
            name=DEVELOPMENT_TENANT_NAME,
            slug=DEVELOPMENT_TENANT_SLUG,
        )
    )
    log.info("development tenant %s ready", DEVELOPMENT_TENANT_ID)


async def create_tenant(db: AsyncSession, name: str, slug: str) -> tuple[Tenant, str]:
    """Provision a tenant and its first key. Returns (tenant, RAW KEY).

    The raw key is returned exactly once and is unrecoverable afterwards —
    only its sha256 is stored.
    """
    from api import ids

    tenant = Tenant(id=ids.tenant_id(), name=name, slug=slug)
    raw = ids.api_key_secret()
    db.add(tenant)
    # Flushed before the key is added: SQLite checks the foreign key at INSERT
    # time, and the unit of work is free to order two independent adds either
    # way round. One flush, no ordering assumption.
    await db.flush()
    db.add(
        ApiKey(
            id=ids.api_key_id(),
            tenant_id=tenant.id,
            name=f"{slug} default key",
            key_hash=hash_key(raw),
        )
    )
    await db.commit()
    return tenant, raw
