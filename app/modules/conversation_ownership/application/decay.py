"""Dormancy decay job (`ConversationStateMachinePort.decayToDormant`): evaluates
per-conversation inactivity against the organization-configurable threshold and
transitions to Dormant, emitting ConversationWentDormant for the future
Follow-up Scheduler (Iteración 6). Runs from a scheduled worker loop, never in
the request path (Architecture.md §8)."""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.conversation_ownership.domain.models import _ACTIVE_STATES
from app.modules.conversation_ownership.infrastructure.repository import ConversationRepository
from app.shared.domain.base import utcnow
from app.shared.infrastructure import event_bus

logger = logging.getLogger(__name__)


async def decay_inactive_conversations(session: AsyncSession) -> int:
    """One scan pass. Returns how many conversations decayed. Caller commits."""
    settings = get_settings()
    cutoff = utcnow() - timedelta(hours=settings.dormancy_threshold_hours)

    repo = ConversationRepository(session)
    stale = await repo.list_inactive_since(cutoff, _ACTIVE_STATES)
    for conversation in stale:
        conversation.decay_to_dormant()
        await repo.save(conversation)
        await event_bus.publish(session, conversation.pull_domain_events())
        logger.info(
            "Conversation decayed to Dormant",
            extra={"conversation_id": str(conversation.id)},
        )
    return len(stale)
