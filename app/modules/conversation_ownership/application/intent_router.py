"""Intent Router (AI-104, scoped): classifies one incoming lead message into a
fixed category before `CoordinatorAgent` picks a branch. Additive only — no
consumer branches on the result yet (see design.md, Non-Goals); this module
only produces the classification and lets the caller record it on the turn's
AIDecisionTrace.

Same config-driven seam as `generative_extractor.py` / `embedding_model.py`:
`get_default_intent_router()` returns the Gemini-backed classifier when
`gemini_api_key` is set, else the deterministic `KeywordIntentRouter` —
keyless dev/test environments stay fully offline.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Literal, Protocol, get_args

import httpx
from langsmith import traceable

from app.core.config import get_settings
from app.modules.conversation_ownership.domain.prompts import INTENT_CLASSIFIER_SYSTEM_PROMPT
from app.shared.infrastructure.pii_redaction import redact_pii

logger = logging.getLogger(__name__)

_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
_MAX_TOKENS = 32
_RETRY_BACKOFF_SECONDS = 1.0
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})

IntentCategory = Literal[
    "qualification",
    "pregunta_informativa",
    "objecion",
    "agendamiento",
    "handoff_explicito",
    "otro",
]

_CATEGORIES: tuple[IntentCategory, ...] = get_args(IntentCategory)

_KEYWORDS: dict[IntentCategory, tuple[str, ...]] = {
    "objecion": ("caro", "costoso", "muy alto", "no me alcanza", "muy lejos", "no confío"),
    "agendamiento": ("agendar", "visita", "cita", "horario", "disponibilidad", "coordinar"),
    "handoff_explicito": ("hablar con alguien", "asesor humano", "un humano", "una persona"),
    "pregunta_informativa": ("qué es", "cómo funciona", "cuánto cuesta el proceso", "información sobre"),
    "qualification": ("busco", "presupuesto", "distrito", "zona", "departamento", "casa"),
}


class IntentRouterPort(Protocol):
    """Classifies one lead message into exactly one `IntentCategory`. Must
    never raise on ordinary input — callers still guard with try/except per
    design.md, but the port itself has no invalid-input error mode."""

    async def classify(self, text: str) -> IntentCategory: ...


class KeywordIntentRouter:
    """Deterministic fallback (no LLM call): keyword matching in a fixed
    priority order, same style as `qualification_flow.py`'s extractors.
    Guarantees a category for any input, including empty/unrelated text
    (falls through to `otro`) — used both as the offline/test default and as
    ground truth for asserting specific categories in tests."""

    async def classify(self, text: str) -> IntentCategory:
        lowered = text.lower()
        for category in (
            "objecion",
            "agendamiento",
            "handoff_explicito",
            "pregunta_informativa",
            "qualification",
        ):
            if any(keyword in lowered for keyword in _KEYWORDS[category]):
                return category  # type: ignore[return-value]
        return "otro"


def _redact_classify_inputs(inputs: dict) -> dict:
    return {"text": redact_pii(inputs.get("text"))}


class GeminiIntentRouter:
    """`IntentRouterPort` over the Gemini `generateContent` API (httpx, no SDK
    dependency — mirrors `GeminiGenerativeExtractor`). One retry on 429/5xx;
    any terminal failure or unparseable output falls back to the deterministic
    `KeywordIntentRouter` for that single call, never raises."""

    def __init__(
        self, api_key: str, model: str, client: httpx.AsyncClient | None = None
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._client = client or httpx.AsyncClient(timeout=10.0)
        self._fallback = KeywordIntentRouter()

    @traceable(
        run_type="llm",
        name="gemini_intent_router_classify",
        process_inputs=_redact_classify_inputs,
    )
    async def classify(self, text: str) -> IntentCategory:
        payload = {
            "systemInstruction": {"parts": [{"text": INTENT_CLASSIFIER_SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": text}]}],
            "generationConfig": {
                "maxOutputTokens": _MAX_TOKENS,
                "responseMimeType": "application/json",
                "thinkingConfig": {"thinkingBudget": 0},
            },
        }
        headers = {"x-goog-api-key": self._api_key, "content-type": "application/json"}
        url = f"{_GEMINI_BASE_URL}/{self._model}:generateContent"

        response = await self._client.post(url, json=payload, headers=headers)
        if response.status_code in _RETRYABLE_STATUS:
            await asyncio.sleep(_RETRY_BACKOFF_SECONDS)
            response = await self._client.post(url, json=payload, headers=headers)
        if response.status_code != 200:
            logger.warning("Intent router call failed: HTTP %s", response.status_code)
            return await self._fallback.classify(text)

        try:
            raw = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError, ValueError):
            logger.warning("Intent router returned an unexpected response shape")
            return await self._fallback.classify(text)
        category = _parse_category(raw)
        if category is None:
            logger.warning("Intent router returned an unrecognized category; falling back")
            return await self._fallback.classify(text)
        return category


def _parse_category(raw: str) -> IntentCategory | None:
    import json

    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None
    candidate = data.get("category") if isinstance(data, dict) else None
    return candidate if candidate in _CATEGORIES else None


_default_router: IntentRouterPort | None = None
_default_built = False


def build_intent_router(api_key: str | None, model: str) -> IntentRouterPort:
    """Config-driven selection: with a key, the real Gemini classifier (with
    its own internal fallback on failure); without one, the deterministic
    classifier directly — matches `build_generative_extractor`'s convention,
    except this port always has a usable implementation (never None)."""
    if api_key:
        return GeminiIntentRouter(api_key, model)
    logger.info(
        "gemini_api_key not configured — intent router runs keyword-only (AI-104)."
    )
    return KeywordIntentRouter()


def get_default_intent_router() -> IntentRouterPort:
    """Process-wide singleton, same convention as `get_default_responder` /
    `get_default_generative_extractor`."""
    global _default_router, _default_built
    if not _default_built:
        settings = get_settings()
        _default_router = build_intent_router(
            settings.gemini_api_key, settings.generative_extractor_model
        )
        _default_built = True
    return _default_router
