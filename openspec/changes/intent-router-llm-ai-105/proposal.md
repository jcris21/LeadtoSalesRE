## Why

`AI-105` in `Documents/Oficial/HU_Calificacion_Recomendacion.md` (lines 709-731) asks for an
"Intent Router (1 llamada LLM, N categorías)" and describes it as fully `[GAP] No implementado`.
That premise is stale: `intent-router-ai-104` (archived `2026-07-25-intent-router-ai-104`) already
shipped `IntentRouterPort`/`GeminiIntentRouter`/`KeywordIntentRouter`
(`app/modules/conversation_ownership/application/intent_router.py`), a 6-category taxonomy that is
a superset of this ticket's 5 named categories, and a wired classification call
(`CoordinatorAgent._classify_intent`) that already records `intent_router.classify` on the turn's
`AIDecisionTrace`. Confirmed by reading `coordinator.py` directly and by the HU doc's own
2026-07-25 correction note on `AI-104`.

What genuinely remains — confirmed by the same correction note ("el resultado de la clasificación
aún no determina ninguna rama de `handle_message`") and by AI-104's `design.md` explicit
Non-Goal — is that the classified category is discarded by its caller
(`await self._classify_intent(text, recorder)`, no assignment). Nothing branches on it. This is
also exactly the blocker the just-merged `knowledge-rag-service-ai-106` change names in its own
docstring: `KnowledgeService.answer` is "NOT wired into `CoordinatorAgent.handle_message`", and
the HU doc's AI-106 entry states plainly: *"el wiring que decide cuándo invocar el servicio
(Objeción vs Q&A) sigue bloqueado por AI-105"*.

## What Changes

- `_classify_intent` returns the classified `IntentCategory` (or `None` on failure) instead of
  discarding it.
- `handle_message` threads that category into `_conversational_turn`.
- **One new consumer branch**, matching the HU doc's own AI-106 Gherkin scenario verbatim
  ("`Given AI-105 clasifica el mensaje como Objeción o Pregunta informativa`"): when the category
  is `"objecion"` or `"pregunta_informativa"`, `CoordinatorAgent` calls
  `KnowledgeService.answer(organization_id, text)`. A grounded (`found=True`) answer becomes the
  turn's reply; a `found=False` result or any lookup failure falls through to today's exact
  existing behavior (the normal LLM responder reply), unchanged.
- No taxonomy change (already correct), no change to `intent_router.py`, no change to
  `knowledge_service.py` — both are consumed as-is.
- All other categories (`qualification`, `agendamiento`, `handoff_explicito`, `otro`) remain
  explicit no-ops — this change does not touch `_scheduling_turn`'s existing
  `ConversationState.RECOMMENDATION` gate (US-212, already wired, already tested) or the identity/
  qualification sequence.
- The deterministic objection-scoring path (`qualification_flow.extract_objection` →
  `LeadScoringService.record_objection`, run unconditionally inside `run_qualification_turn`) is
  untouched — this change adds a grounded answer alongside it, never replaces or gates it.

## Scoping decision (why this and not more)

Two branches were possible for AI-105: (1) full routing — every category gets a dedicated
sub-flow, or (2) the single confirmed-open consumer. Full routing was rejected for this change:
`agendamiento` already has a tested, working deterministic path
(`_scheduling_turn`/US-212) gated on FSM state, not intent category — re-gating it on the
classifier would risk regressing already-shipped, tested behavior for no product-validated
benefit (AI-104's `design.md` Open Questions explicitly flags the category taxonomy as not yet
validated against real traffic). `qualification`/`otro`/`handoff_explicito` have no waiting
consumer today — `handoff_explicito` in particular deliberately overlaps with the guardrail's
deterministic keyword bypass (AI-104 design decision), which remains authoritative. Wiring
branches with no real downstream logic would be dead weight, not a closed gap. The
objeción/pregunta_informativa → `KnowledgeService` branch is the one gap explicitly named as
"blocked by AI-105" by a different, already-merged change (`knowledge-rag-service-ai-106`) — it is
the only branch with a real, tested, standalone-callable consumer waiting on the wiring.

## Capabilities

### Modified Capabilities
- `intent-routing` (`openspec/specs/intent-routing/spec.md`, introduced by
  `intent-router-ai-104`): adds a requirement that the classified category is consumed by
  `CoordinatorAgent` to select the objection/Q&A sub-flow, superseding that spec's implicit
  "classification is recorded but not consumed" posture for this one category pair.

### New Capabilities
(none — no new bounded context; this change is pure wiring between two already-implemented,
already-specified capabilities: `intent-routing` and `knowledge-rag`)

## Impact

- `app/modules/conversation_ownership/application/coordinator.py`: `_classify_intent` return type
  change, `handle_message`/`_conversational_turn` signature changes, new `_knowledge_turn` helper,
  new constructor-injectable `KnowledgeAnswererPort` (default: real `KnowledgeService`).
- No new files, no new tables, no new migration, no new HTTP endpoint.
- `tests/test_coordinator_qualification_turn.py` and other existing `coordinator.py` test files:
  must keep passing unmodified (regression gate) — no assertion changes.
- New test file (or extension) covering the new branch and its precedence against existing
  overrides (`ask_identity`, qualification reprompts).
