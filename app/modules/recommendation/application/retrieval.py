"""Hybrid Retrieval application services (M4, Sprint 3A).

Architecture.md §6.3/§7.10 splits candidate selection into two stages so an
expensive similarity computation never runs over the full inventory:

    Coord->>Filter: search(BuyerProfile completo)
    Filter->>Filter: SQL presupuesto/zona/tipo
    Filter-->>Semantic: candidatos filtrados
    Semantic->>Semantic: similitud sobre candidatos
    Semantic-->>Rank: top-N candidatos

`StructuredFilterService` discards anything that fails a hard constraint
before any vector math happens (cheap, deterministic, no embeddings involved).
`SemanticRetrievalService` then ranks only the survivors by embedding
similarity. Neither service talks to a concrete repository: both depend on
the narrow `PropertyLookup` Protocol below, so this module is testable with
an in-memory fake and converges with whatever `PropertyRepository` the
ingestion workstream lands, purely by structural typing (no import needed).
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Callable
from typing import Protocol

from app.modules.lead_qualification.domain.models import BuyerProfile
from app.modules.recommendation.domain.models import Property, PropertyEmbedding


class PropertyLookup(Protocol):
    """The only shape Hybrid Retrieval needs from a property store.

    Reconciliation contract for the ingestion agent's `PropertyRepository`:
    it must expose these two async methods (structural typing means no
    import or inheritance is required, only matching signatures).
    """

    async def list_for_organization(self, organization_id: uuid.UUID) -> list[Property]:
        """All properties currently known for this organization (pre-filter
        candidate pool). No pagination here — Structured Filter narrows the
        set before anything downstream needs to worry about volume."""
        ...

    async def get_embedding(self, property_id: uuid.UUID) -> PropertyEmbedding | None:
        """The precalculated vector for one property, or None if the
        Ingestion Pipeline hasn't computed one yet (new/changed property)."""
        ...


def _cosine_similarity(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    """Plain-Python cosine similarity over embedding vectors.

    Sprint 3A tests run against SQLite in-memory, not Postgres, so this
    cannot lean on pgvector's `<->` distance operator. Swap this for a
    pgvector ANN query once the real Postgres-backed store lands; until
    then the ranking result is identical, just computed in-process.
    """
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _default_embed_query(buyer_profile: BuyerProfile) -> tuple[float, ...]:
    """Trivial deterministic stand-in for a real query embedder.

    This service doesn't own the embedding model the Ingestion Pipeline
    uses for properties, so it can't produce a vector that's meaningfully
    comparable out of the box. Callers that care about real similarity
    quality should inject `embed_query` with whatever encodes BuyerProfile
    the same way properties were encoded; this default only keeps the
    service usable (and testable) without that dependency.
    """
    budget_signal = 0.0
    if buyer_profile.budget is not None:
        budget_signal = (buyer_profile.budget.minimum + buyer_profile.budget.maximum) / 2.0
    zone_signal = float(len(buyer_profile.locations))
    type_signal = (
        float(hash(buyer_profile.property_type) % 100) if buyer_profile.property_type else 0.0
    )
    return (budget_signal, zone_signal, type_signal)


class StructuredFilterService:
    """Implements `StructuredFilterPort`: SQL-equivalent hard filter, no
    similarity scoring involved (§6.3)."""

    def __init__(self, store: PropertyLookup) -> None:
        self._store = store

    async def filter_candidates(
        self, *, organization_id: uuid.UUID, buyer_profile: BuyerProfile
    ) -> list[Property]:
        properties = await self._store.list_for_organization(organization_id)
        return [
            candidate
            for candidate in properties
            if candidate.matches_hard_filters(
                budget=buyer_profile.budget,
                zones=buyer_profile.locations,
                property_type=buyer_profile.property_type,
            )
        ]


class SemanticRetrievalService:
    """Implements `SemanticRetrievalPort`: ranks the already hard-filtered
    candidates by embedding similarity and returns the top-N (§6.3)."""

    def __init__(
        self,
        store: PropertyLookup,
        *,
        embed_query: Callable[[BuyerProfile], tuple[float, ...]] = _default_embed_query,
    ) -> None:
        self._store = store
        self._embed_query = embed_query

    async def retrieve(
        self, *, buyer_profile: BuyerProfile, candidates: list[Property], top_n: int = 10
    ) -> list[Property]:
        if not candidates:
            return []

        query_vector = self._embed_query(buyer_profile)
        scored: list[tuple[float, Property]] = []
        for candidate in candidates:
            embedding = await self._store.get_embedding(candidate.id)
            if embedding is None:
                # No embedding yet (e.g. just ingested) -> exclude, never crash.
                continue
            similarity = _cosine_similarity(query_vector, embedding.vector)
            scored.append((similarity, candidate))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [candidate for _, candidate in scored[:top_n]]
