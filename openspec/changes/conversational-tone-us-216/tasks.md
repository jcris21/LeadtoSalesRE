## 1. Prompt rewrite

- [x] 1.1 Rewrite `DEFAULT_SYSTEM_PROMPT` in
      `app/modules/conversation_ownership/domain/prompts.py` to add: (a) a non-form,
      natural-conversation instruction, (b) an explicit "summarize every 2 consecutive qualification
      answers before the next question" cadence instruction, (c) warm-professional tone with
      moderate/bounded emoji guidance.
- [x] 1.2 Preserve every existing strict rule verbatim in substance: no invented
      properties/prices/addresses/links, no promised availability/appointments, no sensitive-data
      requests, prompt-injection guard on the lead's message.
- [x] 1.3 Keep the prompt covering all four stages (greeting/qualification/recommendation/handoff)
      in one freeform string — content rewrite only, no restructuring into multiple prompts.

## 2. Tests

- [x] 2.1 Create `tests/test_prompts.py` with assertions that `DEFAULT_SYSTEM_PROMPT` contains:
      non-form/natural-conversation guidance, the 2-consecutive-answers summary cadence instruction,
      warm-professional tone guidance, moderate-emoji guidance.
- [x] 2.2 Add regression assertions that the existing anti-hallucination and prompt-injection guard
      rules are still present after the rewrite.
- [x] 2.3 Run the full `uv run pytest` suite (or the relevant subset:
      `tests/test_prompts.py tests/test_coordinator*.py tests/test_prompt_registry.py`) and confirm
      no regressions.

## 3. Documentation

- [x] 3.1 Update `Documents/Oficial/HU_Calificacion_Recomendacion.md` US-216 status cell (line 634)
      from `No [prompt pendiente]` to reflect the prompt shipping.
