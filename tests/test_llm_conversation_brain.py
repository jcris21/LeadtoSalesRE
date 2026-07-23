"""G4 — LLM-backed conversational brain, provider-agnostic.

The brain (`LLMConversationBrain`) only knows the `ChatModelPort` seam: it
composes the checkpointed history plus the current turn into provider-neutral
messages and returns whatever the chat model says. Provider specifics live in
one adapter behind the port, selected by config (`build_conversation_brain`),
so replacing the LLM vendor never touches the brain, the responder graph or
the Coordinator. A chat-model failure can never break the conversational
turn: the brain degrades to the deterministic `TemplateBrain` reply.
"""

import json
import uuid

import httpx
import pytest

from app.modules.conversation_ownership.application.langgraph_responder import (
    LangGraphResponder,
    TemplateBrain,
)
from app.modules.conversation_ownership.infrastructure.llm_brain import (
    ChatModelError,
    GeminiChatModel,
    LLMConversationBrain,
    build_conversation_brain,
)

SYSTEM_PROMPT = "Eres el asistente inmobiliario."


class FakeChatModel:
    """`ChatModelPort` test double capturing what the brain sends."""

    label = "fake-model"

    def __init__(self, reply: str = "respuesta del modelo") -> None:
        self.reply = reply
        self.calls: list[dict] = []

    async def complete(self, *, system_prompt: str, messages: list[dict[str, str]]) -> str:
        self.calls.append({"system_prompt": system_prompt, "messages": list(messages)})
        return self.reply


class FailingChatModel:
    label = "failing-model"

    async def complete(self, *, system_prompt: str, messages: list[dict[str, str]]) -> str:
        raise ChatModelError("provider unavailable")


async def test_brain_sends_history_plus_current_turn_and_returns_model_reply():
    chat_model = FakeChatModel()
    brain = LLMConversationBrain(chat_model)
    history = [
        {"role": "user", "content": "hola"},
        {"role": "assistant", "content": "¡hola! ¿qué buscas?"},
    ]

    reply = await brain.generate(
        system_prompt=SYSTEM_PROMPT, history=history, text="un depa en Miraflores"
    )

    assert reply == "respuesta del modelo"
    call = chat_model.calls[0]
    assert call["system_prompt"] == SYSTEM_PROMPT
    # History travels intact and the current lead turn is the last user message.
    assert call["messages"] == [
        *history,
        {"role": "user", "content": "un depa en Miraflores"},
    ]


async def test_brain_falls_back_to_template_when_chat_model_fails():
    brain = LLMConversationBrain(FailingChatModel())

    reply = await brain.generate(system_prompt=SYSTEM_PROMPT, history=[], text="hola")

    # The turn still gets a reply — the deterministic template one.
    assert "asistente del equipo de asesores" in reply


async def test_brain_falls_back_to_template_on_empty_model_reply():
    brain = LLMConversationBrain(FakeChatModel(reply="   "))

    reply = await brain.generate(system_prompt=SYSTEM_PROMPT, history=[], text="hola")

    assert "asistente del equipo de asesores" in reply


def test_build_conversation_brain_is_config_driven():
    # Without an API key the pipeline stays deterministic (templates, no network).
    assert isinstance(build_conversation_brain(None, "any-model"), TemplateBrain)
    assert isinstance(build_conversation_brain("test-key", "any-model"), LLMConversationBrain)


async def test_responder_graph_feeds_checkpointed_history_to_llm_brain():
    chat_model = FakeChatModel()
    responder = LangGraphResponder(brain=LLMConversationBrain(chat_model))
    conversation_id = uuid.uuid4()

    await responder.respond(
        system_prompt=SYSTEM_PROMPT, conversation_id=conversation_id, text="turno 1"
    )
    await responder.respond(
        system_prompt=SYSTEM_PROMPT, conversation_id=conversation_id, text="turno 2"
    )

    second_turn_messages = chat_model.calls[1]["messages"]
    assert second_turn_messages == [
        {"role": "user", "content": "turno 1"},
        {"role": "assistant", "content": "respuesta del modelo"},
        {"role": "user", "content": "turno 2"},
    ]


def _chat_response(text: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={"candidates": [{"content": {"parts": [{"text": text}], "role": "model"}}]},
    )


@pytest.mark.asyncio
async def test_gemini_adapter_maps_roles_and_carries_system_prompt():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _chat_response("¡Claro! ¿En qué distrito buscas?")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    model = GeminiChatModel("test-key", "test-model", client)

    reply = await model.complete(
        system_prompt=SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": "hola"},
            {"role": "assistant", "content": "¡hola!"},
            {"role": "user", "content": "busco un depa"},
        ],
    )

    assert reply == "¡Claro! ¿En qué distrito buscas?"
    request = seen[0]
    assert request.url.path.endswith("/models/test-model:generateContent")
    assert request.headers["x-goog-api-key"] == "test-key"
    body = json.loads(request.content)
    assert body["systemInstruction"]["parts"][0]["text"] == SYSTEM_PROMPT
    # Provider-neutral "assistant" role is translated at the adapter boundary.
    assert [c["role"] for c in body["contents"]] == ["user", "model", "user"]


@pytest.mark.asyncio
async def test_gemini_adapter_raises_chat_model_error_on_terminal_http_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "bad request"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    model = GeminiChatModel("test-key", "test-model", client)

    with pytest.raises(ChatModelError):
        await model.complete(
            system_prompt=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": "hola"}],
        )


@pytest.mark.asyncio
async def test_gemini_adapter_is_traceable_and_still_returns_reply_when_tracing_disabled():
    """Tracing must be fail-safe: with LANGSMITH_TRACING unset (default test
    environment), decorating complete() with @traceable changes nothing
    observable — same request, same reply, same exception behavior."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response("respuesta trazada")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    model = GeminiChatModel("test-key", "test-model", client)

    reply = await model.complete(
        system_prompt=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": "hola, mi correo es ana@example.com"}],
    )

    assert reply == "respuesta trazada"
