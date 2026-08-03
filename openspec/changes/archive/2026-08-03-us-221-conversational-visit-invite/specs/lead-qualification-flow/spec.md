## ADDED Requirements

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
