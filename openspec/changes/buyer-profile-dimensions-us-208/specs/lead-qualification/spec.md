## ADDED Requirements

### Requirement: BuyerProfile captures financing type
The system SHALL capture the lead's declared financing type (`cash`, `mortgage_approved`, `mortgage_preapproved`, or `evaluating`) as part of `BuyerProfile`, using the same progressive-profiling mechanism as the existing budget/location/property_type/timeline/must_haves dimensions. `financing_type` SHALL count toward `PROFILE_DIMENSIONS` and therefore toward the completeness gate (QA-14).

#### Scenario: Lead declares payment method
- **WHEN** the lead's message indicates "contado", "crédito hipotecario", "crédito preaprobado", or "evaluando" financing
- **THEN** `BuyerProfile.financing_type` is set to the matching `FinancingType` value
- **AND** `"financing_type"` appears in `BuyerProfile.captured_dimensions()`

#### Scenario: Message carries no financing signal
- **WHEN** the lead's message contains no recognizable financing keyword
- **THEN** no `ProfilePatch` is persisted for `financing_type`
- **AND** no exception is raised to the caller

### Requirement: BuyerProfile captures decision-maker mode
The system SHALL capture whether the lead is deciding the purchase alone, as a couple, or with family (`solo`, `couple`, `family`) as part of `BuyerProfile`, following the same nullable, additive-patch semantics as the other dimensions. `decision_maker_mode` SHALL count toward `PROFILE_DIMENSIONS`.

#### Scenario: Lead declares decision-making context
- **WHEN** the lead's message indicates they are deciding alone, with a partner, or with family
- **THEN** `BuyerProfile.decision_maker_mode` is set to the matching `DecisionMakerMode` value
- **AND** `"decision_maker_mode"` appears in `BuyerProfile.captured_dimensions()`

### Requirement: Profile completeness reflects seven dimensions
`BuyerProfile.completeness()` SHALL compute its percentage against `PROFILE_DIMENSIONS` containing all 7 elements (`budget, locations, property_type, timeline, must_haves, financing_type, decision_maker_mode`), so that the QA-14 gate and `ProfileCompleted` event require all 7 dimensions to reach the configured threshold.

#### Scenario: Existing 5-dimension profile is re-evaluated
- **WHEN** a `BuyerProfile` created before this change (only budget/locations/property_type/timeline/must_haves captured) has its `completeness()` recomputed
- **THEN** the returned percentage is based on a denominator of 7, not 5
- **AND** the profile is not treated as `Complete` unless `financing_type` and `decision_maker_mode` are also captured (or the configured threshold is still met with fewer than 7 dimensions)

### Requirement: ProfileCompleted event includes new dimensions
The `ProfileCompleted` event payload produced by `BuyerProfileCaptureService.update_profile` SHALL include `financing_type` and `decision_maker_mode` in its profile snapshot.

#### Scenario: Profile crosses completeness threshold
- **WHEN** `update_profile` causes completeness to cross the configured threshold
- **THEN** the emitted `ProfileCompleted.profile` dict includes keys `financing_type` and `decision_maker_mode` (nullable) alongside the existing 5 keys
