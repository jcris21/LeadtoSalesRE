## 0. Setup: Create Feature Branch (MANDATORY - FIRST STEP)

- [x] 0.1 Create feature branch `feature/qualification-dimensions-us-202-205` from `main`
- [x] 0.2 Verify branch creation and current branch status

## 1. Qualification Flow module

- [x] 1.1 Create `app/modules/lead_qualification/application/qualification_flow.py` with
      `extract_budget`, `extract_locations`, `extract_property_type`,
      `extract_timeline_and_must_haves` — each returns a `ProfilePatch | None` and, when non-None,
      calls `BuyerProfileCaptureService.update_profile`
- [x] 1.2 `extract_property_type` uses keyword matching (with common Spanish synonyms) first, no LLM
      call required for the common case
- [x] 1.3 Each extractor swallows `ProfileValidationError` into a re-prompt return value instead of
      letting it propagate as an unhandled exception
- [x] 1.4 Each extractor verifies the lead's `organization_id` matches the caller context before
      calling `update_profile` (tenant isolation)

## 2. Support/QA REST endpoints

- [x] 2.1 Create `app/modules/lead_qualification/api/router.py` with
      `POST /api/v1/leads/{lead_id}/profile/budget`
- [x] 2.2 Add `POST /api/v1/leads/{lead_id}/profile/locations`
- [x] 2.3 Add `POST /api/v1/leads/{lead_id}/profile/property-type`
- [x] 2.4 Add `POST /api/v1/leads/{lead_id}/profile/timeline`
- [x] 2.5 Add `POST /api/v1/leads/{lead_id}/profile/must-haves`
- [x] 2.6 Each endpoint returns 200 `{completeness, captured_dimensions}` on success, 404 on
      `LeadNotFoundError`, 422 on `ProfileValidationError`
- [x] 2.7 Register the router in `app/main.py`

## 3. Backend: Review and Update Existing Unit Tests (MANDATORY)

- [x] 3.1 Review `tests/test_buyer_profile.py` for coverage gaps the new extractors expose (budget
      formats, multi-zone, property type synonyms, timeline+must_haves combined patch)
- [x] 3.2 Add unit tests for `qualification_flow.py`: one happy-path + one rejection/no-signal case
      per dimension (budget, locations, property_type, timeline, must_haves)
- [x] 3.3 Add a test asserting a `None` field on `ProfilePatch` never erases a previously captured
      value (`BuyerProfile.apply` behavior, referenced by the timeline/must_haves spec scenario)
- [x] 3.4 Add a cross-tenant rejection test (lead belongs to a different `organization_id`)

## 4. Backend: Run Unit Tests and Verify Database State (MANDATORY)

- [x] 4.1 Capture pre-test database baseline for `buyer_profiles`/`leads` row counts relevant to the
      change
- [x] 4.2 Run targeted unit tests for `qualification_flow.py` and `profile_capture.py`
- [x] 4.3 Run the required broader unit test suite (`uv run pytest --cov=app --cov-fail-under=90` per
      `openspec/config.yaml`)
- [x] 4.4 Verify post-test database state and restore if needed
- [x] 4.5 Create report
      `openspec/changes/qualification-dimensions-us-202-205/reports/YYYY-MM-DD-step-4-unit-test-and-db-verification.md`
- [x] 4.6 Mark this step complete only after tests pass and the report exists

## 5. Backend: Manual Endpoint Testing with curl (MANDATORY - AGENT MUST EXECUTE)

- [x] 5.1 Ensure the backend server is running (start if needed) — resolved (see
      `reports/2026-07-15-step-5-curl-endpoint-verification.md`): the venv's Python interpreter had a
      broken OpenSSL (`OPENSSL_Uplink` crash on any TLS connection); rebuilding `.venv` against a
      working local Python 3.12 interpreter fixed it and the server started against the real DB
- [x] 5.2 Test each of the 5 POST endpoints with curl: valid payload (verify 200 + completeness/
      captured_dimensions), invalid payload (verify 422), non-existent lead (verify 404) — all 15
      checks passed, see report
- [x] 5.3 For each successful POST, restore database state afterward (delete/revert the persisted
      dimension value) — temporary organization/lead/buyer_profile rows deleted after the run
- [x] 5.4 Document all curl commands and responses in
      `openspec/changes/qualification-dimensions-us-202-205/reports/2026-07-15-step-5-curl-endpoint-verification.md`
- [x] 5.5 Verify database state matches pre-test state after cleanup — confirmed 0 rows remaining
      for the temp organization/lead/buyer_profile ids (see report)

## 6. Update Technical Documentation (MANDATORY)

- [x] 6.1 Update `Documents/Oficial/HU_Calificacion_Recomendacion.md` rows for US-202–US-205: rows
      stay "Parcial" — Step 5 (curl verification) is now done (2026-07-15), but per design.md's own
      scope note, "Implementado" requires AI-104 (Coordinator Agent) to route real conversation turns
      into `qualification_flow.py`'s extractors, which remains a separate, not-yet-started change;
      each row's Alineación (b) names the concrete extractor/endpoint implemented
- [x] 6.2 Cross-reference this change and `openspec/specs/lead-qualification/us-202-205-enrichment.md`
      from the updated HU rows
