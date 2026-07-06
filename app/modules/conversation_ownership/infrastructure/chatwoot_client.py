"""Outbound half of the Chatwoot Webhook Adapter (Anti-Corruption Layer).

`ChatwootWebhookPort.send` — delivers Coordinator responses back to Chatwoot,
and posts AI Sidebar content as private notes (visible to brokers, never to the
lead). Fails with retry/backoff; never blocks the conversation flow
(Architecture.md §8, Iteración 2 ports).
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from app.modules.organization.domain.models import ChatwootConfig

logger = logging.getLogger(__name__)

_MAX_ATTEMPTS = 3
_BACKOFF_BASE_SECONDS = 0.5


class ChatwootSendError(Exception):
    """Raised when Chatwoot rejects the message after all retries."""


class ChatwootClient:
    """Thin async client for the Chatwoot application API, scoped to one
    organization's ChatwootConfig (per-org inbox/account/token, QA-03)."""

    def __init__(self, config: ChatwootConfig, *, timeout_seconds: float = 10.0):
        self._config = config
        self._timeout = timeout_seconds

    async def send_message(self, chatwoot_conversation_id: str, content: str) -> None:
        """Public reply the lead sees on WhatsApp."""
        await self._post_message(chatwoot_conversation_id, content, private=False)

    async def send_private_note(self, chatwoot_conversation_id: str, content: str) -> None:
        """AI Sidebar surface: private note only brokers see in Chatwoot."""
        await self._post_message(chatwoot_conversation_id, content, private=True)

    async def _post_message(
        self, chatwoot_conversation_id: str, content: str, *, private: bool
    ) -> None:
        url = (
            f"{self._config.base_url.rstrip('/')}/api/v1/accounts/{self._config.account_id}"
            f"/conversations/{chatwoot_conversation_id}/messages"
        )
        payload = {"content": content, "message_type": "outgoing", "private": private}
        headers = {"api_access_token": self._config.api_access_token}

        last_error: Exception | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.post(url, json=payload, headers=headers)
                    response.raise_for_status()
                    return
            except httpx.HTTPError as exc:
                last_error = exc
                logger.warning(
                    "Chatwoot send failed (attempt %d/%d)",
                    attempt,
                    _MAX_ATTEMPTS,
                    extra={"conversation": chatwoot_conversation_id, "error": str(exc)},
                )
                if attempt < _MAX_ATTEMPTS:
                    await asyncio.sleep(_BACKOFF_BASE_SECONDS * 2 ** (attempt - 1))
        raise ChatwootSendError(
            f"Chatwoot rejected message for conversation {chatwoot_conversation_id}"
        ) from last_error
