## MODIFIED Requirements

### Requirement: Completeness Gate threshold for Recommendation advance
The system SHALL expose a single platform-default completeness threshold,
`Settings.profile_completeness_threshold`, used by `CompletenessGate` and by
`BuyerProfileCaptureService` as the precondition for advancing a lead from
Qualification to Recommendation. This default SHALL be `80.0` percent,
corresponding to 4 of the 5 `BuyerProfile` dimensions (`budget`, `locations`,
`property_type`, `timeline`) being captured, with `must_haves` treated as a
post-Matching refinement dimension.

#### Scenario: Gate allows advance with the 4 primary dimensions captured
- **WHEN** a `BuyerProfile` has `budget`, `locations`, `property_type`, and
  `timeline` captured, and `must_haves` NOT captured
- **THEN** `CompletenessGate().can_advance_to_recommendation(profile)`
  returns `can_advance=True` and `completeness == 80.0`

#### Scenario: ProfileCompleted fires exactly once, at the 4-dimension crossing
- **WHEN** `BuyerProfileCaptureService.update_profile` is called
  progressively for `budget`, `locations`, `property_type`, then `timeline`
  (using the platform-default threshold, no explicit override)
- **THEN** a `ProfileCompleted` event is published exactly once, with
  `completeness == 80.0`, after the `timeline` update
- **AND** a subsequent `must_haves` update does NOT re-publish
  `ProfileCompleted`

#### Scenario: Gate still blocks profiles below 4 primary dimensions
- **WHEN** a `BuyerProfile` has only `budget` and `locations` captured
- **THEN** `CompletenessGate().can_advance_to_recommendation(profile)`
  returns `can_advance=False` with `completeness == 40.0` and the first
  missing dimension named
