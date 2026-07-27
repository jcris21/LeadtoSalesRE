"""US-214 -- LeadReadinessService: continuous weighted score + 3-state
financing readiness. Additive to LeadScoringService (US-209); does not touch
Lead.lead_score/lead_classification."""

import pytest

from app.modules.lead_qualification.application.lead_readiness import (
    LeadReadinessService,
    classify_financing_readiness,
    compute_readiness_score,
)
from app.modules.lead_qualification.domain.models import (
    BuyerProfile,
    DecisionMakerMode,
    FinancingReadiness,
    FinancingType,
    Lead,
    MoneyRange,
    PropertyType,
    Timeline,
)
from app.modules.lead_qualification.infrastructure.repository import (
    BuyerProfileRepository,
    LeadRepository,
)
from app.modules.organization.infrastructure.db_models import OrganizationORM
from app.shared.domain.base import new_id, utcnow


@pytest.fixture
def org_id():
    return new_id()


@pytest.fixture
async def seeded_lead(session_factory, org_id):
    async with session_factory() as session:
        session.add(
            OrganizationORM(id=org_id, name="Org Test", status="active", created_at=utcnow())
        )
        lead = Lead(organization_id=org_id, crm_lead_id="lead-1")
        await LeadRepository(session).add(lead)
        await session.commit()
    return lead.id


def _empty_profile(lead_id):
    return BuyerProfile(lead_id=lead_id)


def _full_profile(lead_id):
    return BuyerProfile(
        lead_id=lead_id,
        budget=MoneyRange(minimum=100_000, maximum=200_000),
        locations=("Miraflores",),
        property_type=PropertyType.APARTMENT,
        timeline=Timeline.IMMEDIATE,
        financing_type=FinancingType.CASH,
        decision_maker_mode=DecisionMakerMode.SOLO,
    )


# --- compute_readiness_score ----------------------------------------------


def test_empty_profile_scores_zero():
    profile = _empty_profile(new_id())
    assert compute_readiness_score(profile) == 0.0


def test_fully_captured_profile_at_max_tiers_scores_100():
    profile = _full_profile(new_id())
    assert compute_readiness_score(profile) == 100.0


def test_partial_profile_with_urgency_signals_scores_between_bounds():
    # Ticket example scenario: financing_type + timeline + locations captured,
    # not all 8 dimensions.
    profile = BuyerProfile(
        lead_id=new_id(),
        locations=("San Isidro",),
        timeline=Timeline.THREE_MONTHS,
        financing_type=FinancingType.MORTGAGE_PREAPPROVED,
    )
    score = compute_readiness_score(profile)
    # locations(15) + timeline 3_months(15) + financing preapproved(15) = 45
    assert score == 45.0
    assert 0.0 < score < 100.0


def test_exploring_timeline_and_evaluating_financing_score_low_tiers():
    profile = BuyerProfile(
        lead_id=new_id(),
        timeline=Timeline.EXPLORING,
        financing_type=FinancingType.EVALUATING,
    )
    # timeline exploring(2) + financing evaluating(8) = 10
    assert compute_readiness_score(profile) == 10.0


def test_score_is_clamped_to_100_upper_bound():
    profile = _full_profile(new_id())
    assert compute_readiness_score(profile) <= 100.0


# --- classify_financing_readiness -----------------------------------------


def test_strong_signals_classify_as_ready():
    profile = BuyerProfile(
        lead_id=new_id(),
        locations=("Miraflores",),
        timeline=Timeline.IMMEDIATE,
        financing_type=FinancingType.CASH,
    )
    assert classify_financing_readiness(profile) is FinancingReadiness.READY


def test_mortgage_approved_with_3_months_and_locations_is_ready():
    profile = BuyerProfile(
        lead_id=new_id(),
        locations=("San Borja",),
        timeline=Timeline.THREE_MONTHS,
        financing_type=FinancingType.MORTGAGE_APPROVED,
    )
    assert classify_financing_readiness(profile) is FinancingReadiness.READY


def test_partial_financing_signal_classifies_as_pre_ready():
    profile = BuyerProfile(
        lead_id=new_id(),
        locations=("Surco",),
        financing_type=FinancingType.EVALUATING,
    )
    assert classify_financing_readiness(profile) is FinancingReadiness.PRE_READY


def test_financing_captured_alone_without_support_stays_discovery():
    profile = BuyerProfile(lead_id=new_id(), financing_type=FinancingType.CASH)
    # financing_type alone, with no timeline/locations support, does not meet
    # PRE_READY's "financing_type + one supporting signal" bar either.
    assert classify_financing_readiness(profile) is FinancingReadiness.DISCOVERY


def test_no_financing_signal_classifies_as_discovery():
    profile = BuyerProfile(lead_id=new_id(), locations=("Lima",), timeline=Timeline.IMMEDIATE)
    assert classify_financing_readiness(profile) is FinancingReadiness.DISCOVERY


def test_empty_profile_classifies_as_discovery():
    profile = _empty_profile(new_id())
    assert classify_financing_readiness(profile) is FinancingReadiness.DISCOVERY


# --- LeadReadinessService.evaluate + persistence ---------------------------


async def test_evaluate_persists_readiness_score_and_financing_readiness(
    session_factory, seeded_lead, org_id
):
    async with session_factory() as session:
        profile = BuyerProfile(
            lead_id=seeded_lead,
            locations=("Miraflores",),
            timeline=Timeline.IMMEDIATE,
            financing_type=FinancingType.CASH,
        )
        await BuyerProfileRepository(session).save(org_id, profile)
        await session.commit()

    async with session_factory() as session:
        profile = await BuyerProfileRepository(session).get_by_lead_id(seeded_lead)
        result = await LeadReadinessService(session).evaluate(profile)
        await session.commit()

    assert result.financing_readiness is FinancingReadiness.READY
    # locations(15) + timeline immediate(20) + financing cash(20) = 55
    assert result.readiness_score == 55.0

    async with session_factory() as session:
        from sqlalchemy import select

        from app.modules.lead_qualification.infrastructure.db_models import BuyerProfileORM

        row = (
            await session.execute(
                select(BuyerProfileORM).where(BuyerProfileORM.lead_id == seeded_lead)
            )
        ).scalar_one()
    assert row.readiness_score == result.readiness_score
    assert row.financing_readiness == "ready"


async def test_evaluate_does_not_touch_other_buyer_profile_columns(
    session_factory, seeded_lead, org_id
):
    async with session_factory() as session:
        profile = BuyerProfile(
            lead_id=seeded_lead,
            budget=MoneyRange(minimum=50_000, maximum=80_000),
            property_type=PropertyType.HOUSE,
        )
        await BuyerProfileRepository(session).save(org_id, profile)
        await session.commit()

    async with session_factory() as session:
        profile = await BuyerProfileRepository(session).get_by_lead_id(seeded_lead)
        await LeadReadinessService(session).evaluate(profile)
        await session.commit()

    async with session_factory() as session:
        reloaded = await BuyerProfileRepository(session).get_by_lead_id(seeded_lead)
    assert reloaded.budget == MoneyRange(minimum=50_000, maximum=80_000)
    assert reloaded.property_type is PropertyType.HOUSE


async def test_set_readiness_returns_false_when_no_profile_row_exists(session_factory, seeded_lead):
    async with session_factory() as session:
        created = await BuyerProfileRepository(session).set_readiness(
            seeded_lead,
            readiness_score=42.0,
            financing_readiness=FinancingReadiness.PRE_READY,
        )
    assert created is False


async def test_lead_score_and_classification_unaffected_by_readiness_evaluation(
    session_factory, seeded_lead, org_id
):
    async with session_factory() as session:
        profile = BuyerProfile(
            lead_id=seeded_lead,
            locations=("Miraflores",),
            timeline=Timeline.IMMEDIATE,
            financing_type=FinancingType.CASH,
        )
        await BuyerProfileRepository(session).save(org_id, profile)
        await session.commit()

    async with session_factory() as session:
        profile = await BuyerProfileRepository(session).get_by_lead_id(seeded_lead)
        await LeadReadinessService(session).evaluate(profile)
        await session.commit()

    async with session_factory() as session:
        lead = await LeadRepository(session).get(seeded_lead)
    # US-209 Hot/Warm/Cold fields untouched by US-214.
    assert lead.lead_score == 0.0
    assert lead.lead_classification.value == "hot"
