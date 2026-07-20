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

import inspect
import logging
import math
import uuid
from collections.abc import Awaitable, Callable
from typing import Protocol

from app.modules.lead_qualification.domain.models import (
    BuyerProfile,
    MoneyRange,
    PropertyType,
)
from app.modules.recommendation.domain.models import Property, PropertyEmbedding

logger = logging.getLogger(__name__)


class PropertyLookup(Protocol):
    """The only shape Hybrid Retrieval needs from a property store.

    Reconciliation contract for `PropertyRepository` (structural typing — no
    import or inheritance required, only matching signatures).
    """

    async def filter_candidates(
        self,
        organization_id: uuid.UUID,
        *,
        budget: MoneyRange | None,
        zones: tuple[str, ...],
        property_type: PropertyType | None,
    ) -> list[Property]:
        """US-303: hard-constraint filter as a SQL WHERE — same semantics as
        `Property.matches_hard_filters` (absent constraint = no clause)."""
        ...

    async def semantic_search(
        self,
        *,
        candidate_ids: list[uuid.UUID],
        query_vector: tuple[float, ...],
        top_n: int,
    ) -> list[Property] | None:
        """US-304: pgvector `<->` ranking over the filtered candidates, or
        None when the backing dialect has no pgvector (caller falls back)."""
        ...

    async def get_embedding(self, property_id: uuid.UUID) -> PropertyEmbedding | None:
        """The precalculated vector for one property, or None if the
        Ingestion Pipeline hasn't computed one yet (new/changed property).
        Used only by the in-memory fallback path."""
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
        # US-303: the WHERE clause runs in the database — the full catalog is
        # never loaded into Python. `Property.matches_hard_filters` remains
        # the domain's executable specification of these semantics.
        return await self._store.filter_candidates(
            organization_id,
            budget=buyer_profile.budget,
            zones=buyer_profile.locations,
            property_type=buyer_profile.property_type,
        )


class SemanticRetrievalService:
    """Implements `SemanticRetrievalPort`: ranks the already hard-filtered
    candidates by embedding similarity and returns the top-N (§6.3)."""

    def __init__(
        self,
        store: PropertyLookup,
        *,
        embed_query: Callable[
            [BuyerProfile], tuple[float, ...] | Awaitable[tuple[float, ...]]
        ] = _default_embed_query,
    ) -> None:
        self._store = store
        self._embed_query = embed_query

    async def retrieve(
        self, *, buyer_profile: BuyerProfile, candidates: list[Property], top_n: int = 10
    ) -> list[Property]:
        if not candidates:
            return []

        try:
            query_vector = self._embed_query(buyer_profile)
            if inspect.isawaitable(query_vector):
                query_vector = await query_vector
        except Exception:  # noqa: BLE001 — degraded ranking beats no recommendation
            logger.exception(
                "Query embedding failed; returning hard-filtered candidates unranked"
            )
            return candidates[:top_n]

        # US-304: SQL-first — on Postgres the ranking happens in the database
        # via pgvector `<->` and no cosine similarity runs in Python. A store
        # without the capability (SQLite tests, in-memory fakes) returns None
        # (or lacks the method) and the in-memory path below takes over.
        # G2 guard: pgvector `<->` on mismatched dimensionality raises and
        # aborts the handler's transaction, so the SQL path only runs when the
        # query vector's length matches the stored embeddings (e.g. keyless
        # 3-dim default vs vector(1536) store routes to the in-memory path,
        # which degrades to neutral scores instead of crashing).
        sql_search = getattr(self._store, "semantic_search", None)
        if sql_search is not None and await self._dimensions_match(candidates, query_vector):
            ranked = await sql_search(
                candidate_ids=[candidate.id for candidate in candidates],
                query_vector=query_vector,
                top_n=top_n,
            )
            if ranked is not None:
                logger.debug("Semantic retrieval served by pgvector <-> query")
                return ranked

        logger.debug("Semantic retrieval falling back to in-memory cosine ranking")
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

    async def _dimensions_match(
        self, candidates: list[Property], query_vector: tuple[float, ...]
    ) -> bool:
        """Probes one stored embedding (they all share the ingestion model) and
        compares its length with the query vector's. False when nothing is
        embedded yet — the SQL inner join and the in-memory path would both
        yield [] there, so skipping SQL loses nothing."""
        for candidate in candidates:
            embedding = await self._store.get_embedding(candidate.id)
            if embedding is not None:
                return len(tuple(embedding.vector)) == len(query_vector)
        return False
