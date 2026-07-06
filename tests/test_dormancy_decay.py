"""Dormancy decay job: inactive conversations decay to Dormant and emit
ConversationWentDormant; active ones are untouched."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.modules.conversation_ownership.application.decay import decay_inactive_conversations
from app.modules.conversation_ownership.domain.models import Conversation, ConversationState
from app.modules.conversation_ownership.infrastructure.db_models import ConversationORM
from app.modules.conversation_ownership.infrastructure.repository import ConversationRepository
from app.modules.organization.infrastructure.db_models import OrganizationORM
from app.shared.domain.base import new_id, utcnow
from app.shared.infrastructure.db_models import OutboxEventORM


@pytest.mark.asyncio
async def test_decay_marks_only_inactive_conversations(session_factory):
    org_id = new_id()
    async with session_factory() as session:
        session.add(OrganizationORM(id=org_id, name="Org", status="active", created_at=utcnow()))
        repo = ConversationRepository(session)

        stale = Conversation(
            organization_id=org_id,
            chatwoot_conversation_id="1",
            state=ConversationState.QUALIFICATION,
            last_contact_at=utcnow() - timedelta(hours=100),
        )
        fresh = Conversation(
            organization_id=org_id,
            chatwoot_conversation_id="2",
            state=ConversationState.QUALIFICATION,
            last_contact_at=utcnow(),
        )
        closed_old = Conversation(
            organization_id=org_id,
            chatwoot_conversation_id="3",
            state=ConversationState.CLOSED_WON,
            last_contact_at=utcnow() - timedelta(hours=500),
        )
        for convo in (stale, fresh, closed_old):
            await repo.add(convo)
        await session.commit()

    async with session_factory() as session:
        decayed = await decay_inactive_conversations(session)
        await session.commit()
    assert decayed == 1

    async with session_factory() as session:
        rows = {
            r.chatwoot_conversation_id: r.state
            for r in (await session.execute(select(ConversationORM))).scalars()
        }
        assert rows["1"] == "Dormant"
        assert rows["2"] == "Qualification"
        assert rows["3"] == "ClosedWon"

        dormant_events = (
            (
                await session.execute(
                    select(OutboxEventORM).where(
                        OutboxEventORM.event_type == "ConversationWentDormant"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(dormant_events) == 1
