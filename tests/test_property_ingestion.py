"""Sprint 3A - Property Ingestion Pipeline (M4, Architecture.md 6.3):
ingesting a fresh organization creates every property + its embedding,
re-ingesting unchanged data never recomputes an embedding, a changed
property's embedding is recomputed, and ingestion never leaks across
organizations."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.modules.lead_qualification.domain.models import PropertyType
from app.modules.organization.infrastructure.db_models import OrganizationORM
from app.modules.recommendation.application.property_ingestion import (
    PropertyIngestionService,
    content_hash,
)
from app.modules.recommendation.domain.models import Property
from app.modules.recommendation.infrastructure.db_models import (
    PropertyEmbeddingORM,
    PropertyORM,
)
from app.modules.recommendation.infrastructure.inventory_source import MockInventorySource
from app.shared.domain.base import new_id, utcnow


class FakeInventorySource:
    """In-memory stand-in so tests can mutate the catalog between ingestion
    runs (mirrors FakeWacrmClient in test_lead_sync.py)."""

    def __init__(self, properties: list[Property]):
        self.properties = properties

    async def fetch(self, organization_id):
        return [p for p in self.properties if p.organization_id == organization_id]


def _property(
    organization_id,
    *,
    property_id=None,
    external_id="INV-100",
    price=100000.0,
    zone="Palermo",
    property_type=PropertyType.APARTMENT,
    features=("balcony",),
    description="A test property.",
):
    return Property(
        id=property_id or uuid.uuid5(uuid.NAMESPACE_URL, f"{organization_id}:{external_id}"),
        organization_id=organization_id,
        external_id=external_id,
        price=price,
        zone=zone,
        property_type=property_type,
        features=features,
        description=description,
        updated_at=utcnow(),
    )


@pytest.fixture
def org_id():
    return new_id()


@pytest.fixture
def other_org_id():
    return new_id()


@pytest.fixture
async def seeded_orgs(session_factory, org_id, other_org_id):
    async with session_factory() as session:
        session.add(OrganizationORM(id=org_id, name="Org A", status="active", created_at=utcnow()))
        session.add(
            OrganizationORM(id=other_org_id, name="Org B", status="active", created_at=utcnow())
        )
        await session.commit()
    return org_id, other_org_id


async def test_ingesting_fresh_organization_creates_properties_and_embeddings(
    session_factory, seeded_orgs
):
    org_id, _ = seeded_orgs
    async with session_factory() as session:
        service = PropertyIngestionService(session, source=MockInventorySource())
        touched = await service.ingest_from_source(org_id)
        await session.commit()

    assert touched == 10  # full mock catalog size

    async with session_factory() as session:
        properties = (
            await session.execute(select(PropertyORM).where(PropertyORM.organization_id == org_id))
        ).scalars().all()
        embeddings = (await session.execute(select(PropertyEmbeddingORM))).scalars().all()
        assert len(properties) == 10
        assert len(embeddings) == 10
        assert {e.property_id for e in embeddings} == {p.id for p in properties}


async def test_reingesting_unchanged_data_does_not_recompute_embeddings(
    session_factory, seeded_orgs
):
    org_id, _ = seeded_orgs
    source = FakeInventorySource([_property(org_id)])

    async with session_factory() as session:
        service = PropertyIngestionService(session, source=source)
        first = await service.ingest_from_source(org_id)
        await session.commit()
    assert first == 1

    async with session_factory() as session:
        stored_before = (await session.execute(select(PropertyEmbeddingORM))).scalar_one()
        computed_at_before = stored_before.computed_at

    # Re-ingest identical content (a fresh updated_at, same features/price/etc).
    source.properties = [_property(org_id)]
    async with session_factory() as session:
        service = PropertyIngestionService(session, source=source)
        second = await service.ingest_from_source(org_id)
        await session.commit()
    assert second == 0

    async with session_factory() as session:
        stored_after = (await session.execute(select(PropertyEmbeddingORM))).scalar_one()
        assert stored_after.computed_at == computed_at_before


async def test_changed_property_recomputes_embedding(session_factory, seeded_orgs):
    org_id, _ = seeded_orgs
    source = FakeInventorySource([_property(org_id, price=100000.0)])

    async with session_factory() as session:
        service = PropertyIngestionService(session, source=source)
        await service.ingest_from_source(org_id)
        await session.commit()

    async with session_factory() as session:
        original = (await session.execute(select(PropertyEmbeddingORM))).scalar_one()
        original_vector = list(original.vector)
        original_hash = original.source_hash

    # Price change -> content hash changes -> embedding must be recomputed.
    source.properties = [_property(org_id, price=250000.0)]
    async with session_factory() as session:
        service = PropertyIngestionService(session, source=source)
        touched = await service.ingest_from_source(org_id)
        await session.commit()
    assert touched == 1

    async with session_factory() as session:
        updated = (await session.execute(select(PropertyEmbeddingORM))).scalar_one()
        assert updated.source_hash != original_hash
        assert list(updated.vector) != original_vector

        prop_row = await session.get(PropertyORM, updated.property_id)
        assert prop_row.price == 250000.0


async def test_ingestion_is_scoped_per_organization(session_factory, seeded_orgs):
    org_id, other_org_id = seeded_orgs
    source = MockInventorySource()

    async with session_factory() as session:
        service = PropertyIngestionService(session, source=source)
        touched = await service.ingest_from_source(org_id)
        await session.commit()
    assert touched == 10

    async with session_factory() as session:
        other_org_properties = (
            await session.execute(
                select(PropertyORM).where(PropertyORM.organization_id == other_org_id)
            )
        ).scalars().all()
        assert other_org_properties == []

        org_properties = (
            await session.execute(select(PropertyORM).where(PropertyORM.organization_id == org_id))
        ).scalars().all()
        assert len(org_properties) == 10


def test_content_hash_ignores_feature_ordering():
    org_id = new_id()
    a = _property(org_id, features=("balcony", "pet_friendly"))
    b = _property(org_id, features=("pet_friendly", "balcony"))
    assert content_hash(a) == content_hash(b)


def test_content_hash_changes_when_description_changes():
    org_id = new_id()
    a = _property(org_id, description="Original description.")
    b = _property(org_id, description="Updated description.")
    assert content_hash(a) != content_hash(b)
