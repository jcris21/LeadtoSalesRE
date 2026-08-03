## Context

`app/modules/appointment/` already exists (US-402: `domain/`, `application/`, `infrastructure/`
with `AvailabilityValidatorPort`, `Broker`, `AvailabilityCheck`). Architecture.md §10 Iter. 5
requires Meet links to be obtained via `conferenceData.createRequest` on the same `events.insert`
call that creates the Calendar event — no separate Meet API integration exists in the codebase
today (`Organization.GoogleWorkspaceConfig` reserved `service_account_json_ref`/`calendar_id`
since Sprint 0, but nothing consumes them). US-404 (Scheduling Service, `[GAP]`) will be the sole
caller of the port this change produces; US-403 has no dependency on US-402 (pure GCP integration),
but both are prerequisites for US-404.

## Goals / Non-Goals

**Goals:**
- Provide `GoogleCalendarPort.create_event(details) -> CalendarEventResult` as a deterministic,
  LLM-free integration adapter that returns a populated `meet_link` from a **single** API call.
- Extend the existing `app/modules/appointment/` module (domain/application/infrastructure) rather
  than creating a new module — this is a sibling capability to `AvailabilityValidatorPort`, not a
  separate bounded context.
- Follow the exact external-adapter shape already established by
  `app/modules/recommendation/infrastructure/maps_client.py`: a narrow `Protocol` seam, a real
  `httpx`-based implementation, and a `Fake*` test double with per-call configurable
  delay/result/failure.
- Surface typed, adapter-level errors for the known Calendar API failure modes (invalid
  credentials, rate limit, server error) so a caller (US-404) can decide retry vs. fail without
  parsing `httpx` internals.

**Non-Goals:**
- No `SchedulingPort.book_visit`, no `Appointment` persistence, no `appointments` table — those
  columns (`calendar_event_id`, `meet_link`) are consumed by US-404 when it exists; this change only
  produces the value objects and the adapter that fill them.
- No retry/backoff policy implemented inside the adapter itself — a single failed call surfaces a
  typed error and returns; retry orchestration (if any) belongs to the caller (US-404), consistent
  with keeping this adapter a thin, deterministic seam.
- No OAuth user-consent flow — authentication is service-account only, per
  `GoogleWorkspaceConfig.service_account_json_ref` (already the modeled auth mechanism, no user
  delegation requirement exists in the HU catalog).

## Decisions

**1. Extend `app/modules/appointment/`, do not create a new module.**
Rationale: US-403 is Architecture.md's "Google Calendar Adapter" layer within the same Appointment
bounded context US-402 started; both are internal steps consumed by the future Scheduling Service
(US-404). Splitting into a separate top-level module would duplicate `domain/application/
infrastructure` scaffolding for no isolation benefit — nothing in the HU catalog requires Calendar
integration to be independently deployable from availability checking.
*Alternative considered:* new `app/modules/calendar/` module. Rejected — no bounded-context
boundary justifies it; both modules are internal collaborators of the same not-yet-built Scheduling
Service.

**2. Single `events.insert` call with `conferenceDataVersion=1`, never a second Meet API call.**
Rationale: this is the explicit Gherkin requirement (US-403) and Architecture.md §10's stated
reason for choosing `conferenceData.createRequest` over the standalone Meet API — one round-trip,
one point of failure, no partial-state risk (event created but Meet link missing because a second
call failed). The Google Calendar API v3 supports embedding a Meet conference request directly in
`events.insert`/`events.patch` via `conferenceData.createRequest` + `conferenceDataVersion=1`,
returning `conferenceData.entryPoints` (from which `hangoutLink`/video URI is read) in the same
response.
*Alternative considered:* create the event, then call a separate Meet-link-generation step.
Rejected per the Gherkin scenario itself ("sin una segunda llamada de API").

**3. Call the Calendar REST API directly over `httpx`, not the `google-api-python-client` SDK.**
Rationale: the codebase has zero Google SDK dependencies today; `maps_client.py` already
established the precedent of calling Google REST APIs directly over `httpx.AsyncClient` rather than
adding a heavyweight, sync-first SDK. Consistency with that adapter (same HTTP client, same
Protocol-seam/Fake-double test pattern) outweighs the convenience the SDK would offer for token
refresh — service-account JWT signing/exchange is a well-understood, small amount of code and keeps
the adapter's dependency footprint identical to the rest of the codebase.
*Alternative considered:* `google-api-python-client` + `google-auth`. Deferred — revisit only if
token-refresh/signing complexity in the direct-`httpx` approach proves to be a real maintenance
burden once implemented; no evidence of that yet.

**4. Typed error hierarchy (`CalendarAuthError`, `CalendarRateLimitError`, `CalendarServiceError`)
instead of letting `httpx.HTTPStatusError` propagate.**
Rationale: US-404 needs to distinguish "credentials are broken, alert an admin" (401/403) from "we
got rate-limited, maybe retry" (429) from "Google is down" (5xx) — collapsing all three into one
raised `httpx` exception would push that parsing responsibility onto every caller instead of the
adapter that already knows the mapping. Mirrors why `MapsClient`'s methods raise via
`response.raise_for_status()` only inside a controlled boundary the caller (`enrich_top3`) already
handles per-property; here the boundary is per-`create_event`-call, and the taxonomy is richer
because a failed booking is higher-stakes than a missing neighborhood amenity.
*Alternative considered:* let `httpx.HTTPStatusError` propagate unchanged. Rejected — forces every
caller to inspect `.response.status_code` itself, which is exactly the kind of untyped
error-handling the project's error-handling standard (validate/handle explicitly at every level)
asks adapters to avoid pushing upward.

## Risks / Trade-offs

- **[Risk]** Service-account JWT signing implemented by hand (no SDK) could have subtle bugs in
  token expiry/refresh handling. **Mitigation:** isolate token acquisition behind a single private
  method inside `GoogleCalendarClient` so it's independently unit-testable and swappable later
  without touching the public `GoogleCalendarPort` contract.
- **[Risk]** `FakeGoogleCalendarClient` diverging from real Calendar API response shape over time
  (e.g. Google changes `conferenceData.entryPoints` structure) → tests pass but the real adapter
  breaks. **Mitigation:** keep the fake's return type identical to `CalendarEventResult` (the
  domain value object), not a raw API payload shape — the fake never needs to mimic Google's JSON,
  only the adapter's already-parsed output, same as `FakeMapsClient` returns `tuple[str, ...]`
  rather than a raw Places API response.
- **[Trade-off]** No retry logic inside the adapter means a transient 5xx surfaces immediately as a
  failure to the caller. **Accepted** — retry policy is a Scheduling Service concern (US-404, not
  yet scoped), and building it here without a concrete caller would be speculative.

## Migration Plan

Not applicable — no database schema changes in this change. `appointments.calendar_event_id` /
`appointments.meet_link` columns are created by US-404's migration when that HU is implemented;
this change only produces the in-memory `CalendarEventResult` value object those columns will
eventually be populated from.

## Open Questions

- Whether `GoogleCalendarClient` should support `events.patch` (update an existing event, e.g. for
  reprogramming per US-406) is left to that future HU — this change implements `create_event` only,
  per the US-403 Gherkin scope.
