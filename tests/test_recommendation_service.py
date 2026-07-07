"""Tests for RecommendationService, the Sprint 3 facade tying filter ->
retrieval -> rank -> explain -> enrich end to end (Architecture.md §7.10).

All five pipeline stages are faked here (each already has its own dedicated
test file — test_property_ingestion.py, test_hybrid_retrieval.py,
test_ranking_engine.py, test_explanation_generator.py,
test_neighborhood_enrichment.py); this file only verifies the orchestration:
call order, data threaded between stages, and the QA-14 completeness
precondition.
"""

from __future__ import annotations

import uuid

import pytest

from app.modules.lead_qualification.application.completeness_gate import CompletenessGate
from app.modules.lead_qualification.domain.models import (
    BuyerProfile,
    MoneyRange,
    PropertyType,
    Timeline,
)
from app.modules.recommendation.application.recommendation_service import (
    IncompleteProfileError,
    RecommendationService,
)
from app.modules.recommendation.domain.models import (
    NeighborhoodInsight,
    Property,
    RankedCandidate,
    RankingSignal,
)


def _property(zone: str = "Palermo") -> Property:
    return Property(
        organization_id=uuid.uuid4(),
        external_id="p-1",
        price=100_000.0,
        zone=zone,
        property_type=PropertyType.APARTMENT,
    )


def _complete_profile(lead_id: uuid.UUID) -> BuyerProfile:
    return BuyerProfile(
        lead_id=lead_id,
        budget=MoneyRange(minimum=80_000.0, maximum=120_000.0),
        locations=("Palermo",),
        property_type=PropertyType.APARTMENT,
        timeline=Timeline.IMMEDIATE,
        must_haves=("balcony",),
    )


def _incomplete_profile(lead_id: uuid.UUID) -> BuyerProfile:
    return BuyerProfile(lead_id=lead_id, budget=MoneyRange(minimum=80_000.0, maximum=120_000.0))


class FakeBuyerProfiles:
    def __init__(self, profile: BuyerProfile | None):
        self._profile = profile

    async def get_by_lead_id(self, lead_id: uuid.UUID) -> BuyerProfile | None:
        return self._profile


class FakeStructuredFilter:
    def __init__(self, candidates: list[Property]):
        self.candidates = candidates
        self.calls: list[dict] = []

    async def filter_candidates(self, *, organization_id, buyer_profile) -> list[Property]:
        self.calls.append({"organization_id": organization_id, "buyer_profile": buyer_profile})
        return self.candidates


class FakeSemanticRetrieval:
    def __init__(self, retrieved: list[Property]):
        self.retrieved = retrieved
        self.calls: list[dict] = []

    async def retrieve(self, *, buyer_profile, candidates, top_n=10) -> list[Property]:
        self.calls.append(
            {"buyer_profile": buyer_profile, "candidates": candidates, "top_n": top_n}
        )
        return self.retrieved


class FakeRankingEngine:
    def __init__(self, ranked: list[RankedCandidate]):
        self.ranked = ranked
        self.calls: list[dict] = []

    def rank(self, *, buyer_profile, candidates, top_k=3) -> list[RankedCandidate]:
        self.calls.append(
            {"buyer_profile": buyer_profile, "candidates": candidates, "top_k": top_k}
        )
        return self.ranked[:top_k]


class FakeExplanation:
    def __init__(self):
        self.calls: list[dict] = []

    async def explain(self, *, property_id, signals) -> str:
        self.calls.append({"property_id": property_id, "signals": signals})
        return f"explanation-for-{property_id}"


class FakeNeighborhoodEnrichment:
    def __init__(self, insights: dict[uuid.UUID, NeighborhoodInsight | None]):
        self.insights = insights
        self.calls: list[dict] = []

    async def enrich_top3(
        self, *, lead_id, property_ids, timeout_ms
    ) -> dict[uuid.UUID, NeighborhoodInsight | None]:
        self.calls.append(
            {"lead_id": lead_id, "property_ids": property_ids, "timeout_ms": timeout_ms}
        )
        return self.insights


def _service(
    *,
    profile: BuyerProfile | None,
    candidates: list[Property],
    retrieved: list[Property],
    ranked: list[RankedCandidate],
    insights: dict[uuid.UUID, NeighborhoodInsight | None],
) -> tuple[RecommendationService, dict]:
    fakes = {
        "buyer_profiles": FakeBuyerProfiles(profile),
        "structured_filter": FakeStructuredFilter(candidates),
        "semantic_retrieval": FakeSemanticRetrieval(retrieved),
        "ranking_engine": FakeRankingEngine(ranked),
        "explanation": FakeExplanation(),
        "neighborhood_enrichment": FakeNeighborhoodEnrichment(insights),
    }
    service = RecommendationService(
        buyer_profiles=fakes["buyer_profiles"],
        structured_filter=fakes["structured_filter"],
        semantic_retrieval=fakes["semantic_retrieval"],
        ranking_engine=fakes["ranking_engine"],
        explanation=fakes["explanation"],
        neighborhood_enrichment=fakes["neighborhood_enrichment"],
        completeness_gate=CompletenessGate(threshold=90.0),
    )
    return service, fakes


@pytest.mark.asyncio
async def test_search_raises_when_profile_is_incomplete():
    lead_id = uuid.uuid4()
    service, _ = _service(
        profile=_incomplete_profile(lead_id),
        candidates=[],
        retrieved=[],
        ranked=[],
        insights={},
    )

    with pytest.raises(IncompleteProfileError):
        await service.search(organization_id=uuid.uuid4(), lead_id=lead_id)


@pytest.mark.asyncio
async def test_search_raises_when_no_buyer_profile_exists():
    lead_id = uuid.uuid4()
    service, _ = _service(
        profile=None, candidates=[], retrieved=[], ranked=[], insights={}
    )

    with pytest.raises(IncompleteProfileError):
        await service.search(organization_id=uuid.uuid4(), lead_id=lead_id)


@pytest.mark.asyncio
async def test_search_threads_candidates_through_every_stage_in_order():
    lead_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    profile = _complete_profile(lead_id)
    candidate = _property()
    signal = RankingSignal(name="budget_fit", weight=0.4, value=1.0)
    ranked_candidate = RankedCandidate(
        property_id=candidate.id, score=0.4, signals=(signal,)
    )
    insight = NeighborhoodInsight(property_id=candidate.id, nearby_places=("Park",))

    service, fakes = _service(
        profile=profile,
        candidates=[candidate],
        retrieved=[candidate],
        ranked=[ranked_candidate],
        insights={candidate.id: insight},
    )

    result = await service.search(organization_id=organization_id, lead_id=lead_id)

    # Structured Filter ran against the real organization_id + profile.
    assert fakes["structured_filter"].calls[0]["organization_id"] == organization_id
    assert fakes["structured_filter"].calls[0]["buyer_profile"] is profile

    # Semantic Retrieval received Structured Filter's output.
    assert fakes["semantic_retrieval"].calls[0]["candidates"] == [candidate]

    # Ranking Engine received Semantic Retrieval's output.
    assert fakes["ranking_engine"].calls[0]["candidates"] == [candidate]

    # Explanation received exactly the winning signals of the ranked candidate,
    # never the candidate list or the score (§7.11 invariant).
    assert fakes["explanation"].calls[0]["property_id"] == candidate.id
    assert fakes["explanation"].calls[0]["signals"] == (signal,)

    # Neighborhood Enrichment received the ranked property ids.
    assert fakes["neighborhood_enrichment"].calls[0]["property_ids"] == [candidate.id]

    assert result.lead_id == lead_id
    assert len(result.items) == 1
    item = result.items[0]
    assert item.property_id == candidate.id
    assert item.rank == 1
    assert item.score == ranked_candidate.score
    assert item.explanation == f"explanation-for-{candidate.id}"
    assert item.neighborhood == insight


@pytest.mark.asyncio
async def test_search_ranks_are_1_indexed_and_ordered_by_score():
    lead_id = uuid.uuid4()
    profile = _complete_profile(lead_id)
    first = _property("Palermo")
    second = _property("Belgrano")
    ranked = [
        RankedCandidate(property_id=first.id, score=0.9, signals=()),
        RankedCandidate(property_id=second.id, score=0.5, signals=()),
    ]

    service, _ = _service(
        profile=profile,
        candidates=[first, second],
        retrieved=[first, second],
        ranked=ranked,
        insights={first.id: None, second.id: None},
    )

    result = await service.search(organization_id=uuid.uuid4(), lead_id=lead_id)

    assert [item.rank for item in result.items] == [1, 2]
    assert result.items[0].property_id == first.id
    assert result.items[1].property_id == second.id


@pytest.mark.asyncio
async def test_search_handles_missing_neighborhood_insight_gracefully():
    """§7.12: a property whose enrichment timed out has `neighborhood=None`,
    never a crash — the Coordinator still sends the Top-3 without it."""
    lead_id = uuid.uuid4()
    profile = _complete_profile(lead_id)
    candidate = _property()
    ranked = [RankedCandidate(property_id=candidate.id, score=1.0, signals=())]

    service, _ = _service(
        profile=profile,
        candidates=[candidate],
        retrieved=[candidate],
        ranked=ranked,
        insights={candidate.id: None},
    )

    result = await service.search(organization_id=uuid.uuid4(), lead_id=lead_id)

    assert result.items[0].neighborhood is None


@pytest.mark.asyncio
async def test_search_returns_empty_result_when_no_candidates_survive_filtering():
    lead_id = uuid.uuid4()
    profile = _complete_profile(lead_id)

    service, fakes = _service(
        profile=profile, candidates=[], retrieved=[], ranked=[], insights={}
    )

    result = await service.search(organization_id=uuid.uuid4(), lead_id=lead_id)

    assert result.items == ()
    # Nothing downstream of filtering should be invoked with empty input.
    assert fakes["semantic_retrieval"].calls[0]["candidates"] == []
