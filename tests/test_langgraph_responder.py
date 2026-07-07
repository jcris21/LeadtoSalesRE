"""Sprint 1 — Coordinator Agent on LangGraph with checkpoints.

What the plan requires ("Coordinator Agent sobre LangGraph con checkpoints",
Architecture.md §6.1) and these tests verify:

- the conversational turn runs through a compiled LangGraph StateGraph;
- state is checkpointed per conversation (`thread_id = conversation_id`): a
  second turn resumes from the first turn's history;
- checkpoints are isolated between conversations;
- the brain stays pluggable behind `ConversationBrain` (LLM lands there later).
"""

import uuid

from app.modules.conversation_ownership.application.langgraph_responder import (
    LangGraphResponder,
    TemplateBrain,
)


class RecordingBrain:
    """Captures the history the graph hands to the brain each turn."""

    def __init__(self) -> None:
        self.seen_histories: list[list[dict[str, str]]] = []

    async def generate(self, *, system_prompt: str, history, text: str) -> str:
        self.seen_histories.append(list(history))
        return f"reply-{len(self.seen_histories)}"


async def test_turn_runs_through_graph_and_returns_brain_reply():
    responder = LangGraphResponder(brain=RecordingBrain())
    reply = await responder.respond(
        system_prompt="prompt", conversation_id=uuid.uuid4(), text="hola"
    )
    assert reply == "reply-1"


async def test_checkpoint_resumes_history_across_turns_same_conversation():
    brain = RecordingBrain()
    responder = LangGraphResponder(brain=brain)
    conversation_id = uuid.uuid4()

    await responder.respond(system_prompt="p", conversation_id=conversation_id, text="turno 1")
    await responder.respond(system_prompt="p", conversation_id=conversation_id, text="turno 2")

    assert brain.seen_histories[0] == []  # first turn starts cold
    # Second turn resumed from the checkpoint: user turn 1 + assistant reply 1.
    assert brain.seen_histories[1] == [
        {"role": "user", "content": "turno 1"},
        {"role": "assistant", "content": "reply-1"},
    ]

    history = await responder.history(conversation_id)
    assert [m["content"] for m in history] == ["turno 1", "reply-1", "turno 2", "reply-2"]


async def test_checkpoints_are_isolated_per_conversation():
    brain = RecordingBrain()
    responder = LangGraphResponder(brain=brain)

    await responder.respond(system_prompt="p", conversation_id=uuid.uuid4(), text="conv A")
    await responder.respond(system_prompt="p", conversation_id=uuid.uuid4(), text="conv B")

    assert brain.seen_histories == [[], []]  # neither saw the other's history


async def test_template_brain_is_deterministic_and_history_aware():
    responder = LangGraphResponder(brain=TemplateBrain())
    conversation_id = uuid.uuid4()

    first = await responder.respond(system_prompt="p", conversation_id=conversation_id, text="hola")
    second = await responder.respond(
        system_prompt="p", conversation_id=conversation_id, text="sigo aquí"
    )

    assert "asistente del equipo de asesores" in first
    assert first != second  # follow-up turns acknowledge the ongoing conversation
