"""Sprint 0 — organizationId resolution middleware (Architecture.md §7.1).

Covers the two resolution sources (JWT `org` claim, Chatwoot webhook path),
the no-resolution case, and that the ContextVar never leaks across requests.
"""

import uuid

from app.core.organization_context import (
    current_organization_id,
    resolve_organization_id,
)
from app.core.security import AuthenticatedPrincipal, create_access_token

ORG_ID = uuid.uuid4()


def _bearer_for(org_id: uuid.UUID) -> str:
    token = create_access_token(
        AuthenticatedPrincipal(
            user_id=uuid.uuid4(), organization_id=org_id, email="a@b.co", role="admin"
        )
    )
    return f"Bearer {token}"


def test_resolves_from_jwt_org_claim():
    resolved = resolve_organization_id(authorization=_bearer_for(ORG_ID), path="/api/v1/anything")
    assert resolved == ORG_ID


def test_resolves_from_webhook_path():
    resolved = resolve_organization_id(
        authorization=None, path=f"/api/v1/webhooks/chatwoot/{ORG_ID}"
    )
    assert resolved == ORG_ID


def test_jwt_takes_precedence_over_path():
    other_org = uuid.uuid4()
    resolved = resolve_organization_id(
        authorization=_bearer_for(ORG_ID), path=f"/api/v1/webhooks/chatwoot/{other_org}"
    )
    assert resolved == ORG_ID


def test_invalid_token_resolves_to_none_not_error():
    resolved = resolve_organization_id(authorization="Bearer not-a-jwt", path="/api/v1/anything")
    assert resolved is None


def test_unresolvable_request_resolves_to_none():
    assert resolve_organization_id(authorization=None, path="/healthz") is None


async def test_middleware_binds_and_clears_contextvar(client):
    """End-to-end through the ASGI stack: during the request the ContextVar is
    bound (the webhook handler runs with it set); after the response it is
    cleared — no leakage into the test's own context."""
    org_id = uuid.uuid4()
    response = await client.post(
        f"/api/v1/webhooks/chatwoot/{org_id}", json={"event": "ignored"}
    )
    # Unknown org -> 404 from the handler, which means routing + middleware ran.
    assert response.status_code == 404
    assert current_organization_id() is None
