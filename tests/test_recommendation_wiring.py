"""Sprint 3 — Recommendation event-bus wiring: ProfileCompleted triggers the
full pipeline (§7.10) and, when a Conversation is already linked to the lead,
delivers the Top-3 via ResponseReady (the same event the Chatwoot sender
already consumes for ordinary conversational replies)."""

import uuid

import pytest
from sqlalchemy import select

import app.modules.recommendation.wiring as recommendation_wiring
from app.modules.conversation_ownership.domain.models import Conversation
from app.modules.conversation_ownership.infrastructure.repository import ConversationRepository
from app.modules.lead_qualification.domain.models import (
    BuyerProfile,
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
from app.modules.recommendation.application.neighborhood_enrichment import (
    NeighborhoodEnrichmentAdapter,
)
from app.modules.recommendation.domain.models import Property, PropertyEmbedding
from app.modules.recommendation.infrastructure.maps_client import FakeMapsClient
from app.modules.recommendation.infrastructure.repository import PropertyRepository
from app.shared.domain.base import new_id, utcnow
from app.shared.infrastructure.db_models import OutboxEventORM


@pytest.fixture
def org_id():
    return new_id()


@pytest.fixture
async def seeded_org(session_factory, org_id):
    async with session_factory() as session:
        session.add(
            OrganizationORM(
                id=org_id, name="Inmobiliaria Test", status="active", created_at=utcnow()
            )
        )
        await session.commit()
    return org_id


@pytest.fixture
async def seeded_lead(session_factory, seeded_org):
    lead = Lead(organization_id=seeded_org, crm_lead_id="crm-1")
    async with session_factory() as session:
        await LeadRepository(session).add(lead)
        await session.commit()
    return lead.id


@pytest.fixture
async def complete_profile(session_factory, seeded_org, seeded_lead):
    profile = BuyerProfile(
        lead_id=seeded_lead,
        budget=MoneyRange(minimum=80_000.0, maximum=120_000.0),
        locations=("Palermo",),
        property_type=PropertyType.APARTMENT,
        timeline=Timeline.IMMEDIATE,
        must_haves=("balcony",),
    )
    async with session_factory() as session:
        await BuyerProfileRepository(session).save(seeded_org, profile)
        await session.commit()
    return profile


@pytest.fixture
async def matching_property(session_factory, seeded_org):
    prop = Property(
        organization_id=seeded_org,
        external_id="p-1",
        price=100_000.0,
        zone="Palermo",
        property_type=PropertyType.APARTMENT,
        features=("balcony",),
    )
    async with session_factory() as session:
        repo = PropertyRepository(session)
        await repo.upsert(prop)
        await repo.save_embedding(
            PropertyEmbedding(property_id=prop.id, vector=(1.0, 1.0, 1.0), model_version="v1"),
            source_hash="hash-1",
        )
        await session.commit()
    return prop.id


@pytest.fixture(autouse=True)
def fake_enrichment_adapter(monkeypatch):
    """Avoid real Google Maps calls: no API key is wired yet, and the wiring
    module's real adapter would otherwise attempt a live HTTP call."""
    adapter = NeighborhoodEnrichmentAdapter(FakeMapsClient())
    monkeypatch.setattr(recommendation_wiring, "_get_enrichment_adapter", lambda: adapter)
    return adapter


def _profile_completed_payload(*, organization_id: uuid.UUID, lead_id: uuid.UUID) -> dict:
    return {
        "organization_id": str(organization_id),
        "fields": {
            "lead_id": str(lead_id),
            "crm_lead_id": "crm-1",
            "completeness": 100.0,
            "profile": {},
        },
    }


@pytest.mark.asyncio
async def test_handle_profile_completed_delivers_top3_to_linked_conversation(
    session_factory, seeded_org, seeded_lead, complete_profile, matching_property
):
    async with session_factory() as session:
        conversation = Conversation(
            organization_id=seeded_org,
            chatwoot_conversation_id="42",
            lead_id=seeded_lead,
        )
        await ConversationRepository(session).add(conversation)
        await session.commit()
        conversation_id = conversation.id

    await recommendation_wiring.handle_profile_completed(
        _profile_completed_payload(organization_id=seeded_org, lead_id=seeded_lead)
    )

    async with session_factory() as session:
        event = (
            await session.execute(
                select(OutboxEventORM).where(OutboxEventORM.event_type == "ResponseReady")
            )
        ).scalar_one()
        assert event.payload["organization_id"] == str(seeded_org)
        assert event.payload["fields"]["chatwoot_conversation_id"] == "42"
        assert event.payload["fields"]["conversation_id"] == str(conversation_id)
        assert "Encontré estas opciones" in event.payload["fields"]["response"]


@pytest.mark.asyncio
async def test_handle_profile_completed_is_a_noop_without_a_linked_conversation(
    session_factory, seeded_org, seeded_lead, complete_profile, matching_property
):
    """The lead may exist before any conversation started — nothing to
    deliver to, and that's expected, not an error."""
    await recommendation_wiring.handle_profile_completed(
        _profile_completed_payload(organization_id=seeded_org, lead_id=seeded_lead)
    )

    async with session_factory() as session:
        events = (
            (await session.execute(select(OutboxEventORM))).scalars().all()
        )
        assert all(event.event_type != "ResponseReady" for event in events)


@pytest.mark.asyncio
async def test_handle_profile_completed_skips_when_profile_is_incomplete(
    session_factory, seeded_org, seeded_lead
):
    """An incomplete BuyerProfile must never reach the pipeline (QA-14),
    even if a (mistaken or stale) ProfileCompleted event fires for it."""
    async with session_factory() as session:
        conversation = Conversation(
            organization_id=seeded_org,
            chatwoot_conversation_id="42",
            lead_id=seeded_lead,
        )
        await ConversationRepository(session).add(conversation)
        await session.commit()

    await recommendation_wiring.handle_profile_completed(
        _profile_completed_payload(organization_id=seeded_org, lead_id=seeded_lead)
    )

    async with session_factory() as session:
        events = (await session.execute(select(OutboxEventORM))).scalars().all()
        assert all(event.event_type != "ResponseReady" for event in events)
