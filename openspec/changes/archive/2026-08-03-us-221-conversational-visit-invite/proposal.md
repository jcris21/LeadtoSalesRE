## Why

Two language surfaces govern how the assistant talks about scheduling once a lead is in
`RECOMMENDATION`, and neither yet implements the conversational-suggestion framing US-221
(`Documents/Oficial/HU_Calificacion_Recomendacion.md:990-1011`) asks for. `DEFAULT_SYSTEM_PROMPT`
step 4 ("Derivación") still tells the LLM that a lead who wants to schedule a visit gets handed off
to a human advisor — which is now factually wrong, since US-212 (already merged into this branch)
wired `run_scheduling_turn` to book the visit automatically the moment the lead's free text carries
a recognizable date+time, with zero human in the loop. Separately, the Top-3 delivery message's
closing question (`GeminiRecommendationNarrator`'s system prompt and its deterministic
`_CLOSING_QUESTION` fallback) is open-ended but doesn't yet frame a visit as the explicit next step
tied to a specific property. US-221 was blocked on US-212 for exactly this reason ("no hay horarios
reales que redactar en lenguaje natural sin el wiring de scheduling") — that dependency is resolved.

## What Changes

- Rewrite `DEFAULT_SYSTEM_PROMPT` step 4 (`app/modules/conversation_ownership/domain/prompts.py`)
  so it no longer claims a human advisor takes over whenever the lead wants to schedule; instead it
  instructs the LLM to draft a conversational suggestion that connects a property the lead has
  engaged with to a visit invitation (pattern: "la opción de la zona X se ajusta a lo que buscas,
  ¿coordinamos una visita? cuéntame qué día y horario te queda bien"), and explicitly names rigid
  yes/no scheduling phrasing ("¿desea agendar? sí/no") as an anti-pattern to avoid. Human handoff
  language is preserved, narrowed to genuinely out-of-scope requests and explicit asks for a person.
- Reword `GeminiRecommendationNarrator._SYSTEM_PROMPT`'s closing-question rule
  (`app/modules/recommendation/infrastructure/llm_narrator.py`) so the Top-3 paragraph's close
  frames a visit as the natural next step tied to the specific recommended option, still never
  inventing times or availability — that stays `run_scheduling_turn`'s job downstream.
- Reword the deterministic `_CLOSING_QUESTION` fallback (`app/modules/recommendation/wiring.py`),
  used only when the LLM narrator is unavailable/keyless, in the same spirit within its plain-text
  constraint.
- Add/extend tests (`tests/test_prompts.py` and a narrator/composer content test) asserting the new
  framing is present and no legacy yes/no or unconditional-handoff phrasing remains, while every
  existing safety/tone assertion in `tests/test_prompts.py` still passes verbatim.
- **Explicitly out of scope**: no change to `run_scheduling_turn`, `AvailabilityValidatorService`,
  `SchedulingService`, or any DB schema/migration. No dependency on US-220's deepening turn (not
  merged into this branch) — the property reference used is whichever one is already available in
  conversation state (the just-delivered Top-3, or a property the lead named in the conversation
  history the LLM already has access to), not a new "elected option" field.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `lead-qualification-flow`: the Coordinator's fallback system prompt (`DEFAULT_SYSTEM_PROMPT`)
  changes its Recommendation/Derivación-stage scheduling-invitation language from a rigid yes/no +
  unconditional human-handoff framing to a conversational suggestion tied to the lead's engaged
  property, consistent with the already-wired US-212 automatic booking path. This is the closest
  existing capability spec to "how the Coordinator's default prompt governs conversation stages" —
  it already covers `DEFAULT_SYSTEM_PROMPT` behavior from US-216/217/218/219 in this same repo, so
  this change adds to it rather than inventing a new capability for one prompt section.

## Impact

- `app/modules/conversation_ownership/domain/prompts.py` — `DEFAULT_SYSTEM_PROMPT` step 4 rewrite.
- `app/modules/recommendation/infrastructure/llm_narrator.py` — `_SYSTEM_PROMPT` closing-question
  rule rewrite.
- `app/modules/recommendation/wiring.py` — `_CLOSING_QUESTION` constant rewrite.
- `tests/test_prompts.py` — new assertions; existing assertions must keep passing unmodified.
- A new or extended test module covering `llm_narrator`/`_format_recommendation_message` content.
- No API contract changes, no schema changes, no new LangGraph node or `AIDecisionTrace` requirement
  (prompt/copy content only — not a new decision point).
