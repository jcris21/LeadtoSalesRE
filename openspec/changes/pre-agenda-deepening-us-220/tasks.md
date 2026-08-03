## 1. Selection persistence

- [x] 1.1 Add `RecommendationRepository.mark_selected(lead_id, property_id, generated_at)` to
      `app/modules/recommendation/infrastructure/repository.py`: loads the batch (`lead_id` +
      `generated_at`), sets `feedback = {"selected_by_lead": True}` on the row matching `property_id`,
      clears `feedback` on every other row in that same batch.
- [x] 1.2 Add `is_lead_selected(row) -> bool` helper (in `scheduling_turn.py`, imported by
      `deepening_turn.py`): `bool(row.feedback) and row.feedback.get("selected_by_lead") is True`.

## 2. Option recognition

- [x] 2.1 Create `app/modules/conversation_ownership/application/deepening_turn.py` with
      `extract_selected_rank(text) -> int | None`: accent-insensitive recognition of ordinal words
      (primera/primero, segunda/segundo, tercera/tercero), `"opción N"`, `"número N"`, `"la N"`, and a
      bare `1`/`2`/`3`; returns `None` on no match (never guesses).
- [x] 2.2 Unit tests for `extract_selected_rank`: each recognized form, accented and unaccented,
      no-match cases (unrelated numbers, no message content, ranks outside 1-3).

## 3. Deepening turn orchestration

- [x] 3.1 Add `DeepeningTurnResult` dataclass (`outcome: Literal["asked","selected","not_applicable"]`,
      `response`, `selected_property_id`) and `run_deepening_turn(session, *, conversation, text)` to
      `deepening_turn.py`: gates on `lead_id is not None`, latest batch size ≥ 2, no row already
      lead-selected, and no recognizable slot in `text` (`extract_confirmed_slot`) before attempting
      rank recognition.
- [x] 3.2 On no rank recognized (and gates passed): `outcome="asked"`, deterministic question as
      `response`.
- [x] 3.3 On a recognized rank matching a row in the batch: call `mark_selected`, return
      `outcome="selected"` with `selected_property_id`. On a recognized rank with no matching row
      (e.g. "opción 4" for a 3-item batch): fall back to `outcome="asked"` (never crash, never guess).

## 4. Coordinator wiring

- [x] 4.1 In `CoordinatorAgent`, add `_deepening_turn(conversation, text, recorder)`: gated on
      `conversation.state is ConversationState.RECOMMENDATION` (mirrors `_scheduling_turn`'s own
      gate), calls `run_deepening_turn`, records
      `recorder.record_tool_call("deepening.run_turn", {"text": text}, outcome)` when the outcome is
      not `"not_applicable"`.
- [x] 4.2 In `_conversational_turn`, call `_deepening_turn` immediately before `_scheduling_turn`: if
      `outcome == "asked"`, use its `response` as this turn's reply and short-circuit (same
      `ResponseReady` short-circuit pattern as the scheduling turn's non-`no_slot` outcomes) — skip
      `_scheduling_turn`, `ResponderPort`, and `guard_reply` (deterministic text, not LLM output, same
      rationale already documented for the scheduling confirmation message). On `"selected"` or
      `"not_applicable"`, continue the turn exactly as before (fall through to `_scheduling_turn`,
      then the normal responder).

## 5. Tests

- [x] 5.1 `tests/test_deepening_turn.py`: `extract_selected_rank` unit tests (Task 2.2);
      `run_deepening_turn` — asks when 2+ items and no selection yet; not_applicable on single-item
      batch; not_applicable when a slot is already present in the text; not_applicable when a
      selection already exists; records selection via `mark_selected` on a recognized rank; falls
      back to "asked" on an out-of-range rank.
- [x] 5.2 Extend `tests/test_scheduling_turn.py`: `_latest_top_pick` (via `run_scheduling_turn`) picks
      the lead-selected row over rank-1 when `feedback.selected_by_lead` is set on a non-rank-1 row.
- [x] 5.3 Extend `tests/test_coordinator_scheduling_turn.py` with a multi-item RECOMMENDATION fixture:
      full `handle_message` flow — first reply (no selection) gets the deepening question, not the
      responder; second reply ("la opción 2") records the selection and falls through to the
      responder; a later slot message books the *selected* (non-rank-1) property, proving the
      US-212 -> US-220 handoff end to end. Confirm the existing single-item fixtures/tests
      (`test_coordinator_message_without_slot_falls_through_to_responder`,
      `test_coordinator_books_appointment_and_transitions_to_appointment_state`,
      `test_coordinator_falls_back_gracefully_when_availability_still_pending`) remain green
      unmodified.
- [x] 5.4 Run `uv run pytest -q` for the full suite; confirm no regressions against the pre-change
      baseline.

## 6. Documentation

- [x] 6.1 Update `Documents/Oficial/HU_Calificacion_Recomendacion.md`'s US-220 row status from "[NUEVA]
      / [GAP]" to reflect the deepening turn now existing, if the row format allows a lightweight
      status edit without disturbing unrelated rows.
