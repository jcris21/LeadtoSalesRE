# intent-routing

## Purpose

Classification of incoming lead messages into a fixed intent category set
(`qualification`, `pregunta_informativa`, `objecion`, `agendamiento`,
`handoff_explicito`, `otro`) via `IntentRouterPort`, invoked from
`CoordinatorAgent.handle_message` ahead of the existing turn-routing sequence.
Introduced by `intent-router-ai-104`.

## Requirements

### Requirement: Classify incoming message intent before turn routing
The system SHALL classify each incoming lead message into exactly one of a fixed category set
(`qualification`, `pregunta_informativa`, `objecion`, `agendamiento`, `handoff_explicito`,
`otro`) via `IntentRouterPort.classify`, invoked from `CoordinatorAgent.handle_message` after the
guardrail bypass check and before the identity gate.

#### Scenario: Message classified while turn processing continues unchanged
- **WHEN** an incoming message passes the guardrail bypass check (guardrail did not trigger)
- **THEN** `IntentRouterPort.classify` is called with the message text
- **AND** today's existing turn sequence (identity gate → qualification turn → conversational
  turn) still executes exactly as before, unaffected by the classification result

#### Scenario: Classification recorded on the turn's AIDecisionTrace
- **WHEN** `IntentRouterPort.classify` returns a category for a turn already inside a
  `trace_decision` block
- **THEN** the recorder captures a tool call named `intent_router.classify` with the input text
  and the resulting category, appended to `AIDecisionTraceORM.tool_calls` for that turn
- **AND** no new database table or column is created; the existing jsonb `tool_calls` field is
  reused

#### Scenario: Classifier failure never breaks the turn
- **WHEN** `IntentRouterPort.classify` raises any exception
- **THEN** the exception is caught within `CoordinatorAgent`, no classification tool call is
  recorded for that turn, and message handling proceeds exactly as if no classification step
  existed

### Requirement: Deterministic fallback classifier for offline/test use
The system SHALL provide a deterministic keyword-based `IntentRouterPort` implementation used
when no LLM credential is configured, so that `CoordinatorAgent` tests and any environment
without LLM credentials keep working without a live model call.

#### Scenario: No LLM credential configured
- **WHEN** the environment has no intent-classification LLM credential configured
- **THEN** the default `IntentRouterPort` implementation resolves to the deterministic
  keyword-based classifier
- **AND** classification still returns one of the fixed category set, never an error, for any
  input text

#### Scenario: Test suite exercises the router without network access
- **WHEN** a unit test constructs `CoordinatorAgent` without an explicit `intent_router` argument
- **THEN** the deterministic fallback classifier is used
- **AND** the test can assert a specific category for a given input message deterministically
