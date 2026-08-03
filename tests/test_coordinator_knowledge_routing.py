"""AI-105: wires the classified intent category into `CoordinatorAgent`'s routing — the
one confirmed-open gap left by `intent-router-ai-104` (classification recorded but never
consumed) and named explicitly by `knowledge-rag-service-ai-106` as blocking its own
`KnowledgeService.answer` wiring. Covers the new `objecion`/`pregunta_informativa` branch,
its not-found/failure fallback, precedence against existing overrides, and that every other
category never invokes the Knowledge/RAG service (see
openspec/changes/intent-router-llm-ai-105/design.md, decision table)."""

import pytest
from sqlalchemy import select

from app.modules.conversation_ownership.application.coordinator import CoordinatorAgent
from app.modules.conversation_ownership.application.intent_router import KeywordIntentRouter
from app.modules.conversation_ownership.domain.models import Conversation
from app.modules.conversation_ownership.infrastructure.repository import ConversationRepository
from app.modules.knowledge.domain.models import KnowledgeAnswer
from app.modules.lead_qualification.application.qualification_flow import _REPROMPT_BUDGET
from app.modules.lead_qualification.domain.models import Lead
from app.modules.lead_qualification.infrastructure.db_models import LeadObjectionORM
from app.modules.lead_qualification.infrastructure.repository import LeadRepository
from app.modules.organization.infrastructure.db_models import OrganizationORM
from app.shared.domain.base import new_id, utcnow
from app.shared.infrastructure.db_models import OutboxEventORM
from app.modules.intelligence_ai_admin.infrastructure.db_models import AIDecisionTraceORM


class StubResponder:
    def __init__(self, reply: str = "respuesta plantilla") -> None:
        self.reply = reply

    async def respond(self, *, system_prompt: str, conversation_id, text: str) -> str:
        return self.reply


class FoundKnowledgeAnswerer:
    """Always finds a grounded answer — used to assert the reply is replaced."""

    def __init__(self, answer_text: str = "El plan de pagos permite hasta 20% de inicial.") -> None:
        self.answer_text = answer_text
        self.calls: list[tuple] = []

    async def answer(self, organization_id, query: str) -> KnowledgeAnswer:
        self.calls.append((organization_id, query))
        return KnowledgeAnswer(
            answer_text=self.answer_text,
            source_document_ids=(new_id(),),
            category=None,
            found=True,
        )


class NotFoundKnowledgeAnswerer:
    """Always returns found=False — used to assert the default reply survives unchanged."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def answer(self, organization_id, query: str) -> KnowledgeAnswer:
        self.calls.append((organization_id, query))
        return KnowledgeAnswer(answer_text="", source_document_ids=(), category=None, found=False)


class RaisingKnowledgeAnswerer:
    """Simulates a lookup failure — must never break the turn."""

    def __init__(self) -> None:
        self.calls = 0

    async def answer(self, organization_id, query: str) -> KnowledgeAnswer:
        self.calls += 1
        raise RuntimeError("knowledge service unavailable")


async def _seed_linked_conversation(session_factory):
    org_id = new_id()
    async with session_factory() as session:
        session.add(OrganizationORM(id=org_id, name="Org", status="active", created_at=utcnow()))
        lead = Lead(organization_id=org_id, crm_lead_id="lead-105")
        await LeadRepository(session).add(lead)
        conversation = Conversation(organization_id=org_id, chatwoot_conversation_id="105")
        conversation.link_lead(lead.id)
        await ConversationRepository(session).add(conversation)
        await session.commit()
        return org_id, conversation.id, lead.id


async def _handle(session_factory, org_id, conversation_id, text, *, knowledge_answerer, responder=None):
    async with session_factory() as session:
        agent = CoordinatorAgent(
            session,
            responder=responder or StubResponder(),
            intent_router=KeywordIntentRouter(),
            knowledge_answerer=knowledge_answerer,
        )
        await agent.handle_message(
            organization_id=org_id, conversation_id=conversation_id, text=text
        )


async def _last_response(session_factory) -> str:
    async with session_factory() as session:
        row = (
            (
                await session.execute(
                    select(OutboxEventORM)
                    .where(OutboxEventORM.event_type == "ResponseReady")
                    .order_by(OutboxEventORM.occurred_at.desc())
                )
            )
            .scalars()
            .first()
        )
        return row.payload["fields"]["response"]


@pytest.mark.asyncio
async def test_objection_message_uses_grounded_knowledge_answer(session_factory):
    org_id, conversation_id, lead_id = await _seed_linked_conversation(session_factory)
    answerer = FoundKnowledgeAnswerer()

    # "caro" -> KeywordIntentRouter classifies as "objecion".
    await _handle(
        session_factory,
        org_id,
        conversation_id,
        "Me parece muy caro, se me va del presupuesto",
        knowledge_answerer=answerer,
    )

    assert await _last_response(session_factory) == answerer.answer_text
    assert len(answerer.calls) == 1
    assert answerer.calls[0][0] == org_id

    # Deterministic objection scoring is unaffected by the new branch.
    async with session_factory() as session:
        objections = (
            (await session.execute(select(LeadObjectionORM).where(LeadObjectionORM.lead_id == lead_id)))
            .scalars()
            .all()
        )
        assert len(objections) == 1
        assert objections[0].type == "precio"


@pytest.mark.asyncio
async def test_informational_question_uses_grounded_knowledge_answer(session_factory):
    org_id, conversation_id, _ = await _seed_linked_conversation(session_factory)
    answerer = FoundKnowledgeAnswerer("El proceso de compra toma en promedio 30 dias.")

    # "Cómo funciona" -> KeywordIntentRouter classifies as "pregunta_informativa".
    await _handle(
        session_factory,
        org_id,
        conversation_id,
        "¿Cómo funciona el proceso de compra?",
        knowledge_answerer=answerer,
    )

    assert await _last_response(session_factory) == answerer.answer_text
    assert len(answerer.calls) == 1


@pytest.mark.asyncio
async def test_objection_without_grounded_answer_falls_back_to_default_reply(session_factory):
    org_id, conversation_id, _ = await _seed_linked_conversation(session_factory)
    responder = StubResponder("respuesta plantilla")
    answerer = NotFoundKnowledgeAnswerer()

    await _handle(
        session_factory,
        org_id,
        conversation_id,
        "Me parece muy caro, se me va del presupuesto",
        knowledge_answerer=answerer,
        responder=responder,
    )

    assert await _last_response(session_factory) == "respuesta plantilla"
    assert len(answerer.calls) == 1


@pytest.mark.asyncio
async def test_knowledge_lookup_failure_falls_back_to_default_reply(session_factory):
    org_id, conversation_id, _ = await _seed_linked_conversation(session_factory)
    responder = StubResponder("respuesta plantilla")
    answerer = RaisingKnowledgeAnswerer()

    await _handle(
        session_factory,
        org_id,
        conversation_id,
        "Me parece muy caro, se me va del presupuesto",
        knowledge_answerer=answerer,
        responder=responder,
    )

    assert await _last_response(session_factory) == "respuesta plantilla"
    assert answerer.calls == 1

    async with session_factory() as session:
        trace = (await session.execute(select(AIDecisionTraceORM))).scalar_one()
        tool_call_names = [call["name"] for call in trace.tool_calls]
        assert "knowledge.answer" not in tool_call_names


@pytest.mark.asyncio
async def test_non_consuming_category_never_calls_knowledge_service(session_factory):
    org_id, conversation_id, _ = await _seed_linked_conversation(session_factory)
    answerer = FoundKnowledgeAnswerer()

    # "Busco" -> KeywordIntentRouter classifies as "qualification", not a consuming category.
    await _handle(
        session_factory,
        org_id,
        conversation_id,
        "Busco un departamento en Surco",
        knowledge_answerer=answerer,
    )

    assert answerer.calls == []


@pytest.mark.asyncio
async def test_qualification_reprompt_overrides_knowledge_answer(session_factory):
    org_id, conversation_id, _ = await _seed_linked_conversation(session_factory)
    answerer = FoundKnowledgeAnswerer()

    # "caro" -> objecion (consumes knowledge service); "0" also triggers the invalid-budget
    # reprompt, which must still win over a found knowledge answer (precedence order).
    await _handle(
        session_factory,
        org_id,
        conversation_id,
        "Es muy caro, mi presupuesto es 0",
        knowledge_answerer=answerer,
    )

    assert await _last_response(session_factory) == _REPROMPT_BUDGET
    # The knowledge branch still ran (category matched) even though its answer lost precedence.
    assert len(answerer.calls) == 1
