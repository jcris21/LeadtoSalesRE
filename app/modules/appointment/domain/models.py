"""Domain model of the Appointment bounded context (M5, Sprint 4.1 — US-402).

`AvailabilityValidatorPort` (application layer) is the deterministic bottleneck
Architecture.md §7.13/§8 mandates before any slot is proposed or confirmed —
this module only defines the entities/value objects it produces and consumes.

`Broker` is new: no equivalent existed anywhere in the codebase before this
change (verified by grep across every module). `AvailabilityCheck` is an
append-only audit trail, never overwritten — the `source` field distinguishes
the `initial` proposal check from the automatic `revalidation_2_4h` check
(design.md Decision 1), so a broker asking "why was this flagged?" has history
to look at instead of only the latest status.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from app.shared.domain.base import AggregateRoot, DomainEvent, Entity, ValueObject, new_id, utcnow


class AvailabilityStatus(StrEnum):
    """Result of one `AvailabilityValidatorPort.check()` call. `PENDING` is
    blocking — it SHALL NOT be silently promoted to `CONFIRMED` on any
    timeout, retry, or default path (spec.md Requirement: Pending status
    requires explicit human confirmation)."""

    CONFIRMED = "confirmed"
    PENDING = "pending"
    UNAVAILABLE = "unavailable"


class AvailabilityCheckSource(StrEnum):
    """Which of the two Gherkin scenarios produced this check (spec.md)."""

    INITIAL = "initial"
    REVALIDATION_2_4H = "revalidation_2_4h"


@dataclass(frozen=True)
class BrokerAvailability(ValueObject):
    """Simplified MVP availability blob (design.md Decision 3: `jsonb`, not a
    normalized schedule table — no requirement yet demands querying
    availability independent of a specific check)."""

    blocks: tuple[dict, ...] = ()


class Broker(Entity):
    """Human agent with specialties and availability — inputs to the
    Availability Validator and (later, Sprint 4/5) to the Ownership Policy
    Engine's specialist-routing scenarios. Organization-scoped (QA-03)."""

    def __init__(
        self,
        *,
        id: uuid.UUID | None = None,
        organization_id: uuid.UUID,
        specialties: tuple[str, ...] = (),
        active: bool = True,
        availability: BrokerAvailability | None = None,
    ) -> None:
        self.id = id or new_id()
        self.organization_id = organization_id
        self.specialties = specialties
        self.active = active
        self.availability = availability or BrokerAvailability()


@dataclass(frozen=True)
class AvailabilityCheck(ValueObject):
    """Auditable record of one availability evaluation. Never updated in
    place — a re-check (initial vs. revalidation_2_4h) always inserts a new
    row (spec.md Requirement: Auditable availability check history)."""

    id: uuid.UUID = field(default_factory=new_id)
    organization_id: uuid.UUID = field(default_factory=new_id)
    property_id: uuid.UUID = field(default_factory=new_id)
    broker_id: uuid.UUID | None = None
    slot: datetime = field(default_factory=utcnow)
    status: AvailabilityStatus = AvailabilityStatus.PENDING
    source: AvailabilityCheckSource = AvailabilityCheckSource.INITIAL
    checked_at: datetime = field(default_factory=utcnow)


@dataclass(frozen=True)
class EventDetails(ValueObject):
    """Input to `GoogleCalendarPort.create_event` (US-403). `attendees` are
    email addresses (lead + broker) invited to the created event."""

    summary: str
    start: datetime
    end: datetime
    attendees: tuple[str, ...] = ()


@dataclass(frozen=True)
class CalendarEventResult(ValueObject):
    """Output of `GoogleCalendarPort.create_event`, populated from the single
    `events.insert` response (spec.md "Single-call event creation with Meet
    link" — no second API call ever produces `meet_link`)."""

    calendar_event_id: str
    meet_link: str


class CalendarAuthError(Exception):
    """Google Calendar API rejected the service-account credentials (401/403)."""


class CalendarRateLimitError(Exception):
    """Google Calendar API rate-limited the request (429)."""


class CalendarServiceError(Exception):
    """Google Calendar API returned a server error (5xx)."""


class AppointmentStatus(StrEnum):
    """Lifecycle of a booked visit (US-404). Only `BOOKED` exists in this
    change's scope — `CANCELLED`/`NO_SHOW` are US-406's concern (design.md
    Non-Goals)."""

    BOOKED = "booked"


@dataclass(frozen=True)
class AppointmentBooked(DomainEvent):
    """Published through the Outbox when `SchedulingService.book_visit`
    succeeds (spec.md "AppointmentBooked is published on successful
    booking") — future consumers (US-405 reminders, analytics) react to
    this without `SchedulingService` knowing about them. Fields are `str`,
    not `uuid.UUID` — the outbox payload is JSON, and every other
    `DomainEvent` in this codebase (`ResponseReady`, `CRMStageSynced`, etc.)
    follows the same convention."""

    appointment_id: str = ""
    calendar_event_id: str = ""
    meet_link: str = ""
    lead_id: str = ""


class SlotNotConfirmedError(Exception):
    """Raised by `SchedulingService.book_visit` when `AvailabilityValidatorPort
    .check()` does not return `confirmed` — booking SHALL be refused with no
    persistence and no side effects (spec.md "Booking re-verifies
    availability internally")."""

    def __init__(self, status: AvailabilityStatus):
        self.status = status
        super().__init__(f"Cannot book: availability status is '{status.value}', not 'confirmed'")


class Appointment(AggregateRoot):
    """A materialized, booked visit (US-404) — the outcome of
    `SchedulingService.book_visit` after `AvailabilityValidatorPort` returns
    `confirmed` and `GoogleCalendarPort.create_event` succeeds."""

    def __init__(
        self,
        *,
        id: uuid.UUID | None = None,
        organization_id: uuid.UUID,
        lead_id: uuid.UUID,
        property_id: uuid.UUID,
        broker_id: uuid.UUID,
        scheduled_at: datetime,
        calendar_event_id: str,
        meet_link: str,
        status: AppointmentStatus = AppointmentStatus.BOOKED,
    ) -> None:
        super().__init__()
        self.id = id or new_id()
        self.organization_id = organization_id
        self.lead_id = lead_id
        self.property_id = property_id
        self.broker_id = broker_id
        self.scheduled_at = scheduled_at
        self.calendar_event_id = calendar_event_id
        self.meet_link = meet_link
        self.status = status
