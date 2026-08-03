## 1. Domain model

- [x] 1.1 Add `Motivation` StrEnum (`RELOCATION`, `INVESTMENT`, `VACATION`, `FIRST_HOME`) to
      `app/modules/lead_qualification/domain/models.py`
- [x] 1.2 Add `motivation` to `PROFILE_DIMENSIONS`
- [x] 1.3 Add `motivation` field to `ProfilePatch`
- [x] 1.4 Add `motivation` param/attribute to `BuyerProfile.__init__`, `apply`, `captured_dimensions`
- [x] 1.5 Add `_INAPPLICABLE_DIMENSIONS_BY_PROPERTY_TYPE` lookup (LAND/COMMERCIAL -> {"bedrooms"})
- [x] 1.6 Update `BuyerProfile.missing_dimensions()` and `completeness()` to exclude inapplicable
      dimensions for the profile's current `property_type`

## 2. Extractor

- [x] 2.1 Add `_MOTIVATION_KEYWORDS` keyword table to
      `app/modules/lead_qualification/application/qualification_flow.py`
- [x] 2.2 Add `extract_motivation` async function (same pattern as `extract_property_type`:
      tenant-assert, first-match-wins, persist via `BuyerProfileCaptureService`)

## 3. Turn orchestration

- [x] 3.1 Add `extract_motivation` to `_DETERMINISTIC_EXTRACTORS` in
      `app/modules/lead_qualification/application/qualification_turn.py`

## 4. Persistence

- [x] 4.1 Add `motivation: Mapped[str | None]` column to `BuyerProfileORM`
      (`app/modules/lead_qualification/infrastructure/db_models.py`)
- [x] 4.2 Map `motivation` in `BuyerProfileRepository.save` and `_to_domain`
      (`app/modules/lead_qualification/infrastructure/repository.py`)
- [x] 4.3 Verify the actual current alembic head by inspecting `alembic/versions/*.py`
      `down_revision` chains (do not assume from docs) — confirmed single linear chain, head is
      `0021_knowledge_documents`
- [x] 4.4 Create new migration `alembic/versions/0022_us219_buyer_profile_motivation.py` with
      `down_revision="0021"`, adding nullable `buyer_profiles.motivation` (`String(32)`), with a
      working `downgrade()`

## 5. Tests

- [x] 5.1 Add `extract_motivation` tests to `tests/test_qualification_flow.py` (one happy path per
      motivation category, one no-signal case, tenant isolation)
- [x] 5.2 Add adaptive `missing_dimensions()`/`completeness()` tests to
      `tests/test_qualification_flow.py` or a new domain test module (LAND/COMMERCIAL excludes
      bedrooms; APARTMENT/HOUSE/None do not)
- [x] 5.3 Add a migration upgrade/downgrade test (column exists after upgrade, gone after downgrade)
      — `tests/test_us219_migration.py`
- [x] 5.4 Run the full `lead_qualification` test suite and confirm no regressions — required fixing
      pre-existing tests in `tests/test_buyer_profile.py`, `tests/test_recommendation_service.py`,
      `tests/test_recommendation_wiring.py`, `tests/test_coordinator_qualification_turn.py` whose
      fixtures assumed 8 dimensions / did not set `motivation`

## 6. Wrap-up

- [x] 6.1 Run `pytest` for the affected modules and record pass/fail counts — full suite:
      416 passed, 1 skipped
- [x] 6.2 Commit with a conventional commit message referencing US-219
