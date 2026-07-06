"""Event-bus wiring for the Conversation & Ownership module (Sprint 1).

Registers the module's consumers on the shared EventBusWorker:

- MessageReceived  -> Coordinator Agent (async reasoning, §7.4)
- ResponseReady    -> Chatwoot Webhook Adapter outbound (send_message)

Handlers open their own session: the worker guarantees at-least-once delivery
and inbox idempotency; each handler owns its transaction.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session_factory
from app.modules.conversation_ownership.application.coordinator import CoordinatorAgent
from app.modules.conversation_ownership.application.sidebar import SidebarPublisher
from app.modules.conversation_ownership.infrastructure.chatwoot_client import ChatwootClient
from app.modules.organization.infrastructure.repository import OrganizationConfigRepository
from app.shared.infrastructure.event_bus import EventBusWorker

logger = logging.getLogger(__name__)


async def _chatwoot_client_for(
    session: AsyncSession, organization_id: uuid.UUID
) -> ChatwootClient | None:
    config = await OrganizationConfigRepository(session).get(organization_id)
    if config is None or config.chatwoot is None:
        logger.error("Organization %s has no Chatwoot config", organization_id)
        return None
    return ChatwootClient(config.chatwoot)


async def handle_message_received(payload: dict) -> None:
    fields = payload["fields"]
    organization_id = uuid.UUID(payload["organization_id"])
    conversation_id = uuid.UUID(fields["conversation_id"])

    async with get_session_factory()() as session:
        client = await _chatwoot_client_for(session, organization_id)
        sidebar = SidebarPublisher(client) if client is not None else None
        coordinator = CoordinatorAgent(session, sidebar=sidebar)
        await coordinator.handle_message(
            organization_id=organization_id,
            conversation_id=conversation_id,
            text=fields.get("text", ""),
        )


async def handle_response_ready(payload: dict) -> None:
    fields = payload["fields"]
    organization_id = uuid.UUID(payload["organization_id"])

    async with get_session_factory()() as session:
        client = await _chatwoot_client_for(session, organization_id)
    if client is None:
        return  # logged above; nothing to send without config
    await client.send_message(fields["chatwoot_conversation_id"], fields["response"])


def register_event_handlers(worker: EventBusWorker) -> None:
    worker.register(
        "MessageReceived", "conversation_ownership.coordinator", handle_message_received
    )
    worker.register(
        "ResponseReady", "conversation_ownership.chatwoot_sender", handle_response_ready
    )
