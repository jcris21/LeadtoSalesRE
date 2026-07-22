"""Coordinator Agent conversational brain on LangGraph with checkpoints
(ImplementationPlan Sprint 1; Agentic_System §5 framework recommendation).

The graph is deliberately small — a single `respond` node — because everything
non-conversational (guardrail, ownership, FSM, persistence) already lives in
deterministic services around `CoordinatorAgent`; the graph only owns the
conversational turn. What LangGraph buys here is the checkpointer: state
(the message history) is checkpointed per `thread_id = conversation_id`, so
every turn resumes from the previous checkpoint instead of starting cold.

The LLM stays pluggable behind `ConversationBrain`. `TemplateBrain` is the
deterministic default so the full pipeline runs without LLM credentials;
swapping in an LLM-backed brain (or richer multi-node graph) changes nothing
outside this module. The default checkpointer is a durable `AsyncPostgresSaver`, wired up at app
boot via `init_persistent_responder()` (own `psycopg` connection pool,
separate from the app's `asyncpg`-based SQLAlchemy engine — no official
asyncpg checkpointer exists); it falls back to `InMemorySaver` if the durable
checkpointer cannot initialize, or when explicitly injected (as tests do) via
the constructor argument. Checkpoint tables are created idempotently via
`AsyncPostgresSaver.setup()` at boot, not by an Alembic migration — that
schema is owned and versioned by `langgraph-checkpoint-postgres` itself.

`TurnState.messages` is bounded to the most recent `conversation_history_window_turns`
turns; turns evicted from the window are folded into `TurnState.summary` via a
deterministic (non-LLM) fold, so long conversations don't grow the checkpoint
payload without bound while still keeping evicted context available to the brain.
"""

from __future__ import annotations

import logging
import uuid
from typing import Protocol, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

logger = logging.getLogger(__name__)


class ConversationBrain(Protocol):
    """Generates the reply for one turn given the checkpointed history."""

    async def generate(
        self, *, system_prompt: str, history: list[dict[str, str]], text: str
    ) -> str: ...


class TemplateBrain:
    """Deterministic brain: keeps the pipeline operational and testable without
    LLM credentials. An LLM-backed implementation replaces this behind
    `ConversationBrain` without touching the graph."""

    async def generate(
        self, *, system_prompt: str, history: list[dict[str, str]], text: str
    ) -> str:
        if history:
            return (
                "¡Gracias por continuar la conversación! Sigo aquí para ayudarte a "
                "encontrar tu propiedad ideal. Cuéntame más sobre lo que buscas."
            )
        return (
            "¡Gracias por tu mensaje! Soy el asistente del equipo de asesores. "
            "Cuéntame qué tipo de propiedad buscas y en qué zona, y te ayudo a "
            "encontrar opciones."
        )


class TurnState(TypedDict, total=False):
    """Graph state. `messages` holds the active (windowed) conversational
    history — the checkpointer persists it per `thread_id`, so it survives
    across turns and (with a durable checkpointer) across process restarts.
    It is a plain replace-channel, not an accumulating reducer: `_respond_node`
    owns concatenation and truncation itself, since folding evicted turns into
    `summary` requires knowing exactly which messages are being dropped."""

    messages: list[dict[str, str]]
    summary: str
    system_prompt: str
    user_input: str
    reply: str


_SUMMARY_MAX_CHARS = 1500
_SUMMARY_TURN_PREVIEW_CHARS = 160


def _fold_summary(existing_summary: str, dropped_messages: list[dict[str, str]]) -> str:
    """Deterministically folds evicted turns into the running summary. No LLM
    call; output is length-capped so it stays bounded across an arbitrarily
    long conversation even under repeated folding."""
    lines = []
    for message in dropped_messages:
        role = message.get("role", "user")
        content = message.get("content", "").strip()
        if len(content) > _SUMMARY_TURN_PREVIEW_CHARS:
            content = content[: _SUMMARY_TURN_PREVIEW_CHARS - 1] + "…"
        lines.append(f"{role}: {content}")

    addition = " | ".join(lines)
    combined = f"{existing_summary} | {addition}" if existing_summary else addition
    if len(combined) > _SUMMARY_MAX_CHARS:
        combined = "…" + combined[-(_SUMMARY_MAX_CHARS - 1) :]
    return combined


class LangGraphResponder:
    """`ResponderPort` implementation on LangGraph with per-conversation
    checkpoints (`thread_id = conversation_id`)."""

    def __init__(
        self,
        brain: ConversationBrain | None = None,
        checkpointer: BaseCheckpointSaver | None = None,
        history_window_turns: int | None = None,
    ) -> None:
        self._brain = brain or TemplateBrain()
        if history_window_turns is None:
            from app.core.config import get_settings

            history_window_turns = get_settings().conversation_history_window_turns
        self._window_messages = history_window_turns * 2  # one turn = user + assistant

        graph = StateGraph(TurnState)
        graph.add_node("respond", self._respond_node)
        graph.add_edge(START, "respond")
        graph.add_edge("respond", END)
        self._graph = graph.compile(checkpointer=checkpointer or InMemorySaver())

    async def _respond_node(self, state: TurnState) -> dict:
        history = state.get("messages", [])
        summary = state.get("summary", "")
        brain_history = [{"role": "system", "content": summary}] + history if summary else history

        reply = await self._brain.generate(
            system_prompt=state.get("system_prompt", ""),
            history=brain_history,
            text=state.get("user_input", ""),
        )

        all_messages = history + [
            {"role": "user", "content": state.get("user_input", "")},
            {"role": "assistant", "content": reply},
        ]

        if len(all_messages) > self._window_messages:
            evicted = all_messages[: -self._window_messages]
            windowed = all_messages[-self._window_messages :]
            summary = _fold_summary(summary, evicted)
        else:
            windowed = all_messages

        return {"messages": windowed, "summary": summary, "reply": reply}

    async def respond(self, *, system_prompt: str, conversation_id: uuid.UUID, text: str) -> str:
        result = await self._graph.ainvoke(
            {"system_prompt": system_prompt, "user_input": text},
            config={"configurable": {"thread_id": str(conversation_id)}},
        )
        return result["reply"]

    async def history(self, conversation_id: uuid.UUID) -> list[dict[str, str]]:
        """Checkpointed message history for one conversation (debug/sidebar use).
        When turns have been evicted from the active window, the accumulated
        summary is surfaced as a leading system-role entry."""
        snapshot = await self._graph.aget_state(
            {"configurable": {"thread_id": str(conversation_id)}}
        )
        if not snapshot.values:
            return []
        messages = list(snapshot.values.get("messages", []))
        summary = snapshot.values.get("summary", "")
        if summary:
            return [{"role": "system", "content": summary}] + messages
        return messages


_default_responder: LangGraphResponder | None = None
_checkpointer_pool: AsyncConnectionPool | None = None


def get_default_responder() -> LangGraphResponder:
    """Process-wide responder: one shared checkpointer so all turns of a
    conversation land on the same thread state. If `init_persistent_responder()`
    already ran (FastAPI lifespan) this returns the durable, Postgres-backed
    instance; otherwise it lazily builds an in-memory-backed one (tests, or
    `conversation_checkpointer=memory`). The brain is config-driven (LLM when a
    key is present, templates otherwise); the import is lazy because
    infrastructure.llm_brain imports this module's contracts."""
    global _default_responder
    if _default_responder is None:
        from app.modules.conversation_ownership.infrastructure.llm_brain import (
            get_default_conversation_brain,
        )

        _default_responder = LangGraphResponder(brain=get_default_conversation_brain())
    return _default_responder


async def init_persistent_responder() -> None:
    """FastAPI lifespan startup hook (G13): opens the durable checkpointer's
    connection pool and installs the process-wide responder, so a process
    restart resumes prior conversational context instead of starting cold.

    Fails open: if the durable checkpointer can't initialize (unreachable DB,
    bad credentials, version mismatch), this logs the error and returns
    without touching `_default_responder` — `get_default_responder()` then
    falls back to its in-memory-backed default and boot proceeds normally
    (same degrade-not-crash pattern as the optional Gemini-key paths).

    Idempotent: a second call is a no-op if a pool is already open, so it is
    safe to call unconditionally from the lifespan without double-opening a
    pool or re-running `setup()` needlessly.
    """
    global _default_responder, _checkpointer_pool

    if _checkpointer_pool is not None:
        return

    from app.core.config import get_settings

    settings = get_settings()
    if settings.conversation_checkpointer != "postgres":
        return

    pool: AsyncConnectionPool | None = None
    try:
        pool = AsyncConnectionPool(
            conninfo=str(settings.database_url),
            min_size=1,
            max_size=5,
            open=False,
            kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        )
        await pool.open()
        checkpointer = AsyncPostgresSaver(pool)
        await checkpointer.setup()
    except Exception:
        logger.exception(
            "Durable (Postgres) checkpointer init failed; "
            "falling back to in-memory conversational history"
        )
        if pool is not None:
            try:
                await pool.close()
            except Exception:
                logger.exception("Failed to close checkpointer pool after init failure")
        return

    from app.modules.conversation_ownership.infrastructure.llm_brain import (
        get_default_conversation_brain,
    )

    _checkpointer_pool = pool
    _default_responder = LangGraphResponder(
        brain=get_default_conversation_brain(),
        checkpointer=checkpointer,
        history_window_turns=settings.conversation_history_window_turns,
    )


async def shutdown_persistent_responder() -> None:
    """FastAPI lifespan shutdown hook: closes the durable checkpointer's
    connection pool and resets module globals so a subsequent init starts
    clean (relevant for tests that exercise both lifecycle hooks)."""
    global _default_responder, _checkpointer_pool

    if _checkpointer_pool is not None:
        await _checkpointer_pool.close()
    _checkpointer_pool = None
    _default_responder = None
