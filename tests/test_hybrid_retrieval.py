"""Tests for the Hybrid Retrieval application services (M4, Sprint 3A).

Pure application logic (Architecture.md §6.3/§7.10): Structured Filter is a
hard-constraint AND, Semantic Retrieval ranks the survivors by cosine
similarity over precalculated embeddings. Both are exercised against an
in-memory fake of `PropertyLookup` -- no DB/conftest fixtures needed.
"""

from __future__ import annotations

import uuid

import pytest

from app.modules.lead_qualification.domain.models import BuyerProfile, MoneyRange, PropertyType
from app.modules.recommendation.application.retrieval import (
    SemanticRetrievalService,
    StructuredFilterService,
)
from app.modules.recommendation.domain.models import Property, PropertyEmbedding

ORG_ID = uuid.uuid4()


class FakePropertyStore:
    """In-memory stand-in for a `PropertyLookup` implementation."""

    def __init__(
        self,
        properties: list[Property] | None = None,
        embeddings: dict[uuid.UUID, PropertyEmbedding] | None = None,
    ) -> None:
        self._properties = properties or []
        self._embeddings = embeddings or {}

    async def filter_candidates(
        self,
        organization_id: uuid.UUID,
        *,
        budget: MoneyRange | None,
        zones: tuple[str, ...],
        property_type: PropertyType | None,
        bedrooms: int | None = None,
    ) -> list[Property]:
        # In-memory mirror of PropertyRepository.filter_candidates' WHERE
        # semantics (US-303/US-222); SQL parity is covered by the DB-backed
        # suite in test_hybrid_retrieval_sql.py.
        return [
            p
            for p in self._properties
            if p.organization_id == organization_id
            and p.matches_hard_filters(
                budget=budget, zones=zones, property_type=property_type, bedrooms=bedrooms
            )
        ]

    async def get_embedding(self, property_id: uuid.UUID) -> PropertyEmbedding | None:
        return self._embeddings.get(property_id)


def make_property(
    *,
    price: float = 100_000.0,
    zone: str = "downtown",
    property_type: PropertyType = PropertyType.APARTMENT,
    organization_id: uuid.UUID = ORG_ID,
    bedrooms: int | None = None,
) -> Property:
    return Property(
        organization_id=organization_id,
        external_id=str(uuid.uuid4()),
        price=price,
        zone=zone,
        property_type=property_type,
        bedrooms=bedrooms,
    )


def make_buyer_profile(
    *,
    budget: MoneyRange | None = None,
    locations: tuple[str, ...] = (),
    property_type: PropertyType | None = None,
    bedrooms: int | None = None,
) -> BuyerProfile:
    return BuyerProfile(
        lead_id=uuid.uuid4(),
        budget=budget,
        locations=locations,
        property_type=property_type,
        bedrooms=bedrooms,
    )


class TestStructuredFilterService:
    @pytest.mark.asyncio
    async def test_discards_property_out_of_budget(self) -> None:
        cheap = make_property(price=50_000.0)
        expensive = make_property(price=500_000.0)
        store = FakePropertyStore(properties=[cheap, expensive])
        service = StructuredFilterService(store)
        profile = make_buyer_profile(budget=MoneyRange(minimum=40_000.0, maximum=100_000.0))

        result = await service.filter_candidates(organization_id=ORG_ID, buyer_profile=profile)

        assert result == [cheap]

    @pytest.mark.asyncio
    async def test_discards_property_out_of_zone(self) -> None:
        in_zone = make_property(zone="downtown")
        out_of_zone = make_property(zone="suburbs")
        store = FakePropertyStore(properties=[in_zone, out_of_zone])
        service = StructuredFilterService(store)
        profile = make_buyer_profile(locations=("downtown",))

        result = await service.filter_candidates(organization_id=ORG_ID, buyer_profile=profile)

        assert result == [in_zone]

    @pytest.mark.asyncio
    async def test_discards_wrong_property_type(self) -> None:
        house = make_property(property_type=PropertyType.HOUSE)
        apartment = make_property(property_type=PropertyType.APARTMENT)
        store = FakePropertyStore(properties=[house, apartment])
        service = StructuredFilterService(store)
        profile = make_buyer_profile(property_type=PropertyType.APARTMENT)

        result = await service.filter_candidates(organization_id=ORG_ID, buyer_profile=profile)

        assert result == [apartment]

    @pytest.mark.asyncio
    async def test_filter_is_strict_and_of_all_constraints(self) -> None:
        """Passes budget+zone but fails type -> must still be discarded."""
        almost_match = make_property(
            price=100_000.0, zone="downtown", property_type=PropertyType.HOUSE
        )
        full_match = make_property(
            price=100_000.0, zone="downtown", property_type=PropertyType.APARTMENT
        )
        store = FakePropertyStore(properties=[almost_match, full_match])
        service = StructuredFilterService(store)
        profile = make_buyer_profile(
            budget=MoneyRange(minimum=50_000.0, maximum=150_000.0),
            locations=("downtown",),
            property_type=PropertyType.APARTMENT,
        )

        result = await service.filter_candidates(organization_id=ORG_ID, buyer_profile=profile)

        assert result == [full_match]

    @pytest.mark.asyncio
    async def test_no_constraints_returns_every_candidate(self) -> None:
        properties = [make_property(), make_property(zone="other")]
        store = FakePropertyStore(properties=properties)
        service = StructuredFilterService(store)
        profile = make_buyer_profile()

        result = await service.filter_candidates(organization_id=ORG_ID, buyer_profile=profile)

        assert result == properties

    @pytest.mark.asyncio
    async def test_discards_property_with_wrong_bedroom_count(self) -> None:
        """US-222: bedrooms is a hard filter, same posture as property_type."""
        two_br = make_property(bedrooms=2)
        three_br = make_property(bedrooms=3)
        store = FakePropertyStore(properties=[two_br, three_br])
        service = StructuredFilterService(store)
        profile = make_buyer_profile(bedrooms=3)

        result = await service.filter_candidates(organization_id=ORG_ID, buyer_profile=profile)

        assert result == [three_br]

    @pytest.mark.asyncio
    async def test_untagged_inventory_excluded_once_bedrooms_constrained(self) -> None:
        """US-222 design.md Decision D1: an absent (`None`) `bedrooms` value on
        the property never matches a present constraint, same "absent value
        never satisfies a present constraint" semantics as the other
        fields — protects against silently showing un-backfilled inventory."""
        untagged = make_property(bedrooms=None)
        store = FakePropertyStore(properties=[untagged])
        service = StructuredFilterService(store)
        profile = make_buyer_profile(bedrooms=2)

        result = await service.filter_candidates(organization_id=ORG_ID, buyer_profile=profile)

        assert result == []

    @pytest.mark.asyncio
    async def test_absent_bedroom_constraint_adds_no_clause(self) -> None:
        properties = [make_property(bedrooms=2), make_property(bedrooms=None)]
        store = FakePropertyStore(properties=properties)
        service = StructuredFilterService(store)
        profile = make_buyer_profile()  # bedrooms=None -> no constraint

        result = await service.filter_candidates(organization_id=ORG_ID, buyer_profile=profile)

        assert result == properties


class TestSemanticRetrievalService:
    @pytest.mark.asyncio
    async def test_empty_candidate_list_returns_empty_result(self) -> None:
        store = FakePropertyStore()
        service = SemanticRetrievalService(store)
        profile = make_buyer_profile()

        result = await service.retrieve(buyer_profile=profile, candidates=[], top_n=10)

        assert result == []

    @pytest.mark.asyncio
    async def test_ranks_by_similarity_descending(self) -> None:
        best = make_property()
        worst = make_property()
        embeddings = {
            best.id: PropertyEmbedding(
                property_id=best.id, vector=(1.0, 0.0, 0.0), model_version="v1"
            ),
            worst.id: PropertyEmbedding(
                property_id=worst.id, vector=(0.0, 1.0, 0.0), model_version="v1"
            ),
        }
        store = FakePropertyStore(embeddings=embeddings)
        service = SemanticRetrievalService(store, embed_query=lambda _profile: (1.0, 0.0, 0.0))
        profile = make_buyer_profile()

        result = await service.retrieve(
            buyer_profile=profile, candidates=[worst, best], top_n=10
        )

        assert result == [best, worst]

    @pytest.mark.asyncio
    async def test_returns_at_most_top_n(self) -> None:
        properties = [make_property() for _ in range(5)]
        embeddings = {
            p.id: PropertyEmbedding(property_id=p.id, vector=(1.0, 0.0), model_version="v1")
            for p in properties
        }
        store = FakePropertyStore(embeddings=embeddings)
        service = SemanticRetrievalService(store, embed_query=lambda _profile: (1.0, 0.0))
        profile = make_buyer_profile()

        result = await service.retrieve(
            buyer_profile=profile, candidates=properties, top_n=2
        )

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_excludes_candidates_missing_embeddings_without_crashing(self) -> None:
        has_embedding = make_property()
        missing_embedding = make_property()
        embeddings = {
            has_embedding.id: PropertyEmbedding(
                property_id=has_embedding.id, vector=(1.0, 0.0), model_version="v1"
            )
        }
        store = FakePropertyStore(embeddings=embeddings)
        service = SemanticRetrievalService(store, embed_query=lambda _profile: (1.0, 0.0))
        profile = make_buyer_profile()

        result = await service.retrieve(
            buyer_profile=profile,
            candidates=[has_embedding, missing_embedding],
            top_n=10,
        )

        assert result == [has_embedding]
