"""Qualification Flow extractors (US-202-US-205): one happy-path + one
rejection/no-signal case per dimension, plus tenant isolation and the
None-never-erases invariant on `BuyerProfile.apply`."""

import pytest

from app.modules.lead_qualification.application.lead_sync import LeadNotFoundError
from app.modules.lead_qualification.application.profile_capture import (
    BuyerProfileCaptureService,
)
from app.modules.lead_qualification.application.qualification_flow import (
    _REPROMPT_BUDGET,
    extract_budget,
    extract_financing_and_decision_mode,
    extract_locations,
    extract_motivation,
    extract_property_type,
    extract_timeline_and_must_haves,
)
from app.modules.lead_qualification.domain.models import (
    BuyerProfile,
    DecisionMakerMode,
    FinancingType,
    Lead,
    Motivation,
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


async def test_extract_budget_single_amount_with_currency_word(
    session_factory, seeded_lead, org_id
):
    async with session_factory() as session:
        result = await extract_budget(
            session,
            lead_id=seeded_lead,
            organization_id=org_id,
            text="Tengo un presupuesto de 150000 dolares",
        )
        await session.commit()
    assert isinstance(result, ProfilePatch)
    assert result.budget == MoneyRange(minimum=150000.0, maximum=150000.0)


async def test_extract_budget_range_with_currency_symbol(session_factory, seeded_lead, org_id):
    async with session_factory() as session:
        result = await extract_budget(
            session,
            lead_id=seeded_lead,
            organization_id=org_id,
            text="Mi presupuesto es entre $100,000 y $150,000",
        )
        await session.commit()
    assert isinstance(result, ProfilePatch)
    assert result.budget == MoneyRange(minimum=100000.0, maximum=150000.0)


async def test_extract_budget_range_with_soles_symbol(session_factory, seeded_lead, org_id):
    async with session_factory() as session:
        result = await extract_budget(
            session,
            lead_id=seeded_lead,
            organization_id=org_id,
            text="Cuento con S/ 200,000 soles disponibles para la compra",
        )
        await session.commit()
    assert isinstance(result, ProfilePatch)
    assert result.budget == MoneyRange(minimum=200000.0, maximum=200000.0)


async def test_extract_budget_invalid_amount_reprompts_instead_of_raising(
    session_factory, seeded_lead, org_id
):
    async with session_factory() as session:
        result = await extract_budget(
            session,
            lead_id=seeded_lead,
            organization_id=org_id,
            text="Mi presupuesto es 0",
        )
    assert result == _REPROMPT_BUDGET


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


async def test_extract_property_type_ambiguous_message_captures_first_mention(
    session_factory, seeded_lead, org_id
):
    """'casa o departamento, lo que salga primero' — the DoD leaves ambiguous
    two-type messages to the 'first mention wins' rule already implemented,
    documented here with a second phrasing distinct from the happy-path test
    above (which mentions type twice, not two different types)."""
    async with session_factory() as session:
        result = await extract_property_type(
            session,
            lead_id=seeded_lead,
            organization_id=org_id,
            text="casa o departamento, lo que salga primero",
        )
    assert isinstance(result, ProfilePatch)
    assert result.property_type is PropertyType.HOUSE


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


async def test_must_haves_deduplicates_within_one_message(session_factory, seeded_lead, org_id):
    async with session_factory() as session:
        result = await extract_timeline_and_must_haves(
            session,
            lead_id=seeded_lead,
            organization_id=org_id,
            text="Es indispensable que tenga cochera, Cochera y balcón",
        )
        await session.commit()
    assert isinstance(result, ProfilePatch)
    assert result.must_haves == ("cochera", "balcón")


async def test_timeline_and_must_haves_persist_independently_across_turns(
    session_factory, seeded_lead, org_id
):
    """US-205 DoD: timeline/must_haves each captured in a separate turn must
    not erase the other — complements
    test_none_field_never_erases_previously_captured_value, which covers
    cross-dimension (locations vs. timeline), by covering the two fields this
    HU itself owns."""
    async with session_factory() as session:
        first = await extract_timeline_and_must_haves(
            session,
            lead_id=seeded_lead,
            organization_id=org_id,
            text="Es indispensable que tenga cochera",
        )
        await session.commit()
    assert isinstance(first, ProfilePatch)
    assert first.must_haves == ("cochera",)
    assert first.timeline is None

    async with session_factory() as session:
        second = await extract_timeline_and_must_haves(
            session,
            lead_id=seeded_lead,
            organization_id=org_id,
            text="Quiero comprar en 6 meses",
        )
        await session.commit()
    assert isinstance(second, ProfilePatch)
    assert second.timeline is Timeline.SIX_MONTHS
    assert second.must_haves is None

    async with session_factory() as session:
        profile = await BuyerProfileRepository(session).get_by_lead_id(seeded_lead)
    assert profile.timeline is Timeline.SIX_MONTHS
    assert profile.must_haves == ("cochera",)


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


# --- financing_type / decision_maker_mode (US-208) ---------------------


async def test_extract_financing_and_decision_mode_both_in_one_message(
    session_factory, seeded_lead, org_id
):
    async with session_factory() as session:
        result = await extract_financing_and_decision_mode(
            session,
            lead_id=seeded_lead,
            organization_id=org_id,
            text="Vamos a comprar en pareja, con crédito hipotecario",
        )
        await session.commit()
    assert isinstance(result, ProfilePatch)
    assert result.financing_type is FinancingType.MORTGAGE_APPROVED
    assert result.decision_maker_mode is DecisionMakerMode.COUPLE

    async with session_factory() as session:
        profile = await BuyerProfileRepository(session).get_by_lead_id(seeded_lead)
    assert "financing_type" in profile.captured_dimensions()
    assert "decision_maker_mode" in profile.captured_dimensions()


async def test_extract_financing_cash_only(session_factory, seeded_lead, org_id):
    async with session_factory() as session:
        result = await extract_financing_and_decision_mode(
            session,
            lead_id=seeded_lead,
            organization_id=org_id,
            text="Voy a pagar al contado",
        )
        await session.commit()
    assert isinstance(result, ProfilePatch)
    assert result.financing_type is FinancingType.CASH
    assert result.decision_maker_mode is None


async def test_extract_decision_mode_solo_only(session_factory, seeded_lead, org_id):
    async with session_factory() as session:
        result = await extract_financing_and_decision_mode(
            session,
            lead_id=seeded_lead,
            organization_id=org_id,
            text="Decido solo, sin nadie más",
        )
        await session.commit()
    assert isinstance(result, ProfilePatch)
    assert result.decision_maker_mode is DecisionMakerMode.SOLO
    assert result.financing_type is None


async def test_extract_financing_and_decision_mode_no_signal(
    session_factory, seeded_lead, org_id
):
    async with session_factory() as session:
        result = await extract_financing_and_decision_mode(
            session,
            lead_id=seeded_lead,
            organization_id=org_id,
            text="Hola, buenas tardes",
        )
    assert result is None


async def test_financing_and_decision_mode_cross_tenant_extraction_is_rejected(
    session_factory, seeded_lead
):
    other_org_id = new_id()
    async with session_factory() as session:
        with pytest.raises(LeadNotFoundError):
            await extract_financing_and_decision_mode(
                session,
                lead_id=seeded_lead,
                organization_id=other_org_id,
                text="Voy a pagar al contado",
            )


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


# --- motivation (US-219) --------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Me voy a mudar pronto y necesito un lugar nuevo", Motivation.RELOCATION),
        ("Estoy buscando un departamento para invertir", Motivation.INVESTMENT),
        ("Quiero una casa de playa para vacacionar", Motivation.VACATION),
        ("Es mi primera vivienda, estoy nervioso", Motivation.FIRST_HOME),
    ],
)
async def test_extract_motivation_happy_path(
    session_factory, seeded_lead, org_id, text, expected
):
    async with session_factory() as session:
        result = await extract_motivation(
            session,
            lead_id=seeded_lead,
            organization_id=org_id,
            text=text,
        )
        await session.commit()
    assert isinstance(result, ProfilePatch)
    assert result.motivation is expected

    async with session_factory() as session:
        profile = await BuyerProfileRepository(session).get_by_lead_id(seeded_lead)
    assert "motivation" in profile.captured_dimensions()
    assert profile.motivation is expected


async def test_extract_motivation_no_signal(session_factory, seeded_lead, org_id):
    async with session_factory() as session:
        result = await extract_motivation(
            session,
            lead_id=seeded_lead,
            organization_id=org_id,
            text="Hola, buenas tardes",
        )
    assert result is None


async def test_extract_motivation_cross_tenant_extraction_is_rejected(
    session_factory, seeded_lead
):
    other_org_id = new_id()
    async with session_factory() as session:
        with pytest.raises(LeadNotFoundError):
            await extract_motivation(
                session,
                lead_id=seeded_lead,
                organization_id=other_org_id,
                text="Me voy a mudar pronto",
            )


# --- adaptive Nivel 2 questions by property_type (US-219) ---------------


def test_missing_dimensions_excludes_bedrooms_for_land():
    profile = BuyerProfile(lead_id=new_id(), property_type=PropertyType.LAND)
    assert "bedrooms" not in profile.missing_dimensions()


def test_missing_dimensions_excludes_bedrooms_for_commercial():
    profile = BuyerProfile(lead_id=new_id(), property_type=PropertyType.COMMERCIAL)
    assert "bedrooms" not in profile.missing_dimensions()


def test_missing_dimensions_keeps_bedrooms_for_apartment_and_house():
    for property_type in (PropertyType.APARTMENT, PropertyType.HOUSE):
        profile = BuyerProfile(lead_id=new_id(), property_type=property_type)
        assert "bedrooms" in profile.missing_dimensions()


def test_missing_dimensions_keeps_bedrooms_when_property_type_unknown():
    profile = BuyerProfile(lead_id=new_id())
    assert "bedrooms" in profile.missing_dimensions()


def test_completeness_reaches_100_without_bedrooms_for_land():
    profile = BuyerProfile(
        lead_id=new_id(),
        property_type=PropertyType.LAND,
        budget=MoneyRange(minimum=100000, maximum=150000),
        locations=("Surco",),
        timeline=Timeline.IMMEDIATE,
        must_haves=("cochera",),
        financing_type=FinancingType.CASH,
        decision_maker_mode=DecisionMakerMode.SOLO,
        motivation=Motivation.INVESTMENT,
    )
    # every dimension except bedrooms is captured, and bedrooms is
    # inapplicable for LAND, so completeness must reach 100%.
    assert profile.completeness() == 100.0
    assert profile.missing_dimensions() == ()


def test_completeness_unaffected_for_apartment():
    profile = BuyerProfile(
        lead_id=new_id(),
        property_type=PropertyType.APARTMENT,
        budget=MoneyRange(minimum=100000, maximum=150000),
    )
    # 2 of 9 dimensions captured (property_type + budget), none excluded.
    assert profile.completeness() == pytest.approx(200.0 / 9.0)
