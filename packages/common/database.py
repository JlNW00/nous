"""Database session factories for async (API) and sync (workers) usage."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager, contextmanager
from typing import AsyncGenerator, Generator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from packages.common.config import settings


# ── Build URLs ──────────────────────────────────────────────────────────────

# Async URL: used as-is from env (postgresql+asyncpg://...)
_async_url = settings.database_url

# Sync URL: swap driver and keep everything else including query params
_sync_url = _async_url.replace("+asyncpg", "+psycopg2")


# ── Async engine (for FastAPI) ──────────────────────────────────────────────

async_engine = create_async_engine(
    _async_url,
    echo=False,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@asynccontextmanager
async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    session = AsyncSessionLocal()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for request-scoped sessions."""
    async with get_async_session() as session:
        yield session


# ── Sync engine (for Celery workers and sync investigation) ────────────────

sync_engine = create_engine(
    _sync_url,
    echo=False,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
)

SyncSessionLocal = sessionmaker(bind=sync_engine, expire_on_commit=False)


@contextmanager
def get_sync_session() -> Generator[Session, None, None]:
    session = SyncSessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
