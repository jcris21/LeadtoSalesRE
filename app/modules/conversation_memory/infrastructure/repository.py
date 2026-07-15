"""Repository translating between `ConversationMemoryObservation` and its ORM
row (AI-102)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.conversation_memory.domain.models import (
    ConversationMemoryObservation,
    MemoryType,
)
from app.modules.conversation_memory.infrastructure.db_models import ConversationMemoryORM


def _ensure_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


class ConversationMemoryRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def add(self, observation: ConversationMemoryObservation) -> None:
        self._session.add(
            ConversationMemoryORM(
                id=observation.id,
                organization_id=observation.organization_id,
                conversation_id=observation.conversation_id,
                lead_id=observation.lead_id,
                memory_type=observation.memory_type.value,
                entity_name=observation.entity_name,
                value=observation.value,
                confidence=observation.confidence,
                created_at=observation.created_at,
            )
        )

    async def list_for_lead(self, lead_id: uuid.UUID) -> list[ConversationMemoryObservation]:
        result = await self._session.execute(
            select(ConversationMemoryORM)
            .where(ConversationMemoryORM.lead_id == lead_id)
            .order_by(ConversationMemoryORM.created_at)
        )
        return [self._to_domain(row) for row in result.scalars().all()]

    async def list_for_conversation(
        self, conversation_id: uuid.UUID
    ) -> list[ConversationMemoryObservation]:
        result = await self._session.execute(
            select(ConversationMemoryORM)
            .where(ConversationMemoryORM.conversation_id == conversation_id)
            .order_by(ConversationMemoryORM.created_at)
        )
        return [self._to_domain(row) for row in result.scalars().all()]

    @staticmethod
    def _to_domain(row: ConversationMemoryORM) -> ConversationMemoryObservation:
        return ConversationMemoryObservation(
            id=row.id,
            organization_id=row.organization_id,
            conversation_id=row.conversation_id,
            lead_id=row.lead_id,
            memory_type=MemoryType(row.memory_type),
            entity_name=row.entity_name,
            value=row.value,
            confidence=row.confidence,
            created_at=_ensure_utc(row.created_at),
        )
