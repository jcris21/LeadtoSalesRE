import uuid

import pytest


async def _create_org_and_login(client, name: str = "Acme Realty") -> tuple[str, str]:
    org_resp = await client.post("/api/v1/organizations", json={"name": name})
    org_id = org_resp.json()["id"]
    email = f"admin-{uuid.uuid4()}@acme.com"
    await client.post(
        "/api/v1/auth/register",
        json={"organization_id": org_id, "email": email, "password": "s3cret-pw"},
    )
    login_resp = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": "s3cret-pw"}
    )
    token = login_resp.json()["access_token"]
    return org_id, token


@pytest.mark.asyncio
async def test_create_organization_starts_onboarding(client):
    resp = await client.post("/api/v1/organizations", json={"name": "New Agency"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "onboarding"


@pytest.mark.asyncio
async def test_get_organization_requires_matching_principal(client):
    org_id, token = await _create_org_and_login(client)
    other_org_id, other_token = await _create_org_and_login(client, name="Other Agency")

    resp = await client.get(
        f"/api/v1/organizations/{org_id}", headers={"Authorization": f"Bearer {other_token}"}
    )
    assert resp.status_code == 403

    resp_ok = await client.get(
        f"/api/v1/organizations/{org_id}", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp_ok.status_code == 200
    assert resp_ok.json()["id"] == org_id


@pytest.mark.asyncio
async def test_upsert_config_activates_org_once_complete(client):
    org_id, token = await _create_org_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.put(
        f"/api/v1/organizations/{org_id}/config",
        headers=headers,
        json={
            "chatwoot": {
                "inbox_id": "1",
                "account_id": "1",
                "api_access_token": "tok",
                "base_url": "http://localhost:3000",
            },
            "whatsapp": {
                "phone_number_id": "123",
                "business_account_id": "456",
                "access_token": "wa-tok",
            },
            "crm": {"base_url": "http://localhost:8080", "api_key": "key", "tenant_ref": "acme"},
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_complete_for_activation"] is True

    org_resp = await client.get(f"/api/v1/organizations/{org_id}", headers=headers)
    assert org_resp.json()["status"] == "active"


@pytest.mark.asyncio
async def test_upsert_partial_config_does_not_activate(client):
    org_id, token = await _create_org_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.put(
        f"/api/v1/organizations/{org_id}/config",
        headers=headers,
        json={
            "chatwoot": {
                "inbox_id": "1",
                "account_id": "1",
                "api_access_token": "tok",
                "base_url": "http://localhost:3000",
            }
        },
    )
    assert resp.status_code == 200
    assert resp.json()["is_complete_for_activation"] is False

    org_resp = await client.get(f"/api/v1/organizations/{org_id}", headers=headers)
    assert org_resp.json()["status"] == "onboarding"
