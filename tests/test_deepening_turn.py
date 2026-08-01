"""US-220: the deepening turn confirms which Top-3 option interested the lead
before a scheduling slot is trusted to resolve a specific property. Follows
the same seeding/harness conventions as tests/test_scheduling_turn.py."""

from __future__ import annotations

import pytest

from app.modules.conversation_ownership.application.deepening_turn import (
    DEEPENING_QUESTION,
    extract_selected_rank,
    run_deepening_turn,
)
from app.modules.conversation_ownership.domain.models import Conversation
from app.modules.lead_qualification.domain.models import Lead
from app.modules.lead_qualification.infrastructure.repository import LeadRepository
from app.modules.organization.infrastructure.db_models import OrganizationORM
from app.modules.recommendation.infrastructure.db_models import PropertyORM, RecommendationORM
from app.shared.domain.base import new_id, utcnow

# --- extract_selected_rank ---------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("me quedo con la segunda", 2),
        ("me gusta la primera opción", 1),
        ("prefiero la tercera", 3),
        ("la opción 3 me encantó", 3),
        ("me interesa la opcion 1", 1),
        ("número 2 por favor", 2),
        ("numero 2 por favor", 2),
        ("la 2 se ve bien", 2),
        ("2", 2),
        ("  3  ", 3),
        ("el segundo depa", 2),
    ],
)
def test_extract_selected_rank_recognizes_option_references(text, expected):
    assert extract_selected_rank(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "¿tiene cochera?",
        "quiero comprar un departamento",
        "",
        "tengo 2 hijos y busco 3 dormitorios extra",  # no option-reference phrase
        "me interesan opciones 1 y 2",
    ],
)
def test_extract_selected_rank_returns_none_without_a_clear_reference(text):
    assert extract_selected_rank(text) is None


def test_deepening_question_asks_which_option_without_inventing_data():
    assert "opciones" in DEEPENING_QUESTION.lower() or "opción" in DEEPENING_QUESTION.lower()


# --- run_deepening_turn -------------------------------------------------------


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
            crm_lead_id="lead-220",
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
    """Seeds one recommendation batch (same `generated_at`) with `rank`
    1..N in `property_ids` order — mirrors a real Top-N delivery."""
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


def _make_conversation(org_id, lead_id):
    conversation = Conversation(organization_id=org_id, chatwoot_conversation_id="220")
    conversation.link_lead(lead_id)
    return conversation


async def test_not_applicable_when_no_lead_linked(session_factory, seeded_org):
    async with session_factory() as session:
        conversation = Conversation(organization_id=seeded_org, chatwoot_conversation_id="220")
        result = await run_deepening_turn(session, conversation=conversation, text="la segunda")
    assert result.outcome == "not_applicable"


async def test_not_applicable_when_no_recommendation_exists(
    session_factory, seeded_org, seeded_lead
):
    async with session_factory() as session:
        conversation = _make_conversation(seeded_org, seeded_lead)
        result = await run_deepening_turn(session, conversation=conversation, text="la segunda")
    assert result.outcome == "not_applicable"


async def test_not_applicable_with_a_single_property_batch(
    session_factory, seeded_org, seeded_lead
):
    """A single-property recommendation has nothing to deepen on (design.md
    Decision 1) — this is also what keeps every existing single-item
    scheduling-turn fixture untouched by this change."""
    property_id = await _seed_property(session_factory, seeded_org, external_id="prop-1")
    await _seed_batch(session_factory, seeded_org, seeded_lead, [property_id])

    async with session_factory() as session:
        conversation = _make_conversation(seeded_org, seeded_lead)
        result = await run_deepening_turn(
            session, conversation=conversation, text="¿tiene cochera?"
        )
    assert result.outcome == "not_applicable"


async def test_asks_deepening_question_on_a_multi_item_batch_with_no_option_named(
    session_factory, seeded_org, seeded_lead
):
    prop1 = await _seed_property(session_factory, seeded_org, external_id="prop-1")
    prop2 = await _seed_property(session_factory, seeded_org, external_id="prop-2")
    prop3 = await _seed_property(session_factory, seeded_org, external_id="prop-3")
    await _seed_batch(session_factory, seeded_org, seeded_lead, [prop1, prop2, prop3])

    async with session_factory() as session:
        conversation = _make_conversation(seeded_org, seeded_lead)
        result = await run_deepening_turn(
            session, conversation=conversation, text="me gustaron todas, no sé cuál elegir"
        )
    assert result.outcome == "asked"
    assert result.response == DEEPENING_QUESTION


async def test_not_applicable_when_message_already_carries_a_slot(
    session_factory, seeded_org, seeded_lead
):
    """design.md Decision 4: a lead who jumps straight to a slot must not be
    blocked by the deepening question — `run_scheduling_turn`'s own rank-1
    fallback still applies."""
    prop1 = await _seed_property(session_factory, seeded_org, external_id="prop-1")
    prop2 = await _seed_property(session_factory, seeded_org, external_id="prop-2")
    await _seed_batch(session_factory, seeded_org, seeded_lead, [prop1, prop2])

    async with session_factory() as session:
        conversation = _make_conversation(seeded_org, seeded_lead)
        result = await run_deepening_turn(
            session, conversation=conversation, text="el 15/08 a las 3pm"
        )
    assert result.outcome == "not_applicable"


async def test_records_selection_on_a_recognized_rank_and_does_not_override_reply(
    session_factory, seeded_org, seeded_lead
):
    prop1 = await _seed_property(session_factory, seeded_org, external_id="prop-1")
    prop2 = await _seed_property(session_factory, seeded_org, external_id="prop-2")
    prop3 = await _seed_property(session_factory, seeded_org, external_id="prop-3")
    await _seed_batch(session_factory, seeded_org, seeded_lead, [prop1, prop2, prop3])

    async with session_factory() as session:
        conversation = _make_conversation(seeded_org, seeded_lead)
        result = await run_deepening_turn(
            session, conversation=conversation, text="la opción 2 se ve bien"
        )
        await session.commit()

    assert result.outcome == "selected"
    assert result.selected_property_id == prop2

    async with session_factory() as session:
        rows = await session.execute(
            RecommendationORM.__table__.select().where(RecommendationORM.lead_id == seeded_lead)
        )
        by_property = {row.property_id: row.feedback for row in rows}
    assert by_property[prop2] == {"selected_by_lead": True}
    assert by_property[prop1] is None
    assert by_property[prop3] is None


async def test_out_of_range_rank_falls_back_to_asking_again(
    session_factory, seeded_org, seeded_lead
):
    prop1 = await _seed_property(session_factory, seeded_org, external_id="prop-1")
    prop2 = await _seed_property(session_factory, seeded_org, external_id="prop-2")
    await _seed_batch(session_factory, seeded_org, seeded_lead, [prop1, prop2])

    async with session_factory() as session:
        conversation = _make_conversation(seeded_org, seeded_lead)
        result = await run_deepening_turn(
            session, conversation=conversation, text="me quedo con la opción 4"
        )
    assert result.outcome == "asked"
    assert result.response == DEEPENING_QUESTION


async def test_not_applicable_once_a_selection_already_exists_for_the_batch(
    session_factory, seeded_org, seeded_lead
):
    prop1 = await _seed_property(session_factory, seeded_org, external_id="prop-1")
    prop2 = await _seed_property(session_factory, seeded_org, external_id="prop-2")
    await _seed_batch(session_factory, seeded_org, seeded_lead, [prop1, prop2])

    async with session_factory() as session:
        conversation = _make_conversation(seeded_org, seeded_lead)
        first = await run_deepening_turn(
            session, conversation=conversation, text="la opción 1"
        )
        await session.commit()
    assert first.outcome == "selected"

    async with session_factory() as session:
        conversation = _make_conversation(seeded_org, seeded_lead)
        second = await run_deepening_turn(
            session, conversation=conversation, text="¿tiene cochera la propiedad?"
        )
    assert second.outcome == "not_applicable"
