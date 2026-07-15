# lead-qualification-flow

## Purpose

Conversational + support-endpoint capture of the four progressive profiling dimensions (budget,
locations, property_type, timeline/must_haves) into `BuyerProfile`, closing the gap between the
existing `lead_qualification` domain/application layers and the conversation. Introduced by
`qualification-dimensions-us-202-205`.

## Requirements

### Requirement: Capture budget dimension
The system SHALL extract a budget range from a lead's message during `ConversationState.QUALIFICATION`
and apply it to the lead's `BuyerProfile` via `BuyerProfileCaptureService.update_profile`.

#### Scenario: Lead states an explicit budget range
- **WHEN** a lead in Discovery/QUALIFICATION sends a message containing a budget range or single amount
- **THEN** `BuyerProfile.budget` is updated with a `MoneyRange(minimum, maximum)` and `"budget"` appears
  in `BuyerProfile.captured_dimensions()`

#### Scenario: Invalid or contradictory budget is rejected before persisting
- **WHEN** the extracted amount is non-positive or `minimum > maximum`
- **THEN** `ProfileValidationError` is raised, no `ProfilePatch` is persisted, and the lead receives a
  conversational re-prompt (or a 422 response on the support endpoint) instead of an unhandled error

#### Scenario: Ambiguous message does not generate a patch
- **WHEN** a lead's message contains no recognizable budget signal
- **THEN** no `ProfilePatch(budget=...)` is constructed and `update_profile` is not called for this
  dimension

### Requirement: Capture locations dimension
The system SHALL extract one or more zones/districts from a lead's message and apply them to
`BuyerProfile.locations` via `update_profile`.

#### Scenario: Lead mentions one or more zones
- **WHEN** a lead in Discovery/QUALIFICATION provides one or more districts/zones in a message
- **THEN** `BuyerProfile.locations` is updated with the tuple of zones and `"locations"` appears in
  `captured_dimensions()`

#### Scenario: No zone recognized
- **WHEN** a lead's message contains no recognizable zone/district
- **THEN** no `ProfilePatch(locations=...)` is constructed (an empty-tuple patch is invalid per
  `ProfilePatch.__post_init__` and must never be attempted)

### Requirement: Capture property type dimension
The system SHALL classify a lead's message against the closed `PropertyType` enum
(`apartment | house | land | commercial | other`) and apply it to `BuyerProfile.property_type` via
`update_profile`.

#### Scenario: Lead indicates a recognized property type
- **WHEN** a lead in Discovery/QUALIFICATION mentions a property type matching `PropertyType`
  (including common Spanish synonyms, e.g. "depa" for "apartment")
- **THEN** `BuyerProfile.property_type` is updated and `"property_type"` appears in
  `captured_dimensions()`

#### Scenario: Message mentions two property types
- **WHEN** a lead's message mentions more than one property type without indicating a preference
- **THEN** the system does not silently pick one; it either captures the first mentioned type or
  re-prompts to disambiguate, but never persists a value the lead did not clearly express

### Requirement: Capture timeline and must-haves dimensions
The system SHALL extract a purchase timeline (closed `Timeline` enum) and/or a list of non-negotiable
requirements (free text) from a lead's message and apply them to `BuyerProfile.timeline` and/or
`BuyerProfile.must_haves` via `update_profile`.

#### Scenario: Lead expresses urgency
- **WHEN** a lead in Discovery/QUALIFICATION expresses a purchase horizon matching one of the 5
  `Timeline` values
- **THEN** `BuyerProfile.timeline` is updated and `"timeline"` appears in `captured_dimensions()`

#### Scenario: Lead states a non-negotiable requirement
- **WHEN** a lead's message expresses one or more must-have requirements
- **THEN** `BuyerProfile.must_haves` is updated with the tuple of requirements and `"must_haves"`
  appears in `captured_dimensions()`

#### Scenario: Both signals present in one message
- **WHEN** a lead's message expresses both urgency and a non-negotiable requirement in the same turn
- **THEN** a single `ProfilePatch` carries both `timeline` and `must_haves`, and applying it does not
  clear any previously captured value for either dimension (a `None` field on `ProfilePatch` never
  erases existing data — verified by `BuyerProfile.apply`)

#### Scenario: No signal for either dimension
- **WHEN** a lead's message expresses neither a timeline nor a must-have requirement
- **THEN** no `ProfilePatch` is constructed for this turn and `update_profile` (which rejects an empty
  patch via `ProfilePatch.is_empty()`) is not called

### Requirement: Tenant isolation on all dimension writes
The system SHALL verify that the target lead belongs to the caller's `organization_id` before applying
any dimension patch, for both the Qualification Flow extraction path and the support REST endpoints.

#### Scenario: Cross-tenant write attempt is rejected
- **WHEN** a request or extracted patch targets a `lead_id` that does not belong to the caller's
  `organization_id`
- **THEN** the write is rejected (404/`LeadNotFoundError` semantics) and no `BuyerProfile` data is
  mutated
