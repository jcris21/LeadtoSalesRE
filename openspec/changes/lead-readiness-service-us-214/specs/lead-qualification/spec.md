## ADDED Requirements

### Requirement: Continuous weighted readiness score
The system SHALL compute a continuous readiness score in the range [0, 100] from a `BuyerProfile`,
via `LeadReadinessService.evaluate`, as an additive weighted sum over six signals: `property_type`
captured (15 pts), `budget` captured (20 pts), `locations` captured (15 pts), `timeline` captured
(urgency-scaled: `immediate`=20, `3_months`=15, `6_months`=10, `over_6_months`=5, `exploring`=2),
`financing_type` captured (readiness-scaled: `cash`=20, `mortgage_approved`=20,
`mortgage_preapproved`=15, `evaluating`=8), and `decision_maker_mode` captured (10 pts). This score
SHALL be independent of and SHALL NOT modify `Lead.lead_score`/`lead_classification` (US-209).

#### Scenario: Empty profile scores zero
- **GIVEN** a `BuyerProfile` with no dimensions captured
- **WHEN** `compute_readiness_score` is called
- **THEN** it returns `0.0`

#### Scenario: Fully captured profile at maximum tiers scores 100
- **GIVEN** a `BuyerProfile` with `property_type`, `budget`, `locations`, `timeline=immediate`,
  `financing_type=cash`, and `decision_maker_mode` all captured
- **WHEN** `compute_readiness_score` is called
- **THEN** it returns `100.0`

#### Scenario: Partial profile with strong urgency signals
- **GIVEN** a `BuyerProfile` with `financing_type`, `timeline`, and `locations` captured, but not all
  8 `PROFILE_DIMENSIONS`
- **WHEN** `LeadReadinessService.evaluate` runs
- **THEN** it returns a continuous score reflecting the captured signals' weights, not just a
  Hot/Warm/Cold bucket

### Requirement: Three-state financing readiness classification
The system SHALL classify a `BuyerProfile` into one of `READY`, `PRE_READY`, or `DISCOVERY`
(`FinancingReadiness` enum) via `classify_financing_readiness`, using the rule: `READY` when
`financing_type` is `cash` or `mortgage_approved`, `timeline` is `immediate` or `3_months`, and
`locations` is captured; `PRE_READY` when `financing_type` is captured (any value) and at least one of
`timeline`/`locations` is also captured; `DISCOVERY` otherwise.

#### Scenario: Strong signals classify as READY
- **GIVEN** a `BuyerProfile` with `financing_type=cash`, `timeline=immediate`, and `locations`
  captured
- **WHEN** `classify_financing_readiness` is called
- **THEN** it returns `FinancingReadiness.READY`

#### Scenario: Partial financing signal classifies as PRE_READY
- **GIVEN** a `BuyerProfile` with `financing_type=evaluating` and `locations` captured, but no
  `timeline`
- **WHEN** `classify_financing_readiness` is called
- **THEN** it returns `FinancingReadiness.PRE_READY`

#### Scenario: No financing signal classifies as DISCOVERY
- **GIVEN** a `BuyerProfile` with no `financing_type` captured
- **WHEN** `classify_financing_readiness` is called
- **THEN** it returns `FinancingReadiness.DISCOVERY`

### Requirement: Readiness output persisted on buyer_profiles
`LeadReadinessService.evaluate` SHALL persist `readiness_score` and `financing_readiness` onto the
`buyer_profiles` row matching the profile's `lead_id`, via an isolated writer
(`BuyerProfileRepository.set_readiness`) that touches only those two columns and never participates in
`BuyerProfileRepository.save`'s progressive-profiling write path.

#### Scenario: Evaluate persists both fields
- **GIVEN** a `buyer_profiles` row exists for `lead_id`
- **WHEN** `LeadReadinessService.evaluate(profile)` is called
- **THEN** the row's `readiness_score` and `financing_readiness` columns are updated to match the
  computed result
- **AND** no other column on that row is modified

#### Scenario: No profile row yet degrades gracefully
- **GIVEN** no `buyer_profiles` row exists for `lead_id`
- **WHEN** `BuyerProfileRepository.set_readiness` is called
- **THEN** it returns `False` and raises no exception
