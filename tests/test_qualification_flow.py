"""Qualification Flow extractors (US-202-US-205): one happy-path + one
rejection/no-signal case per dimension, plus tenant isolation and the
None-never-erases invariant on `BuyerProfile.apply`."""

import pytest

from app.modules.lead_qualification.application.lead_sync import LeadNotFoundError
from app.modules.lead_qualification.application.profile_capture import (
    BuyerProfileCaptureService,
)
from app.modules.lead_qualification.application.qualification_flow import (
    extract_budget,
    extract_locations,
    extract_property_type,
    extract_timeline_and_must_haves,
)
from app.modules.lead_qualification.domain.models import (
    Lead,
    MoneyRange,
    ProfilePatch,
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


# --- budget (US-202) ---------------------------------------------------


async def test_extract_budget_happy_path(session_factory, seeded_lead, org_id):
    async with session_factory() as session:
        result = await extract_budget(
            session,
            lead_id=seeded_lead,
            organization_id=org_id,
            text="Mi presupuesto es entre 100000 y 150000",
        )
        await session.commit()
    assert isinstance(result, ProfilePatch)
    assert result.budget == MoneyRange(minimum=100000.0, maximum=150000.0)

    async with session_factory() as session:
        profile = await BuyerProfileRepository(session).get_by_lead_id(seeded_lead)
    assert "budget" in profile.captured_dimensions()


async def test_extract_budget_no_signal(session_factory, seeded_lead, org_id):
    async with session_factory() as session:
        result = await extract_budget(
            session,
            lead_id=seeded_lead,
            organization_id=org_id,
            text="Quiero un departamento bonito",
        )
    assert result is None


# --- locations (US-203) -------------------------------------------------


async def test_extract_locations_happy_path(session_factory, seeded_lead, org_id):
    async with session_factory() as session:
        result = await extract_locations(
            session,
            lead_id=seeded_lead,
            organization_id=org_id,
            text="Busco algo en Miraflores o Barranco",
        )
        await session.commit()
    assert isinstance(result, ProfilePatch)
    assert set(result.locations) == {"Miraflores", "Barranco"}


async def test_extract_locations_no_signal(session_factory, seeded_lead, org_id):
    async with session_factory() as session:
        result = await extract_locations(
            session,
            lead_id=seeded_lead,
            organization_id=org_id,
            text="No tengo zona en mente todavía",
        )
    assert result is None


# --- property_type (US-204) --------------------------------------------


async def test_extract_property_type_happy_path(session_factory, seeded_lead, org_id):
    async with session_factory() as session:
        result = await extract_property_type(
            session,
            lead_id=seeded_lead,
            organization_id=org_id,
            text="Estoy buscando un depa de 2 dormitorios",
        )
        await session.commit()
    assert isinstance(result, ProfilePatch)
    assert result.property_type is PropertyType.APARTMENT


async def test_extract_property_type_two_mentions_captures_first(
    session_factory, seeded_lead, org_id
):
    async with session_factory() as session:
        result = await extract_property_type(
            session,
            lead_id=seeded_lead,
            organization_id=org_id,
            text="Me interesa una casa, aunque también vería un terreno",
        )
    assert isinstance(result, ProfilePatch)
    assert result.property_type is PropertyType.HOUSE


async def test_extract_property_type_no_signal(session_factory, seeded_lead, org_id):
    async with session_factory() as session:
        result = await extract_property_type(
            session,
            lead_id=seeded_lead,
            organization_id=org_id,
            text="Todavía no sé qué busco",
        )
    assert result is None


# --- timeline / must_haves (US-205) -------------------------------------


async def test_extract_timeline_and_must_haves_both_in_one_message(
    session_factory, seeded_lead, org_id
):
    async with session_factory() as session:
        result = await extract_timeline_and_must_haves(
            session,
            lead_id=seeded_lead,
            organization_id=org_id,
            text="Quiero comprar en 3 meses, indispensable que tenga cochera, ascensor",
        )
        await session.commit()
    assert isinstance(result, ProfilePatch)
    assert result.timeline is Timeline.THREE_MONTHS
    assert result.must_haves == ("cochera", "ascensor")


async def test_extract_timeline_and_must_haves_no_signal(session_factory, seeded_lead, org_id):
    async with session_factory() as session:
        result = await extract_timeline_and_must_haves(
            session,
            lead_id=seeded_lead,
            organization_id=org_id,
            text="Hola, buenas tardes",
        )
    assert result is None


async def test_none_field_never_erases_previously_captured_value(
    session_factory, seeded_lead, org_id
):
    async with session_factory() as session:
        service = BuyerProfileCaptureService(session)
        await service.update_profile(seeded_lead, ProfilePatch(locations=("Surco",)))
        await session.commit()

    async with session_factory() as session:
        result = await extract_timeline_and_must_haves(
            session,
            lead_id=seeded_lead,
            organization_id=org_id,
            text="Quiero comprar en 6 meses",
        )
        await session.commit()
    assert isinstance(result, ProfilePatch)

    async with session_factory() as session:
        profile = await BuyerProfileRepository(session).get_by_lead_id(seeded_lead)
    assert profile.locations == ("Surco",)
    assert profile.timeline is not None


# --- tenant isolation ----------------------------------------------------


async def test_cross_tenant_extraction_is_rejected(session_factory, seeded_lead):
    other_org_id = new_id()
    async with session_factory() as session:
        with pytest.raises(LeadNotFoundError):
            await extract_budget(
                session,
                lead_id=seeded_lead,
                organization_id=other_org_id,
                text="Mi presupuesto es 100000",
            )
