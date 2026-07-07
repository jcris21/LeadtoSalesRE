"""Ranking Engine (M4, Sprint 3A): deterministic, LLM-free scoring per
Architecture.md §6.3 / §7.10 — `score = Σ(signal.weight × value)`."""

from __future__ import annotations

from app.modules.lead_qualification.domain.models import BuyerProfile, MoneyRange, PropertyType
from app.modules.recommendation.application.ranking_engine import WeightedRankingEngine
from app.modules.recommendation.domain.models import Property
from app.shared.domain.base import new_id

engine = WeightedRankingEngine()


def _property(
    *,
    price: float = 100_000,
    zone: str = "downtown",
    property_type: PropertyType = PropertyType.APARTMENT,
    features: tuple[str, ...] = (),
) -> Property:
    return Property(
        organization_id=new_id(),
        external_id="ext-1",
        price=price,
        zone=zone,
        property_type=property_type,
        features=features,
    )


def _buyer_profile(
    *,
    budget: MoneyRange | None = MoneyRange(minimum=80_000, maximum=120_000),
    locations: tuple[str, ...] = ("downtown",),
    property_type: PropertyType | None = PropertyType.APARTMENT,
    must_haves: tuple[str, ...] = ("balcony", "parking"),
) -> BuyerProfile:
    return BuyerProfile(
        lead_id=new_id(),
        budget=budget,
        locations=locations,
        property_type=property_type,
        must_haves=must_haves,
    )


def test_perfect_match_scores_higher_than_no_match():
    buyer = _buyer_profile()
    perfect = _property(
        price=100_000,
        zone="downtown",
        property_type=PropertyType.APARTMENT,
        features=("balcony", "parking", "gym"),
    )
    no_match = _property(
        price=500_000,
        zone="suburbs",
        property_type=PropertyType.HOUSE,
        features=("garden",),
    )

    ranked = engine.rank(buyer_profile=buyer, candidates=[no_match, perfect], top_k=2)

    assert len(ranked) == 2
    assert ranked[0].property_id == perfect.id
    assert ranked[0].score > ranked[1].score
    assert ranked[1].property_id == no_match.id


def test_ranking_is_deterministic():
    buyer = _buyer_profile()
    candidates = [
        _property(price=90_000, zone="downtown", features=("balcony",)),
        _property(price=110_000, zone="suburbs", features=("parking",)),
        _property(price=200_000, zone="downtown", property_type=PropertyType.HOUSE),
    ]

    first_run = engine.rank(buyer_profile=buyer, candidates=candidates, top_k=3)
    second_run = engine.rank(buyer_profile=buyer, candidates=candidates, top_k=3)

    assert [c.property_id for c in first_run] == [c.property_id for c in second_run]
    assert [c.score for c in first_run] == [c.score for c in second_run]


def test_top_k_is_respected():
    buyer = _buyer_profile()
    candidates = [
        _property(price=80_000 + i * 5_000, zone="downtown", features=("balcony",))
        for i in range(5)
    ]

    ranked = engine.rank(buyer_profile=buyer, candidates=candidates, top_k=3)

    assert len(ranked) == 3


def test_ties_are_broken_by_stable_input_order():
    """Two candidates with identical attributes tie on score; `rank` uses
    Python's stable sort, so the one earlier in `candidates` stays first."""
    buyer = _buyer_profile()
    first = _property(price=100_000, zone="downtown", features=("balcony", "parking"))
    second = _property(price=100_000, zone="downtown", features=("balcony", "parking"))

    ranked = engine.rank(buyer_profile=buyer, candidates=[first, second], top_k=2)

    assert ranked[0].score == ranked[1].score
    assert ranked[0].property_id == first.id
    assert ranked[1].property_id == second.id


def test_empty_candidate_list_returns_empty_list():
    buyer = _buyer_profile()

    ranked = engine.rank(buyer_profile=buyer, candidates=[], top_k=3)

    assert ranked == []


def test_signals_sum_to_score():
    buyer = _buyer_profile()
    candidate = _property(
        price=95_000,
        zone="downtown",
        property_type=PropertyType.APARTMENT,
        features=("balcony",),
    )

    ranked = engine.rank(buyer_profile=buyer, candidates=[candidate], top_k=1)

    assert len(ranked) == 1
    result = ranked[0]
    expected_score = sum(signal.weight * signal.value for signal in result.signals)
    assert result.score == expected_score


def test_missing_budget_degrades_gracefully_without_raising():
    buyer = _buyer_profile(budget=None)
    candidate = _property(price=100_000)

    ranked = engine.rank(buyer_profile=buyer, candidates=[candidate], top_k=1)

    assert len(ranked) == 1
    budget_signal = next(s for s in ranked[0].signals if s.name == "budget_fit")
    assert budget_signal.value == 0.0


def test_out_of_range_price_scores_zero_on_budget_fit_but_does_not_raise():
    buyer = _buyer_profile(budget=MoneyRange(minimum=80_000, maximum=120_000))
    candidate = _property(price=999_000)

    ranked = engine.rank(buyer_profile=buyer, candidates=[candidate], top_k=1)

    budget_signal = next(s for s in ranked[0].signals if s.name == "budget_fit")
    assert budget_signal.value == 0.0


def test_empty_must_haves_contributes_zero_not_full_credit():
    buyer = _buyer_profile(must_haves=())
    candidate = _property(features=("balcony", "parking"))

    ranked = engine.rank(buyer_profile=buyer, candidates=[candidate], top_k=1)

    coverage_signal = next(s for s in ranked[0].signals if s.name == "must_have_coverage")
    assert coverage_signal.value == 0.0


def test_partial_must_have_coverage_is_fractional():
    buyer = _buyer_profile(must_haves=("balcony", "parking", "gym"))
    candidate = _property(features=("balcony", "parking"))

    ranked = engine.rank(buyer_profile=buyer, candidates=[candidate], top_k=1)

    coverage_signal = next(s for s in ranked[0].signals if s.name == "must_have_coverage")
    assert coverage_signal.value == 2 / 3
