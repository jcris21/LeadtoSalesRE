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
    Lead,
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
    assert c1 == 20.0
    assert c2 == 40.0


async def test_profile_completed_fires_exactly_on_crossing_threshold(
    session_factory, seeded_lead
):
    async with session_factory() as session:
        service = BuyerProfileCaptureService(session)
        await service.update_profile(seeded_lead, ProfilePatch(budget=MoneyRange(50, 80)))
        await service.update_profile(seeded_lead, ProfilePatch(locations=("Surco",)))
        await service.update_profile(
            seeded_lead, ProfilePatch(property_type=PropertyType.APARTMENT)
        )
        await service.update_profile(seeded_lead, ProfilePatch(timeline=Timeline.THREE_MONTHS))
        completeness = await service.update_profile(
            seeded_lead, ProfilePatch(must_haves=("cochera",))
        )
        # A further refinement must NOT re-publish ProfileCompleted.
        await service.update_profile(seeded_lead, ProfilePatch(locations=("Surco", "Barranco")))
        await session.commit()

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
        assert events[0].payload["fields"]["completeness"] == 100.0


def test_gate_blocks_incomplete_profile_with_directed_missing_dimension():
    profile = BuyerProfile(lead_id=new_id(), budget=MoneyRange(50, 80), locations=("Surco",))
    result = CompletenessGate(threshold=90.0).can_advance_to_recommendation(profile)
    assert result.can_advance is False
    assert result.completeness == 40.0
    assert result.missing_dimension == "property_type"


def test_gate_allows_complete_profile():
    profile = BuyerProfile(
        lead_id=new_id(),
        budget=MoneyRange(50, 80),
        locations=("Surco",),
        property_type=PropertyType.HOUSE,
        timeline=Timeline.IMMEDIATE,
        must_haves=("jardín",),
    )
    result = CompletenessGate(threshold=90.0).can_advance_to_recommendation(profile)
    assert result.can_advance is True
    assert result.completeness == 100.0
    assert result.missing_dimension is None
