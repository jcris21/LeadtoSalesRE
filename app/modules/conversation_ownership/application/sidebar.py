"""AI Sidebar Publisher — publishes state, ownership and explanations to
Chatwoot for the human broker (Architecture.md §6.1). Surface: private notes on
the conversation, visible only to agents in Chatwoot, never to the lead.

Explainability by construction (QA-11): this reads first-class explanation
fields (OwnershipDecision.explanation, Ownership.reason) — it never derives
text from logs.
"""

from __future__ import annotations

import logging

from app.modules.conversation_ownership.application.ownership_policy import OwnershipDecision
from app.modules.conversation_ownership.domain.models import Conversation
from app.modules.conversation_ownership.infrastructure.chatwoot_client import (
    ChatwootClient,
    ChatwootSendError,
)

logger = logging.getLogger(__name__)

_OWNER_LABEL = {"ai": "🤖 AI", "human": "👤 Broker humano", "unassigned": "— Sin asignar"}


def build_sidebar_note(
    conversation: Conversation, decision: OwnershipDecision | None = None
) -> str:
    """Render the sidebar block for one conversation update."""
    lines = [
        "**AI Sidebar**",
        f"Estado: `{conversation.state.value}`",
        f"Owner: {_OWNER_LABEL.get(conversation.ownership.owner_type.value, '?')}",
        f"Motivo: {conversation.ownership.reason}",
    ]
    if decision is not None:
        lines.append(f"Decisión de ownership ({decision.scenario}): {decision.explanation}")
    return "\n".join(lines)


class SidebarPublisher:
    def __init__(self, client: ChatwootClient):
        self._client = client

    async def publish(
        self, conversation: Conversation, decision: OwnershipDecision | None = None
    ) -> None:
        """Best-effort: a sidebar failure must never fail the business operation
        that produced the state change (same contract as TracePort)."""
        note = build_sidebar_note(conversation, decision)
        try:
            await self._client.send_private_note(conversation.chatwoot_conversation_id, note)
        except ChatwootSendError:
            logger.exception(
                "Sidebar publish failed", extra={"conversation_id": str(conversation.id)}
            )
