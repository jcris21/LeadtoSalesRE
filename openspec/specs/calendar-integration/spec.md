## Purpose

Google Calendar Adapter (US-403) provides the deterministic, no-LLM integration seam that turns a
confirmed appointment slot (gated by `AvailabilityValidatorPort`, see appointment-availability) into a
real Google Calendar event with a Meet link, for the organization's configured Google Workspace calendar.
It authenticates via a per-organization service account, translates Calendar API failures into typed
adapter errors, and exposes a fake test double so downstream scheduling code can be tested without network
I/O.

## Requirements

### Requirement: Single-call event creation with Meet link
The system SHALL provide `GoogleCalendarPort.create_event(details: EventDetails) -> CalendarEventResult` as a deterministic integration adapter with no LLM involvement. The underlying Google Calendar API call SHALL request `conferenceData.createRequest` (`conferenceSolutionKey.type = hangoutsMeet`) with `conferenceDataVersion=1` on the same `events.insert` request that creates the event — no second API call SHALL be made to obtain the Meet link.

#### Scenario: Event created with Meet link included
- **WHEN** `GoogleCalendarPort.create_event(details)` is invoked for a validated slot (`AvailabilityValidatorPort` returned `confirmed`)
- **THEN** exactly one HTTP call is made to the Google Calendar API
- **AND** the returned `CalendarEventResult` has both `calendar_event_id` and `meet_link` populated from that single response

### Requirement: Service-account authentication scoped by organization
`GoogleCalendarClient` SHALL authenticate using the service account referenced by `Organization.GoogleWorkspaceConfig.service_account_json_ref` and SHALL target `Organization.GoogleWorkspaceConfig.calendar_id` as the destination calendar. The service account reference or credential contents SHALL NOT appear in logs or trace spans.

#### Scenario: Event created on the organization's configured calendar
- **WHEN** `create_event` is invoked for an organization with `GoogleWorkspaceConfig.calendar_id = "org-calendar@group.calendar.google.com"`
- **THEN** the Calendar API `events.insert` call targets that exact `calendar_id`

#### Scenario: Credentials never logged
- **WHEN** `create_event` is invoked, successfully or not
- **THEN** no log line or trace span attribute contains the service account JSON or its referenced secret value

### Requirement: Typed error propagation on Calendar API failure
`GoogleCalendarClient` SHALL translate known Google Calendar API failure responses into typed adapter errors instead of letting raw HTTP client exceptions propagate: invalid/expired credentials (401/403) SHALL raise a distinct auth error type, rate limiting (429) SHALL raise a distinct rate-limit error type, and server errors (5xx) SHALL raise a distinct service error type.

#### Scenario: Invalid credentials surface a typed auth error
- **WHEN** the Calendar API responds with 401 or 403
- **THEN** `create_event` raises a typed authentication error (not a raw HTTP exception), distinguishable by callers from rate-limit or service errors

#### Scenario: Rate limiting surfaces a typed rate-limit error
- **WHEN** the Calendar API responds with 429
- **THEN** `create_event` raises a typed rate-limit error, distinguishable by callers from auth or service errors

#### Scenario: Server error surfaces a typed service error
- **WHEN** the Calendar API responds with a 5xx status
- **THEN** `create_event` raises a typed service error, distinguishable by callers from auth or rate-limit errors

### Requirement: Testable adapter seam
The system SHALL expose `GoogleCalendarPort` as a narrow Protocol with a `FakeGoogleCalendarClient` test double supporting per-call configurable delay, canned result, or failure, so calling code and tests can exercise success and every typed-error path without network I/O.

#### Scenario: Fake client drives deterministic test scenarios
- **WHEN** a test configures `FakeGoogleCalendarClient` to fail for a specific invocation
- **THEN** `create_event` raises the configured typed error without making any real network call
