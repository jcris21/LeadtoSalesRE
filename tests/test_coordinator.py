"""Coordinator Agent: guardrail-first turn order, scenario-1 AI ownership on
first contact, ResponseReady publication, decision tracing (QA-07) and the
auditable OwnershipDecision record."""

import uuid

import pytest
from sqlalchemy import select

from app.modules.conversation_ownership.application.coordinator import CoordinatorAgent
from app.modules.conversation_ownership.domain.models import Conversation
from app.modules.conversation_ownership.infrastructure.db_models import (
    ConversationORM,
    OwnershipDecisionORM,
)
from app.modules.conversation_ownership.infrastructure.repository import ConversationRepository
from app.modules.intelligence_ai_admin.infrastructure.db_models import AIDecisionTraceORM
from app.modules.organization.infrastructure.db_models import OrganizationORM
from app.shared.domain.base import new_id, utcnow
from app.shared.infrastructure.db_models import OutboxEventORM


class RecordingResponder:
    def __init__(self, reply: str = "Claro, ¿en qué zona buscas?"):
        self.reply = reply
        self.calls: list[dict] = []

    async def respond(self, *, system_prompt: str, conversation_id: uuid.UUID, text: str) -> str:
        self.calls.append(
            {"system_prompt": system_prompt, "conversation_id": conversation_id, "text": text}
        )
        return self.reply


async def _seed_conversation(session_factory) -> tuple[uuid.UUID, uuid.UUID]:
    org_id = new_id()
    async with session_factory() as session:
        session.add(OrganizationORM(id=org_id, name="Org", status="active", created_at=utcnow()))
        conversation = Conversation(organization_id=org_id, chatwoot_conversation_id="42")
        await ConversationRepository(session).add(conversation)
        await session.commit()
        return org_id, conversation.id


@pytest.mark.asyncio
async def test_first_message_gives_ai_ownership_and_publishes_response(session_factory):
    org_id, conversation_id = await _seed_conversation(session_factory)
    responder = RecordingResponder()

    async with session_factory() as session:
        agent = CoordinatorAgent(session, responder=responder)
        await agent.handle_message(
            organization_id=org_id, conversation_id=conversation_id, text="Hola, busco casa"
        )

    async with session_factory() as session:
        convo = await session.get(ConversationORM, conversation_id)
        # AIOwned is momentary: the same turn advances straight into
        # Qualification (§6.1 ArchitecturalDrivers), ownership unchanged.
        assert convo.state == "Qualification"
        assert convo.owner_type == "ai"

        decision = (await session.execute(select(OwnershipDecisionORM))).scalar_one()
        assert decision.scenario == "scenario_1_never_human"

        response_event = (
            await session.execute(
                select(OutboxEventORM).where(OutboxEventORM.event_type == "ResponseReady")
            )
        ).scalar_one()
        assert response_event.payload["fields"]["response"] == responder.reply

        trace = (await session.execute(select(AIDecisionTraceORM))).scalar_one()
        assert trace.agent_name == "coordinator"
        assert trace.output["action"] == "reply"

    assert len(responder.calls) == 1


@pytest.mark.asyncio
async def test_broker_request_bypasses_reasoning_and_transfers(session_factory):
    org_id, conversation_id = await _seed_conversation(session_factory)
    responder = RecordingResponder()

    async with session_factory() as session:
        agent = CoordinatorAgent(session, responder=responder)
        await agent.handle_message(
            organization_id=org_id, conversation_id=conversation_id, text="¿Está María?"
        )

    async with session_factory() as session:
        convo = await session.get(ConversationORM, conversation_id)
        assert convo.state == "AssignedHuman"
        assert convo.owner_type == "human"
        assert "María" in convo.owner_reason

        decision = (await session.execute(select(OwnershipDecisionORM))).scalar_one()
        assert decision.scenario == "scenario_8_broker_requested"

        # The Coordinator never generates a conversational reply on a bypass turn.
        response_events = (
            (
                await session.execute(
                    select(OutboxEventORM).where(OutboxEventORM.event_type == "ResponseReady")
                )
            )
            .scalars()
            .all()
        )
        assert response_events == []

        transfer_event = (
            await session.execute(
                select(OutboxEventORM).where(OutboxEventORM.event_type == "OwnershipTransferred")
            )
        ).scalar_one()
        assert transfer_event.payload["fields"]["to_owner"] == "human"

    assert responder.calls == []  # LLM was never consulted


@pytest.mark.asyncio
async def test_missing_conversation_is_dropped_without_error(session_factory):
    async with session_factory() as session:
        agent = CoordinatorAgent(session, responder=RecordingResponder())
        await agent.handle_message(
            organization_id=new_id(), conversation_id=new_id(), text="hola"
        )  # must not raise
