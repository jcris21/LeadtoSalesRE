## Purpose

Deterministic post-selection turn that asks the lead for the still-missing Nivel 2
qualification dimensions (`timeline`, `financing_type`, `decision_maker_mode`) once the
lead has confirmed interest in a specific recommended property, without blocking
scheduling or the recommendation itself. Introduced by `us-222-reclassify-qualification-levels`.

## ADDED Requirements

### Requirement: Follow-up question fires only after property selection
The system SHALL only ask a Nivel 2 follow-up question once the lead has a persisted
property selection for the latest recommendation batch (the same `RecommendationORM.feedback`
marker `deepening_turn.mark_selected`/`is_lead_selected` already read/write), never before.

#### Scenario: No selection yet
- **WHEN** a conversation is in `ConversationState.RECOMMENDATION` and no property has been
  selected for the latest recommendation batch
- **THEN** the follow-up turn returns `not_applicable` and asks nothing

#### Scenario: Selection made this turn or a previous turn
- **WHEN** the latest recommendation batch has a lead-selected property (regardless of
  which turn produced the selection)
- **AND** `BuyerProfile.missing_dimensions()` still contains at least one of `timeline`,
  `financing_type`, `decision_maker_mode`
- **THEN** the follow-up turn returns a directed question for the first missing one of
  those three, in that order

### Requirement: Follow-up question never blocks scheduling or recommendation
The follow-up turn SHALL be purely additive: a lead who provides a scheduling slot instead
of answering the follow-up question SHALL still have that slot processed by the existing
scheduling turn, and the recommendation itself SHALL NOT depend on Nivel 2 completeness.

#### Scenario: Lead answers with a slot instead of the follow-up question
- **WHEN** the follow-up turn would ask a Nivel 2 question this turn, but the lead's
  message already contains a schedulable slot
- **THEN** the scheduling turn still resolves and books the slot; the follow-up question
  is not asked this turn

#### Scenario: All Nivel 2 dimensions already captured
- **WHEN** `timeline`, `financing_type`, and `decision_maker_mode` are all already captured
  on `BuyerProfile` (whether from passive extraction or a previous follow-up answer)
- **THEN** the follow-up turn returns `not_applicable` and never re-asks

### Requirement: Follow-up turn is deterministic, never LLM-generated
The follow-up question text SHALL be deterministic (no LLM call), following the same
`Literal` outcome / `ResponderPort` short-circuit contract as `deepening_turn.py` and
`scheduling_turn.py`.

#### Scenario: Deterministic text
- **WHEN** the follow-up turn returns an `"asked"` outcome
- **THEN** its `response` is one of a fixed set of directed-question strings, never routed
  through `ResponderPort`/the LLM responder

### Requirement: Top-3 disambiguation question takes precedence
When both the deepening turn (US-220, disambiguating which Top-3 property the lead means)
and the follow-up turn would have something to ask in the same turn, the deepening turn's
question SHALL be sent and the follow-up turn SHALL NOT run that turn.

#### Scenario: Both turns have a question pending
- **WHEN** `deepening_turn` returns `outcome == "asked"` this turn
- **THEN** the follow-up turn is not invoked this turn
