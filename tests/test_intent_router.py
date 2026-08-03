"""AI-104 (scoped): Intent Router classification, recorded on the turn's
AIDecisionTrace but not yet branching CoordinatorAgent's control flow (see
openspec/changes/intent-router-ai-104/design.md, Non-Goals)."""

import pytest
from sqlalchemy import select

from app.modules.conversation_ownership.application.coordinator import CoordinatorAgent
from app.modules.conversation_ownership.domain.models import Conversation
from app.modules.conversation_ownership.infrastructure.repository import ConversationRepository
from app.modules.conversation_ownership.application.intent_router import KeywordIntentRouter
from app.modules.intelligence_ai_admin.infrastructure.db_models import AIDecisionTraceORM
from app.modules.organization.infrastructure.db_models import OrganizationORM
from app.shared.domain.base import new_id, utcnow


class RecordingResponder:
    def __init__(self, reply: str = "Claro, cuéntame más.") -> None:
        self.reply = reply

    async def respond(self, *, system_prompt: str, conversation_id, text: str) -> str:
        return self.reply


class RaisingIntentRouter:
    """Simulates a classifier failure — every call raises, exercising the
    coordinator's swallow-and-continue contract (design.md)."""

    async def classify(self, text: str) -> str:
        raise RuntimeError("classifier unavailable")


async def _seed_conversation(session_factory):
    org_id = new_id()
    async with session_factory() as session:
        session.add(OrganizationORM(id=org_id, name="Org", status="active", created_at=utcnow()))
        conversation = Conversation(organization_id=org_id, chatwoot_conversation_id="1")
        await ConversationRepository(session).add(conversation)
        await session.commit()
        return org_id, conversation.id


@pytest.mark.asyncio
async def test_keyword_router_classifies_each_category():
    router = KeywordIntentRouter()
    assert await router.classify("Me parece muy caro para mi presupuesto") == "objecion"
    assert await router.classify("Quiero agendar una visita el sábado") == "agendamiento"
    assert await router.classify("Quiero hablar con una persona") == "handoff_explicito"
    assert await router.classify("¿Cómo funciona el proceso de compra?") == "pregunta_informativa"
    assert await router.classify("Busco un departamento en Miraflores") == "qualification"
    assert await router.classify("jsdf random text") == "otro"


@pytest.mark.asyncio
async def test_intent_classification_recorded_on_ai_decision_trace(session_factory):
    org_id, conversation_id = await _seed_conversation(session_factory)

    async with session_factory() as session:
        agent = CoordinatorAgent(
            session, responder=RecordingResponder(), intent_router=KeywordIntentRouter()
        )
        await agent.handle_message(
            organization_id=org_id, conversation_id=conversation_id, text="Busco casa en La Molina"
        )

    async with session_factory() as session:
        trace = (await session.execute(select(AIDecisionTraceORM))).scalar_one()
        tool_call_names = [call["name"] for call in trace.tool_calls]
        assert "intent_router.classify" in tool_call_names
        classify_call = next(
            call for call in trace.tool_calls if call["name"] == "intent_router.classify"
        )
        assert classify_call["result"] == "qualification"


@pytest.mark.asyncio
async def test_intent_classifier_failure_does_not_break_the_turn(session_factory):
    org_id, conversation_id = await _seed_conversation(session_factory)
    responder = RecordingResponder(reply="Respuesta normal")

    async with session_factory() as session:
        agent = CoordinatorAgent(session, responder=responder, intent_router=RaisingIntentRouter())
        await agent.handle_message(
            organization_id=org_id, conversation_id=conversation_id, text="Hola"
        )

    async with session_factory() as session:
        trace = (await session.execute(select(AIDecisionTraceORM))).scalar_one()
        tool_call_names = [call["name"] for call in trace.tool_calls]
        assert "intent_router.classify" not in tool_call_names
        assert trace.output["action"] == "reply"
        assert trace.output["response"] == responder.reply
