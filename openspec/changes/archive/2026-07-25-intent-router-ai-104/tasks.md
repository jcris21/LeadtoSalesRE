## 1. Intent Router port and fallback

- [x] 1.1 Create `app/modules/conversation_ownership/application/intent_router.py` with
      `IntentRouterPort` (Protocol, `async def classify(self, text: str) -> str`) and an
      `IntentCategory` literal/enum for the fixed set (`qualification`,
      `pregunta_informativa`, `objecion`, `agendamiento`, `handoff_explicito`, `otro`).
- [x] 1.2 Implement `KeywordIntentRouter` (deterministic fallback) in the same module, following
      the extractor style already used in `qualification_flow.py`.
- [x] 1.3 Add `get_default_intent_router()` factory (lazy import of any real LLM-backed
      implementation, same pattern as `get_default_responder`/`get_default_generative_extractor`),
      falling back to `KeywordIntentRouter` when no LLM credential is configured.

## 2. Prompt

- [x] 2.1 Add the intent-classification prompt constant to
      `app/modules/conversation_ownership/domain/prompts.py`, constrained to return one of the 6
      fixed categories as JSON.

## 3. Wire into CoordinatorAgent

- [x] 3.1 Add `intent_router: IntentRouterPort | None = None` constructor param to
      `CoordinatorAgent.__init__`, defaulting via `get_default_intent_router()`.
- [x] 3.2 Add `_classify_intent` method (mirrors `_identity_gate`'s try/except shape) and call it
      in `handle_message` after the guardrail bypass branch, before `_identity_gate`.
- [x] 3.3 On success, call `recorder.record_tool_call("intent_router.classify", {"text": text},
      category)`. On any exception, log and continue without recording.

## 4. Tests

- [x] 4.1 Unit tests for `KeywordIntentRouter` covering each of the 6 categories.
- [x] 4.2 `CoordinatorAgent` test asserting `AIDecisionTrace.tool_calls` contains an
      `intent_router.classify` entry for a normal turn.
- [x] 4.3 `CoordinatorAgent` test asserting a classifier exception does not change the reply or
      break the turn (existing behavior preserved).

## 5. Documentation

- [x] 5.1 Update `Documents/Oficial/HU_Calificacion_Recomendacion.md`: mark `AI-104` (line 549) as
      resolved by existing `CoordinatorAgent` code, with scope narrowed to Intent Router only via
      this change; reconcile the summary table row (line 597) so it doesn't double-count against
      `AI-105`.
