## Why

US-219 (`Documents/Oficial/HU_Calificacion_Recomendacion.md` lines 942-964) was implemented and
merged (commit `dcdac31`, merged at `759e9ba`) via `openspec/changes/us-219-motivation-adaptive-questions/`,
but never went through a dedicated worktree + `/enrich-us` -> `/propose` -> `/apply` cycle in the
session that reviewed it. This change is a formal audit/verification pass: confirm the merged
implementation actually matches the Gherkin/alignment notes in the HU doc and the existing OpenSpec
proposal, run the full test suite, and fix any small, narrowly-scoped bugs found along the way.

## What Changes

This is an audit, not a feature change. No production behavior is added. Findings:

- **Implementation matches the existing OpenSpec proposal exactly.** `Motivation` StrEnum
  (`relocation | investment | vacation | first_home`), `extract_motivation` in
  `qualification_flow.py`, the 9th `PROFILE_DIMENSIONS` entry, the `buyer_profiles.motivation`
  column (migration `alembic/versions/0022_us219_buyer_profile_motivation.py`), and the
  `_INAPPLICABLE_DIMENSIONS_BY_PROPERTY_TYPE` adaptive filter are all present and wired exactly as
  `us-219-motivation-adaptive-questions/design.md` describes.
- **Documented, intentional deviation from the literal Gherkin example** (not a bug): the HU's
  scenario says "given `property_type = CASA`, no se pregunta por piso/nivel" — this codebase has no
  floor/piso dimension at all, so the implementers (correctly, and already documented in their own
  `design.md` "Context"/"Non-Goals") mapped the *general pattern* (skip Nivel 2 questions irrelevant
  to `property_type`) onto the closest real dimension: `bedrooms` is excluded for `LAND` and
  `COMMERCIAL` property types, not `CASA`. This is a reasonable, pre-documented interpretation given
  the codebase's actual domain model — re-confirmed correct by this audit, not changed.
- **Two stale test assertions found and fixed** (regressions from the interaction of US-219 landing
  alongside US-215's threshold change and US-217's extractor reordering, never re-verified together
  after all three merged into this branch's base):
  1. `tests/test_qualification_flow.py::test_deterministic_extractors_run_nivel_2_bedrooms_last` —
     asserted `_DETERMINISTIC_EXTRACTORS[-1] is extract_bedrooms`, but US-219 correctly appends
     `extract_motivation` (also Nivel 2) after `extract_bedrooms` in
     `app/modules/lead_qualification/application/qualification_turn.py`. The *implementation* is
     correct; the test was never updated. Renamed to
     `test_deterministic_extractors_run_nivel_2_last` and updated to assert both Nivel-2-only
     extractors (`extract_bedrooms`, `extract_motivation`) sort after every Nivel 1 extractor, with
     `extract_motivation` last.
  2. `tests/test_buyer_profile.py::test_profile_completed_fires_exactly_on_crossing_threshold` —
     asserted the `ProfileCompleted` event's stored `completeness` snapshot equals `100.0`, but with
     9 `PROFILE_DIMENSIONS` (post-US-219) and `profile_completeness_threshold = 80.0` (post-US-215),
     the event actually (and correctly, per `BuyerProfileCaptureService.update_profile`'s
     fire-exactly-once-on-crossing design) fires when the 8th dimension is captured
     (`8/9 ≈ 88.89%` ≥ 80%), not when the 9th (`must_haves`) later completes the profile to 100%. The
     *implementation* behaves exactly as designed ("exactly on crossing", not "when finally 100%");
     the test's hardcoded `100.0` expectation was stale. Updated to assert
     `pytest.approx(800.0 / 9)`.

  Neither fix touches production code — both are test-only corrections to match already-correct,
  already-merged behavior.

## Capabilities

### Modified Capabilities

(none — no capability/spec content changes; `lead-qualification-flow`'s spec in
`openspec/changes/us-219-motivation-adaptive-questions/specs/lead-qualification-flow/spec.md`
already accurately describes the current behavior and needs no update)

## Impact

- `tests/test_qualification_flow.py` — test rename + assertion update (no production code change).
- `tests/test_buyer_profile.py` — assertion update (no production code change).
- No schema, API, or domain model changes.
- Full suite (excluding 6 pre-existing, US-219-unrelated test files that crash mid-run in this
  sandboxed Windows environment due to real-network-client construction being blocked by the
  sandbox — `test_wacrm_client.py`, `test_recommendation_wiring.py`, `test_generative_extractor.py`,
  `test_llm_conversation_brain.py`, `test_observability.py`, `test_query_embedding.py`,
  `test_recommendation_schema_persistence.py`): **361 passed, 1 skipped**. The
  `lead_qualification`-specific suite most relevant to US-219
  (`test_qualification_flow.py` + `test_buyer_profile.py` + `test_us219_migration.py`): **52
  passed**.
