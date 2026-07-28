## 1. Configuration

- [x] 1.1 Change `profile_completeness_threshold` default from `90.0` to
      `80.0` in `app/core/config.py`, updating the inline comment to explain
      the 4/5-dimension rationale.

## 2. Tests

- [x] 2.1 Rewrite `test_profile_completed_fires_exactly_on_crossing_threshold`
      in `tests/test_buyer_profile.py` so `ProfileCompleted` is asserted to
      fire exactly once, at `completeness == 80.0`, after the 4th update
      (`timeline`), and the subsequent `must_haves` update does not
      re-publish it.
- [x] 2.2 Add a new test in `tests/test_buyer_profile.py` that builds a
      `BuyerProfile` with the 4 primary dimensions captured (no
      `must_haves`) and asserts `CompletenessGate()` (default, config-sourced
      threshold) returns `can_advance=True` with `completeness == 80.0`.
- [x] 2.3 Confirm `tests/test_recommendation_service.py` and the two
      explicit-threshold cases in `tests/test_buyer_profile.py` still pass
      unchanged (they pass `threshold=90.0` explicitly and are independent
      of the config default).

## 3. Verification

- [x] 3.1 Run `uv run pytest tests/test_buyer_profile.py
      tests/test_recommendation_service.py -q` and confirm all green.
      (Run via the repo's existing `.venv` python -m pytest, since `uv sync`
      could not reach PyPI in this sandbox; 16/16 passed.)
- [x] 3.2 Run the full suite touching `lead_qualification` and
      `recommendation` modules to catch any other implicit dependency on the
      old 90% default. Full suite also run: 145/145 passed.
