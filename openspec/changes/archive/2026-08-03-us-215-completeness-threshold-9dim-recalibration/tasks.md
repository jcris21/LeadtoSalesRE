## 1. Configuration

- [x] 1.1 Change `profile_completeness_threshold` default from `80.0` to
      `65.0` in `app/core/config.py`, updating the inline comment to explain
      the 6/9 (Nivel 1 complete) vs 5/9 rationale.

## 2. Tests

- [x] 2.1 Rewrite `test_profile_completed_fires_exactly_on_crossing_threshold`
      in `tests/test_buyer_profile.py` so `ProfileCompleted` is asserted to
      fire exactly once, at `completeness == pytest.approx(600.0 / 9)`,
      immediately after the 6th update (`decision_maker_mode`, the last
      Nivel 1 dimension), and the three subsequent Nivel 2 updates
      (`bedrooms`, `motivation`, `must_haves`) do not re-publish it.
- [x] 2.2 Add a new test in `tests/test_buyer_profile.py` that builds a
      `BuyerProfile` with exactly the six Nivel 1 dimensions captured (no
      Nivel 2 dimension) and asserts `CompletenessGate()` (default,
      config-sourced threshold) returns `can_advance=True` with
      `completeness == pytest.approx(600.0 / 9)`.
- [x] 2.3 Add a new test in `tests/test_buyer_profile.py` that builds a
      `BuyerProfile` with only five of the six Nivel 1 dimensions captured
      and asserts `CompletenessGate()` (default) returns
      `can_advance=False` with `completeness == pytest.approx(500.0 / 9)`.
- [x] 2.4 Fix `test_deterministic_extractors_run_nivel_2_bedrooms_last` in
      `tests/test_qualification_flow.py` (pre-existing failure from the
      US-219 merge, unrelated to the threshold value but in a file this
      change is asked to bring current): assert `extract_motivation` is the
      last deterministic extractor and that both Nivel-2-only extractors
      (`extract_bedrooms`, `extract_motivation`) follow every Nivel 1
      extractor.
- [x] 2.5 Confirm tests using an explicit `CompletenessGate(threshold=...)`
      override (e.g. `test_gate_blocks_incomplete_profile_with_directed_missing_dimension`,
      `test_gate_allows_complete_profile`, `test_gate_prefers_nivel_1_missing_dimension_over_nivel_2`)
      still pass unchanged — they are independent of the config default.

## 3. Verification

- [x] 3.1 Run `uv run pytest tests/test_buyer_profile.py
      tests/test_qualification_flow.py -q` and confirm all green.
- [x] 3.2 Run `uv run pytest -q` (full suite) and confirm no regressions
      versus the pre-change baseline captured before this change
      (406 passed / 2 known-stale failures / 1 skipped / 16 deselected due
      to a pre-existing, unrelated sandbox SSL/`httpx.AsyncClient()` hang
      also noted in the original `us-215-lower-completeness-gate-threshold`
      change's tasks.md).
