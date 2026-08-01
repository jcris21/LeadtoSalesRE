## Why

`GeminiRecommendationNarrator.narrate` (US-311) already closes the Top-3 message with a preference
question, and `run_scheduling_turn` (US-212, now wired into `CoordinatorAgent`) already books a visit
once the lead states a slot — but nothing in between confirms *which* of the Top-3 properties the
lead actually wants. `scheduling_turn.py::_latest_top_pick` always resolves to the pipeline's rank-1
property, silently ignoring whatever the lead said they liked. A lead who says "sí, el sábado a las
3pm" after being shown three options gets a visit booked for the *wrong* property whenever their
favorite wasn't rank 1. US-220 closes this gap with a deterministic pre-scheduling "deepening" turn.

## What Changes

- Add `app/modules/conversation_ownership/application/deepening_turn.py`: a new orchestration step,
  gated on `conversation.state is ConversationState.RECOMMENDATION`, that (a) asks a deterministic
  question ("¿cuál de estas opciones te llamó más la atención?") when the latest recommendation batch
  has 2+ properties and none has been selected yet and the lead's message carries no recognizable
  slot, or (b) records the lead's selection when their message identifies one of the ranked options
  (ordinal words, "opción N", "número N", or a bare 1-3).
- Extend `RecommendationRepository` with `mark_selected(lead_id, property_id, generated_at)`, reusing
  the existing (currently unused) `RecommendationORM.feedback` JSON column to flag the lead's choice
  — no schema change.
- Extend `scheduling_turn.py::_latest_top_pick` to prefer a batch row flagged as lead-selected before
  falling back to rank-1, so `SchedulingService.book_visit` always targets the property the lead
  actually confirmed interest in once a selection was recorded.
- Wire the new turn into `CoordinatorAgent._conversational_turn`, immediately before the existing
  `_scheduling_turn` call, following the same additive/short-circuit pattern already established for
  the DNI nudge and the scheduling turn itself.

## Deviations from the source HU doc

`Documents/Oficial/HU_Calificacion_Recomendacion.md` describes US-220 as "Prompt/orchestration only"
with "ninguna tabla nueva". The codebase-verified design honors both: no new table or column is added
(the `feedback` JSON column already exists specifically "reserved for future feedback events"), but
the implementation is not purely a system-prompt change — a deterministic (non-LLM) orchestration
step is required so the selected property can be mechanically routed to `run_scheduling_turn`, the
same way the already-merged US-212 scheduling turn and US-218 DNI nudge are deterministic turns
layered around the LLM responder, not new prompt text. A single-property recommendation batch is
treated as `not_applicable` (nothing to deepen on) — this scoping decision isn't in the source doc,
but keeps the change strictly additive: it is what already keeps
`test_coordinator_scheduling_turn.py::test_coordinator_message_without_slot_falls_through_to_responder`
(single-item batch fixture) green with zero modification.

## Capabilities

### New Capabilities
- `conversation-deepening-turn`: the conversational orchestration step that confirms which Top-3
  option interested the lead before a scheduling slot is trusted to resolve a specific property,
  including deterministic option recognition and lead-selection persistence.

### Modified Capabilities
- `conversation-scheduling-turn`: `_latest_top_pick`'s property-resolution rule gains a
  higher-priority source (the lead's recorded selection) before its existing rank-1 fallback.

## Impact

- `app/modules/conversation_ownership/application/deepening_turn.py` — new file.
- `app/modules/conversation_ownership/application/scheduling_turn.py` — `_latest_top_pick` extended;
  new shared `is_lead_selected` helper.
- `app/modules/recommendation/infrastructure/repository.py` — new `RecommendationRepository.mark_selected`.
- `app/modules/conversation_ownership/application/coordinator.py` — new `_deepening_turn` call in
  `_conversational_turn`, before `_scheduling_turn`.
- Tests: `tests/test_deepening_turn.py` (new), `tests/test_scheduling_turn.py` (extended for
  selection-aware `_latest_top_pick`), `tests/test_coordinator_scheduling_turn.py` (extended with a
  multi-item RECOMMENDATION fixture).
- No schema changes — `recommendations.feedback` is a pre-existing nullable JSON column.
