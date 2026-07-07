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
outside this module. The default checkpointer is in-process (`InMemorySaver`);
a durable Postgres checkpointer plugs into the same constructor argument when
cross-replica resume is needed (Sprint 8 concern).
"""

from __future__ import annotations

import operator
import uuid
from typing import Annotated, Protocol, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph


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
    """Graph state. `messages` accumulates across turns via the checkpointer —
    that history IS the conversational memory the plan's 'checkpoints' refer to."""

    messages: Annotated[list[dict[str, str]], operator.add]
    system_prompt: str
    user_input: str
    reply: str


class LangGraphResponder:
    """`ResponderPort` implementation on LangGraph with per-conversation
    checkpoints (`thread_id = conversation_id`)."""

    def __init__(
        self,
        brain: ConversationBrain | None = None,
        checkpointer: BaseCheckpointSaver | None = None,
    ) -> None:
        self._brain = brain or TemplateBrain()

        graph = StateGraph(TurnState)
        graph.add_node("respond", self._respond_node)
        graph.add_edge(START, "respond")
        graph.add_edge("respond", END)
        self._graph = graph.compile(checkpointer=checkpointer or InMemorySaver())

    async def _respond_node(self, state: TurnState) -> dict:
        history = state.get("messages", [])
        reply = await self._brain.generate(
            system_prompt=state.get("system_prompt", ""),
            history=history,
            text=state.get("user_input", ""),
        )
        return {
            "messages": [
                {"role": "user", "content": state.get("user_input", "")},
                {"role": "assistant", "content": reply},
            ],
            "reply": reply,
        }

    async def respond(self, *, system_prompt: str, conversation_id: uuid.UUID, text: str) -> str:
        result = await self._graph.ainvoke(
            {"system_prompt": system_prompt, "user_input": text},
            config={"configurable": {"thread_id": str(conversation_id)}},
        )
        return result["reply"]

    async def history(self, conversation_id: uuid.UUID) -> list[dict[str, str]]:
        """Checkpointed message history for one conversation (debug/sidebar use)."""
        snapshot = await self._graph.aget_state(
            {"configurable": {"thread_id": str(conversation_id)}}
        )
        return list(snapshot.values.get("messages", [])) if snapshot.values else []


_default_responder: LangGraphResponder | None = None


def get_default_responder() -> LangGraphResponder:
    """Process-wide responder: one shared checkpointer so all turns of a
    conversation land on the same thread state."""
    global _default_responder
    if _default_responder is None:
        _default_responder = LangGraphResponder()
    return _default_responder
