## ADDED Requirements

### Requirement: Nivel 1 dimensions precede Nivel 2 refinement dimensions
The system SHALL order `BuyerProfile`'s progressive-profiling dimensions so that all
Nivel 1 (qualification-blocking) dimensions — `budget`, `locations`, `property_type`,
`timeline`, `financing_type`, `decision_maker_mode` — are reported as missing, and thus
directed for the next question, before either Nivel 2 (refinement) dimension —
`must_haves`, `bedrooms`.

#### Scenario: Newly linked lead with no BuyerProfile captured
- **WHEN** a lead with an empty `BuyerProfile` sends a qualifying message
- **THEN** `BuyerProfile.missing_dimensions()` lists `budget`, `locations`,
  `property_type`, `timeline`, `financing_type`, and `decision_maker_mode` before
  `must_haves` and `bedrooms`

#### Scenario: Only a Nivel 1 and a Nivel 2 dimension remain missing
- **WHEN** a `BuyerProfile` has every dimension captured except one Nivel 1 dimension
  (e.g. `financing_type`) and one Nivel 2 dimension (e.g. `must_haves`)
- **THEN** `CompletenessGate.can_advance_to_recommendation().missing_dimension` returns
  the Nivel 1 dimension (`financing_type`), never the Nivel 2 one

#### Scenario: Nivel 2 refinement does not block reaching the completeness threshold
- **WHEN** a `BuyerProfile` has captured enough dimensions to cross
  `profile_completeness_threshold` (US-215's independently configured value), regardless
  of whether `must_haves`/`bedrooms` are among the captured ones
- **THEN** `CompletenessGate.can_advance_to_recommendation().can_advance` is `True`, and
  any still-missing Nivel 2 dimension is treated as post-recommendation refinement, not
  as a precondition
