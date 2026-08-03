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

### Requirement: Tenant isolation on all dimension writes
The system SHALL verify that the target lead belongs to the caller's `organization_id` before applying
any dimension patch, for both the Qualification Flow extraction path and the support REST endpoints.

#### Scenario: Cross-tenant write attempt is rejected
- **WHEN** a request or extracted patch targets a `lead_id` that does not belong to the caller's
  `organization_id`
- **THEN** the write is rejected (404/`LeadNotFoundError` semantics) and no `BuyerProfile` data is
  mutated

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

### Requirement: Adaptive dimension exclusion by property type
The system SHALL exclude profile dimensions that do not apply to the lead's captured
`BuyerProfile.property_type` from `missing_dimensions()` and from the `completeness()` denominator,
so the Coordinator never asks a directed question for an inapplicable dimension. This applies
regardless of whether the excluded dimension is Nivel 1 or Nivel 2 — `bedrooms` is a Nivel 1
(search-pipeline) dimension (see "Nivel 1 dimensions precede Nivel 2 in directed questions"),
and land/commercial purchases have no bedroom count to ask about.

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

### Requirement: Conversational visit-scheduling invitation

While `conversation.state` is `RECOMMENDATION`, the Coordinator's fallback system prompt
(`DEFAULT_SYSTEM_PROMPT`) SHALL instruct the assistant to invite the lead to a visit as a
conversational suggestion tied to a property the lead has engaged with (the just-delivered Top-3 or
a property named earlier in the conversation), rather than as a rigid yes/no question, and SHALL NOT
instruct the assistant to claim a human advisor takes over merely because the lead expresses
scheduling intent — the automatic booking path (`run_scheduling_turn`, US-212) already handles that
without human intervention whenever the lead's message carries a confirmed date+time. Human handoff
guidance SHALL remain for requests genuinely outside the assistant's scope or an explicit request to
speak with a person.

#### Scenario: Lead shows interest in a recommended option
- **WHEN** the assistant is in the Recommendation stage and the lead has engaged with a specific
  property (named it, asked about it, or it is the property just delivered in the Top-3)
- **THEN** the assistant's invitation to visit connects that property to the suggestion of
  coordinating a visit and asks for a preferred day/time, instead of asking a bare "¿deseas
  agendar? sí/no"

#### Scenario: Lead asks to speak with a person
- **WHEN** the lead explicitly asks to speak with a human advisor, or raises something outside the
  assistant's scope
- **THEN** the assistant still tells the lead a human advisor will continue the conversation

### Requirement: Recommendation delivery closes with a visit-oriented invitation

The Top-3 delivery message (produced by `GeminiRecommendationNarrator.narrate` when available, or
the deterministic fallback closing question otherwise) SHALL end by framing a visit as the natural
next step tied to the recommended option(s), without inventing any time, date, or availability
information — slot proposal and validation remain the responsibility of the scheduling turn
(`run_scheduling_turn` / `AvailabilityValidatorService`) downstream, never the narrator or the
deterministic fallback.

#### Scenario: LLM narrator available
- **WHEN** `GeminiRecommendationNarrator.narrate` produces the Top-3 explanation paragraph
- **THEN** the paragraph closes by connecting the recommended option(s) to a visit invitation,
  without stating or implying any specific date, time, or confirmed availability

#### Scenario: LLM narrator unavailable or keyless deployment
- **WHEN** `build_recommendation_narrator` returns `None` (no API key) or `narrate` fails
- **THEN** `_format_recommendation_message` falls back to the deterministic closing question, which
  also frames a visit as the natural next step, keeping the Top-3 message complete without any LLM
  call
