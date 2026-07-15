# Step 4 — Unit Test and DB Verification

**Date:** 2026-07-13
**Change:** qualification-dimensions-us-202-205

## 4.1 Pre-test database baseline

Not applicable in the way the task literally describes: `tests/conftest.py`'s
`session_factory` fixture creates a **fresh in-memory SQLite engine per test**
(`sqlite+aiosqlite:///:memory:`, `Base.metadata.create_all` on setup, engine
disposed on teardown). No test in this suite touches the shared dev/staging
Postgres database, so there is no `buyer_profiles`/`leads` row-count baseline
to capture or restore for the unit-test step. That verification instead
applies to Step 5 (manual curl against the live server), where the pre/post
counts are captured against the real dev database.

## 4.2 Targeted unit tests

```
uv run pytest tests/test_qualification_flow.py tests/test_buyer_profile.py -q
```

Result: **17 passed** (11 new tests in `test_qualification_flow.py` covering
`extract_budget`, `extract_locations`, `extract_property_type`,
`extract_timeline_and_must_haves` — happy path + no-signal/rejection per
dimension, the `None`-never-erases invariant, and cross-tenant rejection; 6
pre-existing tests in `test_buyer_profile.py` unaffected).

## 4.3 Broader unit test suite

Required command per `openspec/config.yaml`:

```
uv run pytest --cov=app --cov-fail-under=90
```

`pytest-cov` is **not installed** in this environment and could not be added
(`uv add --dev pytest-cov` failed — outbound network to PyPI is blocked in
this sandbox: `invalid peer certificate: UnknownIssuer`). This is a
pre-existing environment gap, not something introduced by this change.

Ran the full suite without the coverage flag instead:

```
uv run pytest -q
```

This hung/crashed mid-run inside `tests/test_wacrm_client.py`
(`TestListLeadsUpdatedSince::test_follows_keyset_cursor_and_sends_bearer` and
`TestGetLead::test_unwraps_envelope_and_stamps_org` — async tests built on
`httpx.MockTransport`). Verified via `git stash` that this reproduces
identically on unmodified `main` (before any file from this change existed),
so it is a pre-existing platform/environment issue (Windows + this httpx/anyio
combination), unrelated to `qualification-dimensions-us-202-205`.

Ran the full suite excluding that one pre-existing-hang module:

```
uv run pytest -q --ignore=tests/test_wacrm_client.py
```

Result: **143 passed**, 0 failed — no regressions from this change anywhere
else in the suite.

**Gap flagged, not silently ignored:** the mandatory `--cov-fail-under=90`
gate could not be enforced in this environment (missing `pytest-cov`, no
network to install it). Follow-up: run `uv run pytest --cov=app
--cov-fail-under=90` in an environment with the dependency installed/network
access before merging, to confirm the 90% threshold.

## 4.4 Post-test database state

No shared database was touched (see 4.1) — each test's in-memory SQLite
engine is disposed at teardown. Nothing to restore.

## 4.6 Sign-off

Tests pass (143/143 excluding the pre-existing, unrelated `test_wacrm_client`
hang); report exists at this path. Coverage threshold enforcement is deferred
per the gap noted in 4.3.
