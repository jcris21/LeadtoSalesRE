## Why

The Appointment module (`app/modules/appointment/`) is an empty stub — no code exists to confirm that a
property and its assigned broker are actually available before proposing or confirming a visit slot to a
lead. Per `Documents/Oficial/ImplementationPlan.md` (Sprint 4) and
`Documents/Oficial/ArchitecturalDrivers.md` (E6), this is the mitigation for the single **critical
business risk** of the customer journey: booking a visit to a property that is not actually available.
No downstream scheduling work (Google Calendar Adapter, Scheduling Service, Reminder Scheduler — US-403
to US-406) can safely proceed without this deterministic gate existing first.

## What Changes

- Add a new `AvailabilityValidatorPort.check(property_id, slot) -> confirmed | pending | unavailable`,
  implemented as a deterministic service (no LLM), per `Architecture.md` §7.13/§8.
- Add domain entities `Broker` (organization-scoped: specialties, active flag, availability) and
  `AvailabilityCheck` (auditable record of every validation, including the *source* of the check —
  `initial` proposal vs. automatic `revalidation_2_4h` before the visit).
- Persist both with Row-Level Security by `organization_id`, consistent with every other table since
  Sprint 0.
- Add a scaffolded `app/modules/appointment/` module (`domain/`, `application/`, `infrastructure/`)
  following the same Ports & Adapters convention already used by `lead_qualification/` and
  `recommendation/`.
- Add Alembic migration `0016_sprint4_1_brokers_availability` creating `brokers` and
  `availability_checks`.
- No changes to any existing capability's requirements — this is additive, new capability only.

## Capabilities

### New Capabilities
- `appointment-availability`: deterministic validation of property + broker availability for a proposed
  or already-booked visit slot, including automatic re-validation 2-4h before the visit. Covers
  `AvailabilityValidatorPort`, the `Broker` and `AvailabilityCheck` domain entities, and their
  persistence.

### Modified Capabilities
- None. `properties` (from `property-catalog`) is only read, not modified — `AvailabilityCheck`
  references `property_id` as a foreign key without changing the `Property` aggregate's own schema or
  behavior.

## Impact

- **New code:** `app/modules/appointment/domain/models.py`, `application/availability_validator.py`,
  `infrastructure/db_models.py`, `infrastructure/repository.py`.
- **New migration:** `alembic/versions/0016_sprint4_1_brokers_availability.py`.
- **New tests:** `tests/test_availability_validator.py` — including the critical acceptance test: no
  appointment-booking code path may proceed past `unavailable`.
- **No breaking changes** to any existing module; `appointment/` was an unused stub.
- **Blocks/unblocks:** unblocks US-403 (Google Calendar Adapter) and US-404 (Scheduling Service), which
  both require a `confirmed` `AvailabilityCheck` before creating a Calendar event or persisting an
  `Appointment` (per `Documents/Oficial/HU_Appointment_Handoff_Ownership.md`, Sprint 4.1 dependency map).
