"""Sprint 4.1 — US-403: Google Calendar Adapter. Critical requirement: exactly
one HTTP call to the Calendar API produces both the event and its Meet link
(spec.md "Single-call event creation with Meet link") — never a second call."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.modules.appointment.domain.models import (
    CalendarAuthError,
    CalendarEventResult,
    CalendarRateLimitError,
    CalendarServiceError,
    EventDetails,
)
from app.modules.appointment.infrastructure.google_calendar_client import (
    FakeGoogleCalendarClient,
    GoogleCalendarClient,
)
from app.modules.organization.domain.models import GoogleWorkspaceConfig

CONFIG = GoogleWorkspaceConfig(
    service_account_json_ref="/fake/service-account.json",
    calendar_id="org-calendar@group.calendar.google.com",
)

DETAILS = EventDetails(
    summary="Visita departamento 4B",
    start=datetime(2026, 8, 1, 15, 0, tzinfo=UTC),
    end=datetime(2026, 8, 1, 15, 30, tzinfo=UTC),
    attendees=("lead@example.com", "broker@example.com"),
)


def _success_payload(event_id: str = "evt-123") -> dict:
    return {
        "id": event_id,
        "conferenceData": {
            "entryPoints": [
                {"entryPointType": "video", "uri": "https://meet.google.com/abc-defg-hij"}
            ]
        },
    }


async def _fake_token_provider() -> str:
    return "fake-access-token"


def _client_with_transport(handler) -> tuple[GoogleCalendarClient, list[httpx.Request]]:
    calls: list[httpx.Request] = []

    def _recording_handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request)

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(_recording_handler))
    client = GoogleCalendarClient(
        CONFIG, http_client=http_client, token_provider=_fake_token_provider
    )
    return client, calls


@pytest.mark.asyncio
async def test_create_event_makes_exactly_one_call_and_returns_meet_link():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("conferenceDataVersion") == "1"
        return httpx.Response(200, json=_success_payload())

    client, calls = _client_with_transport(handler)

    result = await client.create_event(DETAILS)

    assert len(calls) == 1
    assert result == CalendarEventResult(
        calendar_event_id="evt-123", meet_link="https://meet.google.com/abc-defg-hij"
    )


@pytest.mark.asyncio
async def test_calendar_id_used_matches_organization_config():
    def handler(request: httpx.Request) -> httpx.Response:
        assert f"/calendars/{CONFIG.calendar_id}/events" in str(request.url)
        return httpx.Response(200, json=_success_payload())

    client, calls = _client_with_transport(handler)

    await client.create_event(DETAILS)

    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [401, 403])
async def test_invalid_credentials_raise_typed_auth_error(status_code):
    client, _ = _client_with_transport(lambda request: httpx.Response(status_code, json={}))

    with pytest.raises(CalendarAuthError):
        await client.create_event(DETAILS)


@pytest.mark.asyncio
async def test_rate_limit_raises_typed_rate_limit_error():
    client, _ = _client_with_transport(lambda request: httpx.Response(429, json={}))

    with pytest.raises(CalendarRateLimitError):
        await client.create_event(DETAILS)


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [500, 502, 503])
async def test_server_error_raises_typed_service_error(status_code):
    client, _ = _client_with_transport(lambda request: httpx.Response(status_code, json={}))

    with pytest.raises(CalendarServiceError):
        await client.create_event(DETAILS)


@pytest.mark.asyncio
async def test_credentials_never_appear_in_request_or_response_capture():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "fake-access-token" not in request.url.params.get("assertion", "")
        return httpx.Response(200, json=_success_payload())

    client, calls = _client_with_transport(handler)

    await client.create_event(DETAILS)

    request = calls[0]
    assert request.headers["Authorization"] == "Bearer fake-access-token"
    body = request.content.decode()
    assert "private_key" not in body
    assert "service-account.json" not in body


class TestFakeGoogleCalendarClient:
    @pytest.mark.asyncio
    async def test_default_result_populates_meet_link(self):
        fake = FakeGoogleCalendarClient()

        result = await fake.create_event(DETAILS)

        assert result.calendar_event_id
        assert result.meet_link
        assert fake.calls == [DETAILS]

    @pytest.mark.asyncio
    async def test_configured_failure_raises_without_network_call(self):
        fake = FakeGoogleCalendarClient(failure=CalendarServiceError("boom"))

        with pytest.raises(CalendarServiceError):
            await fake.create_event(DETAILS)

        assert fake.calls == [DETAILS]

    @pytest.mark.asyncio
    async def test_per_call_failures_list(self):
        fake = FakeGoogleCalendarClient(failures=[CalendarAuthError("bad creds"), None])

        with pytest.raises(CalendarAuthError):
            await fake.create_event(DETAILS)

        result = await fake.create_event(DETAILS)
        assert result.calendar_event_id
