"""Chatwoot Webhook Adapter (inbound ACL): translates message_created payloads
into MessageReceived outbox events, archives the raw message (E10 corpus) and
acks immediately; re-deliveries and non-lead events are no-ops."""

import pytest
from sqlalchemy import select

from app.modules.conversation_ownership.infrastructure.db_models import (
    ArchivedMessageORM,
    ConversationORM,
)
from app.modules.organization.infrastructure.db_models import OrganizationORM
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


def _payload(message_id: int = 1001, text: str = "Hola, busco depto") -> dict:
    return {
        "event": "message_created",
        "id": message_id,
        "content": text,
        "message_type": "incoming",
        "private": False,
        "created_at": 1751830000,
        "sender": {"name": "Lead Pérez"},
        "conversation": {"id": 42, "channel": "Channel::Whatsapp"},
    }


@pytest.mark.asyncio
async def test_incoming_message_creates_conversation_and_outbox_event(
    client, session_factory, seeded_org
):
    response = await client.post(f"/api/v1/webhooks/chatwoot/{seeded_org}", json=_payload())
    assert response.status_code == 200
    assert response.json()["status"] == "accepted"

    async with session_factory() as session:
        convo = (await session.execute(select(ConversationORM))).scalar_one()
        assert convo.chatwoot_conversation_id == "42"
        assert convo.state == "New"
        assert convo.channel == "whatsapp"

        archived = (await session.execute(select(ArchivedMessageORM))).scalar_one()
        assert archived.content == "Hola, busco depto"
        assert archived.raw_payload["event"] == "message_created"

        event = (
            await session.execute(
                select(OutboxEventORM).where(OutboxEventORM.event_type == "MessageReceived")
            )
        ).scalar_one()
        assert event.payload["fields"]["text"] == "Hola, busco depto"
        assert event.payload["organization_id"] == str(seeded_org)


@pytest.mark.asyncio
async def test_redelivered_webhook_is_idempotent(client, session_factory, seeded_org):
    first = await client.post(f"/api/v1/webhooks/chatwoot/{seeded_org}", json=_payload())
    assert first.json()["status"] == "accepted"
    second = await client.post(f"/api/v1/webhooks/chatwoot/{seeded_org}", json=_payload())
    assert second.json()["status"] == "duplicate"

    async with session_factory() as session:
        events = (
            (
                await session.execute(
                    select(OutboxEventORM).where(OutboxEventORM.event_type == "MessageReceived")
                )
            )
            .scalars()
            .all()
        )
        assert len(events) == 1  # no duplicate MessageReceived


@pytest.mark.asyncio
async def test_outgoing_and_private_messages_are_ignored(client, seeded_org):
    outgoing = _payload()
    outgoing["message_type"] = "outgoing"
    response = await client.post(f"/api/v1/webhooks/chatwoot/{seeded_org}", json=outgoing)
    assert response.json()["status"] == "ignored"

    note = _payload()
    note["private"] = True
    response = await client.post(f"/api/v1/webhooks/chatwoot/{seeded_org}", json=note)
    assert response.json()["status"] == "ignored"


@pytest.mark.asyncio
async def test_unknown_organization_is_rejected(client, session_factory):
    response = await client.post(f"/api/v1/webhooks/chatwoot/{new_id()}", json=_payload())
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_second_message_touches_existing_conversation(client, session_factory, seeded_org):
    await client.post(f"/api/v1/webhooks/chatwoot/{seeded_org}", json=_payload(message_id=1))
    await client.post(
        f"/api/v1/webhooks/chatwoot/{seeded_org}", json=_payload(message_id=2, text="¿precio?")
    )
    async with session_factory() as session:
        conversations = (await session.execute(select(ConversationORM))).scalars().all()
        assert len(conversations) == 1
        archived = (await session.execute(select(ArchivedMessageORM))).scalars().all()
        assert len(archived) == 2
