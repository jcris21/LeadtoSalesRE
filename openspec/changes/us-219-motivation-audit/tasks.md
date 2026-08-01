## 1. Enrich (re-verify HU vs. real implementation)

- [x] 1.1 Read `Documents/Oficial/HU_Calificacion_Recomendacion.md` lines 942-964 (US-219 Gherkin +
      alignment notes)
- [x] 1.2 Read the real `Motivation` enum and `_INAPPLICABLE_DIMENSIONS_BY_PROPERTY_TYPE` in
      `app/modules/lead_qualification/domain/models.py`
- [x] 1.3 Read the real `extract_motivation`/`_MOTIVATION_KEYWORDS` in
      `app/modules/lead_qualification/application/qualification_flow.py`
- [x] 1.4 Read the wiring in `qualification_turn.py` and the migration
      `alembic/versions/0022_us219_buyer_profile_motivation.py`
- [x] 1.5 Confirm the "skip piso if CASA" Gherkin example maps to "skip bedrooms if
      LAND/COMMERCIAL" in this codebase (no floor/piso field exists) — documented, intentional,
      already justified in the original `design.md`, not a gap

## 2. Propose (audit the existing OpenSpec artifacts against reality)

- [x] 2.1 Read `openspec/changes/us-219-motivation-adaptive-questions/{proposal,design,tasks}.md`
      and `specs/lead-qualification-flow/spec.md`
- [x] 2.2 Compare every checked task in that change's `tasks.md` against the actual code — all
      verified present and correct
- [x] 2.3 Create this audit change directory (`us-219-motivation-audit/`) documenting the
      comparison, the one intentional Gherkin-vs-implementation deviation, and the two stale-test
      findings

## 3. Apply (verify green, fix small scoped bugs only)

- [x] 3.1 Run `tests/test_qualification_flow.py` + `tests/test_buyer_profile.py` +
      `tests/test_us219_migration.py` — found 2 pre-existing stale assertions (not production bugs)
- [x] 3.2 Fix `test_deterministic_extractors_run_nivel_2_bedrooms_last` (renamed to
      `test_deterministic_extractors_run_nivel_2_last`) to assert `extract_motivation` is last,
      matching the already-correct `_DETERMINISTIC_EXTRACTORS` ordering in `qualification_turn.py`
- [x] 3.3 Fix `test_profile_completed_fires_exactly_on_crossing_threshold`'s hardcoded `100.0` to
      `pytest.approx(800.0 / 9)`, matching the already-correct "fires exactly on crossing 80%"
      behavior of `BuyerProfileCaptureService.update_profile`
- [x] 3.4 Re-run `tests/test_qualification_flow.py` + `tests/test_buyer_profile.py` +
      `tests/test_us219_migration.py` — 52 passed
- [x] 3.5 Run the full suite (offline, `uv run --offline pytest`) — 361 passed, 1 skipped, excluding
      6 files that abort mid-run for an unrelated, pre-existing sandbox/environment reason (real
      HTTP-client construction under Windows sandbox network restrictions), documented in
      `design.md` and confirmed unrelated to US-219's code paths

## 4. Commit

- [x] 4.1 Commit the two test fixes + this audit OpenSpec directory with a conventional commit
      message
