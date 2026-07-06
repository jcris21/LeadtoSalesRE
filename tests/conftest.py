"""Test fixtures: an in-memory SQLite engine swapped in for the Supabase
Postgres engine, so Sprint 0 modules can be exercised in CI without a real
database. Generic sqlalchemy.Uuid/JSON types (see db_models modules) are what
make this portable — the same models run against SQLite here and Postgres in
prod/staging.
"""

import os

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-ci-only")

import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import app.core.database as database_module  # noqa: E402
from app.core.database import Base, get_db_session  # noqa: E402
from app.main import (
    app,  # noqa: E402  (import registers every module's ORM models on Base.metadata)
)


@pytest_asyncio.fixture
async def test_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(test_engine):
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    database_module._engine = test_engine
    database_module._session_factory = factory
    yield factory
    database_module._engine = None
    database_module._session_factory = None


@pytest_asyncio.fixture
async def client(session_factory):
    async def _override_get_db_session():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = _override_get_db_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def db_session(session_factory):
    async with session_factory() as session:
        yield session
        await session.commit()
