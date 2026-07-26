## Why

`AvailabilityValidatorService` (US-402) and `SchedulingService.book_visit` (US-404) are fully
implemented and tested in isolation, but `CoordinatorAgent` never calls them — there is zero code
path from a real conversation to a booked `Appointment`. `ConversationState` already declares the
`RECOMMENDATION -> APPOINTMENT` transition; nothing fires it. This is a pure wiring gap (US-212),
blocking two already-scoped follow-ups (US-213 reminders, US-221 conversational visit invitation).

## What Changes

- Add a deterministic slot recognizer (`extract_confirmed_slot`) that reads a confirmed visit
  date/time out of the lead's free-text message — no LLM call, same rigor as `extract_identity`.
- Add `run_scheduling_turn`, a new orchestration step that, only while
  `conversation.state is ConversationState.RECOMMENDATION`, resolves the recommended property
  (`RecommendationRepository.list_for_lead`, latest batch rank 1), an active broker
  (`BrokerRepository.list_active_for_organization`), and the lead's contact reference, then calls
  `SchedulingService.book_visit`.
- Wire this step into `CoordinatorAgent._conversational_turn`, before the `ResponderPort` call: on a
  successful booking, short-circuit the reply with a confirmation message and transition
  `conversation.state` to `APPOINTMENT`; on `SlotNotConfirmedError` or any resolution failure
  (no recommendation, no active broker, no Calendar credentials), fall back to a graceful
  conversational message and leave `conversation.state` unchanged.
- Add `app/modules/appointment/wiring.py::build_calendar_client`, a per-organization
  `GoogleCalendarPort` builder (same pattern as `lead_qualification.wiring.build_wacrm_client`),
  since no wiring module exists yet for the appointment bounded context.
- No changes to `AvailabilityValidatorService` or `SchedulingService` themselves — this proposal only
  adds callers.

## Capabilities

### New Capabilities
- `conversation-scheduling-turn`: the conversational orchestration step that turns a lead's
  in-chat slot confirmation into a `SchedulingService.book_visit` call, including slot extraction,
  property/broker/attendee resolution, and the `RECOMMENDATION -> APPOINTMENT` FSM transition.

### Modified Capabilities
- (none) — `appointment-scheduling`'s existing requirements (`SchedulingPort.book_visit` contract)
  are unchanged; this proposal only adds a new caller into that existing, already-specified
  behavior.

## Impact

- `app/modules/conversation_ownership/application/coordinator.py` — new call in
  `_conversational_turn`.
- `app/modules/conversation_ownership/application/scheduling_turn.py` — new file.
- `app/modules/appointment/wiring.py` — new file.
- Tests: `tests/test_scheduling_turn.py` (new), extensions to
  `tests/test_coordinator_qualification_turn.py`-style harness for the coordinator integration path.
- No schema changes — `appointments`, `leads.pipeline_stage`, `conversations.state` are all
  pre-existing columns/tables.
