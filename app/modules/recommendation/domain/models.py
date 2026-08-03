"""Domain model of the Recommendation bounded context (M4, Sprint 3A/3B).

Pipeline (Architecture.md §6.3, §7.10-§7.12): Property Ingestion precalculates
embeddings so Semantic Retrieval never embeds at request time; Structured
Filter narrows by BuyerProfile hard constraints before Semantic Retrieval
scores by similarity; Ranking Engine combines weighted RankingSignals into a
deterministic score (no LLM); Explanation Generator phrases the winning
signals in natural language (never invents a reason); Neighborhood Enrichment
fans out to Google Maps for the Top-3 in parallel, with a partial fallback on
timeout and a late `NeighborhoodEnriched` event when the retry succeeds.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from app.modules.lead_qualification.domain.models import MoneyRange, PropertyType
from app.shared.domain.base import DomainEvent, Entity, ValueObject, new_id, utcnow

__all__ = [
    "MoneyRange",
    "NeighborhoodEnriched",
    "NeighborhoodInsight",
    "Property",
    "PropertyEmbedding",
    "RankedCandidate",
    "RankingSignal",
    "RecommendationError",
    "RecommendationItem",
    "RecommendationResult",
]


class RecommendationError(ValueError):
    """Raised when a recommendation-pipeline invariant is violated."""


class Property(Entity):
    """Inventory item mirrored locally so Structured Filter can run plain SQL
    without a round-trip to the inventory source (Architecture.md §6.3)."""

    def __init__(
        self,
        *,
        id: uuid.UUID | None = None,
        organization_id: uuid.UUID,
        external_id: str,
        price: float,
        zone: str,
        property_type: PropertyType,
        features: tuple[str, ...] = (),
        description: str = "",
        name_address: str | None = None,
        estado: str | None = None,
        link_references: tuple[str, ...] = (),
        bedrooms: int | None = None,
        updated_at: datetime | None = None,
    ) -> None:
        self.id = id or new_id()
        self.organization_id = organization_id
        self.external_id = external_id
        self.price = price
        self.zone = zone
        self.property_type = property_type
        self.features = features
        self.description = description
        #: US-222: hard-filter dimension, nullable — inventory not yet
        #: backfilled has no bedroom count and never matches a lead-specified
        #: constraint (`matches_hard_filters`).
        self.bedrooms = bedrooms
        # US-309: fields formalized from the hand-edited Supabase schema.
        # Deliberately NOT part of ingestion's `_content_key` — changing them
        # must not invalidate stored embedding hashes (design.md D3).
        self.name_address = name_address
        self.estado = estado
        self.link_references = link_references
        self.updated_at = updated_at or utcnow()

    def matches_hard_filters(
        self,
        *,
        budget: MoneyRange | None,
        zones: tuple[str, ...],
        property_type: PropertyType | None,
        bedrooms: int | None = None,
    ) -> bool:
        """Structured Filter Service predicate (§6.3): hard constraints only,
        never a ranking signal — a property either qualifies or is discarded."""
        if budget is not None and not (budget.minimum <= self.price <= budget.maximum):
            return False
        if zones and self.zone not in zones:
            return False
        if property_type is not None and self.property_type is not property_type:
            return False
        # US-222: absent constraint = no clause; a present constraint against
        # an untagged (bedrooms=None) property never matches.
        if bedrooms is not None and self.bedrooms != bedrooms:
            return False
        return True


@dataclass(frozen=True)
class PropertyEmbedding(ValueObject):
    """Precalculated vector for one property (pgvector column). Recomputed by
    the Ingestion Pipeline only when the source property's features change —
    never on the request path (Architecture.md §6.3)."""

    property_id: uuid.UUID
    vector: tuple[float, ...]
    model_version: str
    computed_at: datetime = field(default_factory=utcnow)


@dataclass(frozen=True)
class RankingSignal(ValueObject):
    """One weighted factor feeding the Ranking Engine's deterministic score
    (§7.10: `score = Σ(signal.weight × value)`)."""

    name: str
    weight: float
    value: float

    @property
    def contribution(self) -> float:
        return self.weight * self.value


@dataclass(frozen=True)
class RankedCandidate(ValueObject):
    """Ranking Engine output for one property: the score plus the exact
    signals that produced it, so Explanation Generator never has to guess."""

    property_id: uuid.UUID
    score: float
    signals: tuple[RankingSignal, ...]

    def top_signals(self, count: int = 3) -> tuple[RankingSignal, ...]:
        """The 2-3 highest-contribution signals (§7.11 input to Explanation)."""
        return tuple(
            sorted(self.signals, key=lambda s: abs(s.contribution), reverse=True)[:count]
        )


@dataclass(frozen=True)
class NeighborhoodInsight(ValueObject):
    """Google Maps enrichment for one property. `partial=True` marks a
    timeout fallback (§7.12) that a later `NeighborhoodEnriched` event upgrades."""

    property_id: uuid.UUID
    nearby_places: tuple[str, ...]
    partial: bool = False
    generated_at: datetime = field(default_factory=utcnow)


@dataclass(frozen=True)
class RecommendationItem(ValueObject):
    """One Top-3 entry returned to the Coordinator: score, explanation, and
    neighborhood data if it arrived within the enrichment timeout. `signals`
    (US-310) carries the exact RankingSignals that produced the score so
    persistence can audit the ranking rationale."""

    property_id: uuid.UUID
    rank: int
    score: float
    explanation: str
    neighborhood: NeighborhoodInsight | None = None
    signals: tuple[RankingSignal, ...] = ()


@dataclass(frozen=True)
class RecommendationResult(ValueObject):
    lead_id: uuid.UUID
    items: tuple[RecommendationItem, ...]
    generated_at: datetime = field(default_factory=utcnow)


@dataclass(frozen=True)
class NeighborhoodEnriched(DomainEvent):
    """Published when a delayed Maps retry succeeds after the initial
    fan-in timed out (§7.12) — the Coordinator sends a follow-up message."""

    lead_id: str = ""
    property_id: str = ""
    nearby_places: tuple[str, ...] = ()
