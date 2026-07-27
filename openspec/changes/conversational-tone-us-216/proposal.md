## Why

The lead-facing conversation today is governed entirely by `DEFAULT_SYSTEM_PROMPT`
(`app/modules/conversation_ownership/domain/prompts.py`), the fallback prompt `CoordinatorAgent`
sends on every turn across greeting/qualification/recommendation/handoff whenever no
per-organization prompt is published in the Prompt Registry. The current prompt already asks for
one question per turn, but gives the model no guidance to avoid a rigid Q&A cadence, no instruction
to periodically recap what's been understood, and no emoji guidance — so a lead who answers two
qualification questions in a row gets a third bare question with no acknowledgement of what they
already said. US-216 (`Documents/Oficial/HU_Calificacion_Recomendacion.md:821`) asks for a warmer,
non-form conversational tone with a brief summary of understood profile info every 2 consecutive
lead answers during qualification.

## What Changes

- Rewrite the content of `DEFAULT_SYSTEM_PROMPT` to add:
  1. An explicit instruction to hold a natural, flowing conversation (acknowledge what the lead
     said, vary phrasing) rather than a rigid one-question-after-another battery.
  2. A cadence instruction: after every 2 consecutive lead answers containing qualification
     information, the assistant's next reply must open with a brief (1-2 sentence) summary of what
     has been understood so far, before asking the next question.
  3. Explicit warm-professional tone guidance with bounded, moderate emoji use (occasional, not in
     every message).
- Keep every existing strict/anti-hallucination rule (no invented properties/prices, no promised
  availability, no sensitive-data requests, prompt-injection guard) verbatim in substance.
- Add `tests/test_prompts.py` asserting the new content is present and the existing safety rules are
  not weakened.
- Flip the US-216 status cell in `Documents/Oficial/HU_Calificacion_Recomendacion.md` (line 634).

## Explicitly Out of Scope

- **No FSM changes.** `ConversationState` and its transitions are untouched — this is Discovery
  (QUALIFICATION) tone only, not a state change.
- **No DB schema changes.** No new columns, tables, or migrations. No turn-counter field is added
  anywhere in the domain model — the 2-answer cadence is a pure prompt instruction the LLM
  self-tracks from the LangGraph-checkpointed conversation history, matching the ticket's own
  Alineación (d): "sin cambio de código en `llm_brain.py` ni en el grafo."
- **No new services.** Uses the existing Prompt Registry override path
  (`coordinator.py::_load_system_prompt`) unchanged — this proposal only edits the fallback content.
- **No graph/node restructuring.** The `respond` node still only drafts a reply; it decides nothing.

## Capabilities

### New Capabilities

(none — this is a content change to an existing fallback prompt, not a new capability)

### Modified Capabilities

(none formally spec'd) — prompt *content* for `DEFAULT_SYSTEM_PROMPT` is not currently tracked as
an OpenSpec capability under `openspec/specs/` (checked: no `lead-qualification`-style spec entry
governs prompt copy). Per existing repo convention (see US-212's proposal, which also introduced no
delta spec for behavior already covered by an existing, unspec'd wiring), this proposal documents
the change here rather than adding a formal delta spec for what remains an unspec'd prompt-copy
concern.

## Impact

- `app/modules/conversation_ownership/domain/prompts.py` — `DEFAULT_SYSTEM_PROMPT` content rewrite
  only; `INTENT_CLASSIFIER_SYSTEM_PROMPT` untouched.
- `tests/test_prompts.py` — new file, prompt-content regression tests.
- `Documents/Oficial/HU_Calificacion_Recomendacion.md` — US-216 status cell update (line 634).
- No changes to `coordinator.py`, `qualification_flow.py`, `qualification_turn.py`, the LangGraph
  graph definition, or any migration.
