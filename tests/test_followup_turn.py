"""US-222: the follow-up turn asks for the first missing Nivel 2 dimension
(timeline/financing_type/decision_maker_mode) once the lead has selected a
specific recommended property. Follows the same seeding/harness conventions
as tests/test_deepening_turn.py."""

from __future__ import annotations

import pytest

from app.modules.conversation_ownership.application.followup_turn import (
    _FOLLOWUP_QUESTIONS,
    run_followup_turn,
)
from app.modules.conversation_ownership.domain.models import Conversation
from app.modules.lead_qualification.domain.models import (
    BuyerProfile,
    DecisionMakerMode,
    FinancingType,
    Lead,
    Timeline,
)
from app.modules.lead_qualification.infrastructure.repository import (
    BuyerProfileRepository,
    LeadRepository,
)
from app.modules.organization.infrastructure.db_models import OrganizationORM
from app.modules.recommendation.infrastructure.db_models import PropertyORM, RecommendationORM
from app.modules.recommendation.infrastructure.repository import RecommendationRepository
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


@pytest.fixture
async def seeded_lead(session_factory, seeded_org):
    lead_id = new_id()
    async with session_factory() as session:
        lead = Lead(
            id=lead_id,
            organization_id=seeded_org,
            crm_lead_id="lead-222",
            contact_reference="+51999888777",
        )
        await LeadRepository(session).add(lead)
        await session.commit()
    return lead_id


async def _seed_property(session_factory, org_id, *, external_id: str):
    property_id = new_id()
    async with session_factory() as session:
        session.add(
            PropertyORM(
                id=property_id,
                organization_id=org_id,
                external_id=external_id,
                price=250000.0,
                zone="Miraflores",
                property_type="apartment",
                features=[],
                description="",
                name_address=f"Av. {external_id} 123",
                estado="disponible",
                link_references=[],
                updated_at=utcnow(),
            )
        )
        await session.commit()
    return property_id


async def _seed_batch(session_factory, org_id, lead_id, property_ids, *, generated_at=None):
    generated_at = generated_at or utcnow()
    async with session_factory() as session:
        for rank, property_id in enumerate(property_ids, start=1):
            session.add(
                RecommendationORM(
                    id=new_id(),
                    organization_id=org_id,
                    lead_id=lead_id,
                    buyer_profile_id=None,
                    property_id=property_id,
                    rank=rank,
                    score=1.0 - (rank * 0.1),
                    signals=[],
                    explanation="matches budget and zone",
                    neighborhood=None,
                    feedback=None,
                    generated_at=generated_at,
                    delivered_at=None,
                )
            )
        await session.commit()
    return generated_at


async def _mark_selected(session_factory, lead_id, property_id, generated_at):
    async with session_factory() as session:
        await RecommendationRepository(session).mark_selected(lead_id, property_id, generated_at)
        await session.commit()


async def _save_profile(session_factory, org_id, profile):
    async with session_factory() as session:
        await BuyerProfileRepository(session).save(org_id, profile)
        await session.commit()


def _make_conversation(org_id, lead_id):
    conversation = Conversation(organization_id=org_id, chatwoot_conversation_id="222")
    conversation.link_lead(lead_id)
    return conversation


async def test_not_applicable_when_no_lead_linked(session_factory, seeded_org):
    async with session_factory() as session:
        conversation = Conversation(organization_id=seeded_org, chatwoot_conversation_id="222")
        result = await run_followup_turn(session, conversation=conversation, text="en 3 meses")
    assert result.outcome == "not_applicable"


async def test_not_applicable_when_no_recommendation_exists(
    session_factory, seeded_org, seeded_lead
):
    async with session_factory() as session:
        conversation = _make_conversation(seeded_org, seeded_lead)
        result = await run_followup_turn(session, conversation=conversation, text="en 3 meses")
    assert result.outcome == "not_applicable"


async def test_not_applicable_when_no_selection_made_yet(session_factory, seeded_org, seeded_lead):
    """No property selected yet for the latest batch -- that's
    `deepening_turn`'s job, not this one's."""
    prop1 = await _seed_property(session_factory, seeded_org, external_id="prop-1")
    prop2 = await _seed_property(session_factory, seeded_org, external_id="prop-2")
    await _seed_batch(session_factory, seeded_org, seeded_lead, [prop1, prop2])

    async with session_factory() as session:
        conversation = _make_conversation(seeded_org, seeded_lead)
        result = await run_followup_turn(session, conversation=conversation, text="en 3 meses")
    assert result.outcome == "not_applicable"


async def test_asks_first_missing_nivel_2_dimension_after_selection(
    session_factory, seeded_org, seeded_lead
):
    prop1 = await _seed_property(session_factory, seeded_org, external_id="prop-1")
    prop2 = await _seed_property(session_factory, seeded_org, external_id="prop-2")
    generated_at = await _seed_batch(session_factory, seeded_org, seeded_lead, [prop1, prop2])
    await _mark_selected(session_factory, seeded_lead, prop1, generated_at)
    await _save_profile(session_factory, seeded_org, BuyerProfile(lead_id=seeded_lead))

    async with session_factory() as session:
        conversation = _make_conversation(seeded_org, seeded_lead)
        result = await run_followup_turn(session, conversation=conversation, text="gracias")
    assert result.outcome == "asked"
    assert result.response == _FOLLOWUP_QUESTIONS["timeline"]


async def test_asks_second_missing_dimension_once_first_is_captured(
    session_factory, seeded_org, seeded_lead
):
    prop1 = await _seed_property(session_factory, seeded_org, external_id="prop-1")
    prop2 = await _seed_property(session_factory, seeded_org, external_id="prop-2")
    generated_at = await _seed_batch(session_factory, seeded_org, seeded_lead, [prop1, prop2])
    await _mark_selected(session_factory, seeded_lead, prop1, generated_at)
    await _save_profile(
        session_factory, seeded_org, BuyerProfile(lead_id=seeded_lead, timeline=Timeline.IMMEDIATE)
    )

    async with session_factory() as session:
        conversation = _make_conversation(seeded_org, seeded_lead)
        result = await run_followup_turn(session, conversation=conversation, text="gracias")
    assert result.outcome == "asked"
    assert result.response == _FOLLOWUP_QUESTIONS["financing_type"]


async def test_not_applicable_once_all_nivel_2_dimensions_captured(
    session_factory, seeded_org, seeded_lead
):
    prop1 = await _seed_property(session_factory, seeded_org, external_id="prop-1")
    prop2 = await _seed_property(session_factory, seeded_org, external_id="prop-2")
    generated_at = await _seed_batch(session_factory, seeded_org, seeded_lead, [prop1, prop2])
    await _mark_selected(session_factory, seeded_lead, prop1, generated_at)
    await _save_profile(
        session_factory,
        seeded_org,
        BuyerProfile(
            lead_id=seeded_lead,
            timeline=Timeline.IMMEDIATE,
            financing_type=FinancingType.CASH,
            decision_maker_mode=DecisionMakerMode.SOLO,
        ),
    )

    async with session_factory() as session:
        conversation = _make_conversation(seeded_org, seeded_lead)
        result = await run_followup_turn(session, conversation=conversation, text="gracias")
    assert result.outcome == "not_applicable"


def test_followup_questions_cover_exactly_the_nivel_2_dimensions():
    assert set(_FOLLOWUP_QUESTIONS) == {"timeline", "financing_type", "decision_maker_mode"}
