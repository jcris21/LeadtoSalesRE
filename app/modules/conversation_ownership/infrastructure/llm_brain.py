"""LLM-backed `ConversationBrain` (closes gap G4,
docs/e2e-manual-chat-checklist.md) — provider-agnostic by construction.

Everything above this module speaks only provider-neutral contracts: the
brain (`LLMConversationBrain`) implements `ConversationBrain` and talks to a
`ChatModelPort` (system prompt + user/assistant messages -> reply text).
Swapping the LLM vendor means writing one new `ChatModelPort` adapter and
selecting it in `build_conversation_brain` — the brain, the LangGraph
responder and the Coordinator never change.

Same config-driven seam as `generative_extractor.py`: with an API key the
real chat model backs the brain; without one, `TemplateBrain` keeps the
pipeline deterministic and offline. The templates stay first-class — they are
the degradation path when the chat model fails mid-conversation, and later
the hook for broker-customized greetings/keyword triggers.

Pipeline measurement: every turn emits one structured log line
(`conversation_brain_turn source=... model=... latency_ms=...`) so reply
latency and template-fallback rate can be read straight from the logs; reply
*quality* is auditable per turn via the AI decision trace, which records the
final response text.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Protocol

import httpx

from app.core.config import get_settings
from app.modules.conversation_ownership.application.langgraph_responder import (
    ConversationBrain,
    TemplateBrain,
)

logger = logging.getLogger(__name__)

_MAX_OUTPUT_TOKENS = 1024
_RETRY_BACKOFF_SECONDS = 1.0
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class ChatModelError(Exception):
    """Terminal chat-model failure; the brain degrades to the template reply."""


class ChatModelPort(Protocol):
    """Provider-neutral chat completion: a system prompt plus user/assistant
    messages in, reply text out. Adapters raise `ChatModelError` on terminal
    failure; `label` identifies the backing model in metrics logs."""

    label: str

    async def complete(self, *, system_prompt: str, messages: list[dict[str, str]]) -> str: ...


class LLMConversationBrain:
    """`ConversationBrain` that delegates the turn to a `ChatModelPort`. The
    checkpointed history plus the current lead message become the model's
    conversation; any failure (or an empty reply) falls back to the
    deterministic template so the conversational turn never breaks."""

    def __init__(
        self, chat_model: ChatModelPort, fallback: ConversationBrain | None = None
    ) -> None:
        self._chat_model = chat_model
        self._fallback = fallback or TemplateBrain()

    async def generate(
        self, *, system_prompt: str, history: list[dict[str, str]], text: str
    ) -> str:
        messages = [*history, {"role": "user", "content": text}]
        started = time.perf_counter()
        try:
            reply = await self._chat_model.complete(system_prompt=system_prompt, messages=messages)
        except Exception:  # noqa: BLE001 — degrade, never break the turn
            logger.exception(
                "Chat model failed; degrading to template reply (model=%s)",
                self._chat_model.label,
            )
            reply = ""
        latency_ms = int((time.perf_counter() - started) * 1000)

        if reply.strip():
            source = "llm"
        else:
            source = "template_fallback"
            reply = await self._fallback.generate(
                system_prompt=system_prompt, history=history, text=text
            )
        logger.info(
            "conversation_brain_turn source=%s model=%s latency_ms=%d history_turns=%d",
            source,
            self._chat_model.label,
            latency_ms,
            len(history),
        )
        return reply


class GeminiChatModel:
    """`ChatModelPort` over the Gemini `generateContent` API — the only
    provider-aware code on the conversational path (httpx, no SDK; mirrors
    `GeminiGenerativeExtractor`). One retry on 429/5xx, then `ChatModelError`."""

    _BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(self, api_key: str, model: str, client: httpx.AsyncClient | None = None) -> None:
        self._api_key = api_key
        self.label = model
        self._client = client or httpx.AsyncClient(timeout=15.0)

    async def complete(self, *, system_prompt: str, messages: list[dict[str, str]]) -> str:
        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [
                {
                    "role": "model" if message["role"] == "assistant" else "user",
                    "parts": [{"text": message["content"]}],
                }
                for message in messages
            ],
            "generationConfig": {
                "maxOutputTokens": _MAX_OUTPUT_TOKENS,
                # Short conversational replies — thinking would spend the
                # latency budget (QA-01 <15s) without better answers.
                "thinkingConfig": {"thinkingBudget": 0},
            },
        }
        headers = {"x-goog-api-key": self._api_key, "content-type": "application/json"}
        url = f"{self._BASE_URL}/{self.label}:generateContent"

        response = await self._client.post(url, json=payload, headers=headers)
        if response.status_code in _RETRYABLE_STATUS:
            await asyncio.sleep(_RETRY_BACKOFF_SECONDS)
            response = await self._client.post(url, json=payload, headers=headers)
        if response.status_code != 200:
            raise ChatModelError(f"chat completion failed: HTTP {response.status_code}")
        try:
            return response.json()["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ChatModelError("unexpected chat completion response shape") from exc


def build_conversation_brain(api_key: str | None, model: str) -> ConversationBrain:
    """Config-driven selection: with a key, the LLM brain (template as its
    failure fallback); without one, `TemplateBrain` — deterministic, offline."""
    if api_key:
        return LLMConversationBrain(GeminiChatModel(api_key, model))
    logger.info("No LLM API key configured — conversational brain runs on templates (G4).")
    return TemplateBrain()


_default_brain: ConversationBrain | None = None


def get_default_conversation_brain() -> ConversationBrain:
    """Process-wide singleton so every turn shares one HTTP client (same
    convention as `get_default_generative_extractor`). Reuses the platform
    LLM key; the model is provider-specific config, the brain is not."""
    global _default_brain
    if _default_brain is None:
        settings = get_settings()
        _default_brain = build_conversation_brain(
            settings.gemini_api_key, settings.conversation_llm_model
        )
    return _default_brain
