## Why

The happy-path appointment flow has two working pieces — `AvailabilityValidatorPort` (US-402) gates
a slot as `confirmed`/`pending`/`unavailable`, and `GoogleCalendarPort` (US-403) creates a Calendar
event with a Meet link — but nothing yet turns a confirmed slot into a persisted `Appointment`,
notifies the rest of the system it was booked, or moves the lead's CRM stage forward. Without this
change the Coordinator Agent has no way to close CRN-5 (the tool-orchestration happy path
Architecture.md §10 Iter. 5 describes): booking a visit remains impossible end-to-end even though
both of its integration dependencies are implemented.

## What Changes

- Add `Appointment` aggregate (`id`, `organization_id`, `lead_id`, `property_id`, `broker_id`,
  `scheduled_at`, `status`, `calendar_event_id`, `meet_link`) and `AppointmentStatus` enum (`BOOKED`
  only — `CANCELLED`/`NO_SHOW` are US-406's concern) to `app/modules/appointment/domain/models.py`.
- Add `AppointmentBooked` `DomainEvent` (`appointment_id`, `calendar_event_id`, `meet_link`,
  `lead_id`), published through the existing transactional Outbox (`event_bus.publish`).
- Add `SchedulingPort` (Protocol) + `SchedulingService` implementing `book_visit(...)`: re-verifies
  `AvailabilityValidatorPort.check()` returns `confirmed` internally (never trusts a caller-asserted
  precondition — this is the Architecture §8 mandated bottleneck), then orchestrates
  `GoogleCalendarPort.create_event` → persist `Appointment` → publish `AppointmentBooked` →
  `ReminderSchedulerPort.schedule_reminders` → `LeadSyncService.push_profile_update(...,
  pipeline_stage=AppointmentSet)`.
- Add `ReminderSchedulerPort` (Protocol) + `NoOpReminderScheduler` — an explicit placeholder stub,
  since US-405 (the real reminder scheduler) is not yet implemented. Swappable later without
  touching `SchedulingService`.
- Add `AppointmentRepository` to `app/modules/appointment/infrastructure/repository.py`, following
  the exact pattern of `BrokerRepository`/`AvailabilityCheckRepository` in the same file.
- Add Alembic migration `0017`: `appointments` table with RLS by `organization_id`, following the
  exact pattern of migration `0016`.
- Add `"scheduling_service"` to `ALLOWED_ACTORS` in
  `app/modules/lead_qualification/application/lead_sync.py` (one-line addition — `SchedulingService`
  needs to call `LeadSyncService.push_profile_update` as an authorized actor).

## Capabilities

### New Capabilities
- `appointment-scheduling`: Orchestrates booking a validated appointment slot into a persisted
  `Appointment`, coordinating the Availability Validator (US-402) and Google Calendar Adapter
  (US-403) it depends on, publishing `AppointmentBooked`, triggering (stubbed) reminder scheduling,
  and syncing the lead's CRM pipeline stage to `AppointmentSet`.

### Modified Capabilities
- None. `appointment-availability` (US-402) and `calendar-integration` (US-403) are consumed as-is,
  not modified — this change is a new orchestrating capability on top of both, not a change to
  either's requirements.

## Impact

- **Code**: `app/modules/appointment/domain/models.py` (new aggregate/event/enum),
  `app/modules/appointment/application/scheduling_service.py` (new),
  `app/modules/appointment/application/reminder_port.py` (new, port + no-op stub),
  `app/modules/appointment/infrastructure/repository.py` (new `AppointmentRepository`),
  `app/modules/appointment/infrastructure/db_models.py` (new `AppointmentORM`),
  `app/modules/lead_qualification/application/lead_sync.py` (one-line `ALLOWED_ACTORS` addition).
- **Database**: new migration `0017_sprint4_2_appointments.py` creates `appointments` with RLS.
- **Dependencies**: none new — reuses `AvailabilityValidatorPort`, `GoogleCalendarPort`,
  `LeadSyncService`, and the existing Outbox event bus, all already in the codebase.
- **Out of scope**: US-405's real reminder-scheduling logic (only the port + stub land here), US-406
  cancellation/no-show handling, any UI/admin CRUD for appointments.
- **Docs**: `Documents/Oficial/HU_Appointment_Handoff_Ownership.md` US-404 row updated from `[GAP]`
  once merged.
