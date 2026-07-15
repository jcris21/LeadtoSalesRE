## Purpose

Conversation memory captures structured, confidence-scored observations extracted from a lead's free-text conversational messages (e.g. style preferences, family context) via deterministic Spanish keyword/pattern matching. It is a signal store independent from `BuyerProfile` and `PROFILE_DIMENSIONS`, and never gates qualification or completeness.

## Requirements

### Requirement: Free-text conversational signal extraction
The system SHALL extract structured, confidence-scored observations (style preferences and family context, in this first cut) from a lead's free-text conversational message via deterministic Spanish keyword/pattern matching, and SHALL persist each observation as a new row in `conversation_memory` without modifying `BuyerProfile` or any `PROFILE_DIMENSIONS` field.

#### Scenario: Lead mentions an unstructured style preference
- **WHEN** a lead writes a message containing a style/aesthetic cue (e.g. "algo minimalista y luminoso")
- **THEN** a row is inserted into `conversation_memory` with `memory_type=style_preference`, an `entity_name`, a `value` jsonb payload, and a `confidence`
- **AND** the row does not overwrite or modify any `PROFILE_DIMENSIONS` value on the lead's `BuyerProfile`

#### Scenario: Lead mentions family context
- **WHEN** a lead writes a message containing a family-composition cue (e.g. "tenemos dos hijos pequeños")
- **THEN** a row is inserted into `conversation_memory` with `memory_type=family_context`

#### Scenario: Message carries both a style and a family cue
- **WHEN** a single message contains both a style cue and a family-context cue
- **THEN** two separate `conversation_memory` rows are inserted, one per detected signal

#### Scenario: No recognizable signal
- **WHEN** a lead's message contains no recognizable style or family-context keyword
- **THEN** no `conversation_memory` row is inserted

### Requirement: Conversation memory does not gate qualification
The system SHALL NOT use `conversation_memory` rows as an input to `BuyerProfile.completeness()` or the QA-14 completeness gate; `conversation_memory` and `PROFILE_DIMENSIONS` are independent, non-overlapping signal stores.

#### Scenario: Recording an observation does not change profile completeness
- **GIVEN** a `BuyerProfile` at a known completeness percentage
- **WHEN** a `conversation_memory` observation is recorded for the same lead
- **THEN** `BuyerProfile.completeness()` for that lead is unchanged
