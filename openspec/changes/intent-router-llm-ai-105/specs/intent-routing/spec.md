## MODIFIED Requirements

### Requirement: Classify incoming message intent before turn routing
The system SHALL classify each incoming lead message into exactly one of a fixed category set
(`qualification`, `pregunta_informativa`, `objecion`, `agendamiento`, `handoff_explicito`,
`otro`) via `IntentRouterPort.classify`, invoked from `CoordinatorAgent.handle_message` after the
guardrail bypass check and before the identity gate. The classified category SHALL be returned to
`handle_message`'s caller-side logic, not only recorded on the trace.

#### Scenario: Message classified while turn processing continues unchanged
- **WHEN** an incoming message passes the guardrail bypass check (guardrail did not trigger)
- **THEN** `IntentRouterPort.classify` is called with the message text
- **AND** today's existing turn sequence (identity gate → qualification turn → conversational
  turn) still executes exactly as before, unaffected by the classification result for every
  category except `objecion` and `pregunta_informativa` (see the new Knowledge/RAG consumer
  requirement below)

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
  recorded for that turn, `_classify_intent` returns `None`, and message handling proceeds
  exactly as if no classification step existed

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

## ADDED Requirements

### Requirement: Objection and informational-question intents consume the Knowledge/RAG Service
The system SHALL call `KnowledgeService.answer(organization_id, text)` (or an injected
`KnowledgeAnswererPort` implementation) when the classified intent category for a turn is
`objecion` or `pregunta_informativa`, and SHALL use the returned grounded answer as that turn's
reply when found.

#### Scenario: Grounded knowledge answer replaces the default reply
- **GIVEN** a turn's classified intent category is `objecion` or `pregunta_informativa`
- **WHEN** `KnowledgeAnswererPort.answer` returns a `KnowledgeAnswer` with `found=True`
- **THEN** that answer's `answer_text` becomes the turn's reply instead of the default LLM
  responder's output
- **AND** a `knowledge.answer` tool call is recorded on the turn's `AIDecisionTrace`

#### Scenario: No grounded answer falls back to today's exact behavior
- **GIVEN** a turn's classified intent category is `objecion` or `pregunta_informativa`
- **WHEN** `KnowledgeAnswererPort.answer` returns `found=False`, or raises any exception
- **THEN** the turn's reply is exactly the default LLM responder's output, unchanged from
  pre-this-change behavior
- **AND** no `knowledge.answer` tool call is recorded for that turn

#### Scenario: Objection scoring remains independent of the knowledge branch
- **GIVEN** a message classified as `objecion`
- **WHEN** `run_qualification_turn` runs `extract_objection`/`record_objection` for that same
  message
- **THEN** the objection is scored and persisted (`lead_objections`,
  `Lead.lead_score`/`lead_classification`) exactly as before, regardless of whether the knowledge
  branch found a grounded answer

#### Scenario: Identity gate and qualification re-prompts still take precedence
- **GIVEN** a turn where `ask_identity` is true, or `QualificationTurnResult.reprompts` is
  non-empty
- **WHEN** the knowledge branch would otherwise have produced a grounded answer
- **THEN** the identity re-prompt (highest precedence) or the qualification re-prompt (next
  precedence) is used as the turn's reply instead of the knowledge answer

#### Scenario: Other categories never invoke the Knowledge/RAG Service
- **GIVEN** a turn's classified intent category is `qualification`, `agendamiento`,
  `handoff_explicito`, `otro`, or classification failed (`None`)
- **WHEN** `_conversational_turn` runs
- **THEN** `KnowledgeAnswererPort.answer` is never called for that turn
