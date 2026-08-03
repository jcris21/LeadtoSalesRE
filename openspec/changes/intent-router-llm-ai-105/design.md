## Context

`CoordinatorAgent._classify_intent` (AI-104) already runs and already records
`intent_router.classify` on the turn's `AIDecisionTrace`, but its return value is thrown away —
`await self._classify_intent(text, recorder)` in `handle_message`, no assignment. Separately,
`KnowledgeService.answer` (AI-106) is a fully working, tested, organization-scoped RAG lookup that
no code path calls. Both facts are independently confirmed by reading the current code and by
each change's own docstrings (`intent_router.py` module docstring: "Additive only — no consumer
branches on the result yet"; `knowledge_service.py` module docstring: "NOT wired into
`CoordinatorAgent.handle_message`").

## Goals / Non-Goals

**Goals:**
- Make the classified category available to `handle_message`'s caller-side logic (not just the
  trace).
- Wire exactly the one gap a different, already-merged change explicitly named as blocked on this
  one: objeción/pregunta_informativa → `KnowledgeService.answer`.
- Preserve 100% of today's behavior for every other category and for the not-found/failure paths
  of the new branch — this is an additive change, not a rewrite of turn routing.

**Non-Goals:**
- Routing `agendamiento` through the classifier instead of `_scheduling_turn`'s existing
  `ConversationState.RECOMMENDATION` gate (US-212). That gate is deliberately state-based, not
  intent-based, and already tested; re-gating it is a separate, riskier proposal.
- Any behavior for `qualification`, `otro`, `handoff_explicito` — no consumer exists for these
  today; inventing one would be scope creep past what this ticket (and the HU doc's own
  correction note) asks for.
- Rephrasing `KnowledgeAnswer.answer_text` with an LLM (`AnswerPhraserPort` exists in
  `knowledge_service.py` as an unused seam for future work) — out of scope, extractive text is
  used as-is.
- Any taxonomy change to `IntentCategory` — already correct (superset of this ticket's 5 named
  categories).

## Decisions

### Decision table: category → sub-flow

| Category | This change's behavior |
|---|---|
| `objecion` | **New**: `KnowledgeService.answer` called. `found=True` → its `answer_text` becomes the reply. `found=False` → falls through to today's default responder reply, unchanged. Objection scoring (`extract_objection`/`record_objection`) is unaffected either way — it already runs unconditionally in `run_qualification_turn`. |
| `pregunta_informativa` | **New**: same `KnowledgeService.answer` call/fallback as `objecion`. |
| `agendamiento` | No-op (unchanged). `_scheduling_turn` continues to gate purely on `ConversationState.RECOMMENDATION`, independent of intent category — out of scope, see Non-Goals. |
| `qualification` | No-op (unchanged). `run_qualification_turn` continues to run on every message with a linked lead, independent of intent category. |
| `handoff_explicito` | No-op (unchanged). The guardrail's deterministic keyword bypass remains the authoritative human-handoff signal (AI-104 design decision, still valid); this classifier category stays a recorded-but-unconsumed secondary signal. |
| `otro` | No-op (unchanged). |
| Classification failure (`None`) | No-op — identical to today: no branch fires, normal turn proceeds. |

### Backward-compatibility guarantee

For every category except `objecion`/`pregunta_informativa`, and for those two categories when
`KnowledgeService.answer` returns `found=False` or raises, `_conversational_turn`'s output is
byte-for-byte identical to what today's code (pre-this-change) would produce for the same input —
verified by running the existing, unmodified `tests/test_coordinator_qualification_turn.py`,
`tests/test_coordinator.py`, `tests/test_coordinator_identity_gate.py`,
`tests/test_coordinator_grounding_note.py`, `tests/test_coordinator_scheduling_turn.py` suites
against the new code with zero assertion changes.

### Where the branch sits in `_conversational_turn`

After the existing scheduling-turn short-circuit (which already `return`s early for any non-
`no_slot` outcome — objection/Q&A intents are never classified while a scheduling flow is actively
resolving a slot, since that only fires in `RECOMMENDATION` state and requires the lead to already
be mid-booking), and before the default `self._responder.respond(...)` call. The default responder
still runs unconditionally (same rationale as the existing reprompt-override comment: "the
responder still ran so the checkpointed history stays contiguous") — its output is only replaced
when a grounded knowledge answer exists.

### Precedence order (unchanged shape, one new link)

`ask_identity` (highest) > qualification re-prompt > knowledge answer > default responder reply
(lowest). This mirrors the existing two-tier override
(`ask_identity` > reprompt > default) exactly, inserting the new source below the two existing
overrides rather than above — an unresolved identity gate or an invalid profile signal is still
more urgent than answering an objection.

### `guard_reply` still runs over the knowledge answer

Unlike `_scheduling_turn`'s deterministic messages (which bypass `guard_reply` per its own
documented rationale), the knowledge answer is left to flow through the existing
`guard_reply(...)` call along with every other response source. Rationale: no special-casing
needed — `KnowledgeService.answer` is extractive from `approved=true` KB passages only (AI-106
grounding guarantee), so it structurally cannot contain a hallucinated property link for
`guard_reply` to catch; running it through the existing single call path is simpler than adding a
second bypass branch for a check that will always pass.

### Port shape — new `KnowledgeAnswererPort` (Protocol), matching existing conventions

```python
class KnowledgeAnswererPort(Protocol):
    async def answer(self, organization_id: uuid.UUID, query: str) -> KnowledgeAnswer: ...
```

`KnowledgeService.answer(organization_id, query, *, category=None, top_k=3)` already satisfies
this structurally (extra defaulted keyword params). Default wiring in `CoordinatorAgent.__init__`:
`KnowledgeService(session, build_default_query_embedder(get_settings().gemini_api_key))` — same
config-driven seam as `generative_extractor`/`intent_router` (Gemini embedder when
`gemini_api_key` is set, deterministic `HashTextEmbedder` otherwise, so tests stay hermetic).
Constructor-injectable (`knowledge_answerer: KnowledgeAnswererPort | None = None`) for test stubs,
same DI pattern as `responder`/`generative_extractor`/`intent_router`.

### Failure handling — swallow and continue, never break the turn

Matches every other best-effort step in this class (`_identity_gate`'s wacrm-outage handling,
`_build_grounding_note`'s search-diagnostics handling, `_classify_intent` itself): `except
Exception: logger.exception(...); return None`. A knowledge lookup failure produces no extra
`AIDecisionTrace` entry and the turn proceeds as if the branch didn't exist.

## Risks / Trade-offs

- [Risk: `KnowledgeService` construction cost per-turn] → Mitigation: same cost class as
  `generative_extractor`/`intent_router`, built once in `__init__` (per-message
  `CoordinatorAgent` instance), not per-branch-fire; the embedder is the expensive part and it is
  already a lazy, config-gated singleton-style build identical to the existing ports.
- [Risk: empty/sparse KB makes the new branch a no-op in practice for most organizations] →
  Accepted: `found=False` is the documented, tested "no info" signal (AI-106); the branch degrades
  gracefully to today's behavior, which is the explicit backward-compatibility requirement, not a
  bug.
- [Risk: `pregunta_informativa` is broader than `objecion` — could reduce useful LLM conversational
  answers for benign informational questions the KB has no content for] → Mitigation: identical
  fallback as objection — `found=False` still routes to the normal LLM responder, so no
  informational question goes unanswered; the KB is purely additive when it does have content.

## Migration Plan

No data migration, no schema change. Deploy is a plain code change behind the existing
config-driven seams (`gemini_api_key` presence already gates both the intent classifier's Gemini
vs keyword path and the knowledge embedder's Gemini vs hash path) — safe to deploy with no
coordinated config change. Rollback is a normal revert.

## Open Questions

None outstanding for this change's scope. The broader "should `agendamiento`/`qualification`
also branch on intent category" question remains open per AI-104's own Open Questions (taxonomy
not yet validated against real production traffic) and is deliberately deferred, not answered
here.
