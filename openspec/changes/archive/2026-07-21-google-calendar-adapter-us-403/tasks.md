## 1. Domain value objects

- [x] 1.1 Add `EventDetails` value object (`summary`, `start`, `end`, `attendees: tuple[str, ...]`)
      to `app/modules/appointment/domain/models.py`
- [x] 1.2 Add `CalendarEventResult` value object (`calendar_event_id: str`, `meet_link: str`) to
      `app/modules/appointment/domain/models.py`
- [x] 1.3 Add typed error classes (`CalendarAuthError`, `CalendarRateLimitError`,
      `CalendarServiceError`) to `app/modules/appointment/domain/models.py` (or a dedicated
      `errors.py` in the same package), following the exception style already used elsewhere in
      the codebase

## 2. Application port

- [x] 2.1 Define `GoogleCalendarPort` Protocol in `application/calendar_port.py`
      (`create_event(details: EventDetails) -> CalendarEventResult`)

## 3. Infrastructure adapter

- [x] 3.1 Implement `GoogleCalendarClient` in `infrastructure/google_calendar_client.py`: single
      `httpx.AsyncClient` call to Calendar API v3 `events.insert` with
      `conferenceData.createRequest` (`conferenceSolutionKey.type = hangoutsMeet`) and
      `conferenceDataVersion=1` query param, reading `attendees`/`summary`/`start`/`end` from
      `EventDetails` and `calendar_id` from `Organization.GoogleWorkspaceConfig`
- [x] 3.2 Implement service-account JWT acquisition (isolated in a single private method) using
      `service_account_json_ref` — no plaintext secret ever logged or included in trace attributes
- [x] 3.3 Map API response `conferenceData.entryPoints`/event `id` into `CalendarEventResult`
- [x] 3.4 Map 401/403 → `CalendarAuthError`, 429 → `CalendarRateLimitError`, 5xx →
      `CalendarServiceError`; do not let raw `httpx.HTTPStatusError` propagate
- [x] 3.5 Wrap `create_event` with an OpenTelemetry span (module, result, latency), reusing the
      Sprint 0 / US-402 tracing pattern — no new tracing infra
- [x] 3.6 Implement `FakeGoogleCalendarClient` (configurable per-call delay/result/failure),
      mirroring `app/modules/recommendation/infrastructure/maps_client.py`'s `FakeMapsClient`

## 4. Tests

- [x] 4.1 `tests/test_google_calendar_client.py`: success path asserts exactly one HTTP call is
      made and `CalendarEventResult` has both `calendar_event_id` and `meet_link` populated
- [x] 4.2 Test 401/403 responses raise `CalendarAuthError`
- [x] 4.3 Test 429 response raises `CalendarRateLimitError`
- [x] 4.4 Test 5xx response raises `CalendarServiceError`
- [x] 4.5 Test that `calendar_id` used in the request matches
      `Organization.GoogleWorkspaceConfig.calendar_id` for the invoking organization
- [x] 4.6 Test that no log line or trace span attribute contains service-account credential
      contents (assert absence across captured log/span output for a success and a failure case)
- [x] 4.7 `FakeGoogleCalendarClient` unit tests: configured failure raises the expected typed error
      without any network call

## 5. Documentation

- [x] 5.1 Update `Documents/Oficial/HU_Appointment_Handoff_Ownership.md` US-403 "Implementado hoy"
      column from `[GAP]` to reflect the new status once merged
- [ ] 5.2 Run `openspec-sync-specs` (or equivalent) to promote
      `specs/calendar-integration/spec.md` into `openspec/specs/calendar-integration/spec.md` once
      implementation lands — deferred to the `/opsx:archive` step, not run as part of
      `/opsx:apply`
