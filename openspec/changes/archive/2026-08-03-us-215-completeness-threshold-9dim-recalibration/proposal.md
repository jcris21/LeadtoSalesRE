## Why

US-219 added `motivation` as a 9th entry to `PROFILE_DIMENSIONS`
(`app/modules/lead_qualification/domain/models.py`), on top of the 8
dimensions already in place when the original US-215 change set
`profile_completeness_threshold` to `80.0`. That recalibration was tuned for
an 8-dimension model where the 6 Nivel 1 ("core") dimensions crossed the
threshold correctly; with 9 dimensions, 6/9 ≈ 66.67%, which is now *below*
80.0. The `CompletenessGate` therefore no longer opens once the six Nivel 1
signals (`budget`, `locations`, `property_type`, `timeline`,
`financing_type`, `decision_maker_mode`) are captured — it additionally
requires 2 of the 3 Nivel 2 refinement dimensions (`must_haves`, `bedrooms`,
`motivation`), defeating the "recommendation-first once core signals are
known" intent US-215 was written to deliver.

This is a narrow recalibration follow-up: the gate's *rule* (open once
Nivel 1 is complete) is unchanged; only the threshold *constant* needs to
track the current size of `PROFILE_DIMENSIONS`.

## What Changes

- Recalibrate `profile_completeness_threshold` from `80.0` to `65.0` in
  `app/core/config.py`. Justification: with 9 dimensions, `completeness()` =
  `100 * captured/9`. The two achievable values around the Nivel-1-complete
  crossing are 5/9 ≈ 55.56% (one Nivel 1 dimension still missing — gate must
  stay closed) and 6/9 ≈ 66.67% (all Nivel 1 dimensions captured — gate must
  open). `65.0` is the value that opens the gate exactly at 6/9 while
  keeping a rounding margin above 5/9, without requiring any Nivel 2
  dimension.
- Update `tests/test_buyer_profile.py` so tests that rely on the
  config-sourced default threshold (rather than an explicit override)
  assert against the 6/9 ≈ 66.67% crossing point, not the old 80.0/8-
  dimension assumption.
- Update `tests/test_qualification_flow.py` for any end-to-end assertions
  that assumed the old default threshold or an earlier dimension count.
- No change to `PROFILE_DIMENSIONS`, `BuyerProfile.completeness()`, or
  `CompletenessGate`'s comparison logic (`completeness >= threshold`).

## Capabilities

### New Capabilities
(none)

### Modified Capabilities
- `lead-qualification-completeness-gate`: the platform-default completeness
  threshold used to advance a lead from Qualification to Recommendation
  moves from `80.0` (tuned for an 8-dimension profile) to `65.0` (tuned for
  the current 9-dimension profile), so the gate continues to open exactly
  when the six Nivel 1 dimensions are captured.

## Impact

- Code: `app/core/config.py` (1 constant + inline comment).
- Tests: `tests/test_buyer_profile.py`, `tests/test_qualification_flow.py`.
- Downstream: `ProfileCompleted`/Matching consumers are unaffected — they
  already tolerate partial profiles (Nivel 2 dimensions optional in the
  snapshot); only the *timing* of when the event fires relative to
  dimension count changes, not its shape.
- No DDL/migration, no new endpoints, no cross-module boundary changes,
  `organization_id` isolation unaffected (pure config constant).
