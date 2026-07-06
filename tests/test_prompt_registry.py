import uuid

import pytest


async def _create_org_and_login(client) -> tuple[str, str]:
    org_resp = await client.post("/api/v1/organizations", json={"name": "Acme Realty"})
    org_id = org_resp.json()["id"]
    email = f"admin-{uuid.uuid4()}@acme.com"
    await client.post(
        "/api/v1/auth/register",
        json={"organization_id": org_id, "email": email, "password": "s3cret-pw"},
    )
    login_resp = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": "s3cret-pw"}
    )
    return org_id, login_resp.json()["access_token"]


@pytest.mark.asyncio
async def test_publish_and_fetch_active_prompt(client):
    _, token = await _create_org_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}

    publish_resp = await client.post(
        "/api/v1/prompts",
        headers=headers,
        json={
            "agent_name": "coordinator",
            "version": "v1",
            "content": "You are the Coordinator...",
        },
    )
    assert publish_resp.status_code == 201

    active_resp = await client.get("/api/v1/prompts/coordinator/active", headers=headers)
    assert active_resp.status_code == 200
    assert active_resp.json()["version"] == "v1"


@pytest.mark.asyncio
async def test_publishing_new_version_deactivates_previous(client):
    _, token = await _create_org_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}

    await client.post(
        "/api/v1/prompts",
        headers=headers,
        json={"agent_name": "coordinator", "version": "v1", "content": "prompt v1"},
    )
    await client.post(
        "/api/v1/prompts",
        headers=headers,
        json={"agent_name": "coordinator", "version": "v2", "content": "prompt v2"},
    )

    active_resp = await client.get("/api/v1/prompts/coordinator/active", headers=headers)
    assert active_resp.json()["version"] == "v2"


@pytest.mark.asyncio
async def test_missing_active_prompt_returns_404(client):
    _, token = await _create_org_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}
    resp = await client.get("/api/v1/prompts/unknown-agent/active", headers=headers)
    assert resp.status_code == 404
