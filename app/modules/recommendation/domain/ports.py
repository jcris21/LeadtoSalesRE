"""Ports (Protocols) of the Recommendation bounded context (M4, Sprint 3A/3B).

Each Protocol is the seam one Sprint-3 workstream implements against, so the
five pieces of the pipeline (ingestion, structured filter, semantic
retrieval, ranking, explanation, neighborhood enrichment) can be built and
tested independently before the Coordinator wires them together end to end
(§7.10).
"""

from __future__ import annotations

import uuid
from typing import Protocol

from app.modules.lead_qualification.domain.models import BuyerProfile
from app.modules.recommendation.domain.models import (
    NeighborhoodInsight,
    Property,
    RankedCandidate,
    RankingSignal,
)


class PropertyIngestionPort(Protocol):
    """Precalculates/refreshes embeddings when source properties change."""

    async def ingest_from_source(self, organization_id: uuid.UUID) -> int:
        """Pulls new/changed properties from the inventory source, upserts
        them, and (re)computes their embedding. Returns the count touched."""
        ...


class StructuredFilterPort(Protocol):
    """SQL-only hard-constraint filter, run before any semantic scoring."""

    async def filter_candidates(
        self, *, organization_id: uuid.UUID, buyer_profile: BuyerProfile
    ) -> list[Property]: ...


class SemanticRetrievalPort(Protocol):
    """Similarity search over the already-filtered candidate subset."""

    async def retrieve(
        self, *, buyer_profile: BuyerProfile, candidates: list[Property], top_n: int = 10
    ) -> list[Property]: ...


class RankingEnginePort(Protocol):
    """Deterministic, LLM-free scoring (§7.10: `score = Σ(signal.weight × value)`)."""

    def rank(
        self, *, buyer_profile: BuyerProfile, candidates: list[Property], top_k: int = 3
    ) -> list[RankedCandidate]: ...


class ExplanationPort(Protocol):
    """Phrases the winning RankingSignals in natural language. Must never
    receive the full candidate list or decide the ranking (§7.11)."""

    async def explain(
        self, *, property_id: uuid.UUID, signals: tuple[RankingSignal, ...]
    ) -> str: ...


class NeighborhoodEnrichmentPort(Protocol):
    """Fan-out/fan-in Maps enrichment for the Top-3 with timeout + partial
    fallback, and a late retry that publishes `NeighborhoodEnriched` (§7.12)."""

    async def enrich_top3(
        self, *, lead_id: uuid.UUID, property_ids: list[uuid.UUID], timeout_ms: int
    ) -> dict[uuid.UUID, NeighborhoodInsight | None]: ...


class RecommendationPort(Protocol):
    """Facade the Coordinator (and, from Sprint 5, the Handoff Package
    Builder) calls — orchestrates filter -> retrieval -> rank -> explain ->
    enrich end to end and returns the Top-3 (§6.1.1, §7.10)."""

    async def search(self, *, organization_id: uuid.UUID, lead_id: uuid.UUID):  # -> RecommendationResult
        ...
