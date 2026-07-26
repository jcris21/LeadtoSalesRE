"""Coordinator Agent — conducts the lead's conversation through the happy path,
delegating every non-conversational decision to dedicated services
(Architecture.md §6.1; Agentic_System §1: SAS + deterministic services).

Turn order is fixed by contract (GuardrailPort, §8): the Guardrail Interceptor
runs BEFORE any reasoning; on bypass the Coordinator never generates a
conversational reply that turn — ownership transfers immediately (§7.5).

The LLM sits behind `ResponderPort`. The default implementation is
`LangGraphResponder` (langgraph_responder.py): a LangGraph StateGraph with
per-conversation checkpoints (`thread_id = conversation_id`), per Agentic_System
§5. Its brain is deterministic until LLM credentials land, so the pipeline
(webhook -> bus -> coordinator -> ResponseReady -> Chatwoot) stays fully
operational and testable offline. `TemplateResponder` remains as a minimal
stub for isolated unit tests.
"""

from __future__ import annotations

import logging
import uuid
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.conversation_ownership.application.guardrail import GuardrailInterceptor
from app.modules.conversation_ownership.application.intent_router import (
    IntentRouterPort,
    get_default_intent_router,
)
from app.modules.conversation_ownership.application.link_guard import guard_reply
from app.modules.conversation_ownership.application.ownership_policy import (
    OwnershipContext,
    OwnershipDecision,
    OwnershipPolicyEngine,
)
from app.modules.conversation_ownership.application.scheduling_turn import run_scheduling_turn
from app.modules.conversation_ownership.application.sidebar import SidebarPublisher
from app.modules.conversation_ownership.domain.models import (
    Conversation,
    ConversationState,
    OwnerType,
    ResponseReady,
)
from app.modules.conversation_ownership.domain.prompts import DEFAULT_SYSTEM_PROMPT
from app.modules.conversation_ownership.infrastructure.repository import (
    ConversationRepository,
    OwnershipDecisionRepository,
)
from app.modules.conversation_ownership.application.lead_linker import LeadLinker
from app.modules.lead_qualification.application.identity_extraction import (
    REPROMPT_IDENTITY,
    extract_identity,
)
from app.modules.lead_qualification.application.lead_sync import LeadSyncAdapter
from app.modules.lead_qualification.application.qualification_turn import (
    QualificationTurnResult,
    run_qualification_turn,
)
from app.modules.lead_qualification.infrastructure.generative_extractor import (
    GenerativeExtractorPort,
    get_default_generative_extractor,
)
from app.modules.lead_qualification.infrastructure.repository import BuyerProfileRepository
from app.modules.lead_qualification.infrastructure.wacrm_client import WacrmClient
from app.modules.recommendation.application.search_diagnostics import (
    diagnose,
    render_grounding_note,
)
from app.modules.recommendation.infrastructure.repository import PropertyRepository
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
    """Minimal deterministic stub kept for isolated unit tests. Production
    default is LangGraphResponder (see module docstring)."""

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
        generative_extractor: GenerativeExtractorPort | None = None,
        wacrm_client: WacrmClient | None = None,
        intent_router: IntentRouterPort | None = None,
    ):
        from app.modules.conversation_ownership.application.langgraph_responder import (
            get_default_responder,
        )

        self._session = session
        self._responder = responder or get_default_responder()
        self._guardrail = guardrail or GuardrailInterceptor()
        self._policy_engine = policy_engine or OwnershipPolicyEngine()
        self._sidebar = sidebar
        self._generative_extractor = generative_extractor or get_default_generative_extractor()
        self._wacrm_client = wacrm_client
        self._intent_router = intent_router or get_default_intent_router()
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
                await self._classify_intent(text, recorder)
                ask_identity, identity_consumed = await self._identity_gate(
                    conversation, text, recorder
                )
                # A message consumed as identity (name/DNI) is not a
                # qualification signal: the 8-digit DNI would reach the budget
                # extractor and corrupt the profile. Qualification starts on
                # the NEXT message.
                qualification = (
                    None
                    if identity_consumed
                    else await self._qualification_turn(conversation, text)
                )
                if qualification is not None:
                    recorder.record_tool_call(
                        "qualification.run_turn", {"text": text}, qualification.summary()
                    )
                response = await self._conversational_turn(
                    conversation, text, qualification, ask_identity=ask_identity, recorder=recorder
                )
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

    async def _classify_intent(self, text: str, recorder) -> None:
        """AI-104 (scoped): records the message's classified intent category
        on this turn's AIDecisionTrace. Additive-only — no branch in this
        method's caller reads the result yet (design.md Non-Goals); a
        classifier failure must never affect the reply, same contract as
        `_build_grounding_note`."""
        try:
            category = await self._intent_router.classify(text)
        except Exception:  # noqa: BLE001 — classification must never break the turn
            logger.exception("Intent classification failed; continuing without it")
            return
        recorder.record_tool_call("intent_router.classify", {"text": text}, category)

    async def _identity_gate(
        self, conversation: Conversation, text: str, recorder
    ) -> tuple[bool, bool]:
        """G8: leads are born in the chat itself. While the conversation has no
        linked Lead, the reply asks the contact for their name; the first
        message carrying one creates the deal in wacrm (SoR) and mirrors it
        locally in the same transaction — no waiting for the CDC poll, and no
        new conversation state. Returns `(ask_identity, identity_consumed)`:
        `ask_identity` when this turn's reply must (still) ask for identity,
        `identity_consumed` when this message WAS the name/DNI answer — the
        caller must then keep it away from the qualification extractors."""
        if conversation.lead_id is not None or not conversation.contact_reference:
            return False, False
        # The lead may already exist (walk-in registered by a broker, or CDC
        # landed since the webhook's own attempt) — link, never duplicate.
        if await LeadLinker(self._session).link_if_possible(conversation) is not None:
            return False, False
        identity = extract_identity(text)
        if identity is None:
            return True, False
        try:
            client = self._wacrm_client or await self._build_wacrm_client(
                conversation.organization_id
            )
            lead = await LeadSyncAdapter(self._session, client=client).create_lead(
                conversation.organization_id,
                contact_reference=conversation.contact_reference,
                contact_name=identity.full_name,
                dni=identity.dni,
                actor=AGENT_NAME,
            )
        except Exception:  # noqa: BLE001 — a CRM outage must never kill the reply
            logger.exception(
                "wacrm lead creation failed for conversation %s; will retry next turn",
                conversation.id,
            )
            return True, False
        conversation.link_lead(lead.id)
        recorder.record_tool_call(
            "identity.create_lead",
            {"text": text},
            f"lead:{lead.crm_lead_id} name:{identity.full_name} dni:{identity.dni or '-'}",
        )
        return False, True

    async def _build_wacrm_client(self, organization_id: uuid.UUID) -> WacrmClient:
        from app.modules.lead_qualification.wiring import build_wacrm_client

        return await build_wacrm_client(self._session, organization_id)

    async def _qualification_turn(
        self, conversation: Conversation, text: str
    ) -> QualificationTurnResult | None:
        """G1: the chat itself fills the BuyerProfile. Skipped while no Lead is
        linked yet (wacrm CDC is eventually consistent, §7.7) — the
        conversational reply still happens, and qualification resumes on the
        first turn after `LeadLinker` resolves the link."""
        if conversation.lead_id is None:
            return None
        return await run_qualification_turn(
            self._session,
            lead_id=conversation.lead_id,
            organization_id=conversation.organization_id,
            text=text,
            generative_extractor=self._generative_extractor,
        )

    async def _conversational_turn(
        self,
        conversation: Conversation,
        text: str,
        qualification: QualificationTurnResult | None = None,
        ask_identity: bool = False,
        recorder=None,
    ) -> str:
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
            # An AI-owned lead's very next job is qualification (§6.1
            # ArchitecturalDrivers: AIOwned -> Qualification -> Recommendation);
            # AIOwned itself is momentary, not a state the AI lingers in.
            # Qualification -> Recommendation is a separate, explicit
            # transition gated by BuyerProfile completeness (QA-14), fired
            # from `recommendation.wiring.handle_profile_completed` — never
            # here, since the FSM only owns lifecycle shape, not that
            # business rule (§7.8, ArchitecturalDrivers Decision Table row).
            conversation.transition_to(
                ConversationState.QUALIFICATION,
                reason="Ownership assigned to AI; beginning conversational qualification",
            )

        scheduling = await self._scheduling_turn(conversation, text, recorder)
        if scheduling is not None and scheduling.outcome != "no_slot":
            # `guard_reply` polices LLM output for hallucinated property
            # links (link_guard.py docstring) — this message is deterministic,
            # service-composed text (the booking confirmation's `meet_link`
            # comes straight from `GoogleCalendarPort`, the fallback messages
            # are static strings), never LLM free text, so it bypasses the
            # guard the same way the real Top-3 message already does
            # (`recommendation.wiring`, per that docstring's own note).
            response = scheduling.response or ""
            conversation.record_event(
                ResponseReady(
                    organization_id=conversation.organization_id,
                    conversation_id=str(conversation.id),
                    chatwoot_conversation_id=conversation.chatwoot_conversation_id,
                    response=response,
                )
            )
            return response

        system_prompt = await self._load_system_prompt(conversation.organization_id)
        grounding_note = await self._build_grounding_note(conversation, recorder)
        if grounding_note:
            system_prompt = f"{system_prompt}\n\n{grounding_note}"
        response = await self._responder.respond(
            system_prompt=system_prompt, conversation_id=conversation.id, text=text
        )
        if qualification is not None and qualification.reprompts:
            # An extractor saw a signal but couldn't validate it (e.g. a broken
            # budget) — its re-prompt IS the right reply this turn. The
            # responder still ran so the checkpointed history stays contiguous.
            response = qualification.reprompts[0]
        if ask_identity:
            # G8 gate: no Lead linked yet — the reply asks for the contact's
            # name (mutually exclusive with qualification re-prompts, which
            # require a linked lead).
            response = REPROMPT_IDENTITY
        response = await guard_reply(
            self._session, organization_id=conversation.organization_id, reply=response
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

    async def _scheduling_turn(self, conversation: Conversation, text: str, recorder):
        """US-212: only meaningful in `RECOMMENDATION` — aditive-only, same
        gating posture as `_build_grounding_note`. A successful booking
        transitions the FSM to `APPOINTMENT`; every other non-`no_slot`
        outcome overrides this turn's reply with a deterministic message
        (design.md Decision 5) so the LLM never gets a chance to claim a
        visit is booked when it isn't."""
        if conversation.state is not ConversationState.RECOMMENDATION:
            return None
        result = await run_scheduling_turn(self._session, conversation=conversation, text=text)
        if result.outcome == "no_slot":
            return result
        if recorder is not None:
            recorder.record_tool_call("scheduling.run_turn", {"text": text}, result.outcome)
        if result.outcome == "booked":
            conversation.transition_to(
                ConversationState.APPOINTMENT,
                reason="SchedulingService.book_visit succeeded",
            )
        return result

    async def _build_grounding_note(
        self,
        conversation: Conversation,
        recorder,
    ) -> str | None:
        """US-hallucination-fix (2026-07-24, CW-DEMO-1784860599/MSG-0010): a
        lead asked for a property under a budget with zero Supabase matches
        and the conversational brain — which never queries `properties` —
        invented two listings with fake links.

        2026-07-25 follow-up (same conversation, later turn): the original
        fix only ran this check on the turn that just captured budget/zone.
        The very next turn — no new dimension, so no grounding — the LLM,
        primed by its *own* prior "en breve tendrás el Top-3" line, invented
        three full listings with prices and addresses (no links this time,
        so the link guard never saw it). Gate on conversation stage instead
        of "did this turn's message carry a new signal": every Qualification
        turn where the profile already has a budget or a zone re-runs the
        real structured filter, until Recommendation takes over (the
        `RecommendationService`'s own real Top-3) and this stops being
        needed."""
        if conversation.lead_id is None or conversation.state is not ConversationState.QUALIFICATION:
            return None
        try:
            profile = await BuyerProfileRepository(self._session).get_by_lead_id(
                conversation.lead_id
            )
            if profile is None or (profile.budget is None and not profile.locations):
                return None
            diagnosis = await diagnose(
                PropertyRepository(self._session),
                organization_id=conversation.organization_id,
                budget=profile.budget,
                zones=profile.locations,
                property_type=profile.property_type,
            )
        except Exception:  # noqa: BLE001 — grounding must never break the turn
            logger.exception(
                "Search diagnostics failed for conversation %s; continuing without grounding",
                conversation.id,
            )
            return None
        if diagnosis is None:
            return None
        if recorder is not None:
            recorder.record_tool_call(
                "recommendation.diagnose_search",
                {"budget": str(diagnosis.budget), "zones": diagnosis.zones},
                (
                    "has_matches"
                    if diagnosis.has_matches
                    else ("zone_mismatch" if diagnosis.zone_mismatch else "price_mismatch")
                ),
            )
        return render_grounding_note(diagnosis)

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
        return DEFAULT_SYSTEM_PROMPT
