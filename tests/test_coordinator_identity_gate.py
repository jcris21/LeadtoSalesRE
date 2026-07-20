"""G8 (docs/e2e-manual-chat-checklist.md): leads are born in the chat itself.
While a conversation has no linked Lead the Coordinator's reply asks for the
contact's name; the first message carrying one creates the deal in wacrm (SoR)
and mirrors it locally in the same transaction — no waiting for the CDC poll —
then links the conversation. No new conversation state is involved."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.modules.conversation_ownership.application.coordinator import CoordinatorAgent
from app.modules.conversation_ownership.domain.models import Conversation
from app.modules.conversation_ownership.infrastructure.repository import ConversationRepository
from app.modules.lead_qualification.application.identity_extraction import REPROMPT_IDENTITY
from app.modules.lead_qualification.domain.models import Lead
from app.modules.lead_qualification.infrastructure.db_models import (
    BuyerProfileORM,
    CRMAccessAuditORM,
    LeadORM,
)
from app.modules.lead_qualification.infrastructure.repository import LeadRepository
from app.modules.lead_qualification.infrastructure.wacrm_client import WacrmLeadSnapshot
from app.modules.organization.infrastructure.db_models import OrganizationORM
from app.shared.domain.base import new_id, utcnow
from app.shared.infrastructure.db_models import OutboxEventORM

PHONE = "+51999888777"


class StubResponder:
    async def respond(self, *, system_prompt: str, conversation_id, text: str) -> str:
        return "respuesta plantilla"


class NoSignalExtractor:
    async def extract(self, *, text: str, missing_dimensions):
        return None


class FakeWacrmClient:
    def __init__(self, organization_id, *, fail: bool = False):
        self.organization_id = organization_id
        self.fail = fail
        self.created: list[dict] = []

    async def create_lead(self, *, contact_reference, contact_name, dni=None):
        if self.fail:
            raise RuntimeError("wacrm is down")
        self.created.append(
            {
                "contact_reference": contact_reference,
                "contact_name": contact_name,
                "dni": dni,
            }
        )
        return WacrmLeadSnapshot(
            crm_lead_id=f"created-{len(self.created)}",
            organization_id=self.organization_id,
            pipeline_stage="New",
            assigned_broker_id=None,
            lead_score=0.0,
            updated_at=datetime.now(UTC),
            contact_reference=contact_reference,
        )


async def _seed_conversation(session_factory, *, contact_reference=PHONE):
    org_id = new_id()
    async with session_factory() as session:
        session.add(OrganizationORM(id=org_id, name="Org", status="active", created_at=utcnow()))
        conversation = Conversation(
            organization_id=org_id,
            chatwoot_conversation_id="99",
            contact_reference=contact_reference,
        )
        await ConversationRepository(session).add(conversation)
        await session.commit()
        return org_id, conversation.id


async def _handle(session_factory, org_id, conversation_id, text, client):
    async with session_factory() as session:
        agent = CoordinatorAgent(
            session,
            responder=StubResponder(),
            generative_extractor=NoSignalExtractor(),
            wacrm_client=client,
        )
        await agent.handle_message(
            organization_id=org_id, conversation_id=conversation_id, text=text
        )


async def _last_response(session_factory) -> str:
    async with session_factory() as session:
        rows = (
            (
                await session.execute(
                    select(OutboxEventORM).where(OutboxEventORM.event_type == "ResponseReady")
                )
            )
            .scalars()
            .all()
        )
        return rows[-1].payload["fields"]["response"]


@pytest.mark.asyncio
async def test_message_without_name_asks_for_identity_and_creates_nothing(session_factory):
    org_id, conversation_id = await _seed_conversation(session_factory)
    client = FakeWacrmClient(org_id)

    await _handle(session_factory, org_id, conversation_id, "Hola! buenas tardes", client)

    assert await _last_response(session_factory) == REPROMPT_IDENTITY
    assert client.created == []
    async with session_factory() as session:
        assert (await session.execute(select(LeadORM))).scalars().all() == []


@pytest.mark.asyncio
async def test_name_message_creates_lead_mirrors_locally_and_links(session_factory):
    org_id, conversation_id = await _seed_conversation(session_factory)
    client = FakeWacrmClient(org_id)

    await _handle(
        session_factory,
        org_id,
        conversation_id,
        "Me llamo Ana Torres y mi DNI es 45678912",
        client,
    )

    assert client.created == [
        {"contact_reference": PHONE, "contact_name": "Ana Torres", "dni": "45678912"}
    ]
    # The reply moves on — it must NOT keep asking for the name.
    assert await _last_response(session_factory) == "respuesta plantilla"

    async with session_factory() as session:
        # Mirrored locally in the same turn: the CDC poll latency is gone.
        row = (await session.execute(select(LeadORM))).scalar_one()
        assert row.crm_lead_id == "created-1"
        assert row.contact_reference == PHONE
        conversation = await ConversationRepository(session).get(conversation_id)
        assert conversation.lead_id == row.id
        audit = (await session.execute(select(CRMAccessAuditORM))).scalar_one()
        assert (audit.actor, audit.action, audit.allowed) == ("coordinator", "create", True)


@pytest.mark.asyncio
async def test_identity_message_is_not_fed_to_qualification_extractors(session_factory):
    """The turn that consumes a name/DNI ends there: qualification starts on
    the NEXT message. Without this, the 8-digit DNI reaches the budget
    extractor and corrupts the profile (E2E finding 2026-07-19)."""
    org_id, conversation_id = await _seed_conversation(session_factory)
    client = FakeWacrmClient(org_id)

    await _handle(
        session_factory,
        org_id,
        conversation_id,
        "Me llamo Ana Torres y mi DNI es 45678912",
        client,
    )

    async with session_factory() as session:
        assert (await session.execute(select(BuyerProfileORM))).scalars().all() == []


@pytest.mark.asyncio
async def test_conversation_without_contact_reference_skips_gate(session_factory):
    org_id, conversation_id = await _seed_conversation(session_factory, contact_reference=None)
    client = FakeWacrmClient(org_id)

    await _handle(session_factory, org_id, conversation_id, "Hola! buenas tardes", client)

    # Without the shared phone key a lead can't be created nor linked — the
    # normal conversational reply happens instead of the identity ask.
    assert await _last_response(session_factory) == "respuesta plantilla"
    assert client.created == []


@pytest.mark.asyncio
async def test_existing_local_lead_is_linked_not_duplicated(session_factory):
    org_id, conversation_id = await _seed_conversation(session_factory)
    async with session_factory() as session:
        lead = Lead(organization_id=org_id, crm_lead_id="lead-1", contact_reference=PHONE)
        await LeadRepository(session).add(lead)
        await session.commit()
    client = FakeWacrmClient(org_id)

    await _handle(session_factory, org_id, conversation_id, "Hola! buenas tardes", client)

    assert client.created == []  # linked to the mirror, never duplicated in wacrm
    assert await _last_response(session_factory) == "respuesta plantilla"
    async with session_factory() as session:
        conversation = await ConversationRepository(session).get(conversation_id)
        assert conversation.lead_id == lead.id


@pytest.mark.asyncio
async def test_wacrm_failure_keeps_asking_without_breaking_the_turn(session_factory):
    org_id, conversation_id = await _seed_conversation(session_factory)
    client = FakeWacrmClient(org_id, fail=True)

    await _handle(session_factory, org_id, conversation_id, "Me llamo Ana Torres", client)

    # The reply still happens and keeps asking; creation retries next turn.
    assert await _last_response(session_factory) == REPROMPT_IDENTITY
    async with session_factory() as session:
        assert (await session.execute(select(LeadORM))).scalars().all() == []
        conversation = await ConversationRepository(session).get(conversation_id)
        assert conversation.lead_id is None
