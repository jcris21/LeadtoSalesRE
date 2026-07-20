"""Real embedding model (US-308, Sprint 3.1): Google Gemini
`gemini-embedding-001` at 1536 dims behind the `EmbeddingModel` seam of
`property_ingestion.py`.

`build_embedding_model` is the config-driven selection point (design.md D6):
with `gemini_api_key` set it returns the real model; without it, the
deterministic `HashEmbeddingModel` — so tests and keyless dev environments
never make a network call. Failure policy (D5): one retry on 429/5xx, then
raise — a failed embed must never silently leave a stale vector behind
(ingestion only advances `source_hash` after a successful save).

Dimensionality: the model's native output is 3072, but pgvector's HNSW index
caps at 2000 dims, so we request `outputDimensionality: 1536` (Matryoshka
truncation) to keep the existing `vector(1536)` column and HNSW index.
Truncated Gemini embeddings are NOT unit-normalized — we L2-normalize
client-side so cosine/`<->` distances stay meaningful.
"""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Awaitable, Callable

import httpx

from app.modules.lead_qualification.domain.models import BuyerProfile
from app.modules.recommendation.application.property_ingestion import (
    EmbeddingModel,
    HashEmbeddingModel,
)
from app.modules.recommendation.domain.models import Property

logger = logging.getLogger(__name__)

_MODEL_NAME = "gemini-embedding-001"
_GEMINI_EMBED_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/{_MODEL_NAME}:embedContent"
)
_EXPECTED_DIMENSIONS = 1536
_RETRY_BACKOFF_SECONDS = 1.0
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})

#: Gemini task types: the corpus side and the query side are embedded with
#: asymmetric task hints, but land in the same vector space.
_TASK_DOCUMENT = "RETRIEVAL_DOCUMENT"
_TASK_QUERY = "RETRIEVAL_QUERY"


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


def _l2_normalize(vector: tuple[float, ...]) -> tuple[float, ...]:
    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0.0:
        return vector
    return tuple(v / norm for v in vector)


class GeminiEmbeddingModel:
    """`EmbeddingModel` implementation over the Gemini `embedContent` API."""

    model_version = _MODEL_NAME

    def __init__(self, api_key: str, client: httpx.AsyncClient | None = None) -> None:
        self._api_key = api_key
        self._client = client or httpx.AsyncClient(timeout=30.0)

    async def embed(self, property: Property) -> tuple[float, ...]:
        return await self.embed_text(_embed_text(property), context=f"property {property.id}")

    async def embed_text(
        self, text: str, *, context: str = "query", task_type: str = _TASK_DOCUMENT
    ) -> tuple[float, ...]:
        """Shared request path for property content AND BuyerProfile queries
        (G2): both must live in the same embedding space for `<->` distances
        to mean anything (US-304)."""
        payload = {
            "model": f"models/{_MODEL_NAME}",
            "content": {"parts": [{"text": text}]},
            "taskType": task_type,
            "outputDimensionality": _EXPECTED_DIMENSIONS,
        }
        headers = {"x-goog-api-key": self._api_key}

        response = await self._client.post(_GEMINI_EMBED_URL, json=payload, headers=headers)
        if response.status_code in _RETRYABLE_STATUS:
            await asyncio.sleep(_RETRY_BACKOFF_SECONDS)
            response = await self._client.post(
                _GEMINI_EMBED_URL, json=payload, headers=headers
            )
        if response.status_code != 200:
            raise EmbeddingGenerationError(
                f"Embeddings API failed for {context}: HTTP {response.status_code}"
            )

        vector = tuple(float(v) for v in response.json()["embedding"]["values"])
        if len(vector) != _EXPECTED_DIMENSIONS:
            raise EmbeddingGenerationError(
                f"Expected {_EXPECTED_DIMENSIONS} dimensions, got {len(vector)}"
            )
        return _l2_normalize(vector)


def _profile_query_text(buyer_profile: BuyerProfile) -> str:
    """Encodes the BuyerProfile the same way `_embed_text` encodes a property
    (must-haves ~ features, locations ~ zone, type ~ type), so query and
    corpus share one embedding space. Budget is excluded — a structured-filter
    concern, mirroring how `_embed_text` excludes price."""
    return " | ".join(
        part
        for part in (
            ", ".join(buyer_profile.must_haves),
            ", ".join(buyer_profile.locations),
            buyer_profile.property_type.value if buyer_profile.property_type else "",
            f"{buyer_profile.bedrooms} dormitorios" if buyer_profile.bedrooms else "",
        )
        if part
    )


def build_profile_query_embedder(
    api_key: str | None,
) -> Callable[[BuyerProfile], Awaitable[tuple[float, ...]]] | None:
    """G2 (docs/e2e-manual-chat-checklist.md): BuyerProfile -> 1536-dim query
    vector via the same model that embedded the properties (asymmetric
    `RETRIEVAL_QUERY` task hint). Keyless => None: `SemanticRetrievalService`
    keeps its deterministic 3-dim default and its dimension probe routes
    retrieval to the in-memory fallback."""
    if not api_key:
        return None
    model = GeminiEmbeddingModel(api_key)

    async def embed_query(buyer_profile: BuyerProfile) -> tuple[float, ...]:
        return await model.embed_text(
            _profile_query_text(buyer_profile), task_type=_TASK_QUERY
        )

    return embed_query


def build_embedding_model(api_key: str | None) -> EmbeddingModel:
    """Config-driven embedder selection (design.md D6). Callers pass
    `get_settings().gemini_api_key`."""
    if api_key:
        return GeminiEmbeddingModel(api_key)
    logger.warning(
        "gemini_api_key not configured — falling back to the deterministic "
        "HashEmbeddingModel (16-dim stand-in); semantic similarity will not "
        "be meaningful until a real key is provided (US-308)."
    )
    return HashEmbeddingModel()
