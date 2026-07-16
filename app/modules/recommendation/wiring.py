"""Event-bus wiring for the Recommendation module (M4, Sprint 3).

Registers the module's consumer on the shared EventBusWorker:

- ProfileCompleted -> runs the full recommendation pipeline (§7.10) for that
  lead and, if a Conversation is already linked to it (see `LeadLinker`),
  delivers the Top-3 by publishing `ResponseReady` — the same event
  `conversation_ownership.wiring.handle_response_ready` already sends to
  Chatwoot for ordinary conversational replies, so no new delivery mechanism
  is needed here.

Matches Architecture.md's event table (§ "Domain Events"): `ProfileCompleted`
is consumed by both the Lead Sync Adapter (-> wacrm) and Recommendation.
"""

from __future__ import annotations

import logging
import uuid

import httpx

from app.core.database import get_session_factory
from app.modules.conversation_ownership.domain.models import ConversationState, ResponseReady
from app.modules.conversation_ownership.infrastructure.repository import ConversationRepository
from app.modules.lead_qualification.application.completeness_gate import CompletenessGate
from app.modules.lead_qualification.application.lead_sync import LeadNotFoundError
from app.modules.lead_qualification.application.staleness_guard import StalenessGuard
from app.modules.lead_qualification.infrastructure.repository import BuyerProfileRepository
from app.modules.recommendation.application.explanation_generator import ExplanationGenerator
from app.modules.recommendation.application.neighborhood_enrichment import (
    NeighborhoodEnrichmentAdapter,
)
from app.modules.recommendation.application.ranking_engine import WeightedRankingEngine
from app.modules.recommendation.application.recommendation_service import (
    IncompleteProfileError,
    RecommendationService,
)
from app.modules.recommendation.application.retrieval import (
    SemanticRetrievalService,
    StructuredFilterService,
)
from app.modules.recommendation.domain.models import RecommendationResult
from app.modules.recommendation.infrastructure.maps_client import GoogleMapsClient
from app.modules.recommendation.infrastructure.repository import (
    PropertyRepository,
    RecommendationRepository,
)
from app.shared.infrastructure import event_bus
from app.shared.infrastructure.event_bus import EventBusWorker

logger = logging.getLogger(__name__)

_enrichment_adapter: NeighborhoodEnrichmentAdapter | None = None


def _get_enrichment_adapter() -> NeighborhoodEnrichmentAdapter:
    """Process-wide singleton, built lazily on first use (never at import
    time — an event loop must already be running for `httpx.AsyncClient`).

    NeighborhoodEnrichmentAdapter's fire-and-forget background retries
    (§7.12) must outlive any single handler invocation, so the underlying
    http client can't be a per-call context manager (it would close under
    the in-flight retry). No Google Maps API key is wired yet (out of scope
    until Sprint 3B gets credentials) — until then every real call fails
    fast and the adapter's own timeout/fallback degrades gracefully to
    `neighborhood=None`, which is the documented, expected behaviour.
    """
    global _enrichment_adapter
    if _enrichment_adapter is None:
        _enrichment_adapter = NeighborhoodEnrichmentAdapter(
            GoogleMapsClient(httpx.AsyncClient())
        )
    return _enrichment_adapter


def _format_recommendation_message(result: RecommendationResult) -> str:
    """Renders the Top-3 as a plain-text WhatsApp-friendly message. Each
    item's explanation already comes from the Explanation Generator (§7.11);
    this only adds numbering and the neighborhood line when available."""
    if not result.items:
        return (
            "No encontré propiedades que coincidan con tu búsqueda por ahora. "
            "En cuanto tengamos algo que se ajuste, te aviso."
        )
    lines = ["¡Encontré estas opciones para vos!"]
    for item in result.items:
        lines.append(f"\n{item.rank}. {item.explanation}")
        if item.neighborhood is not None and item.neighborhood.nearby_places:
            places = ", ".join(item.neighborhood.nearby_places)
            lines.append(f"   Cerca de: {places}")
    return "\n".join(lines)


async def handle_profile_completed(payload: dict) -> None:
    fields = payload["fields"]
    organization_id = uuid.UUID(payload["organization_id"])
    lead_id = uuid.UUID(fields["lead_id"])

    async with get_session_factory()() as session:
        recommendation_store = RecommendationRepository(session)
        service = RecommendationService(
            buyer_profiles=BuyerProfileRepository(session),
            structured_filter=StructuredFilterService(PropertyRepository(session)),
            semantic_retrieval=SemanticRetrievalService(PropertyRepository(session)),
            ranking_engine=WeightedRankingEngine(),
            explanation=ExplanationGenerator(),
            neighborhood_enrichment=_get_enrichment_adapter(),
            completeness_gate=CompletenessGate(),
            staleness_guard=StalenessGuard(session),
            recommendation_store=recommendation_store,
        )
        try:
            result = await service.search(organization_id=organization_id, lead_id=lead_id)
        except IncompleteProfileError:
            # ProfileCompleted fired, but the gate's own threshold check
            # disagreed (e.g. a lower per-call threshold elsewhere) — nothing
            # to recommend yet, not an error worth failing the outbox delivery.
            logger.info("Recommendation skipped for lead %s: profile incomplete", lead_id)
            return
        except LeadNotFoundError:
            # The Staleness Guard (§7.9) found no Lead mirror to re-sync —
            # the lead was removed/merged after ProfileCompleted fired. There
            # is nothing to recommend against; log and drop rather than fail
            # the outbox delivery for a lead that no longer exists.
            logger.warning(
                "Recommendation skipped for lead %s: Lead not found during staleness check",
                lead_id,
            )
            return

        conversations = ConversationRepository(session)
        conversation = await conversations.get_by_lead_id(organization_id, lead_id)
        if conversation is None:
            logger.info(
                "Recommendation computed for lead %s but no conversation is "
                "linked yet; nothing to deliver",
                lead_id,
            )
            await session.commit()
            return

        if conversation.state is ConversationState.QUALIFICATION:
            # The Specification pattern's verdict (QA-14, §7.8) IS the
            # precondition for this FSM edge — evaluated here, never inside
            # the FSM itself (ArchitecturalDrivers Decision Table: keeps the
            # FSM generic, the business rule lives in its own module).
            conversation.transition_to(
                ConversationState.RECOMMENDATION,
                reason="BuyerProfile completeness threshold reached",
            )
            await conversations.save(conversation)
        elif conversation.state is not ConversationState.RECOMMENDATION:
            # Already past Recommendation (e.g. AssignedHuman, Appointment) or
            # never reached Qualification — the FSM edge doesn't apply, but a
            # re-computed Top-3 is still worth delivering as a message.
            logger.info(
                "Delivering recommendation to conversation %s in state %s "
                "without an FSM transition (not in Qualification)",
                conversation.id,
                conversation.state.value,
            )

        await event_bus.publish(
            session,
            [
                ResponseReady(
                    organization_id=organization_id,
                    conversation_id=str(conversation.id),
                    chatwoot_conversation_id=conversation.chatwoot_conversation_id,
                    response=_format_recommendation_message(result),
                )
            ],
        )
        # US-310 delivery lifecycle: the Top-3 message is now queued on the
        # outbox, so this search's audit rows count as delivered. A result
        # with no items persisted nothing, so there is nothing to stamp.
        if result.items:
            await recommendation_store.mark_delivered(lead_id, result.generated_at)
        await session.commit()


def register_event_handlers(worker: EventBusWorker) -> None:
    worker.register(
        "ProfileCompleted", "recommendation.on_profile_completed", handle_profile_completed
    )
