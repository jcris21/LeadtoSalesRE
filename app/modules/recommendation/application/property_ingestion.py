"""Sprint 3A — Property Ingestion Pipeline (M4, Architecture.md §6.3):
precalculates each property's embedding when it is ingested/updated, so
Semantic Retrieval only ever reads a stored vector and never embeds on the
request path.

Change detection is a content hash (features + description + price + zone +
property_type), not a timestamp comparison — a source that touches
`updated_at` without changing content (e.g. a re-sync) must not trigger a
recompute, and a hash makes that exact instead of guessed.

`EmbeddingModel` is the pluggable seam, same shape as `ConversationBrain` /
`TemplateBrain` in `conversation_ownership/application/langgraph_responder.py`:
`HashEmbeddingModel` is the deterministic default so the pipeline is fully
testable without any real embedding model; a real model-backed implementation
(OpenAI, local sentence-transformers, ...) swaps in behind the same protocol
without touching `PropertyIngestionService`.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Protocol

from app.modules.recommendation.domain.models import Property, PropertyEmbedding
from app.modules.recommendation.infrastructure.repository import PropertyRepository
from app.shared.domain.base import utcnow


class InventorySource(Protocol):
    """Port-shaped stand-in for the inventory adapter (`MockInventorySource`
    today; a real HTTP-backed source later implements the same method)."""

    async def fetch(self, organization_id: uuid.UUID) -> list[Property]: ...


class EmbeddingModel(Protocol):
    """Turns a property's content into its embedding vector. Async (US-308):
    a real model is an HTTP call; the deterministic hash implementation is
    trivially async-compatible."""

    model_version: str

    async def embed(self, property: Property) -> tuple[float, ...]: ...


class HashEmbeddingModel:
    """Deterministic default: hashes the property's content into a
    fixed-length float vector. Keeps the pipeline demonstrably correct and
    testable without any real embedding model or network call. Superseded in
    production by `OpenAIEmbeddingModel` when `openai_api_key` is configured
    (see `infrastructure/embedding_model.build_embedding_model`, US-308)."""

    model_version = "hash-v1"
    vector_size = 16

    async def embed(self, property: Property) -> tuple[float, ...]:
        digest = hashlib.sha256(_content_key(property).encode()).digest()
        return tuple(digest[i % len(digest)] / 255.0 for i in range(self.vector_size))


def _content_key(property: Property) -> str:
    """Canonical string capturing everything that should trigger a recompute
    when it changes. Order-independent for `features` so reordering the same
    set of features is not treated as a change."""
    return "|".join(
        (
            property.external_id,
            f"{property.price:.2f}",
            property.zone,
            property.property_type.value,
            ",".join(sorted(property.features)),
            property.description,
        )
    )


def content_hash(property: Property) -> str:
    return hashlib.sha256(_content_key(property).encode()).hexdigest()


class PropertyIngestionService:
    """`PropertyIngestionPort` implementation: pulls the organization's
    catalog from the inventory source, upserts the local mirror, and
    recomputes an embedding only for properties whose content hash changed
    since the last computed embedding."""

    def __init__(
        self,
        session,
        source: InventorySource,
        embedder: EmbeddingModel | None = None,
    ) -> None:
        self._repo = PropertyRepository(session)
        self._source = source
        self._embedder = embedder or HashEmbeddingModel()

    async def ingest_from_source(self, organization_id: uuid.UUID) -> int:
        properties = await self._source.fetch(organization_id)
        touched = 0
        for property in properties:
            await self._repo.upsert(property)

            new_hash = content_hash(property)
            stored_hash = await self._repo.get_embedding_hash(property.id)
            if stored_hash == new_hash:
                continue

            embedding = PropertyEmbedding(
                property_id=property.id,
                vector=await self._embedder.embed(property),
                model_version=self._embedder.model_version,
                computed_at=utcnow(),
            )
            await self._repo.save_embedding(embedding, source_hash=new_hash)
            touched += 1
        return touched
