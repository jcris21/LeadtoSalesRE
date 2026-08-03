"""Google Calendar Adapter (US-403, Sprint 4.1).

Calls the Calendar API v3 `events.insert` endpoint directly over `httpx`
(design.md Decision 3 — no `google-api-python-client` SDK, consistent with
`app/modules/recommendation/infrastructure/maps_client.py`'s precedent of
calling Google REST APIs directly). `conferenceData.createRequest` +
`conferenceDataVersion=1` are sent on that same request so the Meet link
comes back in the single response (design.md Decision 2) — no second call.

Service-account JWT signing/exchange (design.md Decision 4 — token
acquisition isolated in `_acquire_access_token`) uses `python-jose`
(already a project dependency), never the SDK's client either.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path

import httpx
from jose import jwt
from opentelemetry import trace

from app.modules.appointment.domain.models import (
    CalendarAuthError,
    CalendarEventResult,
    CalendarRateLimitError,
    CalendarServiceError,
    EventDetails,
)
from app.modules.organization.domain.models import GoogleWorkspaceConfig

_CALENDAR_EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events"
_DEFAULT_TOKEN_URL = "https://oauth2.googleapis.com/token"
_CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.events"
_JWT_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:jwt-bearer"
_JWT_TTL_SECONDS = 3600

_tracer = trace.get_tracer(__name__)

TokenProvider = Callable[[], Awaitable[str]]


class GoogleCalendarClient:
    """`GoogleCalendarPort` implementation. `token_provider` defaults to the
    real service-account JWT exchange (`_acquire_access_token`) but can be
    injected (tests) so `create_event`'s single-call contract can be
    exercised without real credential material or a second HTTP call."""

    def __init__(
        self,
        config: GoogleWorkspaceConfig,
        *,
        http_client: httpx.AsyncClient,
        token_provider: TokenProvider | None = None,
    ) -> None:
        self._config = config
        self._http_client = http_client
        self._token_provider = token_provider or self._acquire_access_token

    async def create_event(self, details: EventDetails) -> CalendarEventResult:
        with _tracer.start_as_current_span("google_calendar.create_event") as span:
            span.set_attribute("calendar_id", self._config.calendar_id)
            try:
                access_token = await self._token_provider()
                response = await self._http_client.post(
                    _CALENDAR_EVENTS_URL.format(calendar_id=self._config.calendar_id),
                    params={"conferenceDataVersion": 1},
                    headers={"Authorization": f"Bearer {access_token}"},
                    json=_build_event_payload(details),
                )
                result = _parse_event_response(response)
            except (CalendarAuthError, CalendarRateLimitError, CalendarServiceError) as exc:
                span.set_attribute("result", "error")
                span.set_attribute("error_type", type(exc).__name__)
                raise
            span.set_attribute("result", "success")
            return result

    async def _acquire_access_token(self) -> str:
        """Signs a service-account JWT (RS256) and exchanges it for an OAuth2
        access token. The only method that ever touches credential material —
        never logs it, never includes it in a span attribute."""
        key = _load_service_account_key(self._config.service_account_json_ref)
        token_uri = key.get("token_uri", _DEFAULT_TOKEN_URL)
        now = int(time.time())
        claims = {
            "iss": key["client_email"],
            "scope": _CALENDAR_SCOPE,
            "aud": token_uri,
            "iat": now,
            "exp": now + _JWT_TTL_SECONDS,
        }
        assertion = jwt.encode(claims, key["private_key"], algorithm="RS256")

        response = await self._http_client.post(
            token_uri,
            data={"grant_type": _JWT_GRANT_TYPE, "assertion": assertion},
        )
        _raise_for_calendar_error(response)
        return response.json()["access_token"]


def _load_service_account_key(service_account_json_ref: str) -> dict:
    """`service_account_json_ref` is a file path in the MVP (a secret-manager
    key elsewhere) — the raw JSON is read on demand, never cached in a log or
    inline config value."""
    return json.loads(Path(service_account_json_ref).read_text())


def _build_event_payload(details: EventDetails) -> dict:
    return {
        "summary": details.summary,
        "start": {"dateTime": details.start.isoformat()},
        "end": {"dateTime": details.end.isoformat()},
        "attendees": [{"email": email} for email in details.attendees],
        "conferenceData": {
            "createRequest": {
                "requestId": str(uuid.uuid4()),
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        },
    }


def _raise_for_calendar_error(response: httpx.Response) -> None:
    if response.status_code in (401, 403):
        raise CalendarAuthError(f"Google Calendar rejected the request: {response.status_code}")
    if response.status_code == 429:
        raise CalendarRateLimitError("Google Calendar rate-limited the request")
    if response.status_code >= 500:
        raise CalendarServiceError(f"Google Calendar service error: {response.status_code}")
    response.raise_for_status()


def _parse_event_response(response: httpx.Response) -> CalendarEventResult:
    _raise_for_calendar_error(response)
    payload = response.json()
    meet_link = ""
    for entry_point in payload.get("conferenceData", {}).get("entryPoints", []):
        if entry_point.get("entryPointType") == "video":
            meet_link = entry_point.get("uri", "")
            break
    return CalendarEventResult(calendar_event_id=payload["id"], meet_link=meet_link)


class FakeGoogleCalendarClient:
    """Test double: configurable per-call delay, canned result, or failure —
    mirrors `app/modules/recommendation/infrastructure/maps_client.py`'s
    `FakeMapsClient` so callers/tests never need real network I/O or
    credentials to exercise `GoogleCalendarPort`."""

    def __init__(
        self,
        *,
        result: CalendarEventResult | None = None,
        results: list[CalendarEventResult] | None = None,
        delay_seconds: float = 0.0,
        failure: Exception | None = None,
        failures: list[Exception | None] | None = None,
    ) -> None:
        self._result = result or CalendarEventResult(
            calendar_event_id="fake-event-id", meet_link="https://meet.google.com/fake-link"
        )
        self._results = results
        self._delay_seconds = delay_seconds
        self._failure = failure
        self._failures = failures
        self.calls: list[EventDetails] = []

    async def create_event(self, details: EventDetails) -> CalendarEventResult:
        self.calls.append(details)
        if self._delay_seconds:
            await asyncio.sleep(self._delay_seconds)

        call_index = len(self.calls) - 1
        failure = (
            self._failures[call_index]
            if self._failures is not None and call_index < len(self._failures)
            else self._failure
        )
        if failure is not None:
            raise failure

        if self._results is not None and call_index < len(self._results):
            return self._results[call_index]
        return self._result
