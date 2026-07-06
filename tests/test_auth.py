import uuid

import pytest


@pytest.mark.asyncio
async def test_register_and_login(client):
    org_resp = await client.post("/api/v1/organizations", json={"name": "Acme Realty"})
    assert org_resp.status_code == 201
    org_id = org_resp.json()["id"]

    register_resp = await client.post(
        "/api/v1/auth/register",
        json={"organization_id": org_id, "email": "broker@acme.com", "password": "s3cret-pw"},
    )
    assert register_resp.status_code == 201

    login_resp = await client.post(
        "/api/v1/auth/login", json={"email": "broker@acme.com", "password": "s3cret-pw"}
    )
    assert login_resp.status_code == 200
    body = login_resp.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]


@pytest.mark.asyncio
async def test_login_wrong_password_rejected(client):
    org_resp = await client.post("/api/v1/organizations", json={"name": "Acme Realty"})
    org_id = org_resp.json()["id"]
    await client.post(
        "/api/v1/auth/register",
        json={"organization_id": org_id, "email": "broker2@acme.com", "password": "correct-pw"},
    )

    resp = await client.post(
        "/api/v1/auth/login", json={"email": "broker2@acme.com", "password": "wrong-pw"}
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_register_duplicate_email_conflicts(client):
    org_resp = await client.post("/api/v1/organizations", json={"name": "Acme Realty"})
    org_id = org_resp.json()["id"]
    payload = {"organization_id": org_id, "email": "dup@acme.com", "password": "pw12345678"}
    first = await client.post("/api/v1/auth/register", json=payload)
    second = await client.post("/api/v1/auth/register", json=payload)
    assert first.status_code == 201
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_get_current_principal_rejects_missing_token(client):
    resp = await client.get(f"/api/v1/organizations/{uuid.uuid4()}")
    assert resp.status_code == 401
