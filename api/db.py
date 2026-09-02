"""Async engine + session factory. create_all at startup, no Alembic."""

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

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session


async def init_models() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    log.info("schema ready (%s)", "sqlite" if _is_sqlite else "postgres")


async def drop_all() -> None:
    """Used by POST /api/dev/reset. Guarded by ENABLE_DEV_ENDPOINTS."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
