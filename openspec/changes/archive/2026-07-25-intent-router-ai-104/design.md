## Context

`CoordinatorAgent.handle_message` (`app/modules/conversation_ownership/application/coordinator.py:125-173`)
already runs a fixed sequence: guardrail bypass check → identity gate → qualification turn →
conversational turn. The branch between "identity gate keeps asking for name" vs "qualification
turn runs" vs "conversational turn only" is decided by cheap, local conditions
(`conversation.lead_id is None`, `identity_consumed`), not by understanding what the lead's
message is actually about. There is no signal today for "this message is an objection", "this
message is a scheduling confirmation", or "this message is an informational question unrelated
to qualification" — all of those currently fall through to the same qualification extractors and
the LangGraph responder, relying entirely on the LLM prompt to behave reasonably.

Every existing LLM-adjacent port in this module follows the same shape: a `Protocol` port
(`ResponderPort`, `GenerativeExtractorPort`) with a production implementation behind a lazy
import (avoids import-time cost when unused) and a deterministic stub for tests
(`TemplateResponder`). `trace_decision`/`DecisionTraceRecorder` is the existing, working
mechanism for persisting what an AI decision saw and did — no new persistence path is needed.

## Goals / Non-Goals

**Goals:**
- Classify each incoming message into one of a fixed, small category set via a single LLM call.
- Record the classification and its category on the turn's existing `AIDecisionTrace` (via
  `recorder.record_tool_call`), same as `qualification.run_turn` and `identity.create_lead`.
- Ship a deterministic fallback classifier so `coordinator.py` tests keep running without a live
  LLM (mirrors `TemplateResponder`/`HashEmbeddingModel`).
- Keep the call fully additive: if classification fails or is disabled, today's behavior
  (implicit branching) is unchanged.

**Non-Goals:**
- Branching `CoordinatorAgent`'s actual sub-flow selection on the classified category. Today's
  identity/qualification/conversational sequence stays as-is; consuming the category to actually
  change control flow is future work (would need its own proposal once the category set is
  validated against real traffic).
- Objection Handler and Knowledge/RAG Service (`AI-106`) — out of scope, this change only
  classifies, it does not answer objections or questions.
- Any new table, column, or migration — `AIDecisionTraceORM.tool_calls` (jsonb) already fits this.
- Any new HTTP endpoint — this is an internal step inside an existing message-handling pipeline.

## Decisions

**Where the call sits**: after the guardrail bypass check (line 140), before `_identity_gate`
(line 150). Rationale: the guardrail's job is to detect explicit human-handoff triggers and must
stay first (documented contract, `GuardrailPort` docstring: "runs BEFORE any reasoning"). Placing
intent classification any later (e.g. after qualification) would mean it can't inform routing
this turn, defeating its purpose.

**Port shape — `Protocol`, not a class hierarchy**: matches `ResponderPort`/
`GenerativeExtractorPort` exactly, for consistency and because the codebase has zero use of ABC
in this module.

**Category set — decided here, not deferred**: `qualification | pregunta_informativa |
objecion | agendamiento | handoff_explicito | otro` (6 categories, matching the "6 categorías"
language already in the original `AI-104` ticket text). `handoff_explicito` overlaps somewhat
with what `GuardrailInterceptor.check` already catches via keyword bypass — this is intentional:
the guardrail keyword check is deterministic and fast (runs before any LLM call), the classifier
is a secondary/softer signal recorded for future analysis, not a replacement for the guardrail.

**Fallback implementation — deterministic keyword classifier, not "always otro"**: a stub that
always returns `otro` would make every recorded classification meaningless noise in
`AIDecisionTrace.tool_calls`. Instead the fallback does simple keyword matching (same
extraction style as `qualification_flow.py`'s extractors) so tests can assert specific branches
without needing a live LLM, same rationale as `HashEmbeddingModel` for embeddings.

**Failure handling — swallow and continue, never break the turn**: matches
`_build_grounding_note`'s `except Exception: ... return None` pattern (coordinator.py:377-382)
and `_identity_gate`'s wacrm-outage handling (`except Exception: ... return True, False`,
coordinator.py:238-243). A classification failure records nothing extra on the trace and the
turn proceeds exactly as it does today.

## Risks / Trade-offs

- [Risk: classifying-but-not-acting reads as dead weight] → Mitigation: explicitly scoped as
  Non-Goal in this proposal; the recorded categories are the input needed to validate a real
  category taxonomy against production traffic before committing to branching logic on them —
  cheaper to course-correct a taxonomy than to course-correct routing logic already live.
- [Risk: added LLM call increases per-turn latency and cost] → Mitigation: recorded via
  `recorder.set_cost`, visible per-turn in the existing `AIDecisionTrace`/LangSmith run; no new
  dashboard needed, reuses `cost_usd` already on the schema.
- [Risk: category taxonomy needs product sign-off, may cause rework] → Mitigation: no downstream
  consumer depends on the exact category strings yet (Non-Goal), so a taxonomy change post-launch
  only touches the prompt + this one classifier, nothing else.

## Migration Plan

No data migration. Deploy is a plain code change: `IntentRouterPort` default implementation and
prompt ship together; if the responsible LLM credential is unset, the deterministic fallback
takes over automatically (same pattern as `get_default_generative_extractor`/
`get_default_responder`), so this is safe to deploy with no coordinated config change. No
rollback beyond a normal revert — no schema state to unwind.

## Open Questions

- Should `handoff_explicito` as a classifier category be removed entirely, given the guardrail
  keyword check already exists and is authoritative for human handoff? Leaning toward keeping it
  for now (cheap, gives a comparison signal between keyword bypass and LLM judgment) but this is
  a product call, not an engineering one.
- Final category set naming/count needs product sign-off before the prompt is finalized —
  proposed set above is a starting point grounded in the original ticket's "6 categorías", not a
  locked contract.
