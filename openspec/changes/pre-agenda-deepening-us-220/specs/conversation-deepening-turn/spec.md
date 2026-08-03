## ADDED Requirements

### Requirement: Deepening turn only runs in Recommendation state with a real choice to make
`CoordinatorAgent._conversational_turn` SHALL invoke the deepening turn only when
`conversation.state is ConversationState.RECOMMENDATION`, the conversation has a linked `lead_id`, and
the lead's latest recommendation batch (`RecommendationRepository.list_for_lead`, most recent
`generated_at`) contains 2 or more ranked properties. In any other case the deepening turn SHALL be a
no-op (`outcome="not_applicable"`) and the turn proceeds exactly as if this capability did not exist.

#### Scenario: Single-property recommendation has nothing to deepen on
- **WHEN** the latest recommendation batch for the lead contains exactly one ranked property
- **THEN** the deepening turn returns `not_applicable` and the normal `ResponderPort` reply is used,
  unchanged

#### Scenario: Qualification-state turn is unaffected
- **WHEN** a message arrives while `conversation.state is ConversationState.QUALIFICATION`
- **THEN** the deepening turn is never invoked

### Requirement: The deepening question is asked until an option is selected
While the gate above is satisfied and no property in the latest batch has been recorded as the lead's
selection yet, if the lead's message does not identify one of the ranked options AND does not itself
contain a recognizable scheduling slot, the deepening turn SHALL short-circuit this turn's reply with
a deterministic question asking which option interested the lead, without invoking `ResponderPort`.

#### Scenario: First reply after the Top-3 does not name an option
- **GIVEN** a lead in `RECOMMENDATION` state with a 3-item recommendation batch and no prior selection
- **WHEN** the lead replies "me gustaron todas, no sé cuál elegir"
- **THEN** the turn's reply is the deterministic deepening question and `ResponderPort` is not called

#### Scenario: A message carrying an explicit slot bypasses the question
- **GIVEN** a lead in `RECOMMENDATION` state with a 3-item recommendation batch and no prior selection
- **WHEN** the lead replies "el sábado a las 3pm" (a recognizable slot, no option reference)
- **THEN** the deepening turn returns `not_applicable`, and the existing scheduling turn (US-212)
  proceeds using its own resolution rule

### Requirement: Deterministic option recognition, never a guess
`extract_selected_rank(text)` SHALL recognize an ordinal word ("primera"/"primero",
"segunda"/"segundo", "tercera"/"tercero", accent-insensitive), the phrase "opción N" or "número N", or
a bare digit `1`-`3`, and SHALL return `None` when no such reference is present. It SHALL NOT infer a
selection from property descriptions, zones, or prices.

#### Scenario: Ordinal word recognized
- **WHEN** the lead's message is "me quedo con la segunda"
- **THEN** `extract_selected_rank` returns `2`

#### Scenario: Explicit option phrase recognized
- **WHEN** the lead's message is "la opción 3 me encantó"
- **THEN** `extract_selected_rank` returns `3`

#### Scenario: No option reference
- **WHEN** the lead's message is "¿tiene cochera?"
- **THEN** `extract_selected_rank` returns `None`

### Requirement: A recognized selection is recorded and the turn continues normally
When the lead's message identifies a rank present in the latest recommendation batch, the deepening
turn SHALL record that property as the lead's selection (via
`RecommendationRepository.mark_selected`) and SHALL NOT override this turn's reply — the turn
continues exactly as if the deepening turn had not run (falls through to the existing scheduling turn,
then `ResponderPort`, as applicable).

#### Scenario: Selection recorded on a recognized rank
- **GIVEN** a lead in `RECOMMENDATION` state with a 3-item recommendation batch and no prior selection
- **WHEN** the lead replies "la opción 2 se ve bien"
- **THEN** the rank-2 property's `feedback` is set to indicate the lead's selection, and the turn's
  reply is produced normally (not overridden by the deepening turn)

#### Scenario: Out-of-range rank falls back to asking again
- **GIVEN** a lead in `RECOMMENDATION` state with a 2-item recommendation batch and no prior selection
- **WHEN** the lead replies "me quedo con la opción 4"
- **THEN** no selection is recorded, and the turn's reply is the deterministic deepening question

### Requirement: A recorded selection is used as the scheduling reference
Once a property in the lead's latest recommendation batch is recorded as selected, the existing
scheduling turn (US-212, `run_scheduling_turn` -> `_latest_top_pick`) SHALL resolve that property as
the recommendation reference for `SchedulingService.book_visit`, taking priority over the batch's
original rank-1 property.

#### Scenario: Booking targets the lead's selected property, not rank-1
- **GIVEN** a lead in `RECOMMENDATION` state whose latest batch has the rank-2 property recorded as
  selected (rank-1 remains unselected)
- **WHEN** the lead later confirms a slot (e.g. "el sábado a las 3pm")
- **THEN** `SchedulingService.book_visit` is called with the rank-2 property, not the rank-1 property

#### Scenario: No selection recorded falls back to rank-1, unchanged from US-212
- **GIVEN** a lead in `RECOMMENDATION` state whose latest batch has no property recorded as selected
- **WHEN** the lead confirms a slot
- **THEN** `SchedulingService.book_visit` is called with the rank-1 property, exactly as before this
  change
