"""Lead Linker — resolves which Lead a Conversation belongs to (Sprint 3).

Chatwoot and wacrm are two independent external systems with no shared
identifier of their own; `contact_reference` (the WhatsApp phone number, see
webhook_router._extract_contact_reference) is the one value both sides
happen to expose, so it is the sole matching key. A Conversation may exist
for a while with `lead_id=None` if wacrm hasn't synced that lead yet (§7.7
CDC is eventually consistent) — that's expected, not an error; recommendation
and appointment features simply stay unavailable for that lead until the
next successful match.

Cross-module read (this module reads `lead_qualification.LeadRepository`)
follows the same precedent as `CoordinatorAgent._load_system_prompt` reading
`intelligence_ai_admin.PromptRegistryRepository` — repositories, not events,
for on-demand lookups within a single request/handler transaction.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.conversation_ownership.domain.models import Conversation
from app.modules.lead_qualification.infrastructure.repository import LeadRepository


class LeadLinker:
    def __init__(self, session: AsyncSession) -> None:
        self._leads = LeadRepository(session)

    async def link_if_possible(self, conversation: Conversation) -> uuid.UUID | None:
        """Best-effort: sets `conversation.lead_id` when a matching Lead is
        already mirrored locally. Never raises — an unresolved link is a
        normal, temporary state, not a failure the caller should handle."""
        if conversation.lead_id is not None:
            return conversation.lead_id
        if not conversation.contact_reference:
            return None

        lead = await self._leads.get_by_contact_reference(
            conversation.organization_id, conversation.contact_reference
        )
        if lead is None:
            return None

        conversation.link_lead(lead.id)
        return lead.id
