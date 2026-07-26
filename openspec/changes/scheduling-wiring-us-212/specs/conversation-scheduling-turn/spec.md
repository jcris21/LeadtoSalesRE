## ADDED Requirements

### Requirement: Scheduling turn only runs in Recommendation state
`CoordinatorAgent._conversational_turn` SHALL invoke the scheduling turn only when
`conversation.state is ConversationState.RECOMMENDATION`. In any other state, no slot extraction,
no property/broker resolution, and no `SchedulingService` call SHALL occur — the turn proceeds as
if this capability did not exist.

#### Scenario: Qualification-state turn is unaffected
- **WHEN** a message arrives while `conversation.state is ConversationState.QUALIFICATION`
- **THEN** no slot extraction or scheduling call happens, and the turn behaves exactly as before this
  change (existing `tests/test_coordinator_qualification_turn.py` scenarios remain green)

### Requirement: Deterministic slot extraction, never a guess
`extract_confirmed_slot(text)` SHALL recognize an explicit date (`DD/MM` or `DD/MM/YYYY`) or a
relative day (a Spanish weekday name, "hoy", "mañana") combined with a time expression (`H`, `H:MM`,
optional `am`/`pm`, or "a las Hh"), and SHALL return `None` when no such combination is present in the
message. It SHALL NOT infer a slot from context, prior turns, or partial matches.

#### Scenario: Explicit date and time recognized
- **WHEN** the lead's message is "sí, el 15/08 a las 3pm me viene bien"
- **THEN** `extract_confirmed_slot` returns a `datetime` for August 15 at 15:00

#### Scenario: Relative weekday and time recognized
- **WHEN** the lead's message is "el lunes a las 10am"
- **THEN** `extract_confirmed_slot` returns a `datetime` for the next upcoming Monday at 10:00

#### Scenario: No slot in message
- **WHEN** the lead's message is "me interesa esa propiedad"
- **THEN** `extract_confirmed_slot` returns `None` and the conversational turn falls through
  unchanged (normal `ResponderPort` call, no short-circuit)

### Requirement: Booking resolves property, broker, and attendee from existing data
When a slot is recognized in `RECOMMENDATION` state, the scheduling turn SHALL resolve the property
from the lead's most recent recommendation batch's rank-1 result
(`RecommendationRepository.list_for_lead`), the broker from the first active broker in the
organization (`BrokerRepository.list_active_for_organization`), and the attendee from the linked
`Lead.contact_reference`, before calling `SchedulingService.book_visit`.

#### Scenario: No recommendation exists for the lead
- **WHEN** a slot is recognized but `RecommendationRepository.list_for_lead` returns no rows for the
  lead
- **THEN** `SchedulingService.book_visit` is never called, no exception propagates out of
  `handle_message`, and the turn's reply is a conversational message asking the lead to pick a
  property first

#### Scenario: No active broker exists for the organization
- **WHEN** a slot and a recommended property are both resolved, but
  `BrokerRepository.list_active_for_organization` returns no rows
- **THEN** `SchedulingService.book_visit` is never called, no exception propagates out of
  `handle_message`, and the turn's reply is a graceful conversational fallback message

### Requirement: Successful booking transitions the conversation and short-circuits the reply
When `SchedulingService.book_visit` succeeds, the scheduling turn SHALL transition
`conversation.state` from `RECOMMENDATION` to `APPOINTMENT` and SHALL use a booking-confirmation
message (including the appointment's `meet_link`) as this turn's reply, without invoking
`ResponderPort`.

#### Scenario: Appointment booked and conversation transitions
- **WHEN** a slot, property, broker, and attendee all resolve, and
  `AvailabilityValidatorService.check()` (invoked internally by `book_visit`) returns `confirmed`
- **THEN** an `Appointment` is persisted, `conversation.state` becomes `Appointment`, and the turn's
  reply includes the booked appointment's `meet_link`

### Requirement: Unconfirmed availability degrades gracefully without state change
When `SchedulingService.book_visit` raises `SlotNotConfirmedError`, the scheduling turn SHALL NOT let
the exception propagate out of `handle_message`, SHALL leave `conversation.state` unchanged at
`RECOMMENDATION`, and SHALL reply with a deterministic conversational message stating the slot is
not yet confirmed — never a `ResponderPort`-generated reply that might claim the visit is booked.

#### Scenario: Availability still pending
- **WHEN** a slot, property, broker, and attendee all resolve, but
  `AvailabilityValidatorService.check()` returns `pending` or `unavailable`
- **THEN** no `Appointment` is persisted, `conversation.state` remains `Recommendation`, and the
  turn's reply is a deterministic "not yet confirmed" message

### Requirement: Unexpected scheduling failures never crash the turn
Any exception raised while resolving Calendar credentials, calling `GoogleCalendarPort`, or any other
unexpected failure during the scheduling turn SHALL be caught, logged, and translated into a graceful
conversational fallback reply — `handle_message` SHALL always complete successfully for the caller.

#### Scenario: Organization has no Google Calendar configuration
- **WHEN** a slot, property, broker, and attendee all resolve, but the organization has no
  `google_workspace` configuration
- **THEN** `SchedulingService.book_visit` is never called, no exception propagates out of
  `handle_message`, and the turn's reply is a graceful fallback message ("no pude agendar en este
  momento, un asesor te contactará")
