"""US-218: identity capture is reordered so DNI is deferred past the first
turn, until a recommendation/value moment has been shown
(`ConversationState.RECOMMENDATION`). Name stays the turn-1 minimum wacrm
needs alongside the channel's own phone (`WacrmClient.create_lead`'s
`contact_name` has no default); DNI was already optional there — this change
moves the conversational *ask* for it, not the CRM contract.

Follows the same harness as tests/test_coordinator_identity_gate.py (name
gate) and the RECOMMENDATION-seeding pattern from
tests/test_coordinator_scheduling_turn.py."""

from __future__ import annotations

from sqlalchemy import select

from app.modules.conversation_ownership.application.coordinator import CoordinatorAgent
from app.modules.conversation_ownership.domain.models import Conversation, ConversationState
from app.modules.conversation_ownership.infrastructure.repository import ConversationRepository
from app.modules.lead_qualification.application.identity_extraction import (
    REPROMPT_DNI,
    REPROMPT_IDENTITY,
)
from app.modules.lead_qualification.domain.models import Lead
from app.modules.lead_qualification.infrastructure.db_models import BuyerProfileORM, LeadORM
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
    def __init__(self, organization_id):
        self.organization_id = organization_id
        self.created: list[dict] = []

    async def create_lead(self, *, contact_reference, contact_name, dni=None):
        self.created.append(
            {"contact_reference": contact_reference, "contact_name": contact_name, "dni": dni}
        )
        return WacrmLeadSnapshot(
            crm_lead_id=f"created-{len(self.created)}",
            organization_id=self.organization_id,
            pipeline_stage="New",
            assigned_broker_id=None,
            lead_score=0.0,
            updated_at=utcnow(),
            contact_reference=contact_reference,
        )


async def _seed_new_conversation(session_factory, *, contact_reference=PHONE):
    org_id = new_id()
    async with session_factory() as session:
        session.add(OrganizationORM(id=org_id, name="Org", status="active", created_at=utcnow()))
        conversation = Conversation(
            organization_id=org_id,
            chatwoot_conversation_id="218",
            contact_reference=contact_reference,
        )
        await ConversationRepository(session).add(conversation)
        await session.commit()
        return org_id, conversation.id


async def _seed_conversation_in_state(session_factory, state: ConversationState):
    """A lead already linked, conversation fast-forwarded to `state` — mirrors
    the RECOMMENDATION-seeding helper in test_coordinator_scheduling_turn.py,
    trimmed to what the DNI gate itself needs (no recommendation/broker rows
    required, since this doesn't exercise scheduling)."""
    org_id = new_id()
    async with session_factory() as session:
        session.add(OrganizationORM(id=org_id, name="Org", status="active", created_at=utcnow()))
        lead = Lead(organization_id=org_id, crm_lead_id="lead-218", contact_reference=PHONE)
        await LeadRepository(session).add(lead)

        conversation = Conversation(
            organization_id=org_id, chatwoot_conversation_id="218", contact_reference=PHONE
        )
        conversation.link_lead(lead.id)
        conversation.transition_to(ConversationState.AI_OWNED, reason="test setup")
        if state is not ConversationState.AI_OWNED:
            conversation.transition_to(ConversationState.QUALIFICATION, reason="test setup")
        if state is ConversationState.RECOMMENDATION:
            conversation.transition_to(ConversationState.RECOMMENDATION, reason="test setup")
        await ConversationRepository(session).add(conversation)
        await session.commit()
        return org_id, conversation.id, lead.id


async def _handle(session_factory, org_id, conversation_id, text, client=None):
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


async def test_turn_1_reprompt_never_mentions_dni():
    """US-218: the very first identity ask must not exige DNI."""
    assert "DNI" not in REPROMPT_IDENTITY


async def test_lead_created_on_turn_1_with_name_only_no_dni(session_factory):
    """Leads can be created/advanced without DNI on turn 1 — the minimal
    identifier wacrm needs upfront is the name (+ the already-known phone),
    not the DNI."""
    org_id, conversation_id = await _seed_new_conversation(session_factory)
    client = FakeWacrmClient(org_id)

    await _handle(session_factory, org_id, conversation_id, "Me llamo Ana Torres", client)

    assert client.created == [
        {"contact_reference": PHONE, "contact_name": "Ana Torres", "dni": None}
    ]
    assert await _last_response(session_factory) == "respuesta plantilla"
    async with session_factory() as session:
        row = (await session.execute(select(LeadORM))).scalar_one()
        assert row.crm_lead_id == "created-1"
        conversation = await ConversationRepository(session).get(conversation_id)
        assert conversation.lead_id == row.id


async def test_no_dni_nudge_before_recommendation(session_factory):
    """DNI is never requested while still in Qualification — only after a
    recommendation/value moment (`RECOMMENDATION`)."""
    org_id, conversation_id, _lead_id = await _seed_conversation_in_state(
        session_factory, ConversationState.QUALIFICATION
    )

    await _handle(
        session_factory, org_id, conversation_id, "Busco un depa de 2 dormitorios en Miraflores"
    )

    response = await _last_response(session_factory)
    assert REPROMPT_DNI not in response


async def test_dni_nudge_appended_after_recommendation_shown(session_factory):
    """Once the conversation reaches RECOMMENDATION (a value moment already
    delivered) and no DNI has been volunteered, the reply keeps its normal
    content AND additively asks for the DNI."""
    org_id, conversation_id, _lead_id = await _seed_conversation_in_state(
        session_factory, ConversationState.RECOMMENDATION
    )

    await _handle(session_factory, org_id, conversation_id, "Me interesa la primera opción")

    response = await _last_response(session_factory)
    assert "respuesta plantilla" in response
    assert REPROMPT_DNI in response


async def test_dni_only_message_during_recommendation_is_consumed_not_qualification(
    session_factory,
):
    """A message that is purely the DNI answer, sent during RECOMMENDATION,
    is recognized and excluded from qualification extraction that turn — same
    convention as the existing name-gate `identity_consumed` behavior."""
    org_id, conversation_id, _lead_id = await _seed_conversation_in_state(
        session_factory, ConversationState.RECOMMENDATION
    )

    await _handle(session_factory, org_id, conversation_id, "45678912")

    response = await _last_response(session_factory)
    assert REPROMPT_DNI not in response
    async with session_factory() as session:
        assert (await session.execute(select(BuyerProfileORM))).scalars().all() == []
