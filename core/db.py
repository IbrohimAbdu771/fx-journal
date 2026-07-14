"""Async database engine and session factory."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .models import Base

logger = logging.getLogger(__name__)

_engine = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def init_engine(database_url: str, ssl: bool = False) -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        return
    connect_args: dict = {}
    if "+asyncpg" in database_url:
        # statement_cache_size=0 keeps us compatible with PgBouncer / Neon pooler;
        # a certifi-backed SSL context enables TLS for managed Postgres (Neon, RDS)
        # and works even where the OS CA bundle is missing (e.g. macOS framework py).
        connect_args["statement_cache_size"] = 0
        if ssl:
            import ssl as ssl_lib

            import certifi

            connect_args["ssl"] = ssl_lib.create_default_context(cafile=certifi.where())
    _engine = create_async_engine(
        database_url, pool_pre_ping=True, future=True, connect_args=connect_args
    )
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)
    logger.info("DB engine initialized: %s", database_url.split("@")[-1])


async def create_tables() -> None:
    assert _engine is not None, "init_engine() must be called first"
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("DB tables ready")


@asynccontextmanager
async def session_scope():
    """Transactional session context: commits on success, rolls back on error."""
    assert _sessionmaker is not None, "init_engine() must be called first"
    async with _sessionmaker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
