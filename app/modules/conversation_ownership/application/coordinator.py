"""Coordinator Agent — conducts the lead's conversation through the happy path,
delegating every non-conversational decision to dedicated services
(Architecture.md §6.1; Agentic_System §1: SAS + deterministic services).

Turn order is fixed by contract (GuardrailPort, §8): the Guardrail Interceptor
runs BEFORE any reasoning; on bypass the Coordinator never generates a
conversational reply that turn — ownership transfers immediately (§7.5).

The LLM sits behind `ResponderPort`. Sprint 1 ships `TemplateResponder`, a
deterministic placeholder that keeps the pipeline (webhook -> bus -> coordinator
-> ResponseReady -> Chatwoot) fully operational and testable without LLM
credentials; the LangGraph implementation recommended by Agentic_System §5
plugs in behind the same port without touching this module.
"""

from __future__ import annotations

import logging
import uuid
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.conversation_ownership.application.guardrail import GuardrailInterceptor
from app.modules.conversation_ownership.application.ownership_policy import (
    OwnershipContext,
    OwnershipDecision,
    OwnershipPolicyEngine,
)
from app.modules.conversation_ownership.application.sidebar import SidebarPublisher
from app.modules.conversation_ownership.domain.models import (
    Conversation,
    ConversationState,
    OwnerType,
    ResponseReady,
)
from app.modules.conversation_ownership.infrastructure.repository import (
    ConversationRepository,
    OwnershipDecisionRepository,
)
from app.shared.infrastructure import event_bus
from app.shared.infrastructure.observability import trace_decision

logger = logging.getLogger(__name__)

AGENT_NAME = "coordinator"


class ResponderPort(Protocol):
    """The conversational brain. Receives the system prompt and the lead's turn;
    returns the reply text. LangGraph/LLM implementations must respect this."""

    async def respond(
        self, *, system_prompt: str, conversation_id: uuid.UUID, text: str
    ) -> str: ...


class TemplateResponder:
    """Deterministic Sprint 1 placeholder: acknowledges and advances the
    conversation without an LLM. Replaced behind ResponderPort when LLM
    credentials/LangGraph land (Agentic_System §5)."""

    async def respond(self, *, system_prompt: str, conversation_id: uuid.UUID, text: str) -> str:
        return (
            "¡Gracias por tu mensaje! Soy el asistente del equipo de asesores. "
            "Cuéntame qué tipo de propiedad buscas y en qué zona, y te ayudo a "
            "encontrar opciones."
        )


class CoordinatorAgent:
    """Consumes MessageReceived, produces ResponseReady (or an immediate
    ownership transfer on guardrail bypass). One instance per message handling,
    bound to the handling session so outbox writes share the transaction."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        responder: ResponderPort | None = None,
        guardrail: GuardrailInterceptor | None = None,
        policy_engine: OwnershipPolicyEngine | None = None,
        sidebar: SidebarPublisher | None = None,
    ):
        self._session = session
        self._responder = responder or TemplateResponder()
        self._guardrail = guardrail or GuardrailInterceptor()
        self._policy_engine = policy_engine or OwnershipPolicyEngine()
        self._sidebar = sidebar
        self._conversations = ConversationRepository(session)
        self._decisions = OwnershipDecisionRepository(session)

    async def handle_message(
        self, *, organization_id: uuid.UUID, conversation_id: uuid.UUID, text: str
    ) -> None:
        conversation = await self._conversations.get(conversation_id)
        if conversation is None:
            logger.error("Conversation %s not found; dropping message", conversation_id)
            return
        conversation.touch()

        async with trace_decision(
            self._session,
            organization_id=organization_id,
            agent_name=AGENT_NAME,
            conversation_id=conversation_id,
        ) as recorder:
            bypass = self._guardrail.check(text)
            if bypass is not None:
                recorder.record_tool_call(
                    "guardrail.check", {"text": text}, f"bypass:{bypass.broker_requested}"
                )
                decision = await self._transfer_to_human(conversation, bypass.broker_requested)
                recorder.set_output(
                    {"action": "guardrail_bypass", "explanation": decision.explanation}
                )
            else:
                response = await self._conversational_turn(conversation, text)
                recorder.set_output({"action": "reply", "response": response})

        await self._conversations.save(conversation)
        await event_bus.publish(self._session, conversation.pull_domain_events())
        await self._session.commit()

        if self._sidebar is not None:
            # After commit: sidebar is best-effort and must not roll back the turn.
            await self._sidebar.publish(conversation)

    async def _transfer_to_human(
        self, conversation: Conversation, broker_requested: str | None
    ) -> OwnershipDecision:
        """Scenario 8: bypass — no rule evaluation, no conversational reply this turn."""
        decision = self._policy_engine.evaluate(
            OwnershipContext(
                conversation=conversation,
                broker_requested=broker_requested,
                is_guardrail_bypass=True,
            )
        )
        await self._decisions.add(
            organization_id=conversation.organization_id,
            conversation_id=conversation.id,
            scenario=decision.scenario,
            inputs_snapshot=decision.inputs_snapshot,
            selected_owner=decision.selected_owner.value,
            owner_id=decision.owner_id,
            explanation=decision.explanation,
        )
        conversation.transition_to(
            ConversationState.ASSIGNED_HUMAN,
            reason=decision.explanation,
            owner_type=OwnerType.HUMAN,
            owner_id=decision.owner_id,
        )
        return decision

    async def _conversational_turn(self, conversation: Conversation, text: str) -> str:
        if conversation.state is ConversationState.NEW:
            decision = self._policy_engine.evaluate(OwnershipContext(conversation=conversation))
            await self._decisions.add(
                organization_id=conversation.organization_id,
                conversation_id=conversation.id,
                scenario=decision.scenario,
                inputs_snapshot=decision.inputs_snapshot,
                selected_owner=decision.selected_owner.value,
                owner_id=decision.owner_id,
                explanation=decision.explanation,
            )
            conversation.transition_to(
                ConversationState.AI_OWNED,
                reason=decision.explanation,
                owner_type=OwnerType.AI,
            )

        system_prompt = await self._load_system_prompt(conversation.organization_id)
        response = await self._responder.respond(
            system_prompt=system_prompt, conversation_id=conversation.id, text=text
        )
        conversation.record_event(
            ResponseReady(
                organization_id=conversation.organization_id,
                conversation_id=str(conversation.id),
                chatwoot_conversation_id=conversation.chatwoot_conversation_id,
                response=response,
            )
        )
        return response

    async def _load_system_prompt(self, organization_id: uuid.UUID) -> str:
        """Per-organization active prompt (ConfigStorePort.get_active_prompt).
        Falls back to a safe default while the org hasn't published one — the
        TemplateResponder ignores it anyway; LLM responders should treat the
        registry as required."""
        from app.modules.intelligence_ai_admin.infrastructure.repository import (
            PromptRegistryRepository,
        )

        repo = PromptRegistryRepository(self._session)
        template = await repo.get_template(organization_id, AGENT_NAME)
        if template is not None:
            active = await repo.get_active_version(template.id)
            if active is not None:
                return active.content
        logger.warning(
            "No active prompt for agent '%s' in org %s; using fallback",
            AGENT_NAME,
            organization_id,
        )
        return "Eres el asistente inmobiliario del equipo de asesores."
