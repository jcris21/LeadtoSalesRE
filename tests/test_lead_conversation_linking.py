"""Sprint 3 — Conversation<->Lead identity matching (`LeadLinker`).

Chatwoot and wacrm share no identifier of their own; `contact_reference`
(the WhatsApp phone number) is the sole matching key. These tests cover the
webhook capturing it and `LeadLinker` resolving `Conversation.lead_id` from
it, both when the Lead is already mirrored locally and when it isn't yet."""

import pytest
from sqlalchemy import select

from app.modules.conversation_ownership.application.lead_linker import LeadLinker
from app.modules.conversation_ownership.domain.models import Conversation
from app.modules.conversation_ownership.infrastructure.db_models import ConversationORM
from app.modules.lead_qualification.infrastructure.db_models import LeadORM
from app.modules.organization.infrastructure.db_models import OrganizationORM
from app.shared.domain.base import new_id, utcnow

CONTACT_REFERENCE = "+5491100000000"


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
    lead_id = new_id()
    async with session_factory() as session:
        session.add(
            LeadORM(
                id=lead_id,
                organization_id=seeded_org,
                crm_lead_id="crm-1",
                pipeline_stage="New",
                lead_score=0.0,
                contact_reference=CONTACT_REFERENCE,
                synced_at=utcnow(),
                created_at=utcnow(),
            )
        )
        await session.commit()
    return lead_id


def _payload(message_id: int = 1, phone: str | None = CONTACT_REFERENCE) -> dict:
    sender = {"name": "Lead Pérez"}
    if phone is not None:
        sender["phone_number"] = phone
    return {
        "event": "message_created",
        "id": message_id,
        "content": "Hola, busco depto",
        "message_type": "incoming",
        "private": False,
        "created_at": 1751830000,
        "sender": sender,
        "conversation": {"id": 42, "channel": "Channel::Whatsapp"},
    }


@pytest.mark.asyncio
async def test_webhook_links_conversation_to_lead_when_contact_reference_matches(
    client, session_factory, seeded_org, seeded_lead
):
    response = await client.post(f"/api/v1/webhooks/chatwoot/{seeded_org}", json=_payload())
    assert response.status_code == 200

    async with session_factory() as session:
        convo = (await session.execute(select(ConversationORM))).scalar_one()
        assert convo.contact_reference == CONTACT_REFERENCE
        assert convo.lead_id == seeded_lead


@pytest.mark.asyncio
async def test_webhook_leaves_lead_id_unset_when_no_lead_matches_yet(
    client, session_factory, seeded_org
):
    """The Lead may sync in from wacrm later (§7.7 CDC is eventually
    consistent) — an unresolved link is expected, not an error."""
    response = await client.post(f"/api/v1/webhooks/chatwoot/{seeded_org}", json=_payload())
    assert response.status_code == 200

    async with session_factory() as session:
        convo = (await session.execute(select(ConversationORM))).scalar_one()
        assert convo.contact_reference == CONTACT_REFERENCE
        assert convo.lead_id is None


@pytest.mark.asyncio
async def test_webhook_handles_missing_contact_reference_gracefully(
    client, session_factory, seeded_org
):
    response = await client.post(
        f"/api/v1/webhooks/chatwoot/{seeded_org}", json=_payload(phone=None)
    )
    assert response.status_code == 200

    async with session_factory() as session:
        convo = (await session.execute(select(ConversationORM))).scalar_one()
        assert convo.contact_reference is None
        assert convo.lead_id is None


@pytest.mark.asyncio
async def test_lead_linker_resolves_lead_by_contact_reference(
    session_factory, seeded_org, seeded_lead
):
    async with session_factory() as session:
        conversation = Conversation(
            organization_id=seeded_org,
            chatwoot_conversation_id="99",
            contact_reference=CONTACT_REFERENCE,
        )
        resolved = await LeadLinker(session).link_if_possible(conversation)

    assert resolved == seeded_lead
    assert conversation.lead_id == seeded_lead


@pytest.mark.asyncio
async def test_lead_linker_is_a_noop_when_already_linked(session_factory, seeded_org, seeded_lead):
    other_lead_id = new_id()
    async with session_factory() as session:
        conversation = Conversation(
            organization_id=seeded_org,
            chatwoot_conversation_id="99",
            contact_reference=CONTACT_REFERENCE,
            lead_id=other_lead_id,
        )
        resolved = await LeadLinker(session).link_if_possible(conversation)

    # Already-linked conversations are never re-resolved, even if the
    # contact_reference would now match a different lead.
    assert resolved == other_lead_id
    assert conversation.lead_id == other_lead_id


@pytest.mark.asyncio
async def test_lead_linker_returns_none_without_contact_reference(session_factory, seeded_org):
    async with session_factory() as session:
        conversation = Conversation(
            organization_id=seeded_org, chatwoot_conversation_id="99"
        )
        resolved = await LeadLinker(session).link_if_possible(conversation)

    assert resolved is None
    assert conversation.lead_id is None
