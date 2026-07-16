"""Real embedding model (US-308, Sprint 3.1): OpenAI `text-embedding-3-small`
(1536 dims) behind the `EmbeddingModel` seam of `property_ingestion.py`.

`build_embedding_model` is the config-driven selection point (design.md D6):
with `openai_api_key` set it returns the real model; without it, the
deterministic `HashEmbeddingModel` — so tests and keyless dev environments
never make a network call. Failure policy (D5): one retry on 429/5xx, then
raise — a failed embed must never silently leave a stale vector behind
(ingestion only advances `source_hash` after a successful save).
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from app.modules.recommendation.application.property_ingestion import (
    EmbeddingModel,
    HashEmbeddingModel,
)
from app.modules.recommendation.domain.models import Property

logger = logging.getLogger(__name__)

_OPENAI_EMBEDDINGS_URL = "https://api.openai.com/v1/embeddings"
_MODEL_NAME = "text-embedding-3-small"
_EXPECTED_DIMENSIONS = 1536
_RETRY_BACKOFF_SECONDS = 1.0
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class EmbeddingGenerationError(RuntimeError):
    """Raised when the embeddings API fails after the retry, or returns a
    vector of unexpected dimensionality."""


def _embed_text(property: Property) -> str:
    """The property's semantic content — what similarity should 'mean'.
    Deliberately excludes price/external_id (structured-filter concerns) and
    the US-309 administrative fields (design.md D3)."""
    return " | ".join(
        part
        for part in (
            property.description,
            ", ".join(property.features),
            property.zone,
            property.property_type.value,
        )
        if part
    )


class OpenAIEmbeddingModel:
    """`EmbeddingModel` implementation over the OpenAI embeddings API."""

    model_version = _MODEL_NAME

    def __init__(self, api_key: str, client: httpx.AsyncClient | None = None) -> None:
        self._api_key = api_key
        self._client = client or httpx.AsyncClient(timeout=30.0)

    async def embed(self, property: Property) -> tuple[float, ...]:
        payload = {"model": _MODEL_NAME, "input": _embed_text(property)}
        headers = {"Authorization": f"Bearer {self._api_key}"}

        response = await self._client.post(
            _OPENAI_EMBEDDINGS_URL, json=payload, headers=headers
        )
        if response.status_code in _RETRYABLE_STATUS:
            await asyncio.sleep(_RETRY_BACKOFF_SECONDS)
            response = await self._client.post(
                _OPENAI_EMBEDDINGS_URL, json=payload, headers=headers
            )
        if response.status_code != 200:
            raise EmbeddingGenerationError(
                f"Embeddings API failed for property {property.id}: "
                f"HTTP {response.status_code}"
            )

        vector = tuple(float(v) for v in response.json()["data"][0]["embedding"])
        if len(vector) != _EXPECTED_DIMENSIONS:
            raise EmbeddingGenerationError(
                f"Expected {_EXPECTED_DIMENSIONS} dimensions, got {len(vector)}"
            )
        return vector


def build_embedding_model(api_key: str | None) -> EmbeddingModel:
    """Config-driven embedder selection (design.md D6). Callers pass
    `get_settings().openai_api_key`."""
    if api_key:
        return OpenAIEmbeddingModel(api_key)
    logger.warning(
        "openai_api_key not configured — falling back to the deterministic "
        "HashEmbeddingModel (16-dim stand-in); semantic similarity will not "
        "be meaningful until a real key is provided (US-308)."
    )
    return HashEmbeddingModel()
