## MODIFIED Requirements

### Requirement: Capture timeline dimension
The system SHALL extract a purchase timeline (closed `Timeline` enum) from a lead's
message and apply it to `BuyerProfile.timeline` via `update_profile`, independently of
must-haves extraction.

#### Scenario: Lead expresses urgency
- **WHEN** a lead in Discovery/QUALIFICATION expresses a purchase horizon matching one of
  the 5 `Timeline` values
- **THEN** `BuyerProfile.timeline` is updated and `"timeline"` appears in
  `captured_dimensions()`

#### Scenario: No timeline signal
- **WHEN** a lead's message expresses no purchase horizon
- **THEN** no `ProfilePatch(timeline=...)` is constructed and `update_profile` is not
  called for this dimension

### Requirement: Capture must-haves dimension
The system SHALL extract a list of non-negotiable requirements (free text) from a lead's
message and apply them to `BuyerProfile.must_haves` via `update_profile`, independently of
timeline extraction. `must_haves` is a Nivel 1 (blocking) dimension: it participates in
`CompletenessGate`'s directed-question ordering ahead of `timeline`.

#### Scenario: Lead states a non-negotiable requirement
- **WHEN** a lead's message expresses one or more must-have requirements
- **THEN** `BuyerProfile.must_haves` is updated with the tuple of requirements and
  `"must_haves"` appears in `captured_dimensions()`

#### Scenario: No must-haves signal
- **WHEN** a lead's message expresses no non-negotiable requirement
- **THEN** no `ProfilePatch(must_haves=...)` is constructed and `update_profile` is not
  called for this dimension

#### Scenario: Both signals present in one message
- **WHEN** a lead's message expresses both urgency and a non-negotiable requirement in the
  same turn
- **THEN** `extract_timeline` and `extract_must_haves` each independently produce their own
  `ProfilePatch`, and applying both in sequence does not clear any previously captured
  value for either dimension (a `None` field on `ProfilePatch` never erases existing data —
  verified by `BuyerProfile.apply`), producing an identical end state to the previous
  single combined-patch behavior

### Requirement: Nivel 1 dimensions precede Nivel 2 in directed questions
`PROFILE_DIMENSIONS` SHALL order the six search-pipeline-relevant dimensions (`budget`,
`locations`, `property_type`, `bedrooms`, `motivation`, `must_haves` — the dimensions
`StructuredFilterService` and `SemanticRetrievalService` consume) ahead of the three
sales-follow-up dimensions (`timeline`, `financing_type`, `decision_maker_mode`), so
`BuyerProfile.missing_dimensions()[0]` (the directed question `CompletenessGate` returns)
always exhausts the search-relevant set first, and `CompletenessGate.can_advance_to_recommendation`
reaches its threshold based on those six dimensions alone.

#### Scenario: Nivel 1 dimension missing takes precedence
- **WHEN** a `BuyerProfile` is missing both `must_haves` (Nivel 1) and `financing_type`
  (Nivel 2)
- **THEN** `CompletenessGate.can_advance_to_recommendation(profile).missing_dimension`
  returns `"must_haves"`, not `"financing_type"`

#### Scenario: Recommendation unlocks on Nivel 1 completion alone
- **WHEN** a `BuyerProfile` has `budget`, `locations`, `property_type`, `bedrooms`,
  `motivation`, and `must_haves` captured, and `timeline`/`financing_type`/
  `decision_maker_mode` are all still `None`
- **THEN** `completeness()` meets the configured threshold and
  `CompletenessGate.can_advance_to_recommendation(profile).can_advance` is `True`
