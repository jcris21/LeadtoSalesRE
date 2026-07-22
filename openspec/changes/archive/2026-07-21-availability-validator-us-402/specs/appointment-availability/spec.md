## ADDED Requirements

### Requirement: Deterministic availability check port
The system SHALL provide `AvailabilityValidatorPort.check(property_id, slot) -> confirmed | pending | unavailable` as a deterministic service with no LLM involvement. No appointment slot SHALL be proposed to a lead or confirmed as booked without this port having been invoked first for that exact `(property_id, slot)` pair.

#### Scenario: Slot proposed after successful check
- **WHEN** a lead selects a visit slot for a property from the Top-3
- **THEN** `AvailabilityValidatorPort.check(property_id, slot)` is invoked before the slot is offered back to the lead as confirmed

#### Scenario: Unavailable slot blocks proposal
- **WHEN** `check()` returns `unavailable` for the requested `(property_id, slot)`
- **THEN** the slot is not offered to the lead as bookable, and an alternative slot or property is suggested instead

### Requirement: Pending status requires explicit human confirmation
A `pending` result from `check()` SHALL be treated as blocking — the system SHALL NOT auto-promote a `pending` result to `confirmed` on any timeout, retry, or default path.

#### Scenario: Pending never silently confirms
- **WHEN** `check()` returns `pending` because no real-time availability source exists for that broker/property
- **THEN** the appointment flow does not proceed to booking, and the broker is notified in Chatwoot to confirm manually

### Requirement: Automatic re-validation before the visit
The system SHALL re-invoke `AvailabilityValidatorPort.check()` for a booked appointment automatically between 2 and 4 hours before its scheduled time, recording the result with `source = revalidation_2_4h` distinct from the `initial` proposal check.

#### Scenario: Re-validation confirms an already-booked slot
- **WHEN** a booked appointment reaches its 2-4h re-validation window and `check()` still returns `confirmed`
- **THEN** an `AvailabilityCheck` row is recorded with `source = revalidation_2_4h` and `status = confirmed`, and no further action is taken

#### Scenario: Re-validation detects a status change to unavailable
- **WHEN** a booked appointment's re-validation check returns `unavailable`
- **THEN** the change is recorded with `source = revalidation_2_4h`, and the appointment is flagged for reprogramming rather than silently proceeding

### Requirement: Broker entity with organization-scoped isolation
The system SHALL persist a `Broker` entity (`id`, `organization_id`, `specialties`, `active`, `availability`) with Row-Level Security filtering by `organization_id`, consistent with every other business table.

#### Scenario: Broker rows isolated by organization
- **WHEN** a query for brokers runs under RLS with `app.current_org` set to organization A
- **THEN** only brokers belonging to organization A are returned, regardless of how many organizations exist

### Requirement: Auditable availability check history
Every invocation of `AvailabilityValidatorPort.check()` SHALL persist an `AvailabilityCheck` record (`property_id`, `broker_id` nullable, `slot`, `status`, `checked_at`, `source`), never overwriting a prior check's row.

#### Scenario: Multiple checks for the same slot remain distinct
- **WHEN** the same `(property_id, slot)` is checked twice (once `initial`, once `revalidation_2_4h`)
- **THEN** two separate `AvailabilityCheck` rows exist, both queryable, with different `source` and `checked_at` values
