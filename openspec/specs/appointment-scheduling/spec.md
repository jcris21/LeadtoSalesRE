## Purpose

Appointment scheduling (US-404) is the orchestration service that turns a `confirmed` availability
slot (US-402) plus a created Calendar event (US-403) into a persisted `Appointment`, an
`AppointmentBooked` domain event, a triggered reminder-scheduling side effect, and a CRM pipeline
stage sync — closing the happy-path booking flow (Architecture.md §10 Iter. 5, CRN-5) for the
Coordinator Agent. It provides `SchedulingPort.book_visit(...)`, which never trusts a caller-asserted
"slot is available" precondition and always re-verifies via `AvailabilityValidatorPort.check()`
internally before booking.

## Requirements

### Requirement: Booking re-verifies availability internally
`SchedulingPort.book_visit(...)` SHALL invoke `AvailabilityValidatorPort.check()` internally before booking, regardless of any caller-supplied assertion that the slot is already confirmed. If the result is not `confirmed`, booking SHALL be refused: no `Appointment` row SHALL be persisted, no `AppointmentBooked` event SHALL be published, and no downstream side effect (Calendar event, reminder trigger, CRM sync) SHALL occur.

#### Scenario: Booking proceeds when availability is confirmed
- **WHEN** `book_visit` is invoked for a slot and `AvailabilityValidatorPort.check()` returns `confirmed`
- **THEN** the booking proceeds to create the Calendar event and persist the `Appointment`

#### Scenario: Booking refused when availability is pending
- **WHEN** `book_visit` is invoked and `AvailabilityValidatorPort.check()` returns `pending`
- **THEN** booking is refused, no `Appointment` is persisted, and no `AppointmentBooked` event is published

#### Scenario: Booking refused when availability is unavailable
- **WHEN** `book_visit` is invoked and `AvailabilityValidatorPort.check()` returns `unavailable`
- **THEN** booking is refused, no `Appointment` is persisted, and no `AppointmentBooked` event is published

### Requirement: Successful booking materializes a persisted Appointment
On a `confirmed` availability result, `book_visit` SHALL invoke `GoogleCalendarPort.create_event` and persist an `Appointment` with `status = BOOKED`, `calendar_event_id`, and `meet_link` populated from that call's result.

#### Scenario: Appointment persisted with Calendar details
- **WHEN** `book_visit` completes successfully
- **THEN** an `Appointment` row exists with `status = BOOKED` and both `calendar_event_id` and `meet_link` populated from the `GoogleCalendarPort.create_event` result

### Requirement: AppointmentBooked is published on successful booking
On successful booking, the system SHALL publish an `AppointmentBooked` event (`appointment_id`, `calendar_event_id`, `meet_link`, `lead_id`) through the transactional Outbox, in the same transaction as the `Appointment` persistence.

#### Scenario: Event published alongside the appointment
- **WHEN** `book_visit` completes successfully
- **THEN** an `AppointmentBooked` outbox event exists carrying the same `appointment_id`, `calendar_event_id`, and `meet_link` as the persisted `Appointment`

### Requirement: Reminder scheduling is triggered via a substitutable port
On successful booking, `book_visit` SHALL invoke `ReminderSchedulerPort.schedule_reminders` for the new appointment. The system SHALL provide a `NoOpReminderScheduler` implementation as an explicit placeholder until the real reminder scheduler exists, without requiring any change to `SchedulingService` when the real implementation is substituted.

#### Scenario: Reminder port invoked on successful booking
- **WHEN** `book_visit` completes successfully
- **THEN** `ReminderSchedulerPort.schedule_reminders` is invoked exactly once for the new appointment

### Requirement: Lead pipeline stage syncs to AppointmentSet on successful booking
On successful booking, the system SHALL sync the lead's CRM pipeline stage to `AppointmentSet` via `LeadSyncService.push_profile_update`, using an authorized actor.

#### Scenario: CRM stage synced after booking
- **WHEN** `book_visit` completes successfully for a given `lead_id`
- **THEN** `LeadSyncService.push_profile_update` is invoked for that lead with `pipeline_stage = AppointmentSet`
