"""Async engine + session factory. create_all at startup, no Alembic.

Two Phase 4 additions, both about the same missing thing:

  ensure_development_tenant()  every FK to `tenants` needs `t_dev` to exist
  verify_schema()              create_all() cannot ADD a column, so a database
                               from before Phase 4 must be told to reset

Without the second, a pre-Phase-4 development database starts cleanly and then
fails on the first query with `no such column: candidates.tenant_id`, which
reads like a code bug and is actually a documented one-line fix.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from api.config import settings
from api.models import Base

log = logging.getLogger("proofscreen.db")

_is_sqlite = settings.database_url.startswith("sqlite")

# SQLite is here purely so `pytest` runs without Docker. Production path is
# Postgres 16 + asyncpg.
_kwargs: dict = {"echo": False, "future": True}
if _is_sqlite:
    _kwargs.update(connect_args={"check_same_thread": False}, poolclass=StaticPool)
else:
    _kwargs.update(pool_pre_ping=True, pool_size=10, max_overflow=20)

engine = create_async_engine(settings.database_url, **_kwargs)

if _is_sqlite:
    from sqlalchemy import event

    @event.listens_for(engine.sync_engine, "connect")
    def _arm_sqlite_foreign_keys(dbapi_connection, _record):  # pragma: no cover
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session


class SchemaOutOfDate(RuntimeError):
    """The database predates a schema change and create_all cannot fix it."""


# (table, column) pairs added after the last schema reset. Checked at startup
# on tables that ALREADY EXIST — create_all() creates missing tables happily
# and missing columns not at all.
# KEEP THIS IN SYNC WITH THE MODELS. A pair listed here that does not exist in
# models.py makes every startup raise; a column added to models.py and not
# listed here is a stale database that fails at the first query instead.
_REQUIRED_COLUMNS: tuple[tuple[str, str], ...] = (
    ("candidates", "tenant_id"),
    ("sessions", "tenant_id"),
    ("responses", "tenant_id"),
    ("candidate_outcomes", "tenant_id"),
    ("profiles", "latest_evaluation_id"),
    ("candidate_outcomes", "evaluation_id"),
    ("questions", "move"),
)


def _check_columns(sync_conn) -> list[str]:
    from sqlalchemy import inspect as sa_inspect

    inspector = sa_inspect(sync_conn)
    present = set(inspector.get_table_names())
    missing: list[str] = []
    for table, column in _REQUIRED_COLUMNS:
        if table not in present:
            continue                       # create_all will build it correctly
        names = {c["name"] for c in inspector.get_columns(table)}
        if column not in names:
            missing.append(f"{table}.{column}")
    return missing


async def verify_schema() -> list[str]:
    """Columns this build needs that an existing database does not have.

    Returns the list rather than raising, so a caller can decide. `init_models`
    raises; a test can inspect.
    """
    async with engine.connect() as conn:
        return await conn.run_sync(_check_columns)


async def init_models() -> None:
    stale = await verify_schema()
    if stale:
        raise SchemaOutOfDate(
            "this database predates the current schema and is missing "
            + ", ".join(stale)
            + ". There is no Alembic here by design: run `docker compose down -v` "
            "and re-seed (or delete the sqlite file). See CLAUDE.md rule 7."
        )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Imported here, not at module scope: tenancy imports db for get_db.
        from api.tenancy import ensure_development_tenant

        await ensure_development_tenant(conn)
    log.info("schema ready (%s)", "sqlite" if _is_sqlite else "postgres")


async def drop_all() -> None:
    """Used by POST /api/dev/reset. Guarded by ENABLE_DEV_ENDPOINTS.

    Recreates the development tenant, because every tenant_id column defaults
    to it and every one of them is a foreign key.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        from api.tenancy import ensure_development_tenant

        await ensure_development_tenant(conn)
