## Context

`app/modules/appointment/` already has two working, archived pieces: `AvailabilityValidatorPort`
(US-402, deterministic `confirmed | pending | unavailable` gate) and `GoogleCalendarPort` (US-403,
single-call event + Meet link creation). Architecture.md §10 Iter. 5 / CRN-5 describes a Coordinator
Agent that closes the happy path by delegating to a Scheduling Service node in the same LangGraph
graph. `leads.pipeline_stage` already has an `AppointmentSet` value
(`PipelineStage.APPOINTMENT_SET`) and a reusable write path (`LeadSyncService.push_profile_update`,
US-207) — nothing currently calls it for appointments. US-405 (Reminder Scheduler) and US-406
(cancel/no-show) are both still `[GAP]`; this change is a prerequisite for both per the HU catalog's
dependency ordering.

## Goals / Non-Goals

**Goals:**
- Provide `SchedulingPort.book_visit(...)` as the single orchestration point that turns a validated
  slot into a persisted `Appointment`, coordinating the two existing ports plus the CRM sync path.
- Re-verify availability inside `book_visit` itself, not trust a caller's assertion — Architecture
  §8 names the Availability Validator the mandatory bottleneck, and US-402's critical acceptance
  test ("no code path may produce a `confirmed` booking without an explicit prior check") is only
  actually enforced if every booking path calls `check()` itself.
- Publish `AppointmentBooked` through the existing transactional Outbox so future consumers (US-405
  reminder trigger, analytics, AI Sidebar) can react without this change knowing about them.
- Define `ReminderSchedulerPort` now (as a Protocol) so the Gherkin's "Scheduling Service dispara
  ReminderSchedulerPort.schedule_reminders" step is honored structurally, even though the real
  implementation (US-405) doesn't exist yet — a `NoOpReminderScheduler` fills the gap.

**Non-Goals:**
- No real reminder-scheduling logic (24h/2h persisted jobs) — that is US-405's entire scope; this
  change only defines the port shape US-405 must implement and wires a no-op in its place.
- No cancellation, no-show, or rescheduling handling — `AppointmentStatus` only has `BOOKED` in this
  change; US-406 extends the enum and the FSM transition when it lands.
- No UI/admin CRUD for appointments — same posture as `Broker`/`Property` before their respective
  ingestion UIs existed.
- No retry/idempotency wrapper around `book_visit` as a whole — if `GoogleCalendarPort.create_event`
  fails, the exception propagates and nothing is persisted (single DB transaction), which is
  sufficient for the MVP; a saga/compensation pattern is not justified without evidence of partial-
  failure incidents.

## Decisions

**1. `book_visit` re-invokes `AvailabilityValidatorPort.check()`, never trusts a precondition.**
Rationale: the Gherkin's `Given AvailabilityValidatorPort en confirmed` reads as a precondition on
paper, but `AvailabilityValidatorService._resolve` (US-402) is already idempotent for a
`confirmed` prior check — re-invoking it inside `book_visit` costs one extra call and one extra
audit row (source stays `initial`, consistent with "the check that immediately preceded booking"),
and it is the only way to make the Architecture §8 bottleneck actually load-bearing instead of
advisory. Trusting a caller-supplied "already confirmed" flag would let any future caller bypass
the gate by simply asserting it.
*Alternative considered:* accept a pre-computed `AvailabilityStatus` as a `book_visit` parameter.
Rejected — moves the enforcement responsibility to every future caller instead of the one place
that can guarantee it.

**2. `ReminderSchedulerPort` + `NoOpReminderScheduler` defined here, not deferred entirely to
US-405.**
Rationale: the Gherkin scenario for this HU explicitly includes the reminder-trigger step; skipping
it silently would under-deliver the acceptance criteria. Defining the Protocol now (with a stub
implementation) lets `SchedulingService`'s orchestration be complete and testable today, and gives
US-405 a pre-agreed interface to implement against instead of inventing one under time pressure
later — the same Ports & Adapters substitution already used for `GoogleCalendarPort` before US-403
existed (it was scaffolded conceptually in US-402's Open Questions).
*Alternative considered:* omit the reminder step entirely until US-405 ships. Rejected — the
Gherkin's `And Scheduling Service dispara ReminderSchedulerPort.schedule_reminders` is part of this
HU's stated acceptance criteria, not an optional extension.

**3. `Appointment` persisted in the same DB transaction as the `AvailabilityCheck` write and the
Outbox event — no separate saga.**
Rationale: `AsyncSession`-scoped units of work are the established pattern across every module
(`LeadSyncService`, `AvailabilityValidatorService`); wrapping `create_event` (external HTTP call) and
the persistence step in one transaction means a Calendar API failure raises before any row commits,
which is exactly the desired "nothing half-booked" behavior for the MVP's scale. If a
transient Calendar failure needs to survive a retry across process boundaries, that's a concrete
future requirement, not evidenced yet.
*Alternative considered:* two-phase — persist `Appointment` in a `PENDING_CALENDAR` state first,
then update after `create_event` succeeds. Rejected as premature: no requirement yet demands
surviving a mid-flight crash between "event created" and "row persisted" (both happen in the same
async call within one request), and it would expand `AppointmentStatus` beyond this HU's stated
scope (`BOOKED` only).

**4. `SchedulingService` calls `LeadSyncService.push_profile_update` directly (in-process), not via
a published event a separate handler consumes.**
Rationale: every other read/write to CRM data goes exclusively through `LeadSyncService` (QA-08 —
"the SINGLE point with read/write permission to CRM data"); calling it directly here is consistent
with how `push_profile_update` is already invoked in this codebase (synchronously, from the caller
that knows the new stage), not via an event-driven side channel. Adding `"scheduling_service"` to
`ALLOWED_ACTORS` is the one-line integration point QA-08's audit trail requires.
*Alternative considered:* publish `AppointmentBooked` and have a dedicated Outbox consumer call
`push_profile_update`. Rejected — adds an async hop and a new consumer registration for no
architectural benefit; `AppointmentBooked` is still published for other consumers that do want an
async signal (reminders, later analytics), but the CRM sync itself doesn't need to wait for a poll
cycle.

## Risks / Trade-offs

- **[Risk]** `NoOpReminderScheduler` means no reminder is ever actually sent until US-405 ships —
  brokers/leads get no 24h/2h nudge in the interim. **Mitigation:** explicitly documented in the
  stub's docstring and in this design doc; tracked as a known gap in
  `Documents/Oficial/HU_Appointment_Handoff_Ownership.md` (US-405 remains `[GAP]`), not silently
  hidden behind a port that looks "done."
- **[Risk]** Re-invoking `AvailabilityValidatorPort.check()` inside `book_visit` adds one more
  `AvailabilityCheck` row per booking attempt (even successful ones), slightly inflating the audit
  table. **Accepted** — the audit trail is the point (US-402 spec.md), and one extra row per booking
  is negligible at MVP scale.
- **[Trade-off]** No saga/compensation for a Calendar-succeeds-but-DB-write-fails edge case (e.g.
  process killed between the two). **Accepted for the MVP** — single-transaction scope makes this
  vanishingly rare in practice (both happen within one async request), and building compensation
  logic without an observed incident would be speculative.

## Migration Plan

1. Alembic migration `0017_sprint4_2_appointments`: create `appointments` with RLS policy mirroring
   `0016` (`brokers`/`availability_checks`), FKs to `organizations`, `leads`, `properties`, `brokers`
   (nullable, `ON DELETE SET NULL` for broker — an appointment shouldn't vanish if a broker record is
   removed).
2. No backfill — new table, no existing data.
3. Rollback: standard Alembic `downgrade()` drops the table; no other module reads it yet.

## Open Questions

- Whether `book_visit` should accept a `broker_id` explicitly or resolve one via
  `BrokerRepository.list_active_for_organization` is left to `tasks.md`/implementation — the
  Gherkin only specifies "attendees definidos (lead + broker)," implying the caller (Coordinator)
  already knows which broker is attending; this change accepts `broker_id` as a required
  `book_visit` parameter rather than inventing a broker-assignment policy that belongs to a future
  HU (e.g. the Ownership Policy Engine's specialist-routing work).
