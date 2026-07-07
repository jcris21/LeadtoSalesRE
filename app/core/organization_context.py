"""Single enforcement point for `organizationId` resolution (Architecture.md
§7.1, Sprint 0): every request is bound to at most one organization before any
router runs, instead of each router re-deriving it ad hoc.

Resolution order:

1. Bearer JWT `org` claim (admin/broker API) — invalid or absent tokens resolve
   to nothing here; rejecting them stays the job of the auth dependency, this
   middleware never turns a bad token into a 500.
2. Chatwoot webhook path (`/webhooks/chatwoot/{organization_id}`) — the URL is
   configured per organization in Chatwoot (QA-03).

The resolved id is exposed through a ContextVar so repositories, observability
and the RLS hook (`SET LOCAL app.current_organization_id`, when the backend
moves off the BYPASSRLS role) all read the same source of truth.
"""

from __future__ import annotations

import re
import uuid
from contextvars import ContextVar

from fastapi import HTTPException, status
from jose import JWTError, jwt

from app.core.config import get_settings

_current_organization_id: ContextVar[uuid.UUID | None] = ContextVar(
    "current_organization_id", default=None
)

_WEBHOOK_ORG_PATTERN = re.compile(r"/webhooks/chatwoot/(?P<org>[0-9a-fA-F-]{36})(?:/|$)")


def current_organization_id() -> uuid.UUID | None:
    """The organization the current request resolved to, if any."""
    return _current_organization_id.get()


def require_organization_id() -> uuid.UUID:
    """FastAPI dependency: the request MUST be bound to an organization."""
    organization_id = _current_organization_id.get()
    if organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Request is not bound to an organization",
        )
    return organization_id


def resolve_organization_id(*, authorization: str | None, path: str) -> uuid.UUID | None:
    """Pure resolution logic (unit-testable without ASGI plumbing)."""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        settings = get_settings()
        try:
            payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
            return uuid.UUID(payload["org"])
        except (JWTError, KeyError, ValueError):
            # Malformed/forged tokens are the auth dependency's 401, not ours.
            pass

    match = _WEBHOOK_ORG_PATTERN.search(path)
    if match:
        try:
            return uuid.UUID(match.group("org"))
        except ValueError:
            pass
    return None


class OrganizationContextMiddleware:
    """Pure ASGI middleware: resolves the organization once per request and
    guarantees the ContextVar never leaks across requests."""

    def __init__(self, app) -> None:  # noqa: ANN001 - ASGI app callable
        self._app = app

    async def __call__(self, scope, receive, send) -> None:  # noqa: ANN001 - ASGI signature
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        headers = {
            name.decode("latin-1").lower(): value.decode("latin-1")
            for name, value in scope.get("headers", [])
        }
        organization_id = resolve_organization_id(
            authorization=headers.get("authorization"), path=scope.get("path", "")
        )
        token = _current_organization_id.set(organization_id)
        try:
            await self._app(scope, receive, send)
        finally:
            _current_organization_id.reset(token)
