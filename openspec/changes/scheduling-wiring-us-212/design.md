## Context

`CoordinatorAgent._conversational_turn` (`app/modules/conversation_ownership/application/coordinator.py`)
already gates a similar aditive-only step (`_build_grounding_note`) on `conversation.state`. The
scheduling step follows the exact same shape: gated on `ConversationState.RECOMMENDATION`, wrapped in
its own exception handling so a failure degrades gracefully instead of breaking the turn, and it may
short-circuit the reply (same pattern already used for `qualification.reprompts` and `ask_identity`).

`SchedulingService.book_visit` (`app/modules/appointment/application/scheduling_service.py`) and
`AvailabilityValidatorService` (`app/modules/appointment/application/availability_validator.py`) are
complete and tested (`tests/test_scheduling_service.py`, `tests/test_availability_validator.py`).
`AvailabilityValidatorService` never invents `confirmed` out of nothing (design.md Decision 2 of
US-402) — in the MVP, a slot is `confirmed` only if a prior `AvailabilityCheck` row already recorded
it as such. That means most first-time slot mentions will resolve to `pending` and
`book_visit` will raise `SlotNotConfirmedError` — this is expected, not a bug in this change; the
manual broker-confirmation flow that produces a `confirmed` check is explicitly out of scope
(US-402 Non-Goals).

## Goals / Non-Goals

**Goals:**
- Give `CoordinatorAgent` a real path from "lead confirms a visit time in chat" to a persisted
  `Appointment`, reusing `SchedulingService`/`AvailabilityValidatorService` exactly as they are.
- Keep the new step purely additive: zero behavior change for any `conversation.state` other than
  `RECOMMENDATION`, and zero change to `QUALIFICATION`-path tests
  (`tests/test_coordinator_qualification_turn.py`).
- Never let a scheduling failure (missing recommendation, missing broker, missing Calendar
  credentials, `SlotNotConfirmedError`) crash `handle_message` — always degrade to a conversational
  reply, same contract as `_identity_gate`'s wacrm-outage handling.

**Non-Goals:**
- Broker specialty/zone-based assignment — first active broker only (matches existing MVP posture
  of `AvailabilityValidatorService`, which already treats broker existence/activity as the only
  gate).
- A system-proposed slot-picker UI/flow. This change only recognizes a slot the lead states in free
  text; it does not generate or present slot options.
- `ReminderSchedulerPort` real implementation (US-213) — `NoOpReminderScheduler` stays as-is,
  `SchedulingService` already calls it.
- Broker email/attendee — `Broker` has no email field today; `attendees` carries only the lead's
  `contact_reference`. Adding a broker attendee is a separate, later change if needed.
- Natural-language date parsing sophistication beyond explicit date/time and simple relative-day
  patterns (weekday name, "hoy", "mañana") — no new third-party date-parsing dependency is added.

## Decisions

**Decision 1: `extract_confirmed_slot` is a standalone deterministic function, not an LLM call.**
Every other "recognize a structured value out of free text" step in this codebase
(`extract_identity`, the qualification dimension extractors) is a regex-based deterministic
recognizer with an explicit "no match -> None, never guess" contract. Slot recognition follows the
same contract: matches an explicit date (`DD/MM[/YYYY]`) or a relative weekday/"hoy"/"mañana", paired
with a time expression (`H`, `H:MM`, optional `am`/`pm`, or "a las Hh"). No match -> `None`, and the
turn falls through unchanged (same as `_classify_intent`'s try/except-and-continue posture already
established for aditive steps). No new dependency (`dateutil`/`dateparser`) is introduced — the
project doesn't already depend on one, and the recognized grammar is small enough for stdlib
`datetime` + `re`.

**Decision 2: Property/broker resolution lives in `scheduling_turn.py`, not in a repository/service
change.** `RecommendationRepository.list_for_lead` and `BrokerRepository.list_active_for_organization`
already return everything needed; "latest batch, rank 1" and "first active broker" are call-site
policy, not new persistence behavior, so no repository or service files are touched (respects the
constraint against modifying `app/modules/recommendation/**` beyond read-only calls).

**Decision 3: `run_scheduling_turn` re-uses the coordinator's own `AsyncSession`, mirroring
`_qualification_turn`.** `SchedulingService`/`AvailabilityValidatorService` both take a session at
construction and participate in the same transaction the coordinator already manages (commit happens
once, at the end of `handle_message`) — no separate transaction boundary, no double-commit risk.

**Decision 4: A new `app/modules/appointment/wiring.py::build_calendar_client` mirrors
`lead_qualification.wiring.build_wacrm_client`'s shape exactly** — read `OrganizationConfigRepository
.get(organization_id)`, and if `google_workspace` is `None`, return a sentinel/raise a typed error the
caller catches (`CalendarNotConfiguredError`), instead of letting `GoogleCalendarClient`'s
construction fail with an unrelated `AttributeError`/`KeyError`. This mirrors `build_wacrm_client`'s
explicit "fail loudly with a typed error, not silently" stance for a present-but-incomplete config,
while a wholly absent config degrades gracefully (caught by `run_scheduling_turn`, not raised past
it).

**Decision 5: Short-circuit only on `outcome == "booked"`.** Every other outcome
(`no_slot`, `no_recommendation`, `no_broker`, `not_confirmed`, `error`) either falls through to the
normal `ResponderPort` call (`no_slot` — no evidence the lead was even trying to book) or overrides
the reply with a deterministic message the same way `ask_identity`/`qualification.reprompts` already
do (all the others — the lead clearly tried to confirm a visit, so a canned LLM reply that ignores
that risks the exact hallucination class `_build_grounding_note`'s docstring already documents two
real incidents of).

## Risks / Trade-offs

- [Risk] `AvailabilityValidatorService`'s conservative default means most real slot confirmations hit
  `pending`, so the happy "booked" path is rare until the (out-of-scope) manual broker-confirmation
  flow exists → Mitigation: this is documented, expected MVP behavior (matches US-402 design), not a
  defect of this change; the `not_confirmed` conversational fallback message sets the lead's
  expectation correctly ("un asesor confirmará tu horario").
- [Risk] Regex-based slot extraction is inherently limited (no relative expressions like "el próximo
  viernes", no timezone handling beyond the org's implicit local time) → Mitigation: explicitly scoped
  as a Non-Goal; a message the recognizer misses simply falls through to the normal conversational
  reply, same failure mode as any other extractor in this codebase, not a regression.
- [Risk] Picking "first active broker" ignores any real assignment logic → Mitigation: matches
  `AvailabilityValidatorService`'s own existing MVP posture (broker existence/activity only); revisit
  together if/when specialty-based routing is scoped.
- [Trade-off] `build_calendar_client` adds a second wiring module for the appointment context instead
  of extending an existing one, since none exists yet → accepted, keeps the appointment module's
  wiring separate from unrelated modules per the codebase's per-module `wiring.py` convention already
  seen in `recommendation/wiring.py`.
