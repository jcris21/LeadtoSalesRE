"""Scheduling Service (US-404, Sprint 4.2).

Closes CRN-5 (Architecture.md §10 Iter. 5): the Coordinator Agent's happy-path
tool orchestration. `book_visit` is the single entry point that turns a
validated slot into a persisted `Appointment`, coordinating everything this
bounded context has built so far — `AvailabilityValidatorPort` (US-402),
`GoogleCalendarPort` (US-403), the (stubbed) `ReminderSchedulerPort`
(placeholder for US-405), and the CRM pipeline-stage sync (`LeadSyncAdapter`,
reusing the US-207 write path).

design.md Decision 1: `book_visit` re-invokes `AvailabilityValidatorPort
.check()` itself — it never trusts a caller-asserted "already confirmed".
That is what makes Architecture §8's bottleneck load-bearing rather than
advisory.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.appointment.application.availability_validator import (
    AvailabilityValidatorService,
)
from app.modules.appointment.application.calendar_port import GoogleCalendarPort
from app.modules.appointment.application.reminder_port import (
    NoOpReminderScheduler,
    ReminderSchedulerPort,
)
from app.modules.appointment.domain.models import (
    Appointment,
    AppointmentBooked,
    AvailabilityCheckSource,
    AvailabilityStatus,
    EventDetails,
    SlotNotConfirmedError,
)
from app.modules.appointment.infrastructure.repository import AppointmentRepository
from app.modules.lead_qualification.application.lead_sync import LeadSyncAdapter
from app.modules.lead_qualification.domain.models import PipelineStage
from app.shared.infrastructure import event_bus
from app.shared.infrastructure.observability import trace_decision

_DEFAULT_VISIT_DURATION_MINUTES = 30
_ACTOR = "scheduling_service"


class SchedulingPort(Protocol):
    """`book_visit` SHALL refuse (raise `SlotNotConfirmedError`, persist
    nothing) unless `AvailabilityValidatorPort.check()` returns `confirmed`
    for the exact `(property_id, slot)` being booked (spec.md "Booking
    re-verifies availability internally")."""

    async def book_visit(
        self,
        *,
        organization_id: uuid.UUID,
        lead_id: uuid.UUID,
        property_id: uuid.UUID,
        broker_id: uuid.UUID,
        slot: datetime,
        attendees: tuple[str, ...],
    ) -> Appointment: ...


class SchedulingService:
    """`SchedulingPort` implementation. Orchestrates, never re-implements —
    every step delegates to an existing port/service (Ports & Adapters,
    QA-05)."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        calendar: GoogleCalendarPort,
        reminders: ReminderSchedulerPort | None = None,
        lead_sync: LeadSyncAdapter | None = None,
    ) -> None:
        self._session = session
        self._calendar = calendar
        self._reminders = reminders or NoOpReminderScheduler()
        self._availability = AvailabilityValidatorService(session)
        self._appointments = AppointmentRepository(session)
        self._lead_sync = lead_sync or LeadSyncAdapter(session)

    async def book_visit(
        self,
        *,
        organization_id: uuid.UUID,
        lead_id: uuid.UUID,
        property_id: uuid.UUID,
        broker_id: uuid.UUID,
        slot: datetime,
        attendees: tuple[str, ...],
    ) -> Appointment:
        async with trace_decision(
            self._session, organization_id=organization_id, agent_name="scheduling_service"
        ) as recorder:
            status = await self._availability.check(
                organization_id=organization_id,
                property_id=property_id,
                slot=slot,
                broker_id=broker_id,
                source=AvailabilityCheckSource.INITIAL,
            )
            if status is not AvailabilityStatus.CONFIRMED:
                recorder.set_output({"result": "refused", "availability_status": status.value})
                raise SlotNotConfirmedError(status)

            calendar_result = await self._calendar.create_event(
                EventDetails(
                    summary=f"Visita de propiedad {property_id}",
                    start=slot,
                    end=slot + timedelta(minutes=_DEFAULT_VISIT_DURATION_MINUTES),
                    attendees=attendees,
                )
            )

            appointment = Appointment(
                organization_id=organization_id,
                lead_id=lead_id,
                property_id=property_id,
                broker_id=broker_id,
                scheduled_at=slot,
                calendar_event_id=calendar_result.calendar_event_id,
                meet_link=calendar_result.meet_link,
            )
            await self._appointments.save(appointment)
            appointment.record_event(
                AppointmentBooked(
                    organization_id=organization_id,
                    appointment_id=str(appointment.id),
                    calendar_event_id=calendar_result.calendar_event_id,
                    meet_link=calendar_result.meet_link,
                    lead_id=str(lead_id),
                )
            )
            recorder.set_output({"result": "booked", "appointment_id": str(appointment.id)})

        await event_bus.publish(self._session, appointment.pull_domain_events())
        await self._reminders.schedule_reminders(appointment.id, slot)
        await self._lead_sync.push_profile_update(
            lead_id, actor=_ACTOR, pipeline_stage=PipelineStage.APPOINTMENT_SET
        )
        return appointment
