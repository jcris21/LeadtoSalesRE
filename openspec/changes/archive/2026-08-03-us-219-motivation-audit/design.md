## Context

US-219 (`Documents/Oficial/HU_Calificacion_Recomendacion.md` lines 942-964, marked `[NUEVA]`) was
implemented and merged directly (`dcdac31` -> `759e9ba`) with its own OpenSpec change
(`us-219-motivation-adaptive-questions/`, tasks all checked, claiming "full suite: 416 passed, 1
skipped"). This audit worktree was created to re-verify that claim end to end, on the actual merged
branch tip, since the story skipped the usual dedicated-worktree review cycle.

## Audit Method

1. Read the HU's Gherkin/alignment notes and the existing `us-219-motivation-adaptive-questions/`
   proposal.md, design.md, tasks.md, and spec.md.
2. Read the real implementation: `Motivation` enum and `_INAPPLICABLE_DIMENSIONS_BY_PROPERTY_TYPE` in
   `app/modules/lead_qualification/domain/models.py`, `extract_motivation`/`_MOTIVATION_KEYWORDS` in
   `app/modules/lead_qualification/application/qualification_flow.py`, wiring in
   `qualification_turn.py`, persistence in `infrastructure/db_models.py` +
   `infrastructure/repository.py`, and the migration
   `alembic/versions/0022_us219_buyer_profile_motivation.py`.
3. Ran the dedicated US-219 tests, then the full suite, offline (`uv run --offline pytest`, since
   this sandbox has no outbound network access to PyPI — `uv`'s local wheel cache was already
   populated and sufficient).

## Findings

### Implementation vs. HU Gherkin

The literal Gherkin scenario (`property_type = CASA` -> "no se pregunta por piso/nivel") cannot be
implemented literally: this codebase has no floor/piso field anywhere in `BuyerProfile`. The
original implementers already recognized and documented this in their own `design.md`
("Non-Goals: Not introducing a literal floor/piso dimension") and picked the closest real analogue:
`bedrooms` is excluded from `missing_dimensions()`/`completeness()` for `PropertyType.LAND` and
`PropertyType.COMMERCIAL` (property types where asking bedroom count is genuinely irrelevant),
**not** for `CASA`/`HOUSE` as the literal Gherkin text would suggest. This audit confirms that
mapping is still the most reasonable one available in the current domain model and requires no
change — `HOUSE` legitimately does have a bedroom count worth asking about, unlike the Gherkin's
"piso" (floor number within a building), which only applies to apartments and simply doesn't exist
as a field to skip.

### Implementation vs. OpenSpec proposal

Full match. Every task in `us-219-motivation-adaptive-questions/tasks.md` is verifiably done in the
current code:
- `Motivation` StrEnum with the 4 HU-specified categories.
- `motivation` is `PROFILE_DIMENSIONS[8]` (9th dimension), sorted last (Nivel 2) per the
  Nivel-1/Nivel-2 ordering convention established by US-217.
- `extract_motivation` follows the same tenant-assert -> keyword-match -> `ProfilePatch` ->
  `BuyerProfileCaptureService.update_profile` pattern as every other extractor in the file.
- `buyer_profiles.motivation` (nullable `String(32)`) added via migration `0022`, chained correctly
  off head `0021`, with a working `downgrade()` (verified by
  `tests/test_us219_migration.py::test_upgrade_adds_motivation_column` /
  `test_downgrade_drops_motivation_column`, both passing).
- Round-trip persistence (`BuyerProfileRepository.save`/`_to_domain`) correctly maps
  `Motivation(row.motivation)` both ways.

### Test suite: two stale assertions, no production bugs

`tasks.md` §5.4 claims the suite was fixed for the 9-dimension/motivation change and passed at 416/1
skipped. Re-running the suite on this branch tip today surfaces 2 failures, both **test-only staleness**,
not production defects:

1. `test_deterministic_extractors_run_nivel_2_bedrooms_last` hardcoded `extract_bedrooms` as the
   last deterministic extractor; US-219 correctly appends `extract_motivation` after it. The
   production ordering is correct and intentional (`qualification_turn.py`'s own comment documents
   Nivel 1 -> Nivel 2 precedence); only the test's assumption was outdated.
2. `test_profile_completed_fires_exactly_on_crossing_threshold` hardcoded `100.0` as the
   `ProfileCompleted` event's stored completeness. With 9 dimensions and the US-215-lowered 80%
   threshold, the event now (correctly) fires when completeness first crosses 80% — at the 8th
   captured dimension, `8/9 ≈ 88.89%` — not when the profile later reaches 100%. This is exactly the
   documented "fires exactly once, on crossing" semantics; the test's `100.0` literal was never
   updated for the interaction of US-215 (lower threshold) + US-219 (9th dimension).

Both are fixed as test-only changes (see `proposal.md`). No `app/` code changed.

### Unrelated environment finding (out of scope, documented for the record)

6 test files unrelated to `lead_qualification`/US-219 (`test_wacrm_client.py`,
`test_recommendation_wiring.py`, `test_generative_extractor.py`, `test_llm_conversation_brain.py`,
`test_observability.py`, `test_query_embedding.py`, `test_recommendation_schema_persistence.py` —
6 files, one item overlaps the wiring/persistence pair) abort mid-run with no traceback (bare
process exit, exit code 1) in this specific sandboxed Windows shell, each after a test that
constructs a real HTTP/API client (e.g. `GoogleMapsClient`, wacrm's `httpx.AsyncClient`) even though
the calls themselves are mocked via `httpx.MockTransport`. This reproduces identically outside any
change from this audit and is unrelated to US-219's code paths — left untouched and out of scope.

## Risks / Trade-offs

None — this change modifies only test assertions to match already-correct, already-merged
production behavior. No behavior change for any lead, organization, or API consumer.
