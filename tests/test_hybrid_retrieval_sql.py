"""Sprint 3.2 — US-303 (SQL WHERE structured filter) and US-304 (pgvector
SQL-path selection in semantic retrieval)."""

from __future__ import annotations

import uuid

import pytest

from app.modules.lead_qualification.domain.models import BuyerProfile, MoneyRange, PropertyType
from app.modules.organization.infrastructure.db_models import OrganizationORM
from app.modules.recommendation.application.retrieval import (
    SemanticRetrievalService,
    StructuredFilterService,
)
from app.modules.recommendation.domain.models import Property
from app.modules.recommendation.infrastructure.repository import PropertyRepository
from app.shared.domain.base import new_id, utcnow


@pytest.fixture
def org_id():
    return new_id()


@pytest.fixture
async def seeded_org(session_factory, org_id):
    async with session_factory() as session:
        session.add(
            OrganizationORM(id=org_id, name="Org Test", status="active", created_at=utcnow())
        )
        await session.commit()
    return org_id


def _property(org_id, *, price=100_000.0, zone="Miraflores", ptype=PropertyType.APARTMENT):
    return Property(
        organization_id=org_id,
        external_id=str(uuid.uuid4()),
        price=price,
        zone=zone,
        property_type=ptype,
    )


async def _seed(session_factory, properties):
    async with session_factory() as session:
        repo = PropertyRepository(session)
        for p in properties:
            await repo.upsert(p)
        await session.commit()


# --- US-303: SQL WHERE parity ------------------------------------------------


async def test_sql_filter_applies_all_hard_constraints(session_factory, seeded_org):
    org_id = seeded_org
    match = _property(org_id)
    out_of_budget = _property(org_id, price=500_000.0)
    out_of_zone = _property(org_id, zone="Surco")
    wrong_type = _property(org_id, ptype=PropertyType.HOUSE)
    await _seed(session_factory, [match, out_of_budget, out_of_zone, wrong_type])

    profile = BuyerProfile(
        lead_id=new_id(),
        budget=MoneyRange(minimum=50_000.0, maximum=150_000.0),
        locations=("Miraflores",),
        property_type=PropertyType.APARTMENT,
    )
    async with session_factory() as session:
        service = StructuredFilterService(PropertyRepository(session))
        result = await service.filter_candidates(
            organization_id=org_id, buyer_profile=profile
        )
    assert [p.id for p in result] == [match.id]


async def test_sql_filter_absent_constraints_add_no_clauses(session_factory, seeded_org):
    org_id = seeded_org
    a = _property(org_id, price=10_000.0, zone="A", ptype=PropertyType.HOUSE)
    b = _property(org_id, price=900_000.0, zone="B", ptype=PropertyType.LAND)
    await _seed(session_factory, [a, b])

    profile = BuyerProfile(lead_id=new_id())  # no budget, no zones, no type
    async with session_factory() as session:
        service = StructuredFilterService(PropertyRepository(session))
        result = await service.filter_candidates(
            organization_id=org_id, buyer_profile=profile
        )
    assert {p.id for p in result} == {a.id, b.id}


async def test_sql_filter_is_tenant_scoped(session_factory, seeded_org, org_id):
    other_org = new_id()
    async with session_factory() as session:
        session.add(
            OrganizationORM(id=other_org, name="Org B", status="active", created_at=utcnow())
        )
        await session.commit()
    mine = _property(org_id)
    theirs = _property(other_org)
    await _seed(session_factory, [mine, theirs])

    async with session_factory() as session:
        service = StructuredFilterService(PropertyRepository(session))
        result = await service.filter_candidates(
            organization_id=org_id, buyer_profile=BuyerProfile(lead_id=new_id())
        )
    assert [p.id for p in result] == [mine.id]


# --- US-304: SQL path selection -----------------------------------------------


async def test_semantic_search_reports_unsupported_on_sqlite(session_factory, seeded_org):
    org_id = seeded_org
    p = _property(org_id)
    await _seed(session_factory, [p])
    async with session_factory() as session:
        result = await PropertyRepository(session).semantic_search(
            candidate_ids=[p.id], query_vector=(0.1, 0.2), top_n=5
        )
    assert result is None  # SQLite has no pgvector -> caller falls back


class SqlCapableStore:
    """Fake store whose semantic_search 'is' the database ranking."""

    def __init__(self, ranked: list[Property]):
        self.ranked = ranked
        self.search_calls: list[dict] = []
        self.embedding_calls = 0

    async def semantic_search(self, *, candidate_ids, query_vector, top_n):
        self.search_calls.append(
            {"candidate_ids": candidate_ids, "query_vector": query_vector, "top_n": top_n}
        )
        return self.ranked[:top_n]

    async def get_embedding(self, property_id):
        self.embedding_calls += 1
        return None


async def test_retrieve_uses_sql_path_and_never_python_cosine():
    org_id = new_id()
    first, second, third = (_property(org_id) for _ in range(3))
    store = SqlCapableStore(ranked=[first, second, third])
    service = SemanticRetrievalService(store, embed_query=lambda _p: (1.0, 0.0))

    result = await service.retrieve(
        buyer_profile=BuyerProfile(lead_id=new_id()),
        candidates=[third, first, second],
        top_n=2,
    )

    assert result == [first, second]  # SQL ordering wins, top_n honored
    assert store.search_calls[0]["top_n"] == 2
    assert store.embedding_calls == 0  # in-memory path never ran
