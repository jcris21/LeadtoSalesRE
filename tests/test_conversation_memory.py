"""AI-102 — Conversation Memory: free-text style/family-context extraction
into `conversation_memory`, independent of `BuyerProfile`/`PROFILE_DIMENSIONS`."""

import pytest

from app.modules.conversation_memory.application.memory_extraction import (
    extract_conversation_memory,
)
from app.modules.conversation_memory.domain.models import MemoryType
from app.modules.conversation_memory.infrastructure.repository import (
    ConversationMemoryRepository,
)
from app.modules.conversation_ownership.domain.models import Conversation
from app.modules.conversation_ownership.infrastructure.repository import ConversationRepository
from app.modules.lead_qualification.application.profile_capture import (
    BuyerProfileCaptureService,
)
from app.modules.lead_qualification.application.lead_sync import LeadNotFoundError
from app.modules.lead_qualification.domain.models import Lead, MoneyRange, ProfilePatch
from app.modules.lead_qualification.infrastructure.repository import LeadRepository
from app.modules.organization.infrastructure.db_models import OrganizationORM
from app.shared.domain.base import new_id, utcnow


@pytest.fixture
def org_id():
    return new_id()


@pytest.fixture
async def seeded_lead_and_conversation(session_factory, org_id):
    async with session_factory() as session:
        session.add(
            OrganizationORM(id=org_id, name="Org Test", status="active", created_at=utcnow())
        )
        lead = Lead(organization_id=org_id, crm_lead_id="lead-1")
        await LeadRepository(session).add(lead)
        conversation = Conversation(
            organization_id=org_id, chatwoot_conversation_id="42", lead_id=lead.id
        )
        await ConversationRepository(session).add(conversation)
        await session.commit()
    return lead.id, conversation.id


# --- extraction ------------------------------------------------------------


async def test_extract_style_preference_happy_path(session_factory, seeded_lead_and_conversation, org_id):
    lead_id, conversation_id = seeded_lead_and_conversation
    async with session_factory() as session:
        result = await extract_conversation_memory(
            session,
            conversation_id=conversation_id,
            lead_id=lead_id,
            organization_id=org_id,
            text="Busco algo minimalista y luminoso",
        )
        await session.commit()
    assert len(result) == 1
    assert result[0].memory_type is MemoryType.STYLE_PREFERENCE
    assert set(result[0].value["adjectives"]) == {"minimalista", "luminoso"}
    assert result[0].confidence == 0.6

    async with session_factory() as session:
        rows = await ConversationMemoryRepository(session).list_for_lead(lead_id)
    assert len(rows) == 1


async def test_extract_family_context_happy_path(session_factory, seeded_lead_and_conversation, org_id):
    lead_id, conversation_id = seeded_lead_and_conversation
    async with session_factory() as session:
        result = await extract_conversation_memory(
            session,
            conversation_id=conversation_id,
            lead_id=lead_id,
            organization_id=org_id,
            text="Tenemos hijos, son pequeños",
        )
        await session.commit()
    assert len(result) == 1
    assert result[0].memory_type is MemoryType.FAMILY_CONTEXT


async def test_message_with_both_signals_inserts_two_rows(
    session_factory, seeded_lead_and_conversation, org_id
):
    lead_id, conversation_id = seeded_lead_and_conversation
    async with session_factory() as session:
        result = await extract_conversation_memory(
            session,
            conversation_id=conversation_id,
            lead_id=lead_id,
            organization_id=org_id,
            text="Buscamos algo minimalista para nuestra familia, tenemos hijos",
        )
        await session.commit()
    assert len(result) == 2
    types = {obs.memory_type for obs in result}
    assert types == {MemoryType.STYLE_PREFERENCE, MemoryType.FAMILY_CONTEXT}


async def test_no_signal_inserts_nothing(session_factory, seeded_lead_and_conversation, org_id):
    lead_id, conversation_id = seeded_lead_and_conversation
    async with session_factory() as session:
        result = await extract_conversation_memory(
            session,
            conversation_id=conversation_id,
            lead_id=lead_id,
            organization_id=org_id,
            text="Hola, buenas tardes",
        )
    assert result == []


async def test_cross_tenant_extraction_is_rejected(session_factory, seeded_lead_and_conversation):
    lead_id, conversation_id = seeded_lead_and_conversation
    other_org_id = new_id()
    async with session_factory() as session:
        with pytest.raises(LeadNotFoundError):
            await extract_conversation_memory(
                session,
                conversation_id=conversation_id,
                lead_id=lead_id,
                organization_id=other_org_id,
                text="Busco algo minimalista",
            )


async def test_recording_observation_does_not_change_profile_completeness(
    session_factory, seeded_lead_and_conversation, org_id
):
    lead_id, conversation_id = seeded_lead_and_conversation
    async with session_factory() as session:
        service = BuyerProfileCaptureService(session)
        completeness_before = await service.update_profile(
            lead_id, ProfilePatch(budget=MoneyRange(50_000, 80_000))
        )
        await session.commit()

    async with session_factory() as session:
        await extract_conversation_memory(
            session,
            conversation_id=conversation_id,
            lead_id=lead_id,
            organization_id=org_id,
            text="Buscamos algo minimalista",
        )
        await session.commit()

    async with session_factory() as session:
        from app.modules.lead_qualification.infrastructure.repository import (
            BuyerProfileRepository,
        )

        profile = await BuyerProfileRepository(session).get_by_lead_id(lead_id)
    assert profile.completeness() == completeness_before
