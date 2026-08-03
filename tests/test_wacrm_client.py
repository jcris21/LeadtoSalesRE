"""Unit tests for the wacrm HTTP client's wire-format handling: Bearer auth,
`{data}` envelope unwrapping, keyset pagination, and the dual-mode
organization_id resolution (real API: from the caller's context; legacy mock
shape: from the payload). All HTTP is faked with httpx.MockTransport."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import httpx
import pytest

from app.modules.lead_qualification.infrastructure.wacrm_client import (
    MAX_LIST_PAGES,
    WacrmClient,
    _parse_snapshot,
    _unwrap,
)

ORG_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
BROKER_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")


def _deal(deal_id: str = "d1", **overrides) -> dict:
    payload = {
        "id": deal_id,
        "pipeline_stage": "Qualified",
        "assigned_broker_id": str(BROKER_ID),
        "updated_at": "2026-07-08T12:00:00Z",
        "contact_reference": "+14155550123",
    }
    payload.update(overrides)
    return payload


def _client_with(handler) -> WacrmClient:
    client = WacrmClient(
        base_url="https://crm.example.com/api/v1",
        api_key="wacrm_live_secret",
        organization_id=ORG_ID,
    )
    transport = httpx.MockTransport(handler)
    original_http = client._http

    def patched_http() -> httpx.AsyncClient:
        real = original_http()
        return httpx.AsyncClient(
            transport=transport, base_url=str(real.base_url), headers=real.headers
        )

    client._http = patched_http  # type: ignore[method-assign]
    return client


class TestParseSnapshot:
    def test_real_shape_uses_caller_organization_id(self):
        snapshot = _parse_snapshot(_deal(), ORG_ID)
        assert snapshot.organization_id == ORG_ID
        assert snapshot.crm_lead_id == "d1"
        assert snapshot.pipeline_stage == "Qualified"
        assert snapshot.assigned_broker_id == BROKER_ID
        assert snapshot.contact_reference == "+14155550123"

    def test_z_suffix_timestamp_parses_as_utc(self):
        snapshot = _parse_snapshot(_deal(updated_at="2026-07-08T12:00:00.123Z"), ORG_ID)
        assert snapshot.updated_at == datetime(2026, 7, 8, 12, 0, 0, 123000, tzinfo=UTC)

    def test_legacy_mock_shape_reads_organization_id_from_payload(self):
        snapshot = _parse_snapshot(_deal(organization_id=str(ORG_ID)), None)
        assert snapshot.organization_id == ORG_ID

    def test_non_uuid_broker_id_becomes_none(self):
        snapshot = _parse_snapshot(_deal(assigned_broker_id="broker-42"), ORG_ID)
        assert snapshot.assigned_broker_id is None


class TestUnwrap:
    def test_unwraps_data_envelope(self):
        assert _unwrap({"data": [1, 2]}) == [1, 2]

    def test_passes_bare_payload_through(self):
        assert _unwrap([{"id": "d1"}]) == [{"id": "d1"}]


class TestListLeadsUpdatedSince:
    @pytest.mark.asyncio
    async def test_follows_keyset_cursor_and_sends_bearer(self):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            if request.url.params.get("cursor") == "page2":
                return httpx.Response(
                    200, json={"data": [_deal("d2")], "meta": {"next_cursor": None}}
                )
            return httpx.Response(
                200, json={"data": [_deal("d1")], "meta": {"next_cursor": "page2"}}
            )

        client = _client_with(handler)
        since = datetime(2026, 7, 1, tzinfo=UTC)
        snapshots = await client.list_leads_updated_since(ORG_ID, since)

        assert [s.crm_lead_id for s in snapshots] == ["d1", "d2"]
        assert all(s.organization_id == ORG_ID for s in snapshots)
        assert len(seen) == 2
        assert seen[0].headers["Authorization"] == "Bearer wacrm_live_secret"
        assert seen[0].url.params["updated_since"] == since.isoformat()
        assert "organization_id" not in seen[0].url.params  # implicit in the key

    @pytest.mark.asyncio
    async def test_runaway_pagination_raises_instead_of_hanging(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json={"data": [], "meta": {"next_cursor": "again"}}
            )

        client = _client_with(handler)
        with pytest.raises(RuntimeError, match=str(MAX_LIST_PAGES)):
            await client.list_leads_updated_since(ORG_ID, datetime(2026, 7, 1, tzinfo=UTC))


class TestGetLead:
    @pytest.mark.asyncio
    async def test_unwraps_envelope_and_stamps_org(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path.endswith("/deals/d1")
            return httpx.Response(200, json={"data": _deal("d1")})

        client = _client_with(handler)
        snapshot = await client.get_lead("d1")
        assert snapshot is not None
        assert snapshot.crm_lead_id == "d1"
        assert snapshot.organization_id == ORG_ID

    @pytest.mark.asyncio
    async def test_404_returns_none(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"error": {"code": "not_found"}})

        client = _client_with(handler)
        assert await client.get_lead("missing") is None


class TestCreateLead:
    @pytest.mark.asyncio
    async def test_posts_deal_with_contact_and_new_stage(self):
        bodies: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "POST"
            assert request.url.path.endswith("/deals")
            bodies.append(json.loads(request.content))
            return httpx.Response(201, json={"data": _deal("d9", pipeline_stage="New")})

        client = _client_with(handler)
        snapshot = await client.create_lead(
            contact_reference="+51999888777", contact_name="Ana Torres"
        )
        assert snapshot.crm_lead_id == "d9"
        assert snapshot.organization_id == ORG_ID
        # dni absent -> key omitted entirely, mirroring update_stage's convention.
        assert bodies == [
            {
                "contact_phone": "+51999888777",
                "contact_name": "Ana Torres",
                "stage_name": "New",
            }
        ]

    @pytest.mark.asyncio
    async def test_includes_dni_only_when_given(self):
        bodies: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            bodies.append(json.loads(request.content))
            return httpx.Response(201, json={"data": _deal("d9", pipeline_stage="New")})

        client = _client_with(handler)
        await client.create_lead(
            contact_reference="+51999888777", contact_name="Ana Torres", dni="45678912"
        )
        assert bodies[0]["contact_dni"] == "45678912"


class TestUpdateStage:
    @pytest.mark.asyncio
    async def test_patches_stage_name_and_omits_absent_broker(self):
        bodies: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            bodies.append(json.loads(request.content))
            return httpx.Response(
                200, json={"data": _deal("d1", pipeline_stage="Negotiation")}
            )

        client = _client_with(handler)
        snapshot = await client.update_stage("d1", "Negotiation")
        assert snapshot.pipeline_stage == "Negotiation"
        # A present null would UNASSIGN the broker on the real API — the key
        # must be omitted entirely when the caller didn't specify one.
        assert bodies == [{"stage_name": "Negotiation"}]

    @pytest.mark.asyncio
    async def test_sends_broker_when_given(self):
        bodies: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            bodies.append(json.loads(request.content))
            return httpx.Response(200, json={"data": _deal("d1")})

        client = _client_with(handler)
        await client.update_stage("d1", "Qualified", assigned_broker_id=BROKER_ID)
        assert bodies == [{"stage_name": "Qualified", "assigned_broker_id": str(BROKER_ID)}]
