## Why

`AI-104` in `Documents/Oficial/HU_Calificacion_Recomendacion.md` (lines 549-570) describes a
"Coordinator Agent" as `[GAP — no implementado]`, but `CoordinatorAgent.handle_message`
(`app/modules/conversation_ownership/application/coordinator.py`) already exists and already
orchestrates the turn (guardrail interceptor → identity gate → qualification turn →
conversational turn → ownership policy), and already persists `AIDecisionTraceORM` rows via
`trace_decision` (`app/shared/infrastructure/observability.py`). The ticket's premise is stale.

What genuinely does not exist — confirmed by grep, zero hits for the symbol `IntentRouter` in
`app/` — is the LLM-backed intent classification step that should run before the Coordinator
picks a branch. Today that branching is an implicit `if conversation.lead_id is None` check
(`_qualification_turn`), not a classification of the lead's actual intent (question, objection,
scheduling request, etc.). This is the same gap already flagged separately as `AI-105` in the
same document (lines 679-704). This change scopes `AI-104` down to exactly that remaining piece
— the Intent Router — instead of re-building a Coordinator that already ships.

## What Changes

- Add an `IntentRouterPort` (Protocol) classifying an incoming lead message into one of a fixed
  set of categories, with a deterministic fallback implementation for offline/test use (same
  pattern as `TemplateResponder` and `HashEmbeddingModel`).
- Wire one classification call into `CoordinatorAgent.handle_message`, after the guardrail bypass
  check and before `_identity_gate`/`_qualification_turn`, recorded as a `tool_call` on the
  existing `AIDecisionTrace` for that turn (no new table, no new columns).
- Add a classification prompt (new entry alongside `DEFAULT_SYSTEM_PROMPT` in
  `app/modules/conversation_ownership/domain/prompts.py`).
- Do **not** touch: guardrail, identity gate, qualification turn, ownership policy, or
  `AIDecisionTraceORM` schema — all already implemented and out of scope.
- Documentation: mark `AI-104` in `HU_Calificacion_Recomendacion.md` as resolved-by-existing-code
  / merged into this change, to avoid the tracking table (line 597) double-counting it against
  `AI-105`.

## Capabilities

### New Capabilities
- `intent-routing`: LLM-backed classification of an incoming conversational turn into a fixed
  category set, consumed by `CoordinatorAgent` to select which sub-flow handles the turn, with
  the classification recorded on the turn's `AIDecisionTrace`.

### Modified Capabilities
(none — no existing spec's requirements change; `CoordinatorAgent`'s turn-handling behavior gains
a new upstream step but its documented contracts, if any exist under `openspec/specs/`, are not
altered)

## Impact

- `app/modules/conversation_ownership/application/coordinator.py`: new `_classify_intent` step
  wired into `handle_message`.
- New file: `app/modules/conversation_ownership/application/intent_router.py` (or
  `infrastructure/` if it wraps a real LLM call) defining `IntentRouterPort` and the default
  implementation.
- `app/modules/conversation_ownership/domain/prompts.py`: new classification prompt constant.
- No new migrations, no new tables/columns, no new HTTP endpoints.
- Downstream: no consumers of the classified category exist yet in this change (Objection
  Handler / Matching Engine delegation is `AI-106`/already-implemented deterministic services,
  respectively) — this change only produces and records the classification, it does not yet
  branch behavior on it beyond what already exists.
