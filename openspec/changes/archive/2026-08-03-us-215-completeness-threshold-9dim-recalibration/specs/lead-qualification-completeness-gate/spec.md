## MODIFIED Requirements

### Requirement: Completeness Gate threshold for Recommendation advance
The system SHALL expose a single platform-default completeness threshold,
`Settings.profile_completeness_threshold`, used by `CompletenessGate` and by
`BuyerProfileCaptureService` as the precondition for advancing a lead from
Qualification to Recommendation. This default SHALL be `65.0` percent,
recalibrated for the current 9-dimension `BuyerProfile` model (`budget`,
`locations`, `property_type`, `timeline`, `financing_type`,
`decision_maker_mode` as Nivel 1; `must_haves`, `bedrooms`, `motivation` as
Nivel 2 refinement), so the gate opens exactly once all six Nivel 1
dimensions are captured (6/9 ≈ 66.67%) and stays closed with only five of
six (5/9 ≈ 55.56%).

#### Scenario: Gate allows advance with all six Nivel 1 dimensions captured
- **WHEN** a `BuyerProfile` has `budget`, `locations`, `property_type`,
  `timeline`, `financing_type`, and `decision_maker_mode` captured, and no
  Nivel 2 dimension (`must_haves`, `bedrooms`, `motivation`) captured
- **THEN** `CompletenessGate().can_advance_to_recommendation(profile)`
  (default, config-sourced threshold) returns `can_advance=True` with
  `completeness == pytest.approx(600.0 / 9)`

#### Scenario: Gate still blocks with one Nivel 1 dimension missing
- **WHEN** a `BuyerProfile` has only five of the six Nivel 1 dimensions
  captured (any one missing, e.g. `decision_maker_mode`)
- **THEN** `CompletenessGate().can_advance_to_recommendation(profile)`
  (default, config-sourced threshold) returns `can_advance=False` with
  `completeness == pytest.approx(500.0 / 9)`

#### Scenario: ProfileCompleted fires exactly once, at the Nivel-1-complete crossing
- **WHEN** `BuyerProfileCaptureService.update_profile` is called
  progressively for the six Nivel 1 dimensions in order (`budget`,
  `locations`, `property_type`, `timeline`, `financing_type`,
  `decision_maker_mode`), using the platform-default threshold (no
  explicit override), followed by the three Nivel 2 dimensions
  (`bedrooms`, `motivation`, `must_haves`)
- **THEN** a `ProfileCompleted` event is published exactly once, with
  `completeness == pytest.approx(600.0 / 9)`, immediately after the
  `decision_maker_mode` update
- **AND** none of the subsequent Nivel 2 updates re-publish
  `ProfileCompleted`
