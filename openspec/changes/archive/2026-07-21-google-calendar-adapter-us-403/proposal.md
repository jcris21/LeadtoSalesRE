## Why

The Scheduling Service (US-404, not yet built) needs to create a Google Calendar event with an
auto-generated Meet link in a single API call, so a validated appointment slot (US-402,
`AvailabilityValidatorPort` → `confirmed`) can be turned into a bookable event with a video-call
link without a second round-trip to a separate Meet API. No `GoogleCalendarPort` or adapter exists
in the codebase today (Architecture.md §10 Iter. 5) — `Organization.GoogleWorkspaceConfig`
(`service_account_json_ref`, `calendar_id`) already reserved the config surface in Sprint 0, but
nothing consumes it yet.

## What Changes

- Add `GoogleCalendarPort` (Protocol) to the existing `app/modules/appointment/application/` layer:
  `create_event(details: EventDetails) -> CalendarEventResult`.
- Add `EventDetails` and `CalendarEventResult` value objects to
  `app/modules/appointment/domain/models.py`.
- Add `GoogleCalendarClient` (real adapter) to `app/modules/appointment/infrastructure/`: calls
  Google Calendar API v3 `events.insert` with `conferenceData.createRequest`
  (`conferenceSolutionKey.type = hangoutsMeet`) and `conferenceDataVersion=1` in one HTTP call —
  never a second call to obtain the Meet link. Authenticates via the service account referenced by
  `GoogleWorkspaceConfig.service_account_json_ref`; targets `GoogleWorkspaceConfig.calendar_id`.
- Add `FakeGoogleCalendarClient` test double (delays/results/failures configurable per call),
  mirroring `app/modules/recommendation/infrastructure/maps_client.py`'s `FakeMapsClient` pattern.
- Typed error propagation for Calendar API failures (401/403 invalid credentials, 429 rate limit,
  5xx) instead of raw `httpx` exceptions escaping the adapter.
- OpenTelemetry span around `create_event` (latency + result), reusing the Sprint 0 / US-402
  tracing pattern; never logs service-account contents.

## Capabilities

### New Capabilities
- `calendar-integration`: Deterministic Google Calendar adapter that creates a calendar event with
  an auto-generated Meet link in a single API call, with typed error handling and tracing. No LLM
  or business-decision involvement — purely an integration seam consumed by the (future) Scheduling
  Service.

### Modified Capabilities
- None. `appointment-availability` (US-402, already synced to `openspec/specs/`) is unaffected —
  this change adds a sibling capability in the same module, not a modification to availability
  validation requirements.

## Impact

- **Code**: `app/modules/appointment/domain/models.py` (new value objects),
  `app/modules/appointment/application/` (new port), `app/modules/appointment/infrastructure/`
  (new adapter + fake).
- **Dependencies**: `httpx` (already used by `maps_client.py`) for the real Calendar API call; no
  new third-party SDK — call the REST API directly, consistent with the existing Maps adapter
  pattern.
- **Config**: consumes existing `Organization.GoogleWorkspaceConfig` fields
  (`service_account_json_ref`, `calendar_id`); no new config fields.
- **Out of scope**: `SchedulingPort.book_visit`, the `appointments` table, retry/reprogramming
  logic — all deferred to US-404, which will be the sole caller of `GoogleCalendarPort`.
- **Docs**: `Documents/Oficial/HU_Appointment_Handoff_Ownership.md` US-403 row updated from `[GAP]`
  once merged.
