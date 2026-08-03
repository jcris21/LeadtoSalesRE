"""G13 — durability of the LangGraph checkpoint against a real Postgres.

Gated behind `@pytest.mark.integration` and an explicit `TEST_POSTGRES_DSN`
env var (deliberately NOT `DATABASE_URL` — that points at this project's
Supabase system-of-record, and this test creates/writes checkpoint tables, so
it must never run against it by accident). Skips cleanly when unset, which is
the default in CI and local dev.
"""

import os
import uuid

import pytest
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.modules.conversation_ownership.application.langgraph_responder import (
    LangGraphResponder,
)

TEST_POSTGRES_DSN = os.environ.get("TEST_POSTGRES_DSN")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not TEST_POSTGRES_DSN,
        reason="TEST_POSTGRES_DSN not set; skipping Postgres checkpointer integration test",
    ),
]


class RecordingBrain:
    def __init__(self) -> None:
        self.seen_histories: list[list[dict[str, str]]] = []

    async def generate(self, *, system_prompt: str, history, text: str) -> str:
        self.seen_histories.append(list(history))
        return f"reply-{len(self.seen_histories)}"


async def _open_saver(pool: AsyncConnectionPool):
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    saver = AsyncPostgresSaver(pool)
    await saver.setup()
    return saver


async def test_history_persists_across_independently_constructed_saver_instances():
    """Two independent pool/saver instances bound to the same DB and
    `thread_id` see the same checkpointed history — the durability guarantee
    an in-memory checkpointer cannot provide across a process restart."""
    conversation_id = uuid.uuid4()
    connection_kwargs = {"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row}

    pool_a = AsyncConnectionPool(
        conninfo=TEST_POSTGRES_DSN, min_size=1, max_size=2, open=False, kwargs=connection_kwargs
    )
    await pool_a.open()
    try:
        saver_a = await _open_saver(pool_a)
        responder_a = LangGraphResponder(brain=RecordingBrain(), checkpointer=saver_a)
        await responder_a.respond(
            system_prompt="p", conversation_id=conversation_id, text="turno 1"
        )
    finally:
        await pool_a.close()

    pool_b = AsyncConnectionPool(
        conninfo=TEST_POSTGRES_DSN, min_size=1, max_size=2, open=False, kwargs=connection_kwargs
    )
    await pool_b.open()
    try:
        saver_b = await _open_saver(pool_b)
        responder_b = LangGraphResponder(brain=RecordingBrain(), checkpointer=saver_b)

        history = await responder_b.history(conversation_id)
        assert [m["content"] for m in history] == ["turno 1", "reply-1"]
    finally:
        await pool_b.close()
