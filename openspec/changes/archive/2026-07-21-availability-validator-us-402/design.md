## Context

`app/modules/appointment/` exists only as an empty stub (`__init__.py`). Architecture.md §7.13/§8
mandates `AvailabilityValidatorPort` as the single deterministic bottleneck no appointment flow may
bypass: it must be invoked both when a slot is first proposed and again automatically 2-4h before the
visit (re-validation, mitigating the critical business risk of a lead showing up to an unavailable
property). No `Broker` entity exists anywhere in the codebase today (verified by grep across all
modules) — brokers today are only implicit CRM references inside `Lead`. Downstream work (US-403 Google
Calendar Adapter, US-404 Scheduling Service) both require a `confirmed` `AvailabilityCheck` before they
may run, per `Documents/Oficial/HU_Appointment_Handoff_Ownership.md`.

## Goals / Non-Goals

**Goals:**
- Provide `AvailabilityValidatorPort.check(property_id, slot) -> confirmed | pending | unavailable` as a
  deterministic, LLM-free service.
- Model `Broker` and `AvailabilityCheck` with `organization_id` + RLS, matching every other table's
  isolation pattern since Sprint 0.
- Make every check auditable (`source: initial | revalidation_2_4h`) so a broker/admin can answer "why
  was this rescheduled?" later (supports QA-11 explainability for the eventual Handoff/OPE work).
- Scaffold `app/modules/appointment/` following the exact Ports & Adapters layout already used by
  `lead_qualification/` and `recommendation/` (`domain/`, `application/`, `infrastructure/`, later
  `wiring.py` once US-404 consumes this port).

**Non-Goals:**
- No Google Calendar integration (US-403) or `Appointment` persistence/booking (US-404) — this change
  only produces the gate they will call.
- No real broker calendar/CRM sync — the MVP models `Broker.availability` as a simple JSON blob owned by
  this module; integrating a broker's actual calendar is out of scope until evidence justifies it.
- No UI/admin CRUD for brokers — `Broker` rows are seeded/managed directly for the MVP, same posture as
  `Property` seeding before an ingestion UI existed.

## Decisions

**1. `AvailabilityCheck` as its own audit table, not a column on the future `appointments` table.**
Rationale: the re-validation scenario (2-4h before the visit) must leave a trace of *when* the status
changed, not just the latest value — otherwise a broker asking "why did this get flagged?" has no
history. A dedicated table with `source` distinguishes the two Gherkin scenarios (initial vs.
revalidation) without overloading `appointments.status` (which US-404 will own for `AppointmentStatus`,
a different lifecycle entirely).
*Alternative considered:* single `availability_status` column on `appointments`. Rejected — `US-404`'s
`Appointment` doesn't exist yet in this change, and collapsing the two concerns would force this HU to
depend on US-404 instead of the other way around, inverting the dependency the HU catalog already
established.

**2. `pending` status maps to "requires manual broker confirmation", never to an implicit `confirmed`.**
Rationale: the MVP has no real-time broker/owner availability feed (`Agentic_System.md`: *"confirmar
disponibilidad si no hay estado en tiempo real"*). Treating `pending` as blocking (not proceed-by-default)
is the only choice consistent with QA-09 (no silent defaults) and the critical acceptance test ("ningún
test de agendamiento pasa si Avail devuelve unavailable" generalizes to: nothing proceeds without an
explicit `confirmed`).
*Alternative considered:* auto-confirm after a timeout. Rejected — directly contradicts the risk
mitigation this HU exists to provide.

**3. `Broker.availability` as `jsonb`, not a normalized `broker_schedules` table.**
Rationale: MVP scale (≤6 brokers/agency × 10 agencies) doesn't justify a normalized schedule model yet;
`jsonb` keeps the migration small and defers the real design question (recurring availability vs. one-off
blocks) until a broker-calendar integration is actually scoped. Same trade-off already accepted for
`Property.features` (jsonb) in `property-catalog`.
*Alternative considered:* dedicated `broker_availability_slots` table. Deferred — no requirement yet
demands querying availability independent of a specific check.

**4. Reuse `properties.id` as a foreign key, never duplicate `Property` fields into `AvailabilityCheck`.**
Rationale: `Property` is a Recommendation-module aggregate (Sprint 3, already built); Ports & Adapters
(QA-05) means Appointment reads it by id only, never re-implements its schema.

## Risks / Trade-offs

- **[Risk]** No real broker/owner availability source in the MVP → most checks may resolve `pending`
  indefinitely. **Mitigation:** `pending` is surfaced to the broker in Chatwoot (existing AI Sidebar
  channel, no new UI needed) for manual confirmation; not silently retried forever.
- **[Risk]** `jsonb` availability is not queryable for "find any available broker" style searches.
  **Mitigation:** out of scope for US-402 (only checks a specific `broker_id` + `slot`); acceptable until
  a future HU needs broker search.
- **[Trade-off]** Introducing `Broker` now, ahead of any UI to manage it, means initial rows are
  seeded/manual (same pattern as `Property` before `PropertyIngestionService` existed) — accepted
  precedent, not a new risk class for this codebase.

## Migration Plan

1. Alembic migration `0016_sprint4_1_brokers_availability`: create `brokers` and `availability_checks`
   with RLS policies mirroring `properties`/`recommendations` (organization_id-scoped).
2. No backfill needed — both tables are new, no existing data to migrate.
3. Rollback: standard Alembic `downgrade()` drops both tables; no other module reads them yet (safe to
   drop without cascading impact).

## Open Questions

- Exact re-validation scheduling mechanism (cron-style loop vs. reuse of the future Reminder Scheduler's
  job infrastructure, US-405) is left to `tasks.md`/implementation — Architecture.md doesn't mandate a
  specific job runner, only that it happens 2-4h before `scheduledAt`. Since `scheduledAt` only exists
  once `Appointment` (US-404) is built, the automatic re-validation scenario's *trigger* is implemented as
  part of US-404/US-405, not this change — this change ships `check()` re-invokable on demand; the
  scheduling of *when* to re-invoke it is explicitly deferred and tracked in
  `Documents/Oficial/HU_Appointment_Handoff_Ownership.md` (US-405 depends on US-404 which depends on this
  change).
