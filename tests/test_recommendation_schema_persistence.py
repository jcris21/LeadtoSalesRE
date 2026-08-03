"""Sprint 3.1 — US-309 (properties schema reconciliation), US-308 (real
embedding model), US-310 (recommendations persistence)."""

from __future__ import annotations

import uuid

import httpx
import pytest
from sqlalchemy import select

import app.modules.recommendation.infrastructure.embedding_model as embedding_model_module
from app.modules.lead_qualification.application.profile_capture import (
    BuyerProfileCaptureService,
)
from app.modules.lead_qualification.domain.models import (
    Lead,
    MoneyRange,
    ProfilePatch,
    PropertyType,
)
from app.modules.lead_qualification.infrastructure.repository import (
    BuyerProfileRepository,
    LeadRepository,
)
from app.modules.organization.infrastructure.db_models import OrganizationORM
from app.modules.recommendation.application.property_ingestion import (
    HashEmbeddingModel,
    content_hash,
)
from app.modules.recommendation.domain.models import (
    NeighborhoodInsight,
    Property,
    RankingSignal,
    RecommendationItem,
    RecommendationResult,
)
from app.modules.recommendation.infrastructure.db_models import RecommendationORM
from app.modules.recommendation.infrastructure.embedding_model import (
    EmbeddingGenerationError,
    GeminiEmbeddingModel,
    build_embedding_model,
)
from app.modules.recommendation.infrastructure.repository import (
    PropertyRepository,
    RecommendationRepository,
)
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


def _property(org_id, **overrides) -> Property:
    defaults = dict(
        organization_id=org_id,
        external_id="INV-1",
        price=120_000.0,
        zone="Miraflores",
        property_type=PropertyType.APARTMENT,
        features=("balcony",),
        description="Depto luminoso.",
    )
    defaults.update(overrides)
    return Property(**defaults)


# --- US-309: reconciled schema round-trip ------------------------------------


async def test_property_new_fields_round_trip(session_factory, seeded_org):
    org_id = seeded_org
    property = _property(
        org_id,
        name_address="Av. Pardo 123",
        estado="disponible",
        link_references=("https://example.com/foto1.jpg", "https://example.com/tour.pdf"),
    )
    async with session_factory() as session:
        await PropertyRepository(session).upsert(property)
        await session.commit()

    async with session_factory() as session:
        stored = (await PropertyRepository(session).list_for_organization(org_id))[0]
    assert stored.zone == "Miraflores"
    assert stored.name_address == "Av. Pardo 123"
    assert stored.estado == "disponible"
    assert stored.link_references == (
        "https://example.com/foto1.jpg",
        "https://example.com/tour.pdf",
    )


def test_content_hash_ignores_reconciled_fields():
    org_id = new_id()
    plain = _property(org_id)
    annotated = _property(
        org_id,
        name_address="Av. Pardo 123",
        estado="reservado",
        link_references=("https://example.com/foto.jpg",),
    )
    assert content_hash(plain) == content_hash(annotated)


# --- US-308: real embedding model ---------------------------------------------


def _mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_gemini_embedding_returns_normalized_1536_vector(seeded_org):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured["payload"] = json.loads(request.content)
        captured["auth"] = request.headers.get("x-goog-api-key")
        return httpx.Response(200, json={"embedding": {"values": [0.001] * 1536}})

    model = GeminiEmbeddingModel("test-key", client=_mock_client(handler))
    vector = await model.embed(_property(seeded_org))

    assert len(vector) == 1536
    assert captured["payload"]["model"] == "models/gemini-embedding-001"
    assert captured["payload"]["taskType"] == "RETRIEVAL_DOCUMENT"
    assert captured["payload"]["outputDimensionality"] == 1536
    assert "Depto luminoso." in captured["payload"]["content"]["parts"][0]["text"]
    assert captured["auth"] == "test-key"
    assert model.model_version == "gemini-embedding-001"
    # Truncated Gemini vectors are re-normalized client-side to unit L2 norm.
    assert abs(sum(v * v for v in vector) - 1.0) < 1e-6


async def test_gemini_embedding_retries_once_then_succeeds(seeded_org, monkeypatch):
    monkeypatch.setattr(embedding_model_module, "_RETRY_BACKOFF_SECONDS", 0.0)
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(429, json={"error": "rate limited"})
        return httpx.Response(200, json={"embedding": {"values": [0.5] * 1536}})

    model = GeminiEmbeddingModel("test-key", client=_mock_client(handler))
    vector = await model.embed(_property(seeded_org))
    assert calls["count"] == 2
    assert len(vector) == 1536


async def test_gemini_embedding_raises_after_second_failure(seeded_org, monkeypatch):
    monkeypatch.setattr(embedding_model_module, "_RETRY_BACKOFF_SECONDS", 0.0)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "down"})

    model = GeminiEmbeddingModel("test-key", client=_mock_client(handler))
    with pytest.raises(EmbeddingGenerationError):
        await model.embed(_property(seeded_org))


def test_build_embedding_model_selects_by_key():
    assert isinstance(build_embedding_model("real-key"), GeminiEmbeddingModel)
    assert isinstance(build_embedding_model(None), HashEmbeddingModel)


# --- US-310: recommendations persistence ---------------------------------------


async def _seed_lead_profile_property(session_factory, org_id):
    async with session_factory() as session:
        lead = Lead(organization_id=org_id, crm_lead_id="lead-1")
        await LeadRepository(session).add(lead)
        await session.commit()
    async with session_factory() as session:
        await BuyerProfileCaptureService(session).update_profile(
            lead.id, ProfilePatch(budget=MoneyRange(50_000, 150_000))
        )
        await session.commit()
    property = _property(org_id)
    async with session_factory() as session:
        await PropertyRepository(session).upsert(property)
        await session.commit()
    async with session_factory() as session:
        profile = await BuyerProfileRepository(session).get_by_lead_id(lead.id)
    return lead.id, profile.id, property.id


def _result(lead_id, property_id, generated_at=None) -> RecommendationResult:
    signal = RankingSignal(name="budget_fit", weight=0.4, value=1.0)
    return RecommendationResult(
        generated_at=generated_at or utcnow(),
        lead_id=lead_id,
        items=(
            RecommendationItem(
                property_id=property_id,
                rank=1,
                score=0.4,
                explanation="Encaja en tu presupuesto.",
                neighborhood=NeighborhoodInsight(
                    property_id=property_id, nearby_places=("Parque Kennedy",)
                ),
                signals=(signal,),
            ),
        ),
    )


async def test_save_result_persists_one_row_per_item(session_factory, seeded_org):
    org_id = seeded_org
    lead_id, profile_id, property_id = await _seed_lead_profile_property(
        session_factory, org_id
    )
    result = _result(lead_id, property_id)

    async with session_factory() as session:
        await RecommendationRepository(session).save_result(
            organization_id=org_id, buyer_profile_id=profile_id, result=result
        )
        await session.commit()

    async with session_factory() as session:
        rows = await RecommendationRepository(session).list_for_lead(lead_id)
    assert len(rows) == 1
    row = rows[0]
    assert row.rank == 1
    assert row.score == 0.4
    assert row.signals == [{"name": "budget_fit", "weight": 0.4, "value": 1.0}]
    assert row.explanation == "Encaja en tu presupuesto."
    assert row.neighborhood["nearby_places"] == ["Parque Kennedy"]
    assert row.feedback is None
    assert row.delivered_at is None
    assert row.organization_id == org_id
    assert row.buyer_profile_id == profile_id


async def test_empty_result_persists_nothing(session_factory, seeded_org):
    org_id = seeded_org
    lead_id, profile_id, _ = await _seed_lead_profile_property(session_factory, org_id)

    async with session_factory() as session:
        await RecommendationRepository(session).save_result(
            organization_id=org_id,
            buyer_profile_id=profile_id,
            result=RecommendationResult(lead_id=lead_id, items=()),
        )
        await session.commit()

    async with session_factory() as session:
        rows = (await session.execute(select(RecommendationORM))).scalars().all()
    assert rows == []


async def test_mark_delivered_stamps_only_the_matching_batch(session_factory, seeded_org):
    org_id = seeded_org
    lead_id, profile_id, property_id = await _seed_lead_profile_property(
        session_factory, org_id
    )
    from datetime import timedelta

    now = utcnow()
    # Explicit distinct timestamps: two utcnow() calls in a row can collide
    # at the platform timer's resolution, and (lead_id, generated_at) is the
    # batch identity mark_delivered filters on.
    first = _result(lead_id, property_id, generated_at=now)
    second = _result(lead_id, property_id, generated_at=now + timedelta(seconds=5))

    async with session_factory() as session:
        repo = RecommendationRepository(session)
        await repo.save_result(
            organization_id=org_id, buyer_profile_id=profile_id, result=first
        )
        await repo.save_result(
            organization_id=org_id, buyer_profile_id=profile_id, result=second
        )
        await session.commit()

    async with session_factory() as session:
        await RecommendationRepository(session).mark_delivered(lead_id, first.generated_at)
        await session.commit()

    async with session_factory() as session:
        rows = await RecommendationRepository(session).list_for_lead(lead_id)
    delivered = [r for r in rows if r.delivered_at is not None]
    pending = [r for r in rows if r.delivered_at is None]
    assert len(delivered) == 1
    assert len(pending) == 1


class FakeStore:
    def __init__(self):
        self.calls: list[dict] = []

    async def save_result(self, *, organization_id, buyer_profile_id, result) -> None:
        self.calls.append(
            {
                "organization_id": organization_id,
                "buyer_profile_id": buyer_profile_id,
                "result": result,
            }
        )


async def test_service_persists_via_store_and_threads_signals():
    """Facade-level: search() with a store persists the result whose items
    carry the ranked candidates' signals (US-310)."""
    from app.modules.lead_qualification.application.completeness_gate import (
        CompletenessGate,
    )
    from app.modules.recommendation.application.recommendation_service import (
        RecommendationService,
    )
    from app.modules.recommendation.domain.models import RankedCandidate
    from tests.test_recommendation_service import (
        FakeBuyerProfiles,
        FakeExplanation,
        FakeNeighborhoodEnrichment,
        FakeRankingEngine,
        FakeSemanticRetrieval,
        FakeStructuredFilter,
        _complete_profile,
    )

    lead_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    profile = _complete_profile(lead_id)
    candidate = _property(organization_id)
    signal = RankingSignal(name="budget_fit", weight=0.4, value=1.0)
    store = FakeStore()

    service = RecommendationService(
        buyer_profiles=FakeBuyerProfiles(profile),
        structured_filter=FakeStructuredFilter([candidate]),
        semantic_retrieval=FakeSemanticRetrieval([candidate]),
        ranking_engine=FakeRankingEngine(
            [RankedCandidate(property_id=candidate.id, score=0.4, signals=(signal,))]
        ),
        explanation=FakeExplanation(),
        neighborhood_enrichment=FakeNeighborhoodEnrichment({candidate.id: None}),
        completeness_gate=CompletenessGate(threshold=90.0),
        recommendation_store=store,
    )

    result = await service.search(organization_id=organization_id, lead_id=lead_id)

    assert result.items[0].signals == (signal,)
    assert len(store.calls) == 1
    assert store.calls[0]["organization_id"] == organization_id
    assert store.calls[0]["buyer_profile_id"] == profile.id
    assert store.calls[0]["result"] is result
