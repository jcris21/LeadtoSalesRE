"""Repository translating between the Conversation aggregate and its ORM rows,
plus the raw-message archive and ownership-decision writers."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.conversation_ownership.domain.models import (
    Channel,
    Conversation,
    ConversationState,
    Ownership,
    OwnerType,
)
from app.modules.conversation_ownership.infrastructure.db_models import (
    ArchivedMessageORM,
    ConversationORM,
    OwnershipDecisionORM,
)
from app.shared.domain.base import new_id, utcnow


class ConversationRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def add(self, conversation: Conversation) -> None:
        self._session.add(self._to_row(conversation))

    async def get(self, conversation_id: uuid.UUID) -> Conversation | None:
        row = await self._session.get(ConversationORM, conversation_id)
        return self._to_domain(row) if row is not None else None

    async def get_by_chatwoot_id(
        self, organization_id: uuid.UUID, chatwoot_conversation_id: str
    ) -> Conversation | None:
        result = await self._session.execute(
            select(ConversationORM).where(
                ConversationORM.organization_id == organization_id,
                ConversationORM.chatwoot_conversation_id == chatwoot_conversation_id,
            )
        )
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row is not None else None

    async def get_by_lead_id(
        self, organization_id: uuid.UUID, lead_id: uuid.UUID
    ) -> Conversation | None:
        """Resolves the conversation to deliver a Recommendation/Appointment
        message to, once the Coordinator only has a `lead_id` (e.g. reacting
        to `ProfileCompleted`). None means no conversation has linked this
        lead yet."""
        result = await self._session.execute(
            select(ConversationORM).where(
                ConversationORM.organization_id == organization_id,
                ConversationORM.lead_id == lead_id,
            )
        )
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row is not None else None

    async def save(self, conversation: Conversation) -> None:
        row = await self._session.get(ConversationORM, conversation.id)
        if row is None:
            await self.add(conversation)
            return
        row.state = conversation.state.value
        row.owner_type = conversation.ownership.owner_type.value
        row.owner_id = conversation.ownership.owner_id
        row.owner_since = conversation.ownership.since
        row.owner_reason = conversation.ownership.reason
        row.last_contact_at = conversation.last_contact_at
        row.contact_reference = conversation.contact_reference
        row.lead_id = conversation.lead_id

    async def list_inactive_since(
        self, cutoff: datetime, active_states: frozenset[ConversationState]
    ) -> list[Conversation]:
        """Conversations whose last lead activity predates `cutoff` — the decay
        job's scan (ConversationStateMachinePort.decayToDormant)."""
        result = await self._session.execute(
            select(ConversationORM).where(
                ConversationORM.last_contact_at < cutoff,
                ConversationORM.state.in_([s.value for s in active_states]),
            )
        )
        return [self._to_domain(row) for row in result.scalars().all()]

    @staticmethod
    def _to_row(conversation: Conversation) -> ConversationORM:
        return ConversationORM(
            id=conversation.id,
            organization_id=conversation.organization_id,
            chatwoot_conversation_id=conversation.chatwoot_conversation_id,
            channel=conversation.channel.value,
            state=conversation.state.value,
            owner_type=conversation.ownership.owner_type.value,
            owner_id=conversation.ownership.owner_id,
            owner_since=conversation.ownership.since,
            owner_reason=conversation.ownership.reason,
            last_contact_at=conversation.last_contact_at,
            contact_reference=conversation.contact_reference,
            lead_id=conversation.lead_id,
            created_at=conversation.created_at,
        )

    @staticmethod
    def _to_domain(row: ConversationORM) -> Conversation:
        return Conversation(
            id=row.id,
            organization_id=row.organization_id,
            chatwoot_conversation_id=row.chatwoot_conversation_id,
            channel=Channel(row.channel),
            state=ConversationState(row.state),
            ownership=Ownership(
                owner_type=OwnerType(row.owner_type),
                owner_id=row.owner_id,
                since=row.owner_since,
                reason=row.owner_reason,
            ),
            last_contact_at=row.last_contact_at,
            contact_reference=row.contact_reference,
            lead_id=row.lead_id,
            created_at=row.created_at,
        )


class MessageArchiveRepository:
    """Raw conversation archiving (Sprint 1 deliverable — E10 corpus)."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def archive(
        self,
        *,
        organization_id: uuid.UUID,
        conversation_id: uuid.UUID,
        chatwoot_message_id: str,
        sender: str,
        content: str,
        raw_payload: dict,
        message_timestamp: datetime,
    ) -> bool:
        """Idempotent by (conversation_id, chatwoot_message_id): re-delivered
        webhooks are a no-op. Returns False when the message was already archived."""
        result = await self._session.execute(
            select(ArchivedMessageORM.id).where(
                ArchivedMessageORM.conversation_id == conversation_id,
                ArchivedMessageORM.chatwoot_message_id == chatwoot_message_id,
            )
        )
        if result.scalar_one_or_none() is not None:
            return False
        self._session.add(
            ArchivedMessageORM(
                id=new_id(),
                organization_id=organization_id,
                conversation_id=conversation_id,
                chatwoot_message_id=chatwoot_message_id,
                sender=sender,
                content=content,
                raw_payload=raw_payload,
                message_timestamp=message_timestamp,
                archived_at=utcnow(),
            )
        )
        return True


class OwnershipDecisionRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def add(
        self,
        *,
        organization_id: uuid.UUID,
        conversation_id: uuid.UUID,
        scenario: str,
        inputs_snapshot: dict,
        selected_owner: str,
        owner_id: uuid.UUID | None,
        explanation: str,
    ) -> uuid.UUID:
        decision_id = new_id()
        self._session.add(
            OwnershipDecisionORM(
                id=decision_id,
                organization_id=organization_id,
                conversation_id=conversation_id,
                scenario=scenario,
                inputs_snapshot=inputs_snapshot,
                selected_owner=selected_owner,
                owner_id=owner_id,
                explanation=explanation,
                decided_at=utcnow(),
            )
        )
        return decision_id
