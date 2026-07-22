"""G13 — startup/shutdown lifecycle of the process-wide LangGraph responder.

Uses fakes for the pool/saver (no real Postgres) so these stay fast, always-on
unit tests: they verify our own control flow (idempotent init, mode
switching, clean teardown), not psycopg/langgraph-checkpoint-postgres
themselves — that's covered by the Postgres-gated integration test.
"""

from langgraph.checkpoint.memory import InMemorySaver

import app.modules.conversation_ownership.application.langgraph_responder as responder_module
from app.core.config import get_settings


class FakePool:
    def __init__(self, *args, **kwargs) -> None:
        self.open_calls = 0
        self.close_calls = 0

    async def open(self) -> None:
        self.open_calls += 1

    async def close(self) -> None:
        self.close_calls += 1


class FakeSaver(InMemorySaver):
    """Subclasses `InMemorySaver` (a real `BaseCheckpointSaver`) so it passes
    `graph.compile()`'s strict isinstance check, while overriding `setup()` to
    count calls the way `AsyncPostgresSaver.setup()` would be counted."""

    def __init__(self, pool) -> None:
        super().__init__()
        self.pool = pool
        self.setup_calls = 0

    async def setup(self) -> None:
        self.setup_calls += 1


def _reset_module_globals():
    responder_module._default_responder = None
    responder_module._checkpointer_pool = None


async def test_init_persistent_responder_is_idempotent(monkeypatch):
    _reset_module_globals()
    monkeypatch.setenv("CONVERSATION_CHECKPOINTER", "postgres")
    get_settings.cache_clear()

    created_pools: list[FakePool] = []

    def fake_pool_factory(*args, **kwargs):
        pool = FakePool()
        created_pools.append(pool)
        return pool

    monkeypatch.setattr(responder_module, "AsyncConnectionPool", fake_pool_factory)
    monkeypatch.setattr(responder_module, "AsyncPostgresSaver", FakeSaver)

    try:
        await responder_module.init_persistent_responder()
        await responder_module.init_persistent_responder()  # second call: no-op

        assert len(created_pools) == 1  # pool opened exactly once, not twice
        assert created_pools[0].open_calls == 1
        assert responder_module._default_responder is not None
    finally:
        await responder_module.shutdown_persistent_responder()
        get_settings.cache_clear()


async def test_memory_mode_skips_durable_init_and_get_default_responder_falls_back(monkeypatch):
    _reset_module_globals()
    monkeypatch.setenv("CONVERSATION_CHECKPOINTER", "memory")
    get_settings.cache_clear()

    try:
        await responder_module.init_persistent_responder()

        assert responder_module._checkpointer_pool is None
        assert responder_module._default_responder is None

        # get_default_responder() still works, falling back to its lazy
        # in-memory-backed default (pre-existing behavior, unaffected by G13).
        responder = responder_module.get_default_responder()
        assert responder is not None
    finally:
        _reset_module_globals()
        get_settings.cache_clear()
