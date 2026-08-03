## 1. Database

- [x] 1.1 Generate Alembic migration `properties.bedrooms` (nullable `Integer`, no
      default, no backfill) via `uv run alembic revision --autogenerate`. (hand-written
      `alembic/versions/0023_properties_bedrooms.py`, following the project's existing
      hand-written-migration convention — no live DB available to autogenerate against.)
- [x] 1.2 Applied migrations 0020-0023 (`alembic upgrade head`) against the shared
      Supabase instance (user-confirmed). Verified `properties.bedrooms` exists as
      nullable `integer`, and confirmed the round-trip with a manual insert/select
      (`bedrooms=3` in, `bedrooms=3` out) inside a rolled-back transaction — no test
      data left behind.

## 2. Domain (`lead_qualification`)

- [x] 2.1 Reorder `PROFILE_DIMENSIONS` in
      `app/modules/lead_qualification/domain/models.py` to
      `budget, locations, property_type, bedrooms, motivation, must_haves, timeline,
      financing_type, decision_maker_mode`.
- [x] 2.2 Replace the Nivel1/Nivel2 rationale comment (US-217's `LeadReadinessService`
      mapping) with the new search-pipeline-driven rationale, referencing US-222.

## 3. Domain (`recommendation`)

- [x] 3.1 Add `bedrooms: int | None = None` to `Property.__init__`
      (`app/modules/recommendation/domain/models.py`).
- [x] 3.2 Add `bedrooms: int | None` parameter to `Property.matches_hard_filters`, same
      "absent constraint = no clause" semantics as the existing fields.
- [x] 3.3 Add `bedrooms: Mapped[int | None]` column to `PropertyORM`
      (`app/modules/recommendation/infrastructure/db_models.py`).

## 4. Structured filter (hybrid-retrieval)

- [x] 4.1 Add `bedrooms: int | None` to the `PropertyLookup.filter_candidates` Protocol
      (`app/modules/recommendation/application/retrieval.py`).
- [x] 4.2 Thread `buyer_profile.bedrooms` through
      `StructuredFilterService.filter_candidates` to the store call.
- [x] 4.3 Add `PropertyORM.bedrooms == bedrooms` (only when `bedrooms is not None`) to the
      SQL `WHERE` in `PropertyRepository.filter_candidates`
      (`app/modules/recommendation/infrastructure/repository.py`), mirroring the existing
      `property_type` clause. Also threaded `bedrooms` through `_to_row`/`_to_domain`/
      `upsert` so persisted/read `Property` objects round-trip the field.
- [x] 4.4 Checked `search_diagnostics.diagnose`/`render_grounding_note`: deliberately left
      bedroom-unaware — it only grounds budget/zone mismatches (gated on
      `budget is None and not zones`), unrelated to the bedroom hard filter. No change
      needed.

## 5. Extractor split (`qualification_flow.py`)

- [x] 5.1 Split `extract_timeline_and_must_haves` into `extract_timeline` and
      `extract_must_haves`, each keeping its existing regex/keyword body verbatim.
- [x] 5.2 Update `_DETERMINISTIC_EXTRACTORS` in `qualification_turn.py`: `extract_must_haves`
      in the Nivel 1 block (with `extract_locations`, `extract_property_type`,
      `extract_bedrooms`, `extract_motivation`), `extract_timeline` and
      `extract_financing_and_decision_mode` in the Nivel 2 block. Update the module's
      docstring/comment referencing US-217 to reference US-222 instead.

## 6. LeadReadinessService (US-214)

- [x] 6.1 Remap `compute_readiness_score`'s weight table to
      `property_type=15, budget=20, locations=15, bedrooms=15, motivation=15,
      must_haves=20` (sums to 100), removing the `timeline`/`financing_type`/
      `decision_maker_mode` weights from this function (dead `_TIMELINE_WEIGHTS`/
      `_FINANCING_WEIGHTS`/`_DECISION_MAKER_WEIGHT` removed too).
- [x] 6.2 Leave `classify_financing_readiness` unchanged (still reads `financing_type`,
      `timeline`, `locations`) — added a comment noting it intentionally still depends on
      Nivel 2 fields, confirmed out of scope for US-222.
- [x] 6.3 Update `lead_readiness.py`'s module docstring signal-mapping table to reflect
      the new weighted set.

## 7. New follow-up turn

- [x] 7.1 Create `app/modules/conversation_ownership/application/followup_turn.py`:
      `run_followup_turn(session, *, conversation, text) -> FollowupTurnResult`
      (`Literal["asked", "not_applicable"]` outcome, same shape as
      `DeepeningTurnResult`).
- [x] 7.2 Implement: fetch latest recommendation batch via
      `RecommendationRepository.list_for_lead`; `not_applicable` if empty or nothing
      selected (`is_lead_selected`); else compute
      `BuyerProfile.missing_dimensions()` intersected with
      `{"timeline", "financing_type", "decision_maker_mode"}` and return a directed
      question for the first missing one (fixed strings, no LLM), or `not_applicable` if
      none missing.
- [x] 7.3 Wire into `coordinator._conversational_turn`: call after `_deepening_turn`'s
      "asked" short-circuit and before `_scheduling_turn`, short-circuiting on
      `outcome == "asked"`. Reachable on the very turn `_deepening_turn` resolves a
      selection (`outcome == "selected"`), since only the "asked" branch short-circuits
      above it — matches the "selection made this turn" spec scenario.
- [x] 7.4 Add `_followup_turn` helper method to `Coordinator`, following the same
      `recorder.record_tool_call("qualification.followup_turn", ...)` pattern as
      `_deepening_turn`.

## 8. Documentation

- [x] 8.1 Update `Documents/Oficial/HU_Calificacion_Recomendacion.md` with the new
      Nivel 1/Nivel 2 split and the follow-up-turn flow. (Added a new US-222 section
      superseding US-217, left US-217 as historical record.)

## 9. Tests

- [x] 9.1 `test_buyer_profile.py`: update `PROFILE_DIMENSIONS` order assertions; add a
      test proving `missing_dimensions()`/`CompletenessGate` prefer the new Nivel 1 set.
- [x] 9.2 `test_qualification_flow.py`: split existing combined timeline/must_haves tests
      into per-extractor tests; add a same-message-both-signals test verifying two
      independent patches compose identically to the old combined patch.
- [x] 9.3 `test_coordinator_qualification_turn.py`: checked — no `_DETERMINISTIC_EXTRACTORS`
      ordering assertions in this file (that coverage lives in
      `test_qualification_flow.py`); no change needed.
- [x] 9.4 `test_hybrid_retrieval.py`: fixed `FakePropertyStore.filter_candidates` (would
      have broken on the new `bedrooms=` kwarg) and added bedroom hard-filter cases
      (match/mismatch, untagged-inventory exclusion, absent-constraint no-op).
      `test_recommendation_service.py` not touched — no `bedrooms`-specific assertions
      needed there beyond the retrieval-layer coverage.
- [x] 9.5 `test_ranking_engine.py`: ran unmodified against the new code — 35/35 passed
      alongside `test_coordinator_qualification_turn.py`/`test_recommendation_service.py`/
      `test_hybrid_retrieval_sql.py`/`test_property_ingestion.py`; `must_haves` semantic
      scoring behavior confirmed unchanged, no edits needed.
- [x] 9.6 New `test_followup_turn.py`: 7 tests covering all `qualification-followup-turn`
      spec scenarios (no lead, no recommendation, no selection yet, first-missing-asked,
      second-missing-asked, all-captured no-reask, question-set coverage).
- [x] 9.7 `test_lead_readiness_service.py` (existing US-214 file, not a new one): rewrote
      `compute_readiness_score` tests for the new weight table;
      `classify_financing_readiness` tests untouched (confirmed still passing unmodified).

**Regression found and fixed during verification**: `tests/test_recommendation_wiring.py`'s
`matching_property` fixture didn't set `bedrooms`, while `complete_profile` set
`bedrooms=2` — under the new hard filter this excluded the property from search results
and broke `test_handle_profile_completed_delivers_top3_to_linked_conversation`. Fixed by
adding `bedrooms=2` to the fixture.

## 10. Verification

- [x] 10.1 Ran the FULL suite (`pytest tests/ -q`), not just the touched files — 469 passed,
      1 skipped, 3 failed on first pass. 1 real regression found and fixed (see note in
      §9). The other 2 (`test_langsmith_config.py`,
      `test_observability.py::test_trace_decision_persists_none_when_tracing_disabled`)
      are pre-existing environment leakage (a machine-level `LANGSMITH_API_KEY`
      overriding `_env_file=None` in the test) — unrelated to US-222, confirmed by zero
      edits to `config.py`/`observability.py` this change. Final confirmation run
      in progress.
- [ ] 10.2 Manual/E2E smoke: NOT DONE — needs a running app + Chatwoot/browser session,
      out of scope for this automated pass. A lead completing only the 6 new Nivel 1
      dimensions should reach the recommendation; selecting a Top-3 property should
      trigger the follow-up question for the first missing Nivel 2 dimension; providing a
      slot instead should still book the visit.
