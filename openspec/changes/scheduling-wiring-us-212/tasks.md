## 1. Appointment wiring module

- [x] 1.1 Create `app/modules/appointment/wiring.py` with `CalendarNotConfiguredError` and
      `build_calendar_client(session, organization_id) -> GoogleCalendarPort`, mirroring
      `lead_qualification.wiring.build_wacrm_client`'s shape (read `OrganizationConfigRepository`,
      raise the typed error when `google_workspace` is absent, construct `GoogleCalendarClient`
      otherwise).

## 2. Slot extraction

- [x] 2.1 Create `app/modules/conversation_ownership/application/scheduling_turn.py` with
      `extract_confirmed_slot(text: str, *, reference_now: datetime) -> datetime | None`: regex
      recognition of explicit `DD/MM[/YYYY]` dates and relative weekday/"hoy"/"mañana" combined with
      a time expression (`H`, `H:MM`, optional `am`/`pm`, "a las Hh").
- [x] 2.2 Unit tests for `extract_confirmed_slot`: explicit date+time, relative weekday+time,
      "hoy"/"mañana"+time, no-match cases (no date, no time, ambiguous text), 12h/24h and am/pm
      edge cases.

## 3. Scheduling turn orchestration

- [x] 3.1 Add `SchedulingTurnResult` dataclass (`outcome`, `response`, `appointment`) and
      `run_scheduling_turn(session, *, conversation, text, ...)` to `scheduling_turn.py`: resolves
      recommended property (`RecommendationRepository.list_for_lead`, latest `generated_at`, rank 1),
      active broker (`BrokerRepository.list_active_for_organization`, first), and attendee
      (`Lead.contact_reference` via `LeadRepository`); calls `SchedulingService.book_visit`.
- [x] 3.2 Handle `SlotNotConfirmedError` -> `outcome="not_confirmed"` with a deterministic fallback
      message; missing recommendation -> `outcome="no_recommendation"`; missing broker ->
      `outcome="no_broker"`; `CalendarNotConfiguredError`/unexpected exceptions ->
      `outcome="error"`, all logged, none propagated.
- [x] 3.3 On success, build a confirmation message including `appointment.meet_link` and return
      `outcome="booked"`.

## 4. Coordinator wiring

- [x] 4.1 In `CoordinatorAgent._conversational_turn`, before building `system_prompt`/calling
      `ResponderPort`: if `conversation.state is ConversationState.RECOMMENDATION`, call
      `run_scheduling_turn`.
- [x] 4.2 On `outcome == "booked"`: call `conversation.transition_to(ConversationState.APPOINTMENT,
      reason=...)` and short-circuit the reply with the booking confirmation message (skip
      `ResponderPort`, mirror the `ask_identity`/`qualification.reprompts` override pattern).
- [x] 4.3 On any other outcome besides `no_slot`: use the deterministic fallback message as the
      reply, still short-circuiting `ResponderPort` (same rationale as `_build_grounding_note`'s
      anti-hallucination posture — never let the LLM claim a visit is booked when it isn't).
- [x] 4.4 On `outcome == "no_slot"`: no reply override, turn proceeds exactly as before this change.
- [x] 4.5 Record a `recorder.record_tool_call("scheduling.run_turn", ...)` entry on the
      `AIDecisionTrace`, matching the existing `qualification.run_turn`/`intent_router.classify`
      convention.

## 5. Tests

- [x] 5.1 `tests/test_scheduling_turn.py`: happy path (booked appointment, `pipeline_stage` and
      `appointments` persisted, `AppointmentBooked` in outbox); availability conflict
      (`pending`/`unavailable` -> `not_confirmed`, nothing persisted); no recommendation; no active
      broker; no Calendar config.
- [x] 5.2 Extend the coordinator test harness (pattern from
      `tests/test_coordinator_qualification_turn.py`) with a `RECOMMENDATION`-state conversation
      fixture: full `handle_message` call proving the FSM transition to `Appointment`, the
      short-circuited reply, and that `QUALIFICATION`-state behavior is untouched by this change.
- [x] 5.3 Run the full `pytest` suite and confirm no regressions in existing coordinator/scheduling
      tests.

## 6. Documentation

- [x] 6.1 Update `Documents/Oficial/HU_Calificacion_Recomendacion.md`'s US-212 row status from
      "No [GAP de wiring]" to reflect the wiring now existing (only if the row format allows a
      lightweight status edit without disturbing unrelated rows).
