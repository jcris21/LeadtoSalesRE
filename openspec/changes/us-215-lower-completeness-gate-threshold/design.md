## Context

`CompletenessGate` (`app/modules/lead_qualification/application/completeness_gate.py`)
is the single point of truth for the `Qualification -> Recommendation`
transition precondition (QA-14, Architecture.md §7.8/§10 Iter. 3). It reads
its default threshold from `Settings.profile_completeness_threshold`
(`app/core/config.py:42`, currently `90.0`). `BuyerProfileCaptureService`
(`app/modules/lead_qualification/application/profile_capture.py`) uses the
same setting to decide exactly when to publish `ProfileCompleted` (on
crossing, not on every update).

`BuyerProfile` has exactly 5 dimensions (`PROFILE_DIMENSIONS` in
`app/modules/lead_qualification/domain/models.py`): `budget`, `locations`,
`property_type`, `timeline`, `must_haves`. `completeness()` is
`100 * captured/5`, so the only achievable values are 0, 20, 40, 60, 80, 100 —
there is no continuous scale.

## Goals / Non-Goals

**Goals:**
- Recalibrate the platform-default completeness threshold so the gate opens
  once the 4 primary dimensions (`budget`, `locations`, `property_type`,
  `timeline`) are captured, enabling a recommendation-first flow.
- Keep `must_haves` as a Nivel 2 refinement dimension captured after Matching
  has already started (US-217 scope, not this change).
- Preserve `CompletenessGate`'s "single point of truth" contract — no new
  gate, no parallel threshold logic.

**Non-Goals:**
- Changing `PROFILE_DIMENSIONS`, `completeness()`, or the progressive
  profiling flow.
- Per-organization configurable thresholds (out of scope; the setting is
  still a single platform-wide default, consistent with current config
  architecture — see `app/core/config.py` module docstring on
  per-organization config living in `OrganizationConfig`, not here).
- Any change to the Matching/Recommendation pipeline itself.

## Decisions

- **Threshold value: `80.0`, not an arbitrary value in (80, 90).**
  Because `completeness()` only produces multiples of 20, any threshold in
  `(80, 100]` requires all 5 dimensions, and any threshold in `(60, 80]`
  requires exactly 4. `80.0` is the tightest value that satisfies "advances
  once the 4 primary dimensions are captured" while still requiring all 4 of
  them (not just 3). This matches the Gherkin literally: `completeness(profile)
  >= new threshold` must hold exactly when the 4 named dimensions are present.
- **Change the config default only — no new constructor parameter.**
  Both `CompletenessGate` and `BuyerProfileCaptureService` already accept an
  explicit `threshold`/`completeness_threshold` override, so tests that need
  a different value keep working unchanged. Only the *default* (sourced from
  `get_settings().profile_completeness_threshold`) changes.
- **Update the one test coupled to the default instead of leaving it broken.**
  `test_profile_completed_fires_exactly_on_crossing_threshold` in
  `tests/test_buyer_profile.py` calls `BuyerProfileCaptureService(session)`
  with no explicit threshold, so it exercises the real default. Its
  assertions currently assume the crossing point is 100% (5th update). With
  the new default it is 80% (4th update, before `must_haves`). The test is
  rewritten to assert the event fires once completeness reaches 80% and that
  the subsequent `must_haves` update (now pure refinement) does not
  re-publish it.
- **Add a dedicated gate-level test for the Gherkin scenario.** A new test in
  `tests/test_buyer_profile.py` builds a `BuyerProfile` with exactly the 4
  primary dimensions (no `must_haves`) and asserts
  `CompletenessGate().can_advance_to_recommendation(profile)` returns
  `can_advance=True` with `completeness == 80.0`, using the default
  (config-sourced) threshold rather than an explicit override — this is what
  actually proves the recalibration took effect end-to-end.

## Risks / Trade-offs

- [Risk] Any other test or code path silently assumes 90% is required to
  reach "qualified enough" → Mitigation: grepped the whole repo for
  `profile_completeness_threshold` and `CompletenessGate(` before making the
  change; only `tests/test_recommendation_service.py:163` and two cases in
  `tests/test_buyer_profile.py` pass an explicit `threshold=90.0`, which are
  intentionally independent of the config default and are left unchanged as
  they test gate behavior at an arbitrary threshold, not the platform
  default.
- [Risk] Downstream consumers of `ProfileCompleted` (Recommendation/Matching)
  built implicit assumptions on receiving a "fully complete" profile
  snapshot → Mitigation: `_snapshot()` in `BuyerProfileCaptureService`
  already serializes all 5 dimensions as optional/nullable fields
  (`must_haves` can be an empty list), so partial profiles were already a
  representable, tolerated shape before this change; no consumer code change
  required, verified by re-running `tests/test_recommendation_service.py`.
- [Trade-off] Recommendation quality may be lower on average since Matching
  can now run without `must_haves` — this is the intended product trade-off
  of US-215 (recommendation-first) and is explicitly deferred to US-217 for
  refinement, not something to compensate for in this change.

## Migration Plan

- Single-line config default change, no schema/data migration.
- No feature flag: this changes default behavior for all organizations
  immediately since `profile_completeness_threshold` is a platform-level
  setting (env-overridable if a rollback or per-environment tuning is ever
  needed, since it's a `Settings` field driven by `.env`).
- Rollback: revert the constant to `90.0` in `app/core/config.py`; no data
  cleanup needed since the gate is a pure read-time predicate.

## Open Questions

- Should `profile_completeness_threshold` eventually move into
  `OrganizationConfig` for per-organization tuning? Out of scope for US-215;
  flagged here for whoever picks up multi-tenant threshold configuration
  later.
