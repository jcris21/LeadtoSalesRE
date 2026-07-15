"""Domain model of the Conversation Memory bounded context (AI-102, Sprint
2.1).

`ConversationMemoryObservation` captures free-text conversational signal
(style adjectives, family context — see `MemoryType`) that is structurally
different from `lead_qualification.BuyerProfile`'s closed-enum/range
dimensions: it runs in parallel to `PROFILE_DIMENSIONS`, never overwrites it,
and is append-only (a lead can raise the same signal more than once, each is
its own row) — see
`openspec/changes/conversation-memory-extraction-ai-102/design.md`.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from app.shared.domain.base import Entity, new_id, utcnow


class MemoryType(StrEnum):
    """Category of a free-text conversational observation. `TONE` is a
    placeholder for a future extractor (see design.md Decision 2) — no
    extraction branch targets it in this change."""

    STYLE_PREFERENCE = "style_preference"
    FAMILY_CONTEXT = "family_context"
    TONE = "tone"


class ConversationMemoryObservation(Entity):
    """One free-text signal extracted from a lead's message. Append-only —
    never updated or deleted, and never merged into `BuyerProfile`."""

    def __init__(
        self,
        *,
        id: uuid.UUID | None = None,
        conversation_id: uuid.UUID,
        lead_id: uuid.UUID,
        organization_id: uuid.UUID,
        memory_type: MemoryType,
        entity_name: str,
        value: dict,
        confidence: float,
        created_at: datetime | None = None,
    ) -> None:
        self.id = id or new_id()
        self.conversation_id = conversation_id
        self.lead_id = lead_id
        self.organization_id = organization_id
        self.memory_type = memory_type
        self.entity_name = entity_name
        self.value = value
        self.confidence = confidence
        self.created_at = created_at or utcnow()
