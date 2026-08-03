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
    """US-215 (recalibrated for US-219's 9-dimension model): `ProfileCompleted`
    must fire exactly once, right when the six Nivel 1 dimensions are
    captured (6/9 ~= 66.67%, above the 65.0 platform-default threshold), not
    on the later Nivel 2 refinement updates."""
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
        completeness_at_nivel_1_complete = await service.update_profile(
            seeded_lead, ProfilePatch(decision_maker_mode=DecisionMakerMode.SOLO)
        )
        # Nivel 2 refinement — must NOT re-publish ProfileCompleted.
        await service.update_profile(seeded_lead, ProfilePatch(bedrooms=2))
        await service.update_profile(
            seeded_lead, ProfilePatch(motivation=Motivation.FIRST_HOME)
        )
        completeness = await service.update_profile(
            seeded_lead, ProfilePatch(must_haves=("cochera",))
        )
        await service.update_profile(seeded_lead, ProfilePatch(locations=("Surco", "Barranco")))
        await session.commit()

    assert completeness_at_nivel_1_complete == pytest.approx(600.0 / 9)
    assert completeness == 100.0
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
        assert events[0].payload["fields"]["completeness"] == pytest.approx(600.0 / 9)


def test_gate_default_threshold_allows_advance_with_all_nivel_1_dimensions():
    """US-215 recalibration (dimensions updated for US-222): with the
    platform-default threshold, the gate opens once all six of ANY 6/9
    dimensions are captured (`completeness()` is dimension-agnostic) — this
    scenario captures the old Nivel 1 set plus decision_maker_mode, still
    6/9, to prove the threshold math itself is unaffected by which
    dimensions they are."""
    profile = BuyerProfile(
        lead_id=new_id(),
        budget=MoneyRange(50, 80),
        locations=("Surco",),
        property_type=PropertyType.HOUSE,
        timeline=Timeline.IMMEDIATE,
        financing_type=FinancingType.CASH,
        decision_maker_mode=DecisionMakerMode.SOLO,
    )
    result = CompletenessGate().can_advance_to_recommendation(profile)
    assert result.can_advance is True
    assert result.completeness == pytest.approx(600.0 / 9)
    assert result.missing_dimension is None


def test_gate_default_threshold_blocks_with_one_nivel_1_dimension_missing():
    """The default threshold must not open one Nivel 1 dimension early:
    5 of 6 Nivel 1 dimensions (5/9 ~= 55.56%) stays below the 65.0 default."""
    profile = BuyerProfile(
        lead_id=new_id(),
        budget=MoneyRange(50, 80),
        locations=("Surco",),
        property_type=PropertyType.HOUSE,
        bedrooms=3,
        motivation=Motivation.FIRST_HOME,
        # must_haves intentionally left uncaptured.
    )
    result = CompletenessGate().can_advance_to_recommendation(profile)
    assert result.can_advance is False
    assert result.completeness == pytest.approx(500.0 / 9)
    assert result.missing_dimension == "must_haves"


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
    """Five of six Nivel 1 dimensions (missing `must_haves`) must NOT
    reach the recalibrated default threshold."""
    profile = BuyerProfile(
        lead_id=new_id(),
        budget=MoneyRange(50, 80),
        locations=("Surco",),
        property_type=PropertyType.HOUSE,
        bedrooms=3,
        motivation=Motivation.FIRST_HOME,
    )
    assert profile.completeness() == pytest.approx(500.0 / 9.0)
    result = CompletenessGate().can_advance_to_recommendation(profile)
    assert result.can_advance is False
    assert result.missing_dimension == "must_haves"


# --- US-208: financing_type / decision_maker_mode dimensions -----------


def test_profile_dimensions_now_has_nine_elements():
    from app.modules.lead_qualification.domain.models import PROFILE_DIMENSIONS

    # US-222 (superseding US-217): Nivel 1 (search-pipeline-relevant)
    # dimensions precede Nivel 2 (post-selection follow-up) dimensions --
    # timeline/financing_type/decision_maker_mode sort last.
    assert PROFILE_DIMENSIONS == (
        "budget",
        "locations",
        "property_type",
        "bedrooms",
        "motivation",
        "must_haves",
        "timeline",
        "financing_type",
        "decision_maker_mode",
    )


# --- US-222 (superseding US-217): Nivel 1 / Nivel 2 precedence ---------


def test_gate_prefers_nivel_1_missing_dimension_over_nivel_2():
    """When both a Nivel 1 (must_haves) and a Nivel 2 (financing_type)
    dimension are missing, the directed question must target Nivel 1 first."""
    profile = BuyerProfile(
        lead_id=new_id(),
        budget=MoneyRange(50, 80),
        locations=("Surco",),
        property_type=PropertyType.HOUSE,
        bedrooms=3,
        motivation=Motivation.FIRST_HOME,
        timeline=Timeline.IMMEDIATE,
        decision_maker_mode=DecisionMakerMode.SOLO,
        # must_haves and financing_type intentionally left uncaptured.
    )
    result = CompletenessGate(threshold=90.0).can_advance_to_recommendation(profile)
    assert result.can_advance is False
    assert result.missing_dimension == "must_haves"


def test_missing_dimensions_lists_nivel_1_before_nivel_2():
    profile = BuyerProfile(lead_id=new_id())
    missing = profile.missing_dimensions()
    nivel_1 = ("budget", "locations", "property_type", "bedrooms", "motivation", "must_haves")
    nivel_2 = ("timeline", "financing_type", "decision_maker_mode")
    last_nivel_1_index = max(missing.index(dim) for dim in nivel_1)
    first_nivel_2_index = min(missing.index(dim) for dim in nivel_2)
    assert last_nivel_1_index < first_nivel_2_index


def test_recommendation_unlocks_on_nivel_1_completion_alone():
    """US-222: the six Nivel 1 dimensions alone (6/9 = 66.7%) cross the 65%
    threshold (US-215) without any Nivel 2 dimension captured."""
    profile = BuyerProfile(
        lead_id=new_id(),
        budget=MoneyRange(50, 80),
        locations=("Surco",),
        property_type=PropertyType.HOUSE,
        bedrooms=3,
        motivation=Motivation.FIRST_HOME,
        must_haves=("jardín",),
        # timeline, financing_type, decision_maker_mode intentionally uncaptured.
    )
    result = CompletenessGate().can_advance_to_recommendation(profile)
    assert result.can_advance is True


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
