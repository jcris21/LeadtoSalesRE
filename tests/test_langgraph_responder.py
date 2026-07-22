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

from langgraph.checkpoint.memory import InMemorySaver

from app.modules.conversation_ownership.application.langgraph_responder import (
    LangGraphResponder,
    TemplateBrain,
    _fold_summary,
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


# --- G13: windowed history + deterministic summary -------------------------


def test_fold_summary_is_deterministic_and_length_capped():
    dropped = [
        {"role": "user", "content": "turno 1"},
        {"role": "assistant", "content": "reply-1"},
    ]

    first = _fold_summary("", dropped)
    second = _fold_summary(first, dropped)  # same fold applied again

    assert first == _fold_summary("", dropped)  # deterministic: same inputs, same output
    assert "turno 1" in first and "reply-1" in first

    # Repeated folding over a long conversation never grows past the cap.
    summary = ""
    long_turn = [
        {"role": "user", "content": "x" * 500},
        {"role": "assistant", "content": "y" * 500},
    ]
    for _ in range(50):
        summary = _fold_summary(summary, long_turn)
        assert len(summary) <= 1500
    assert len(second) <= 1500


async def test_window_truncates_messages_and_folds_evicted_turns_into_summary():
    brain = RecordingBrain()
    responder = LangGraphResponder(brain=brain, history_window_turns=2)
    conversation_id = uuid.uuid4()

    for text in ("turno 1", "turno 2", "turno 3"):
        await responder.respond(system_prompt="p", conversation_id=conversation_id, text=text)

    history = await responder.history(conversation_id)

    # Window holds the last 2 turns (4 messages) plus a leading summary entry
    # for the evicted first turn.
    assert history[0]["role"] == "system"
    assert "turno 1" in history[0]["content"]
    contents = [m["content"] for m in history[1:]]
    assert contents == ["turno 2", "reply-2", "turno 3", "reply-3"]
    assert "turno 1" not in contents  # evicted turn only survives in the summary


async def test_summary_reaches_brain_once_truncation_has_occurred():
    brain = RecordingBrain()
    responder = LangGraphResponder(brain=brain, history_window_turns=1)
    conversation_id = uuid.uuid4()

    await responder.respond(system_prompt="p", conversation_id=conversation_id, text="turno 1")
    # First turn: nothing evicted yet, brain sees empty history, no summary.
    assert brain.seen_histories[0] == []

    await responder.respond(system_prompt="p", conversation_id=conversation_id, text="turno 2")
    # Second turn triggers eviction of turn 1 into the summary; third turn's
    # brain call should receive that summary as a leading system entry.
    await responder.respond(system_prompt="p", conversation_id=conversation_id, text="turno 3")

    third_turn_history = brain.seen_histories[2]
    assert third_turn_history[0]["role"] == "system"
    assert "turno 1" in third_turn_history[0]["content"]


async def test_restart_simulation_new_responder_instance_resumes_shared_checkpoint():
    """The actual G13 acceptance criterion: a new `LangGraphResponder`
    instance (simulating a process restart) sharing the same checkpointer and
    `thread_id` resumes prior conversational context instead of starting cold."""
    shared_checkpointer = InMemorySaver()
    conversation_id = uuid.uuid4()

    responder_a = LangGraphResponder(brain=RecordingBrain(), checkpointer=shared_checkpointer)
    await responder_a.respond(system_prompt="p", conversation_id=conversation_id, text="turno 1")

    # Simulate a process restart: brand-new instance, same checkpointer + thread_id.
    brain_b = RecordingBrain()
    responder_b = LangGraphResponder(brain=brain_b, checkpointer=shared_checkpointer)

    history = await responder_b.history(conversation_id)
    assert [m["content"] for m in history] == ["turno 1", "reply-1"]

    await responder_b.respond(system_prompt="p", conversation_id=conversation_id, text="turno 2")
    assert brain_b.seen_histories[0] == [
        {"role": "user", "content": "turno 1"},
        {"role": "assistant", "content": "reply-1"},
    ]
