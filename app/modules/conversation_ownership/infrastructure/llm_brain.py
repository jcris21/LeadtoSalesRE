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
the final degradation path when every configured chat model fails
mid-conversation, and later the hook for broker-customized greetings/keyword
triggers.

Two providers can be wired at once: Gemini (primary) and Groq (secondary),
composed via `FallbackChatModel` — itself a `ChatModelPort`, so
`LLMConversationBrain` never knows there are two providers behind it. Groq
is tried only when Gemini raises (quota, outage, transient 5xx); `TemplateBrain`
still only kicks in once both have failed.

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
from langsmith import traceable
from langsmith.run_helpers import get_current_run_tree

from app.core.config import get_settings
from app.modules.conversation_ownership.application.langgraph_responder import (
    ConversationBrain,
    TemplateBrain,
)
from app.shared.infrastructure.pii_redaction import redact_pii

logger = logging.getLogger(__name__)

_MAX_OUTPUT_TOKENS = 1024
_MAX_ATTEMPTS = 3
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


class FallbackChatModel:
    """`ChatModelPort` that chains two providers: the primary answers the
    turn; on any failure it falls through to the secondary before the brain
    ever degrades to the template. `label` reflects whichever provider
    actually answered the last call, so `conversation_brain_turn` logs show
    which one was used per turn."""

    def __init__(self, primary: "ChatModelPort", secondary: "ChatModelPort") -> None:
        self._primary = primary
        self._secondary = secondary
        self.label = primary.label

    async def complete(self, *, system_prompt: str, messages: list[dict[str, str]]) -> str:
        try:
            reply = await self._primary.complete(system_prompt=system_prompt, messages=messages)
            self.label = self._primary.label
            return reply
        except Exception:  # noqa: BLE001 — try the secondary before giving up
            logger.exception(
                "Primary chat model failed; falling back to secondary (primary=%s, secondary=%s)",
                self._primary.label,
                self._secondary.label,
            )
        reply = await self._secondary.complete(system_prompt=system_prompt, messages=messages)
        self.label = self._secondary.label
        return reply


def _redact_complete_inputs(inputs: dict) -> dict:
    return {
        "system_prompt": redact_pii(inputs.get("system_prompt")),
        "messages": [
            {**message, "content": redact_pii(message.get("content"))}
            for message in inputs.get("messages", [])
        ],
    }


def _redact_complete_output(output: object) -> dict:
    return {"reply": redact_pii(output) if isinstance(output, str) else output}


def _attach_usage_metadata(
    *, input_tokens: int | None, output_tokens: int | None, total_tokens: int | None
) -> None:
    """Records token counts on the active LangSmith run (the `@traceable`
    `complete()` span itself, per LangSmith's `usage_metadata` convention —
    same shape the built-in Google/Anthropic integrations use) so the UI
    shows per-call cost. No-op when tracing is disabled or the provider
    didn't return usage counts."""
    run_tree = get_current_run_tree()
    if run_tree is None:
        return
    usage = {
        key: value
        for key, value in (
            ("input_tokens", input_tokens),
            ("output_tokens", output_tokens),
            ("total_tokens", total_tokens),
        )
        if value is not None
    }
    if usage:
        run_tree.extra.setdefault("metadata", {})["usage_metadata"] = usage


class GeminiChatModel:
    """`ChatModelPort` over the Gemini `generateContent` API — the only
    provider-aware code on the conversational path (httpx, no SDK; mirrors
    `GeminiGenerativeExtractor`). Up to `_MAX_ATTEMPTS` (3) tries on 429/5xx,
    exponential backoff between them, then `ChatModelError`."""

    _BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(self, api_key: str, model: str, client: httpx.AsyncClient | None = None) -> None:
        self._api_key = api_key
        self.label = model
        self._client = client or httpx.AsyncClient(timeout=15.0)

    @traceable(
        run_type="llm",
        name="gemini_conversation_brain_complete",
        process_inputs=_redact_complete_inputs,
        process_outputs=_redact_complete_output,
    )
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

        response: httpx.Response | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            response = await self._client.post(url, json=payload, headers=headers)
            if response.status_code not in _RETRYABLE_STATUS:
                break
            if attempt < _MAX_ATTEMPTS:
                await asyncio.sleep(_RETRY_BACKOFF_SECONDS * 2 ** (attempt - 1))
        if response.status_code != 200:
            raise ChatModelError(f"chat completion failed: HTTP {response.status_code}")
        try:
            body = response.json()
            usage = body.get("usageMetadata", {})
            _attach_usage_metadata(
                input_tokens=usage.get("promptTokenCount"),
                output_tokens=usage.get("candidatesTokenCount"),
                total_tokens=usage.get("totalTokenCount"),
            )
            return body["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ChatModelError("unexpected chat completion response shape") from exc


class GroqChatModel:
    """`ChatModelPort` over Groq's OpenAI-compatible chat completions API —
    same retry/backoff contract as `GeminiChatModel`. Messages already use
    the "user"/"assistant" roles the brain produces, which is exactly what
    this API expects, so (unlike Gemini) no role translation is needed here."""

    _URL = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(self, api_key: str, model: str, client: httpx.AsyncClient | None = None) -> None:
        self._api_key = api_key
        self.label = model
        self._client = client or httpx.AsyncClient(timeout=15.0)

    @traceable(
        run_type="llm",
        name="groq_conversation_brain_complete",
        process_inputs=_redact_complete_inputs,
        process_outputs=_redact_complete_output,
    )
    async def complete(self, *, system_prompt: str, messages: list[dict[str, str]]) -> str:
        payload = {
            "model": self.label,
            "messages": [{"role": "system", "content": system_prompt}, *messages],
            "max_tokens": _MAX_OUTPUT_TOKENS,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "content-type": "application/json",
        }

        response: httpx.Response | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            response = await self._client.post(self._URL, json=payload, headers=headers)
            if response.status_code not in _RETRYABLE_STATUS:
                break
            if attempt < _MAX_ATTEMPTS:
                await asyncio.sleep(_RETRY_BACKOFF_SECONDS * 2 ** (attempt - 1))
        if response.status_code != 200:
            raise ChatModelError(f"chat completion failed: HTTP {response.status_code}")
        try:
            body = response.json()
            usage = body.get("usage", {})
            _attach_usage_metadata(
                input_tokens=usage.get("prompt_tokens"),
                output_tokens=usage.get("completion_tokens"),
                total_tokens=usage.get("total_tokens"),
            )
            return body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ChatModelError("unexpected chat completion response shape") from exc


def build_conversation_brain(
    api_key: str | None,
    model: str,
    *,
    groq_api_key: str | None = None,
    groq_model: str = "llama-3.3-70b-versatile",
) -> ConversationBrain:
    """Config-driven selection: Gemini is primary when its key is set; with a
    Groq key also set, Groq becomes the fallback `ChatModelPort` (tried when
    Gemini raises — quota, outage, transient 5xx) before the brain ever
    degrades to `TemplateBrain`. Either key alone still works standalone;
    with neither, the brain stays on templates (deterministic, offline)."""
    primary: ChatModelPort | None = GeminiChatModel(api_key, model) if api_key else None
    secondary: ChatModelPort | None = (
        GroqChatModel(groq_api_key, groq_model) if groq_api_key else None
    )

    if primary and secondary:
        return LLMConversationBrain(FallbackChatModel(primary, secondary))
    if primary or secondary:
        return LLMConversationBrain(primary or secondary)
    logger.info("No LLM API key configured — conversational brain runs on templates (G4).")
    return TemplateBrain()


_default_brain: ConversationBrain | None = None


def get_default_conversation_brain() -> ConversationBrain:
    """Process-wide singleton so every turn shares one HTTP client (same
    convention as `get_default_generative_extractor`). Reuses the platform
    LLM keys; the models are provider-specific config, the brain is not."""
    global _default_brain
    if _default_brain is None:
        settings = get_settings()
        _default_brain = build_conversation_brain(
            settings.gemini_api_key,
            settings.conversation_llm_model,
            groq_api_key=settings.groq_api_key,
            groq_model=settings.groq_conversation_llm_model,
        )
    return _default_brain
