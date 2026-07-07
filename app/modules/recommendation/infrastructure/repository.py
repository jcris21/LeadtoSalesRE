"""Repository translating between Recommendation domain objects and their
ORM rows (M4, Sprint 3A). `PropertyRepository` is the seam the Ingestion
Pipeline (and, later, Structured Filter) reads/writes through."""

from __future__ import annotations

import uuid
from datetime import UTC

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.lead_qualification.domain.models import PropertyType
from app.modules.recommendation.domain.models import Property, PropertyEmbedding
from app.modules.recommendation.infrastructure.db_models import (
    PropertyEmbeddingORM,
    PropertyORM,
)


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
