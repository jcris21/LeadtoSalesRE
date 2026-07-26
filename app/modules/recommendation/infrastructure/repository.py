"""Repository translating between Recommendation domain objects and their
ORM rows (M4, Sprint 3A). `PropertyRepository` is the seam the Ingestion
Pipeline (and, later, Structured Filter) reads/writes through."""

from __future__ import annotations

import uuid
from datetime import UTC

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.lead_qualification.domain.models import MoneyRange, PropertyType
from app.modules.recommendation.domain.models import (
    NeighborhoodInsight,
    Property,
    PropertyEmbedding,
    RecommendationResult,
)
from app.modules.recommendation.infrastructure.db_models import (
    PropertyEmbeddingORM,
    PropertyORM,
    RecommendationORM,
)
from app.shared.domain.base import new_id, utcnow


def _ensure_utc(value):
    return value if value.tzinfo else value.replace(tzinfo=UTC)


class PropertyRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def upsert(self, property: Property) -> None:
        """Insert or update by local id (deterministic per organization +
        external_id — see `MockInventorySource`), never duplicating a row for
        the same inventory item."""
        row = await self._session.get(PropertyORM, property.id)
        if row is None:
            self._session.add(self._to_row(property))
            return
        row.external_id = property.external_id
        row.price = property.price
        row.zone = property.zone
        row.property_type = property.property_type.value
        row.features = list(property.features)
        row.description = property.description
        row.name_address = property.name_address
        row.estado = property.estado
        row.link_references = list(property.link_references)
        row.updated_at = property.updated_at

    async def get_embedding(self, property_id: uuid.UUID) -> PropertyEmbedding | None:
        row = await self._session.get(PropertyEmbeddingORM, property_id)
        return self._to_embedding_domain(row) if row is not None else None

    async def get_embedding_hash(self, property_id: uuid.UUID) -> str | None:
        """Content fingerprint the stored embedding was computed from — lets
        the Ingestion Pipeline decide "unchanged" without exposing storage
        details through the `PropertyEmbedding` value object."""
        row = await self._session.get(PropertyEmbeddingORM, property_id)
        return row.source_hash if row is not None else None

    async def save_embedding(self, embedding: PropertyEmbedding, *, source_hash: str) -> None:
        if self._session.bind.dialect.name == "postgresql":
            # The ORM column stays portable JSON (SQLite tests), but the real
            # Postgres column is vector(1536) — binding through the ORM emits
            # `$n::JSON` and fails, so upsert with an explicit vector cast
            # (same dialect-gated pattern as `semantic_search`).
            vector_literal = "[" + ",".join(f"{v:.10f}" for v in embedding.vector) + "]"
            await self._session.execute(
                text(
                    "INSERT INTO property_embeddings "
                    "(property_id, vector, model_version, source_hash, computed_at) "
                    "VALUES (:property_id, CAST(:vec AS vector), :model_version, "
                    ":source_hash, :computed_at) "
                    "ON CONFLICT (property_id) DO UPDATE SET "
                    "vector = EXCLUDED.vector, model_version = EXCLUDED.model_version, "
                    "source_hash = EXCLUDED.source_hash, computed_at = EXCLUDED.computed_at"
                ),
                {
                    "property_id": str(embedding.property_id),
                    "vec": vector_literal,
                    "model_version": embedding.model_version,
                    "source_hash": source_hash,
                    "computed_at": embedding.computed_at,
                },
            )
            return
        row = await self._session.get(PropertyEmbeddingORM, embedding.property_id)
        if row is None:
            row = PropertyEmbeddingORM(property_id=embedding.property_id)
            self._session.add(row)
        row.vector = list(embedding.vector)
        row.model_version = embedding.model_version
        row.source_hash = source_hash
        row.computed_at = embedding.computed_at

    async def list_for_organization(self, organization_id: uuid.UUID) -> list[Property]:
        result = await self._session.execute(
            select(PropertyORM).where(PropertyORM.organization_id == organization_id)
        )
        return [self._to_domain(row) for row in result.scalars().all()]

    async def filter_candidates(
        self,
        organization_id: uuid.UUID,
        *,
        budget: MoneyRange | None,
        zones: tuple[str, ...],
        property_type: PropertyType | None,
    ) -> list[Property]:
        """US-303: hard-constraint filter pushed down to SQL WHERE — same
        semantics as `Property.matches_hard_filters` (an absent constraint
        adds no clause), always scoped by organization."""
        query = select(PropertyORM).where(PropertyORM.organization_id == organization_id)
        if budget is not None:
            query = query.where(
                PropertyORM.price >= budget.minimum, PropertyORM.price <= budget.maximum
            )
        if zones:
            query = query.where(PropertyORM.zone.in_(zones))
        if property_type is not None:
            query = query.where(PropertyORM.property_type == property_type.value)
        result = await self._session.execute(query)
        return [self._to_domain(row) for row in result.scalars().all()]

    async def count_available(
        self, organization_id: uuid.UUID, *, zones: tuple[str, ...] = ()
    ) -> int:
        """Count of `estado="disponible"` properties, optionally narrowed to
        `zones` — used to ground a zero-result conversational reply in a real
        citywide (zones=()) or per-zone availability figure instead of the
        LLM inventing one (see `application.search_diagnostics`)."""
        query = (
            select(func.count())
            .select_from(PropertyORM)
            .where(PropertyORM.organization_id == organization_id, PropertyORM.estado == "disponible")
        )
        if zones:
            query = query.where(PropertyORM.zone.in_(zones))
        result = await self._session.execute(query)
        return result.scalar_one()

    async def count_near_price(
        self,
        organization_id: uuid.UUID,
        *,
        budget: MoneyRange,
        zones: tuple[str, ...] = (),
        tolerance: float = 0.20,
    ) -> int:
        """Count of `estado="disponible"` properties within `budget` widened
        by `tolerance` on both ends — the "closer price" figure offered to a
        lead whose exact budget matched nothing (US-hallucination-fix)."""
        low = budget.minimum * (1 - tolerance)
        high = budget.maximum * (1 + tolerance)
        query = (
            select(func.count())
            .select_from(PropertyORM)
            .where(
                PropertyORM.organization_id == organization_id,
                PropertyORM.estado == "disponible",
                PropertyORM.price >= low,
                PropertyORM.price <= high,
            )
        )
        if zones:
            query = query.where(PropertyORM.zone.in_(zones))
        result = await self._session.execute(query)
        return result.scalar_one()

    async def semantic_search(
        self,
        *,
        candidate_ids: list[uuid.UUID],
        query_vector: tuple[float, ...],
        top_n: int,
    ) -> list[Property] | None:
        """US-304: pgvector `<->` (cosine distance) ranking over the already
        hard-filtered candidates. Returns None on dialects without pgvector
        (e.g. the SQLite test harness) so the caller falls back to the
        in-memory path — the service owns that decision (design D3/D4)."""
        if self._session.bind.dialect.name != "postgresql" or not candidate_ids:
            return None
        vector_literal = "[" + ",".join(f"{v:.10f}" for v in query_vector) + "]"
        query = (
            select(PropertyORM)
            .join(PropertyEmbeddingORM, PropertyEmbeddingORM.property_id == PropertyORM.id)
            .where(PropertyORM.id.in_(candidate_ids))
            .order_by(
                text("property_embeddings.vector <-> CAST(:query_vector AS vector)").bindparams(
                    query_vector=vector_literal
                )
            )
            .limit(top_n)
        )
        result = await self._session.execute(query)
        return [self._to_domain(row) for row in result.scalars().all()]

    @staticmethod
    def _to_row(property: Property) -> PropertyORM:
        return PropertyORM(
            id=property.id,
            organization_id=property.organization_id,
            external_id=property.external_id,
            price=property.price,
            zone=property.zone,
            property_type=property.property_type.value,
            features=list(property.features),
            description=property.description,
            name_address=property.name_address,
            estado=property.estado,
            link_references=list(property.link_references),
            updated_at=property.updated_at,
        )

    @staticmethod
    def _to_domain(row: PropertyORM) -> Property:
        return Property(
            id=row.id,
            organization_id=row.organization_id,
            external_id=row.external_id,
            price=row.price,
            zone=row.zone,
            property_type=PropertyType(row.property_type),
            features=tuple(row.features or ()),
            description=row.description,
            name_address=row.name_address,
            estado=row.estado,
            link_references=tuple(row.link_references or ()),
            updated_at=_ensure_utc(row.updated_at),
        )

    @staticmethod
    def _to_embedding_domain(row: PropertyEmbeddingORM) -> PropertyEmbedding:
        return PropertyEmbedding(
            property_id=row.property_id,
            vector=tuple(row.vector),
            model_version=row.model_version,
            computed_at=_ensure_utc(row.computed_at),
        )


class SqlPropertyLocationLookup:
    """`PropertyLocationPort` backed by a fresh session per lookup (US-307).

    Neighborhood enrichment's fan-out and its background retry both run
    without a caller-owned session — the retry is fire-and-forget, outside
    any request (see `NeighborhoodEnrichmentAdapter._publish_late_insight`,
    which opens its own session the same way) — so this owns a short-lived
    session per call rather than depending on state some other component
    holds open.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def location_for(self, property_id: uuid.UUID) -> str | None:
        async with self._session_factory() as session:
            row = await session.get(PropertyORM, property_id)
        if row is None:
            return None
        return row.name_address or row.zone or None


def _neighborhood_snapshot(insight: NeighborhoodInsight | None) -> dict | None:
    if insight is None:
        return None
    return {
        "nearby_places": list(insight.nearby_places),
        "partial": insight.partial,
        "generated_at": insight.generated_at.isoformat(),
    }


class RecommendationRepository:
    """US-310: audit-trail persistence for recommendation searches. Satisfies
    `RecommendationService`'s structural `RecommendationStore` dependency."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def save_result(
        self,
        *,
        organization_id: uuid.UUID,
        buyer_profile_id: uuid.UUID | None,
        result: RecommendationResult,
    ) -> None:
        """One row per ranked item. `delivered_at` stays NULL here — delivery
        is the caller's event (see `mark_delivered`)."""
        for item in result.items:
            self._session.add(
                RecommendationORM(
                    id=new_id(),
                    organization_id=organization_id,
                    lead_id=result.lead_id,
                    buyer_profile_id=buyer_profile_id,
                    property_id=item.property_id,
                    rank=item.rank,
                    score=item.score,
                    signals=[
                        {"name": s.name, "weight": s.weight, "value": s.value}
                        for s in item.signals
                    ],
                    explanation=item.explanation,
                    neighborhood=_neighborhood_snapshot(item.neighborhood),
                    feedback=None,
                    generated_at=result.generated_at,
                    delivered_at=None,
                )
            )

    async def mark_delivered(self, lead_id: uuid.UUID, generated_at) -> None:
        """Stamps `delivered_at` on the rows of one search (lead + timestamp
        identify the batch) after the message was actually published."""
        result = await self._session.execute(
            select(RecommendationORM).where(
                RecommendationORM.lead_id == lead_id,
                RecommendationORM.generated_at == generated_at,
            )
        )
        now = utcnow()
        for row in result.scalars().all():
            row.delivered_at = now

    async def list_for_lead(self, lead_id: uuid.UUID) -> list[RecommendationORM]:
        result = await self._session.execute(
            select(RecommendationORM)
            .where(RecommendationORM.lead_id == lead_id)
            .order_by(RecommendationORM.generated_at, RecommendationORM.rank)
        )
        return list(result.scalars().all())
