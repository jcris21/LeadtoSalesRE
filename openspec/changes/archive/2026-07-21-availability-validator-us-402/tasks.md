## 1. Module scaffolding

- [x] 1.1 Create `app/modules/appointment/domain/__init__.py`, `application/__init__.py`,
      `infrastructure/__init__.py` following the exact layout of `app/modules/lead_qualification/`
- [x] 1.2 Define `AvailabilityStatus` enum (`confirmed`, `pending`, `unavailable`) and
      `AvailabilityCheckSource` enum (`initial`, `revalidation_2_4h`) in `domain/models.py`
- [x] 1.3 Define `Broker` entity (`id`, `organization_id`, `specialties: tuple[str, ...]`,
      `active: bool`, `availability: dict`) in `domain/models.py`
- [x] 1.4 Define `AvailabilityCheck` value object (`property_id`, `broker_id: UUID | None`, `slot`,
      `status: AvailabilityStatus`, `checked_at`, `source: AvailabilityCheckSource`) in `domain/models.py`

## 2. Persistence

- [x] 2.1 Add `BrokerORM` and `AvailabilityCheckORM` to `infrastructure/db_models.py`
      (organization_id FK + index, matching `PropertyORM`/`RecommendationORM` conventions)
- [x] 2.2 Write Alembic migration `0016_sprint4_1_brokers_availability.py`: create `brokers` and
      `availability_checks` tables with RLS policies scoped by `organization_id`
- [x] 2.3 Implement `BrokerRepository` (get_by_id, list_active_for_organization) and
      `AvailabilityCheckRepository` (save, list_for_property_and_slot) in `infrastructure/repository.py`

## 3. Availability Validator service

- [x] 3.1 Define `AvailabilityValidatorPort` Protocol in `application/availability_validator.py`
      (`check(property_id: UUID, slot: datetime) -> AvailabilityStatus`)
- [x] 3.2 Implement the deterministic `AvailabilityValidatorService` (MVP logic: `pending` when no
      real-time broker/owner signal exists; never silently promotes `pending` to `confirmed`)
- [x] 3.3 Persist every `check()` invocation as an `AvailabilityCheck` row via
      `AvailabilityCheckRepository.save`, tagging `source` correctly (`initial` vs.
      `revalidation_2_4h` — caller-supplied, per design.md Open Questions)
- [x] 3.4 Wire OpenTelemetry span + `AIDecisionTrace` emission around `check()` (module, result,
      latency), reusing the existing tracing pattern from Sprint 0 — no new tracing infra needed

## 4. Tests

- [x] 4.1 `tests/test_availability_validator.py`: unit tests for `confirmed`/`pending`/`unavailable`
      paths, asserting `pending` never silently becomes `confirmed`
- [x] 4.2 **Critical acceptance test:** assert no code path can produce a `confirmed` booking signal
      without `AvailabilityCheck.status == confirmed` existing first for that `(property_id, slot)`
- [x] 4.3 Test RLS isolation: brokers/availability_checks from organization A never leak into a query
      scoped to organization B
- [x] 4.4 Test that two checks for the same `(property_id, slot)` with different `source` persist as
      two distinct rows (no overwrite)

## 5. Documentation

- [x] 5.1 Update `Documents/Oficial/HU_Appointment_Handoff_Ownership.md` US-402 "Implementado hoy" column
      from `[GAP]` to reflect the new status once merged
- [x ] 5.2 Run `openspec-sync-specs` (or equivalent) to promote `specs/appointment-availability/spec.md`
      into `openspec/specs/appointment-availability/spec.md` once implementation lands, mirroring the
      archive step already used for prior sprints (`sprint-3-2-hybrid-retrieval-sql`, etc.) — deferred to
      the `/opsx:archive` step, not run as part of `/opsx:apply`
