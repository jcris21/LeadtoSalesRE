"""Google Calendar Adapter port (US-403, Sprint 4.1).

Architecture.md §10 Iter. 5: `conferenceData.createRequest` on the same
`events.insert` call that creates the event — no separate Meet API
integration exists or is needed. Purely deterministic integration; no LLM,
no business decision. The sole (future) caller is the Scheduling Service
(US-404, `SchedulingPort.book_visit`), which requires a `confirmed`
`AvailabilityCheck` (US-402) before invoking this port — that ordering is
enforced by the caller, not by this port itself.
"""

from __future__ import annotations

from typing import Protocol

from app.modules.appointment.domain.models import CalendarEventResult, EventDetails


class GoogleCalendarPort(Protocol):
    """`create_event` SHALL make exactly one Google Calendar API call and
    return a `CalendarEventResult` with both `calendar_event_id` and
    `meet_link` populated from that single response (spec.md "Single-call
    event creation with Meet link")."""

    async def create_event(self, details: EventDetails) -> CalendarEventResult: ...
