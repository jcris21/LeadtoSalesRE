"""Reminder Scheduler port (US-404 placeholder for US-405, Sprint 4.2).

US-405 (Reminder Scheduler 24h/2h, `Documents/Oficial/HU_Appointment_Handoff_Ownership.md`)
is not implemented yet. This Protocol is defined now so `SchedulingService.book_visit`'s
orchestration (Gherkin: "Scheduling Service dispara ReminderSchedulerPort.schedule_reminders")
is structurally complete today; `NoOpReminderScheduler` is an explicit, documented stand-in
until the real implementation lands and is substituted here — no other code changes.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Protocol


class ReminderSchedulerPort(Protocol):
    """`schedule_reminders` is invoked once per successful booking
    (`SchedulingService.book_visit`). The real implementation (US-405) will
    persist 24h/2h reminder jobs; this Protocol only fixes the shape it must
    satisfy."""

    async def schedule_reminders(
        self, appointment_id: uuid.UUID, scheduled_at: datetime
    ) -> None: ...


class NoOpReminderScheduler:
    """Placeholder `ReminderSchedulerPort` implementation (design.md Decision
    2). No reminder is actually sent — this is a known, documented gap
    tracked as US-405 `[GAP]` in
    `Documents/Oficial/HU_Appointment_Handoff_Ownership.md`, not a silent
    no-op disguised as a finished feature."""

    async def schedule_reminders(self, appointment_id: uuid.UUID, scheduled_at: datetime) -> None:
        return None
