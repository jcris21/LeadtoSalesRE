## ADDED Requirements

### Requirement: Conversational checkpoint survives process restart
The system SHALL persist the LangGraph conversational checkpoint (`TurnState`) to a durable store keyed by `thread_id = conversation_id`, such that a new `LangGraphResponder` instance constructed after a process restart resumes the same conversational context instead of starting cold.

#### Scenario: New responder instance rehydrates prior turns
- **GIVEN** a conversation has completed one or more turns against a durable checkpointer
- **WHEN** a new `LangGraphResponder` instance is constructed (simulating a process restart) and queried with the same `conversation_id`
- **THEN** `history()` returns the previously recorded conversational context
- **AND** the next turn's brain call receives that prior context instead of an empty history

#### Scenario: Checkpointer initialization fails at boot
- **GIVEN** the durable checkpointer backend is unreachable or misconfigured at startup
- **WHEN** the application initializes the persistent responder
- **THEN** the application SHALL log the failure and fall back to an in-memory checkpointer
- **AND** application boot SHALL NOT fail as a result

### Requirement: Active checkpoint history is bounded by a window
The system SHALL bound `TurnState.messages` to the most recent `conversation_history_window_turns` turns, so the checkpoint payload does not grow without limit across a long conversation.

#### Scenario: Turn count exceeds the configured window
- **GIVEN** a conversation has produced more turns than `conversation_history_window_turns`
- **WHEN** a new turn completes
- **THEN** `TurnState.messages` SHALL contain at most `conversation_history_window_turns` turns (the most recent ones)
- **AND** the turns evicted from `messages` SHALL NOT be silently discarded

#### Scenario: Turn count is within the configured window
- **GIVEN** a conversation has produced fewer turns than `conversation_history_window_turns`
- **WHEN** a new turn completes
- **THEN** `TurnState.messages` SHALL contain the full turn history unmodified

### Requirement: Evicted turns are folded into a persisted, bounded summary
The system SHALL deterministically fold turns evicted from the window into a `summary` field, without invoking an LLM, and SHALL cap the summary's length so it does not grow without bound across an arbitrarily long conversation. The summary SHALL be persisted in the same checkpoint as `messages`, so it survives a process restart under the same guarantee as the windowed history.

#### Scenario: A turn is evicted from the window
- **WHEN** a turn falls outside `conversation_history_window_turns` due to a new turn completing
- **THEN** that turn's content SHALL be folded into `TurnState.summary` via a deterministic function
- **AND** no LLM call SHALL be made to produce the summary

#### Scenario: Summary length is capped
- **GIVEN** many turns have been evicted over a long conversation
- **WHEN** the summary is folded again
- **THEN** the resulting `summary` SHALL NOT exceed a fixed maximum length

#### Scenario: Summary reaches the conversational brain without changing its contract
- **WHEN** a turn is generated and a non-empty `summary` exists
- **THEN** the summary SHALL be made available to `ConversationBrain.generate()` as part of the `history` argument (e.g. a prepended system-role entry)
- **AND** the `ConversationBrain` protocol signature SHALL remain unchanged

### Requirement: Accumulated summary is exposed via history()
The system SHALL surface the accumulated `summary`, alongside the windowed `messages`, through `LangGraphResponder.history()`.

#### Scenario: History is requested for a conversation with an evicted-turns summary
- **WHEN** `history(conversation_id)` is called for a conversation whose checkpoint has a non-empty `summary`
- **THEN** the returned result SHALL include the summary in addition to the windowed messages
