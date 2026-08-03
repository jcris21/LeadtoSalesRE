## ADDED Requirements

### Requirement: Capture motivation dimension
The system SHALL extract a purchase motivation from a lead's message during
`ConversationState.QUALIFICATION`, classified against the closed `Motivation` enum
(`relocation | investment | vacation | first_home`), and apply it to `BuyerProfile.motivation` via
`BuyerProfileCaptureService.update_profile`.

#### Scenario: Lead expresses a recognized motivation
- **WHEN** a lead in Discovery/QUALIFICATION mentions a motivation matching `Motivation` (e.g.
  "me voy a mudar" for relocation, "para invertir" for investment, "casa de playa" for vacation,
  "es mi primera vivienda" for first_home)
- **THEN** `BuyerProfile.motivation` is updated and `"motivation"` appears in
  `BuyerProfile.captured_dimensions()`

#### Scenario: No motivation signal in message
- **WHEN** a lead's message contains no recognizable motivation signal
- **THEN** no `ProfilePatch(motivation=...)` is constructed and `update_profile` is not called for
  this dimension

### Requirement: Adaptive Nivel 2 questions by property type
The system SHALL exclude profile dimensions that do not apply to the lead's captured
`BuyerProfile.property_type` from `missing_dimensions()` and from the `completeness()` denominator,
so the Coordinator never asks a directed Nivel 2 question for an inapplicable dimension.

#### Scenario: Property type is LAND or COMMERCIAL
- **WHEN** `BuyerProfile.property_type` is `LAND` or `COMMERCIAL`
- **THEN** `"bedrooms"` is excluded from `missing_dimensions()` and from the denominator used by
  `completeness()`, even if `bedrooms` was never captured

#### Scenario: Property type is APARTMENT or HOUSE
- **WHEN** `BuyerProfile.property_type` is `APARTMENT` or `HOUSE`
- **THEN** no dimension is excluded; `missing_dimensions()`/`completeness()` behave exactly as before
  this change

#### Scenario: Property type not yet captured
- **WHEN** `BuyerProfile.property_type` is `None`
- **THEN** no dimension is excluded (filtering only applies once the property type is known)
