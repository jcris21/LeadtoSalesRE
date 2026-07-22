## 1. Domain model

- [x] 1.1 Add `AppointmentStatus` enum (`BOOKED` only, for this HU's scope) to
      `app/modules/appointment/domain/models.py`
- [x] 1.2 Add `Appointment` aggregate (`AggregateRoot`: `id`, `organization_id`, `lead_id`,
      `property_id`, `broker_id`, `scheduled_at`, `status`, `calendar_event_id`, `meet_link`) to
      `app/modules/appointment/domain/models.py`
- [x] 1.3 Add `AppointmentBooked` `DomainEvent` (`appointment_id`, `calendar_event_id`,
      `meet_link`, `lead_id`) to `app/modules/appointment/domain/models.py`
- [x] 1.4 Add a typed exception (e.g. `SlotNotConfirmedError`) raised when `book_visit` is invoked
      for a slot that is not `confirmed`

## 2. Reminder port (US-405 placeholder)

- [x] 2.1 Define `ReminderSchedulerPort` Protocol (`schedule_reminders(appointment_id, scheduled_at)
      -> None`) in `application/reminder_port.py`
- [x] 2.2 Implement `NoOpReminderScheduler` in the same file — docstring explicitly states this is
      a placeholder pending US-405, never silently presented as the real implementation

## 3. Persistence

- [x] 3.1 Add `AppointmentORM` to `infrastructure/db_models.py` (organization_id FK + index,
      lead_id/property_id/broker_id FKs, matching `BrokerORM`/`AvailabilityCheckORM` conventions)
- [x] 3.2 Write Alembic migration `0017_sprint4_2_appointments.py`: create `appointments` with RLS
      policy scoped by `organization_id`, following the exact pattern of `0016`
- [x] 3.3 Implement `AppointmentRepository` (`save`, `get_by_id`) in `infrastructure/repository.py`,
      following the exact pattern of `BrokerRepository`/`AvailabilityCheckRepository`

## 4. Scheduling Service

- [x] 4.1 Define `SchedulingPort` Protocol (`book_visit(...) -> Appointment`) in
      `application/scheduling_service.py`
- [x] 4.2 Implement `SchedulingService.book_visit`: invoke `AvailabilityValidatorPort.check()`
      internally; raise the typed exception (task 1.4) and persist nothing if not `confirmed`
- [x] 4.3 On `confirmed`: invoke `GoogleCalendarPort.create_event`, persist the `Appointment` via
      `AppointmentRepository`, record and publish `AppointmentBooked` via `event_bus.publish`
- [x] 4.4 Invoke `ReminderSchedulerPort.schedule_reminders` for the new appointment
- [x] 4.5 Invoke `LeadSyncService.push_profile_update(lead_id, actor="scheduling_service",
      pipeline_stage=PipelineStage.APPOINTMENT_SET)`
- [x] 4.6 Add `"scheduling_service"` to `ALLOWED_ACTORS` in
      `app/modules/lead_qualification/application/lead_sync.py`
- [x] 4.7 Wrap `book_visit` with an OpenTelemetry span (module, result, latency), reusing the
      Sprint 0 / US-402 tracing pattern

## 5. Tests

- [x] 5.1 `tests/test_scheduling_service.py`: happy-path test — confirmed availability → Calendar
      event created → `Appointment` persisted with `status=BOOKED` and populated
      `calendar_event_id`/`meet_link` → `AppointmentBooked` outbox event exists → reminder port
      invoked → `LeadSyncService.push_profile_update` invoked with `AppointmentSet`
- [x] 5.2 **Critical acceptance test:** booking is refused (raises, no `Appointment` persisted, no
      `AppointmentBooked` published, no Calendar/reminder/CRM side effects) when
      `AvailabilityValidatorPort.check()` returns `pending`
- [x] 5.3 Same critical test for `unavailable`
- [x] 5.4 Test RLS isolation: appointments from organization A never leak into a query scoped to
      organization B

## 6. Documentation

- [x] 6.1 Update `Documents/Oficial/HU_Appointment_Handoff_Ownership.md` US-404 "Implementado hoy"
      column from `[GAP]` to reflect the new status once merged
- [ ] 6.2 Run `openspec-sync-specs` (or equivalent) to promote
      `specs/appointment-scheduling/spec.md` into `openspec/specs/appointment-scheduling/spec.md`
      once implementation lands — deferred to the `/opsx:archive` step, not run as part of
      `/opsx:apply`
