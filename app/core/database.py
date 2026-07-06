"""Async SQLAlchemy engine/session against Supabase Postgres.

organization_id isolation (QA-03) is enforced primarily at the application layer:
every repository query and every router filters explicitly by organization_id /
the authenticated principal's organization_id. RLS policies also exist on every
org-scoped table (see alembic/versions/0001_sprint0_foundation.py) as
defense-in-depth per Architecture.md Iteration 1 — but they only take effect for
a database role WITHOUT BYPASSRLS. This backend connects with the Supabase
`service_role` key, which has BYPASSRLS by design (Supabase's own model: the
trusted backend bypasses RLS, RLS protects direct client access via PostgREST).
If this service ever connects with a non-bypass role, wire a
`SET LOCAL app.current_organization_id` per request before relying on RLS here.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for every SQLAlchemy model in every bounded context."""


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            str(settings.database_url).replace("postgresql://", "postgresql+asyncpg://", 1),
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=10,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding a request-scoped session."""
    async with get_session_factory()() as session:
        yield session


@asynccontextmanager
async def session_scope() -> AsyncGenerator[AsyncSession, None]:
    """Context manager for use outside request scope (workers, scripts)."""
    async with get_session_factory()() as session:
        async with session.begin():
            yield session
