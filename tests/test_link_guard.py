"""US-hallucination-fix defense-in-depth: `guard_reply` is the last gate
before a conversational reply reaches the lead. Any URL it contains must be a
real property link for the organization, or the whole message is swapped for
a safe fallback — this is what should have caught CW-DEMO-1784860599/MSG-0010
even if the grounding/prompt fixes had missed the case."""

from __future__ import annotations

import uuid

import pytest

from app.modules.conversation_ownership.application.link_guard import (
    FALLBACK_REPLY,
    LISTING_FALLBACK_REPLY,
    guard_reply,
)
from app.modules.lead_qualification.domain.models import PropertyType
from app.modules.organization.infrastructure.db_models import OrganizationORM
from app.modules.recommendation.domain.models import Property
from app.modules.recommendation.infrastructure.repository import PropertyRepository
from app.shared.domain.base import new_id, utcnow


@pytest.fixture
def org_id():
    return new_id()


@pytest.fixture
async def seeded_org(session_factory, org_id):
    async with session_factory() as session:
        session.add(OrganizationORM(id=org_id, name="Org Test", status="active", created_at=utcnow()))
        await session.commit()
    return org_id


async def _seed_property(session_factory, org_id, *, link):
    async with session_factory() as session:
        await PropertyRepository(session).upsert(
            Property(
                organization_id=org_id,
                external_id=str(uuid.uuid4()),
                price=100_000.0,
                zone="Miraflores",
                property_type=PropertyType.APARTMENT,
                link_references=(link,),
            )
        )
        await session.commit()


async def test_reply_without_urls_passes_through_unchanged(session_factory, seeded_org):
    async with session_factory() as session:
        result = await guard_reply(
            session, organization_id=seeded_org, reply="¡Claro! Cuéntame qué zona te interesa."
        )
    assert result == "¡Claro! Cuéntame qué zona te interesa."


async def test_reply_with_real_property_link_passes_through(session_factory, seeded_org):
    await _seed_property(session_factory, seeded_org, link="https://demo.realestate/listing/1")

    async with session_factory() as session:
        result = await guard_reply(
            session,
            organization_id=seeded_org,
            reply="Mira esta opción: https://demo.realestate/listing/1",
        )
    assert "https://demo.realestate/listing/1" in result


async def test_reply_with_fabricated_link_is_replaced_with_fallback(session_factory, seeded_org):
    await _seed_property(session_factory, seeded_org, link="https://demo.realestate/listing/1")

    async with session_factory() as session:
        result = await guard_reply(
            session,
            organization_id=seeded_org,
            reply="Mira esta opción: https://fake-listings.example/depto-falso",
        )
    assert result == FALLBACK_REPLY


async def test_reply_with_no_known_properties_at_all_is_replaced(session_factory, seeded_org):
    async with session_factory() as session:
        result = await guard_reply(
            session,
            organization_id=seeded_org,
            reply="Este depto te puede interesar: https://fake-listings.example/depto-falso",
        )
    assert result == FALLBACK_REPLY


async def test_reply_shaped_like_fabricated_listing_is_replaced_even_without_a_url(
    session_factory, seeded_org
):
    """2026-07-25 incident: the LLM invented 3 full listings (price, area,
    address) with no URL at all — the URL check above had nothing to catch."""
    reply = (
        "¡Genial! Aquí tienes tres opciones:\n\n"
        "1. Departamento en Av. Comandante Espinar: USD 250,000, 85 m²\n"
        "2. Departamento en Calle General Mendiburu: USD 280,000, 90 m²\n"
        "3. Departamento en Calle Mártir Olaya: USD 230,000, 80 m²\n"
    )
    async with session_factory() as session:
        result = await guard_reply(session, organization_id=seeded_org, reply=reply)
    assert result == LISTING_FALLBACK_REPLY


async def test_reply_merely_mentioning_the_leads_own_budget_passes_through(
    session_factory, seeded_org
):
    """A single price echoed back (no numbered listing) must not trip the
    heuristic — it's ordinary qualification conversation, not a fabricated
    listing."""
    reply = "Perfecto, con un presupuesto de USD 250,000 puedo afinar la búsqueda."
    async with session_factory() as session:
        result = await guard_reply(session, organization_id=seeded_org, reply=reply)
    assert result == reply


async def test_reply_with_short_numbered_list_but_no_price_passes_through(
    session_factory, seeded_org
):
    """A numbered list alone (e.g. clarifying questions) isn't a listing —
    only numbered items *plus* price/area tokens should trip the guard."""
    reply = "Para afinar la búsqueda dime:\n1. Tu zona preferida\n2. Tu presupuesto aproximado"
    async with session_factory() as session:
        result = await guard_reply(session, organization_id=seeded_org, reply=reply)
    assert result == reply
