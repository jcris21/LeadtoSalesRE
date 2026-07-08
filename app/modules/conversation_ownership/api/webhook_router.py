"""Inbound half of the Chatwoot Webhook Adapter (Anti-Corruption Layer).

Translates Chatwoot webhook payloads into our own domain events and acks
immediately (<1s, QA-01): the handler only upserts the Conversation projection,
archives the raw message (Sprint 1 deliverable, E10 corpus) and writes
MessageReceived to the outbox — all in one transaction. The Coordinator
processes asynchronously via the Event Bus worker (Architecture.md §7.4).

The webhook URL carries the organization_id (configured per organization in
Chatwoot), keeping isolation explicit (QA-03). Non-message events and outgoing/
private messages are acked and ignored — Chatwoot remains SoR for them.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.conversation_ownership.application.lead_linker import LeadLinker
from app.modules.conversation_ownership.domain.models import Channel, Conversation, MessageReceived
from app.modules.conversation_ownership.infrastructure.repository import (
    ConversationRepository,
    MessageArchiveRepository,
)
from app.modules.organization.infrastructure.db_models import OrganizationORM
from app.shared.infrastructure import event_bus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/chatwoot/{organization_id}", status_code=status.HTTP_200_OK)
async def receive_chatwoot_webhook(
    organization_id: uuid.UUID,
    payload: dict,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, str]:
    org = await session.get(OrganizationORM, organization_id)
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown organization")

    if payload.get("event") != "message_created":
        return {"status": "ignored", "reason": "unsupported event"}
    if payload.get("message_type") != "incoming" or payload.get("private", False):
        return {"status": "ignored", "reason": "not an incoming lead message"}

    chatwoot_conversation_id = str(_dig(payload, "conversation", "id") or "")
    chatwoot_message_id = str(payload.get("id") or "")
    if not chatwoot_conversation_id or not chatwoot_message_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Payload missing conversation.id or message id",
        )
    text = payload.get("content") or ""
    sender = str(_dig(payload, "sender", "name") or "lead")
    created_at = _parse_timestamp(payload.get("created_at"))

    conversations = ConversationRepository(session)
    conversation = await conversations.get_by_chatwoot_id(organization_id, chatwoot_conversation_id)
    if conversation is None:
        conversation = Conversation(
            organization_id=organization_id,
            chatwoot_conversation_id=chatwoot_conversation_id,
            channel=_channel_from_payload(payload),
            contact_reference=_extract_contact_reference(payload),
        )
    else:
        conversation.touch(created_at)

    if conversation.lead_id is None:
        # Best-effort re-check on every turn: wacrm's CDC sync is eventually
        # consistent, so a lead absent at conversation-creation time may have
        # landed locally since (§7.7) — cheap to retry, no-op if still absent.
        await LeadLinker(session).link_if_possible(conversation)
    await conversations.save(conversation)

    archive = MessageArchiveRepository(session)
    newly_archived = await archive.archive(
        organization_id=organization_id,
        conversation_id=conversation.id,
        chatwoot_message_id=chatwoot_message_id,
        sender=sender,
        content=text,
        raw_payload=payload,
        message_timestamp=created_at,
    )
    if not newly_archived:
        # Chatwoot re-delivered a webhook we already processed — idempotent no-op.
        return {"status": "duplicate"}

    await event_bus.publish(
        session,
        [
            MessageReceived(
                organization_id=organization_id,
                conversation_id=str(conversation.id),
                chatwoot_conversation_id=chatwoot_conversation_id,
                sender=sender,
                text=text,
                message_timestamp=created_at.isoformat(),
            )
        ],
    )
    await session.commit()
    return {"status": "accepted"}


def _dig(payload: dict, *keys: str) -> object:
    node: object = payload
    for key in keys:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def _parse_timestamp(raw: object) -> datetime:
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(raw, tz=UTC)
    if isinstance(raw, str):
        try:
            parsed = datetime.fromisoformat(raw)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            logger.warning("Unparseable Chatwoot timestamp %r; using now()", raw)
    return datetime.now(UTC)


def _extract_contact_reference(payload: dict) -> str | None:
    """The identifier shared with wacrm's Lead.contact_reference (Sprint 3
    identity matching) — a WhatsApp sender's phone number, or a generic
    contact identifier for non-WhatsApp channels."""
    phone = _dig(payload, "sender", "phone_number")
    if phone:
        return str(phone)
    identifier = _dig(payload, "sender", "identifier")
    return str(identifier) if identifier else None


def _channel_from_payload(payload: dict) -> Channel:
    channel_raw = str(_dig(payload, "conversation", "channel") or "").lower()
    if "whatsapp" in channel_raw:
        return Channel.WHATSAPP
    if "web" in channel_raw:
        return Channel.WEB
    return Channel.OTHER
