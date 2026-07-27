## Original

#### AI-105 [NUEVA] — Intent Router (1 llamada LLM, N categorías)

Como sistema quiero clasificar cada mensaje entrante en una categoría de intención (calificación,
pregunta informativa, objeción, agendamiento, otro) mediante una única llamada LLM ligera, para
enrutar el turno sin necesidad de un agente autónomo adicional.

```gherkin
Feature: Enrutamiento por intención
Scenario: Mensaje ambiguo entre pregunta y objeción
  Given un mensaje entrante del lead
  When IntentRouter.classify se ejecuta (1 llamada LLM, salida JSON acotada a N categorías)
  Then CoordinatorAgent recibe la categoría antes de decidir el sub-flujo
  And se registra un AIDecisionTrace con la categoría y el mensaje clasificado
```

**Alineación**: (a) Transversal — corre al inicio de `CoordinatorAgent.handle_message`, antes de
`run_qualification_turn` / `_conversational_turn`. (b) Capa agentic: no existe hoy — confirmado
por ausencia total de símbolo `IntentRouter` en `app/`. Reemplazaría el gate implícito de
`run_qualification_turn` (que hoy decide solo por "¿hay Lead vinculado?", no por intención del
mensaje). (c) `ai_decision_traces` (tabla ya existe en Supabase, sin consumidor actual). (d) [GAP]
No implementado. Prerrequisito conceptual de AI-106 (enrutar Objeción vs Q&A) y de un
agendamiento con lenguaje natural más fino en US-212.

## Enhanced

### Correction of premise (2026-07-27, verified against actual code)

The ticket's premise — "IntentRouter no existe hoy" — is **stale**. A prior change,
`intent-router-ai-104` (archived `2026-07-25-intent-router-ai-104`), already implemented:

- `IntentRouterPort` (Protocol), `GeminiIntentRouter`, `KeywordIntentRouter` in
  `app/modules/conversation_ownership/application/intent_router.py`.
- A 6-category taxonomy (`IntentCategory` = `qualification | pregunta_informativa | objecion |
  agendamiento | handoff_explicito | otro`) — a superset of this ticket's 5 named categories
  (`handoff_explicito` was added deliberately as a softer secondary signal alongside the
  guardrail's deterministic keyword bypass; see AI-104 `design.md` Decisions). **No taxonomy
  change is needed** — the existing set already covers every category this ticket names.
- `CoordinatorAgent._classify_intent`, invoked from `handle_message` right after the guardrail
  bypass check and before the identity gate — exactly the position this ticket's Gherkin
  describes ("antes de decidir el sub-flujo").
- Registration of the classification as a `tool_call` (`intent_router.classify`) on the turn's
  existing `AIDecisionTrace` via `recorder.record_tool_call` — satisfies the ticket's `Then ...
  And se registra un AIDecisionTrace` clause as written.
- A deterministic `KeywordIntentRouter` fallback for offline/test/keyless environments, and a
  `GeminiIntentRouter` behind `gemini_api_key`, both never raising (fail-safe fallback to
  keyword classification on any Gemini error).

**What is confirmed still missing**, per `Documents/Oficial/HU_Calificacion_Recomendacion.md`'s
own 2026-07-25 correction note on AI-104 and the AI-104 `design.md` explicit Non-Goal: *"the
classified category is produced but never used to decide which sub-flow `handle_message`
runs."* `_classify_intent` is called, but its return value is discarded by the caller today
(`await self._classify_intent(text, recorder)` — no assignment). This is the actual, sole
remaining gap this change (`intent-router-llm-ai-105`) closes.

### Scoped functionality (this change)

1. **Return the classified category to the caller.** `_classify_intent` changes from
   `-> None` to `-> IntentCategory | None` (`None` only on classification failure, preserving
   today's "never break the turn" contract). `handle_message` captures it and threads it into
   `_conversational_turn`.
2. **Wire exactly one consumer, per the HU doc's own AI-106 Gherkin** (`Given AI-105 clasifica el
   mensaje como Objeción o Pregunta informativa / When KnowledgeService.answer recupera pasajes
   ... `): when the classified category is `"objecion"` or `"pregunta_informativa"`,
   `CoordinatorAgent` calls `KnowledgeService.answer(organization_id, text)` (AI-106, already
   implemented and merged, previously unwired — confirmed by its own module docstring: "NOT wired
   into `CoordinatorAgent.handle_message`"). If `KnowledgeAnswer.found` is `True`, that grounded,
   extractive answer becomes this turn's reply (bypassing the LLM responder's freeform text, same
   rationale `_scheduling_turn` already documents for deterministic composed text). If `found` is
   `False` (empty/irrelevant KB), or the lookup raises, **today's exact behavior is preserved
   unchanged** — the normal LLM responder's reply is used, with no observable difference from
   before this change.
3. **All other categories (`qualification`, `agendamiento`, `handoff_explicito`, `otro`) are
   explicit no-ops in this change** — 100% backward-compatible fall-through to today's existing
   turn sequence. `agendamiento` already has a dedicated, tested deterministic path
   (`_scheduling_turn`, US-212) gated on `ConversationState.RECOMMENDATION`, not on intent
   category — wiring the classifier to that gate is out of scope here (would change working,
   tested behavior for a ticket explicitly scoped to the objection/Q&A gap called out by name in
   the HU doc's own AI-106 entry).
4. **The deterministic objection-scoring path is untouched.**
   `qualification_flow.extract_objection` → `LeadScoringService.record_objection` continues to
   run unconditionally inside `run_qualification_turn` for every message (as it does today,
   independent of intent classification) — this change only *adds* a grounded answer alongside
   the existing score-only detection, it does not replace or gate it.
5. **`AIDecisionTrace` registration is unchanged** — `intent_router.classify` was already recorded
   by AI-104; this change adds one more `tool_call` (`knowledge.answer`) only on the turns where
   the new branch actually fires, matching the existing `qualification.run_turn` /
   `identity.create_lead` / `scheduling.run_turn` pattern.

### Fields / data touched

No new columns, no new tables, no new migration. Reuses:
- `ai_decision_traces.tool_calls` (jsonb, existing) — one additional entry per fired branch.
- `knowledge_documents` (existing, migration `0021`, AI-106) — read-only from this change.
- `lead_objections` (existing, US-209) — write path unchanged.

### Endpoints

None. This is an internal orchestration step inside the existing
`CoordinatorAgent.handle_message` message-handling pipeline; no new HTTP surface.

### Files to modify

- `app/modules/conversation_ownership/application/coordinator.py`:
  - `_classify_intent` returns `IntentCategory | None` instead of `None`.
  - `handle_message` captures the returned category and passes it to `_conversational_turn`.
  - `_conversational_turn` gains the new knowledge-lookup branch (new private helper
    `_knowledge_turn`) and a new constructor-injectable `KnowledgeAnswererPort` (protocol,
    default `KnowledgeService` wired with `build_default_query_embedder`).
- No changes to `app/modules/conversation_ownership/application/intent_router.py` (taxonomy
  already correct).
- No changes to `app/modules/knowledge/application/knowledge_service.py` (already correct,
  standalone-callable per its own docstring).

### Definition of done

- [ ] `_classify_intent` returns the category; `AIDecisionTrace` recording unchanged/verified.
- [ ] Objection/Q&A branch calls `KnowledgeService.answer` and, when grounded, replaces the
      turn's reply; bypasses `guard_reply`'s property-link check is NOT required (extractive KB
      text still passes through `guard_reply` unchanged — simpler, no special-casing needed since
      KB content has no property links to false-positive on).
- [ ] All other categories fall through to today's exact behavior — regression-tested against the
      existing `tests/test_coordinator_qualification_turn.py` suite (unmodified assertions).
- [ ] `ask_identity` and qualification re-prompt overrides still take precedence over a knowledge
      answer, same precedence order as today (identity > reprompt > knowledge > default response).
- [ ] Knowledge lookup failures never break the turn (try/except, same contract as
      `_build_grounding_note` / `_identity_gate`).
- [ ] New unit tests: knowledge-service-driven reply on objection, on pregunta_informativa,
      not-found fallback, failure fallback, non-consuming categories unaffected, precedence order.
- [ ] Full test suite (`-m "not integration"`) green, no regressions.

### Non-functional requirements

- **Observability**: new `knowledge.answer` tool call on `AIDecisionTrace`, same shape/pattern as
  existing tool calls — no new dashboard needed.
- **Performance**: one additional retrieval call only on the two consuming categories (not every
  turn); reuses the already-open `AsyncSession`.
- **Resilience**: knowledge lookup failure is swallowed, never propagates — matches every other
  best-effort step in `CoordinatorAgent` (`_identity_gate`, `_build_grounding_note`).
- **Security/tenancy**: `KnowledgeService.answer` is already organization-scoped (AI-106); this
  change passes `conversation.organization_id` unchanged, no new tenancy surface.
