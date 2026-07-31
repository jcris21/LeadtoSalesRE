"""Sprint 2 — BuyerProfile Capture Service (E3, §7.8) + Completeness Gate
(QA-14): progressive profiling one dimension at a time, range validation before
persisting, ProfileCompleted exactly on crossing the threshold, and the gate as
the single point of truth for the Qualification -> Recommendation precondition."""

import pytest
from sqlalchemy import select

from app.modules.lead_qualification.application.completeness_gate import CompletenessGate
from app.modules.lead_qualification.application.profile_capture import (
    BuyerProfileCaptureService,
)
from app.modules.lead_qualification.domain.models import (
    BuyerProfile,
    DecisionMakerMode,
    FinancingType,
    Lead,
    Motivation,
    MoneyRange,
    ProfilePatch,
    ProfileValidationError,
    PropertyType,
    Timeline,
)
from app.modules.lead_qualification.infrastructure.repository import LeadRepository
from app.modules.organization.infrastructure.db_models import OrganizationORM
from app.shared.domain.base import new_id, utcnow
from app.shared.infrastructure.db_models import OutboxEventORM


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


def test_money_range_rejects_invalid_budget():
    with pytest.raises(ProfileValidationError):
        MoneyRange(minimum=0, maximum=100)
    with pytest.raises(ProfileValidationError):
        MoneyRange(minimum=200, maximum=100)


def test_empty_patch_is_rejected():
    with pytest.raises(ProfileValidationError):
        ProfilePatch(locations=())


async def test_progressive_profiling_one_dimension_at_a_time(session_factory, seeded_lead):
    async with session_factory() as session:
        service = BuyerProfileCaptureService(session)
        c1 = await service.update_profile(
            seeded_lead, ProfilePatch(budget=MoneyRange(50_000, 80_000))
        )
        c2 = await service.update_profile(seeded_lead, ProfilePatch(locations=("Miraflores",)))
        await session.commit()
    assert c1 == pytest.approx(100.0 / 9)
    assert c2 == pytest.approx(200.0 / 9)


async def test_profile_completed_fires_exactly_on_crossing_threshold(
    session_factory, seeded_lead
):
    """US-215/217/219: with the recalibrated default threshold (65.0),
    ProfileCompleted fires as soon as the six Nivel 1 dimensions are
    captured — Nivel 2 refinement (bedrooms, motivation, must_haves) is
    captured afterwards and must NOT re-publish the event."""
    async with session_factory() as session:
        service = BuyerProfileCaptureService(session)
        await service.update_profile(seeded_lead, ProfilePatch(budget=MoneyRange(50, 80)))
        await service.update_profile(seeded_lead, ProfilePatch(locations=("Surco",)))
        await service.update_profile(
            seeded_lead, ProfilePatch(property_type=PropertyType.APARTMENT)
        )
        await service.update_profile(seeded_lead, ProfilePatch(timeline=Timeline.THREE_MONTHS))
        await service.update_profile(
            seeded_lead, ProfilePatch(financing_type=FinancingType.CASH)
        )
        completeness = await service.update_profile(
            seeded_lead, ProfilePatch(decision_maker_mode=DecisionMakerMode.SOLO)
        )
        # Nivel 2 refinement after the gate already opened must NOT
        # re-publish ProfileCompleted.
        await service.update_profile(seeded_lead, ProfilePatch(bedrooms=2))
        await service.update_profile(
            seeded_lead, ProfilePatch(motivation=Motivation.FIRST_HOME)
        )
        await service.update_profile(seeded_lead, ProfilePatch(must_haves=("cochera",)))
        await session.commit()

    assert completeness == pytest.approx(600.0 / 9.0)
    async with session_factory() as session:
        events = (
            (
                await session.execute(
                    select(OutboxEventORM).where(OutboxEventORM.event_type == "ProfileCompleted")
                )
            )
            .scalars()
            .all()
        )
        assert len(events) == 1
        assert events[0].payload["fields"]["completeness"] == pytest.approx(600.0 / 9.0)


def test_gate_blocks_incomplete_profile_with_directed_missing_dimension():
    profile = BuyerProfile(lead_id=new_id(), budget=MoneyRange(50, 80), locations=("Surco",))
    result = CompletenessGate(threshold=90.0).can_advance_to_recommendation(profile)
    assert result.can_advance is False
    assert result.completeness == pytest.approx(200.0 / 9)
    assert result.missing_dimension == "property_type"


def test_gate_allows_complete_profile():
    profile = BuyerProfile(
        lead_id=new_id(),
        budget=MoneyRange(50, 80),
        locations=("Surco",),
        property_type=PropertyType.HOUSE,
        timeline=Timeline.IMMEDIATE,
        must_haves=("jardín",),
        financing_type=FinancingType.CASH,
        decision_maker_mode=DecisionMakerMode.SOLO,
        bedrooms=3,
        motivation=Motivation.FIRST_HOME,
    )
    result = CompletenessGate(threshold=90.0).can_advance_to_recommendation(profile)
    assert result.can_advance is True
    assert result.completeness == 100.0
    assert result.missing_dimension is None


def test_gate_opens_at_default_threshold_once_nivel_1_captured():
    """US-215 Gherkin (recalibrated for the final 9-dimension model): the
    platform-default threshold (65.0, set in `app/core/config.py`) must open
    the gate once all six Nivel 1 dimensions are captured, with the Nivel 2
    refinement fields (`must_haves`, `bedrooms`, `motivation`) still empty."""
    profile = BuyerProfile(
        lead_id=new_id(),
        budget=MoneyRange(50, 80),
        locations=("Surco",),
        property_type=PropertyType.HOUSE,
        timeline=Timeline.THREE_MONTHS,
        financing_type=FinancingType.CASH,
        decision_maker_mode=DecisionMakerMode.SOLO,
    )
    assert profile.completeness() == pytest.approx(600.0 / 9.0)
    result = CompletenessGate().can_advance_to_recommendation(profile)
    assert result.can_advance is True
    assert result.missing_dimension is None


def test_gate_stays_closed_at_default_threshold_missing_one_nivel_1_dimension():
    """Five of six Nivel 1 dimensions (missing `decision_maker_mode`) must NOT
    reach the recalibrated default threshold."""
    profile = BuyerProfile(
        lead_id=new_id(),
        budget=MoneyRange(50, 80),
        locations=("Surco",),
        property_type=PropertyType.HOUSE,
        timeline=Timeline.THREE_MONTHS,
        financing_type=FinancingType.CASH,
    )
    assert profile.completeness() == pytest.approx(500.0 / 9.0)
    result = CompletenessGate().can_advance_to_recommendation(profile)
    assert result.can_advance is False
    assert result.missing_dimension == "decision_maker_mode"


# --- US-208: financing_type / decision_maker_mode dimensions -----------


def test_profile_dimensions_now_has_nine_elements():
    from app.modules.lead_qualification.domain.models import PROFILE_DIMENSIONS

    # US-217: Nivel 1 (qualification-blocking) dimensions precede Nivel 2
    # (refinement) dimensions -- must_haves/bedrooms sort last.
    assert PROFILE_DIMENSIONS == (
        "budget",
        "locations",
        "property_type",
        "timeline",
        "financing_type",
        "decision_maker_mode",
        "must_haves",
        "bedrooms",
        "motivation",
    )


# --- US-217: Nivel 1 / Nivel 2 precedence -------------------------------


def test_gate_prefers_nivel_1_missing_dimension_over_nivel_2():
    """When both a Nivel 1 (financing_type) and a Nivel 2 (must_haves)
    dimension are missing, the directed question must target Nivel 1 first."""
    profile = BuyerProfile(
        lead_id=new_id(),
        budget=MoneyRange(50, 80),
        locations=("Surco",),
        property_type=PropertyType.HOUSE,
        timeline=Timeline.IMMEDIATE,
        decision_maker_mode=DecisionMakerMode.SOLO,
        bedrooms=3,
        # must_haves and financing_type intentionally left uncaptured.
    )
    result = CompletenessGate(threshold=90.0).can_advance_to_recommendation(profile)
    assert result.can_advance is False
    assert result.missing_dimension == "financing_type"


def test_missing_dimensions_lists_nivel_1_before_nivel_2():
    profile = BuyerProfile(lead_id=new_id())
    missing = profile.missing_dimensions()
    nivel_1 = ("budget", "locations", "property_type", "timeline", "financing_type", "decision_maker_mode")
    nivel_2 = ("must_haves", "bedrooms")
    last_nivel_1_index = max(missing.index(dim) for dim in nivel_1)
    first_nivel_2_index = min(missing.index(dim) for dim in nivel_2)
    assert last_nivel_1_index < first_nivel_2_index


def test_original_five_dimensions_no_longer_report_full_completeness():
    profile = BuyerProfile(
        lead_id=new_id(),
        budget=MoneyRange(50, 80),
        locations=("Surco",),
        property_type=PropertyType.HOUSE,
        timeline=Timeline.IMMEDIATE,
        must_haves=("jardín",),
    )
    assert profile.completeness() == pytest.approx(500.0 / 9)
    assert profile.completeness() < 100.0
    assert set(profile.missing_dimensions()) == {
        "financing_type",
        "decision_maker_mode",
        "bedrooms",
        "motivation",
    }


def test_captured_dimensions_include_financing_and_decision_mode():
    profile = BuyerProfile(
        lead_id=new_id(),
        financing_type=FinancingType.MORTGAGE_APPROVED,
        decision_maker_mode=DecisionMakerMode.COUPLE,
    )
    assert "financing_type" in profile.captured_dimensions()
    assert "decision_maker_mode" in profile.captured_dimensions()


def test_apply_patch_sets_financing_and_decision_mode():
    profile = BuyerProfile(lead_id=new_id())
    profile.apply(
        ProfilePatch(
            financing_type=FinancingType.EVALUATING,
            decision_maker_mode=DecisionMakerMode.FAMILY,
        )
    )
    assert profile.financing_type is FinancingType.EVALUATING
    assert profile.decision_maker_mode is DecisionMakerMode.FAMILY


def test_apply_with_none_does_not_erase_financing_and_decision_mode():
    profile = BuyerProfile(
        lead_id=new_id(),
        financing_type=FinancingType.CASH,
        decision_maker_mode=DecisionMakerMode.SOLO,
    )
    profile.apply(ProfilePatch(locations=("Barranco",)))
    assert profile.financing_type is FinancingType.CASH
    assert profile.decision_maker_mode is DecisionMakerMode.SOLO
