"""Scheduling turn (US-212): the conversational orchestration step that turns
a lead's in-chat slot confirmation into a `SchedulingService.book_visit` call.

`SchedulingService`/`AvailabilityValidatorService` (US-402/US-404) are complete
and tested in isolation — this module only adds the missing caller: gated on
`ConversationState.RECOMMENDATION` (design.md Decision 1), it recognizes a
slot deterministically (never a guess — same "no match -> None" contract as
`identity_extraction.extract_identity`), resolves the recommended property,
an active broker and the lead's contact reference, then delegates entirely to
`SchedulingService.book_visit`, which re-verifies availability internally.

`AvailabilityValidatorService` never invents `confirmed` out of nothing (US-402
design.md Decision 2) — in the MVP, most first-time slot mentions resolve to
`pending` and raise `SlotNotConfirmedError`. That is expected here, not a bug:
the manual broker-confirmation flow that produces a `confirmed` check is out
of this change's scope.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.appointment.application.scheduling_service import SchedulingService
from app.modules.appointment.domain.models import Appointment, SlotNotConfirmedError
from app.modules.appointment.infrastructure.repository import BrokerRepository
from app.modules.appointment.wiring import CalendarNotConfiguredError, build_calendar_client
from app.modules.conversation_ownership.domain.models import Conversation
from app.modules.lead_qualification.application.lead_sync import LeadSyncAdapter
from app.modules.lead_qualification.infrastructure.repository import LeadRepository
from app.modules.lead_qualification.wiring import build_wacrm_client
from app.modules.recommendation.infrastructure.repository import RecommendationRepository
from app.shared.domain.base import utcnow

logger = logging.getLogger(__name__)

SchedulingOutcome = Literal[
    "booked", "not_confirmed", "no_recommendation", "no_broker", "error", "no_slot"
]

_NOT_CONFIRMED_MESSAGE = (
    "¡Perfecto! Ya registré tu interés en ese horario. Un asesor lo confirmará "
    "en breve y te avisamos por acá apenas quede agendado."
)
_NO_RECOMMENDATION_MESSAGE = (
    "Antes de agendar una visita, cuéntame cuál de las propiedades que te "
    "compartí te interesa."
)
_UNAVAILABLE_ADVISOR_MESSAGE = (
    "No pude agendar la visita en este momento. Un asesor te contactará para "
    "coordinar el horario."
)

#: Spanish weekday name -> Python's `datetime.weekday()` index (Monday = 0).
_WEEKDAYS: dict[str, int] = {
    "lunes": 0,
    "martes": 1,
    "miercoles": 2,
    "miércoles": 2,
    "jueves": 3,
    "viernes": 4,
    "sabado": 5,
    "sábado": 5,
    "domingo": 6,
}

#: `DD/MM` or `DD/MM/YYYY` — the only explicit-date grammar this recognizer
#: supports (design.md Non-Goals: no relative expressions beyond weekday/
#: "hoy"/"mañana", no third-party date-parsing dependency).
_EXPLICIT_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b")

_RELATIVE_DAY_RE = re.compile(
    r"\b(hoy|mañana|manana|lunes|martes|mi[ée]rcoles|jueves|viernes|s[áa]bado|domingo)\b"
)

#: A time expression SHALL carry either an explicit "a las" trigger or an
#: am/pm suffix — a bare number alone (e.g. the "15" in "15/08") must never
#: be misread as a time.
_TIME_RE = re.compile(
    r"(?:a las\s+)(\d{1,2})(?::(\d{2}))?\s*(am|pm)?"
    r"|(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b",
    re.IGNORECASE,
)


def _resolve_time(match: re.Match[str]) -> tuple[int, int] | None:
    hour_s, minute_s, meridiem = match.group(1), match.group(2), match.group(3)
    if hour_s is None:
        hour_s, minute_s, meridiem = match.group(4), match.group(5), match.group(6)
    if hour_s is None:
        return None
    hour = int(hour_s)
    minute = int(minute_s) if minute_s else 0
    if meridiem is not None:
        meridiem = meridiem.lower()
        if meridiem == "pm" and hour != 12:
            hour += 12
        elif meridiem == "am" and hour == 12:
            hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour, minute


def _resolve_date(text: str, *, reference_now: datetime) -> datetime | None:
    explicit = _EXPLICIT_DATE_RE.search(text)
    if explicit is not None:
        day, month = int(explicit.group(1)), int(explicit.group(2))
        year_s = explicit.group(3)
        year = int(year_s) if year_s else reference_now.year
        if year < 100:
            year += 2000
        try:
            return reference_now.replace(
                year=year, month=month, day=day, hour=0, minute=0, second=0, microsecond=0
            )
        except ValueError:
            return None

    relative = _RELATIVE_DAY_RE.search(text)
    if relative is None:
        return None
    word = relative.group(1).lower().replace("manana", "mañana")
    base = reference_now.replace(hour=0, minute=0, second=0, microsecond=0)
    if word == "hoy":
        return base
    if word == "mañana":
        return base + timedelta(days=1)
    target_weekday = _WEEKDAYS[word]
    # "el lunes" means the next upcoming Monday, not necessarily today — a
    # lead who means today says "hoy" instead.
    days_ahead = (target_weekday - base.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return base + timedelta(days=days_ahead)


def extract_confirmed_slot(text: str, *, reference_now: datetime | None = None) -> datetime | None:
    """Deterministic slot recognition: an explicit date or a relative day
    (weekday name / "hoy" / "mañana") combined with a time expression. No
    match on either half returns `None` — this function never guesses a
    slot out of ambiguous text (same contract as `extract_identity`)."""
    lowered = text.strip().lower()
    if not lowered:
        return None
    reference_now = reference_now or utcnow()
    date_part = _resolve_date(lowered, reference_now=reference_now)
    if date_part is None:
        return None
    time_match = _TIME_RE.search(lowered)
    if time_match is None:
        return None
    time_part = _resolve_time(time_match)
    if time_part is None:
        return None
    hour, minute = time_part
    return date_part.replace(hour=hour, minute=minute)


@dataclass(frozen=True)
class SchedulingTurnResult:
    """Outcome of one scheduling turn attempt. `response` is `None` only for
    `outcome == "no_slot"` — the caller keeps the normal `ResponderPort` reply
    in that case; every other outcome carries a deterministic message the
    caller SHALL use instead of the LLM's own reply (design.md Decision 5)."""

    outcome: SchedulingOutcome
    response: str | None = None
    appointment: Appointment | None = None


async def run_scheduling_turn(
    session: AsyncSession,
    *,
    conversation: Conversation,
    text: str,
    attendee_fallback: str = "",
) -> SchedulingTurnResult:
    """Only meaningful while `conversation.state is ConversationState.RECOMMENDATION`
    — callers are expected to gate on that themselves (mirrors
    `_build_grounding_note`'s own state gate)."""
    slot = extract_confirmed_slot(text)
    if slot is None:
        return SchedulingTurnResult(outcome="no_slot")

    lead_id = conversation.lead_id
    if lead_id is None:
        return SchedulingTurnResult(outcome="no_slot")

    recommendations = await RecommendationRepository(session).list_for_lead(lead_id)
    top_pick = _latest_top_pick(recommendations)
    if top_pick is None:
        return SchedulingTurnResult(
            outcome="no_recommendation", response=_NO_RECOMMENDATION_MESSAGE
        )

    brokers = await BrokerRepository(session).list_active_for_organization(
        conversation.organization_id
    )
    if not brokers:
        logger.warning(
            "Scheduling turn: no active broker for organization %s",
            conversation.organization_id,
        )
        return SchedulingTurnResult(outcome="no_broker", response=_UNAVAILABLE_ADVISOR_MESSAGE)
    broker = brokers[0]

    lead = await LeadRepository(session).get(lead_id)
    attendee = (lead.contact_reference if lead is not None else None) or attendee_fallback
    attendees = (attendee,) if attendee else ()

    try:
        calendar = await build_calendar_client(session, conversation.organization_id)
    except CalendarNotConfiguredError:
        logger.info(
            "Scheduling turn: organization %s has no Calendar configuration yet",
            conversation.organization_id,
        )
        return SchedulingTurnResult(outcome="error", response=_UNAVAILABLE_ADVISOR_MESSAGE)
    except Exception:  # noqa: BLE001 — a malformed config must never break the turn
        logger.exception(
            "Scheduling turn: failed to build Calendar client for organization %s",
            conversation.organization_id,
        )
        return SchedulingTurnResult(outcome="error", response=_UNAVAILABLE_ADVISOR_MESSAGE)

    wacrm_client = await build_wacrm_client(session, conversation.organization_id)
    lead_sync = LeadSyncAdapter(session, client=wacrm_client)
    service = SchedulingService(session, calendar=calendar, lead_sync=lead_sync)
    try:
        appointment = await service.book_visit(
            organization_id=conversation.organization_id,
            lead_id=lead_id,
            property_id=top_pick,
            broker_id=broker.id,
            slot=slot,
            attendees=attendees,
        )
    except SlotNotConfirmedError as exc:
        logger.info(
            "Scheduling turn: slot not confirmed for conversation %s (status=%s)",
            conversation.id,
            exc.status.value,
        )
        return SchedulingTurnResult(outcome="not_confirmed", response=_NOT_CONFIRMED_MESSAGE)
    except Exception:  # noqa: BLE001 — scheduling must never crash the turn
        logger.exception(
            "Scheduling turn: unexpected failure booking visit for conversation %s",
            conversation.id,
        )
        return SchedulingTurnResult(outcome="error", response=_UNAVAILABLE_ADVISOR_MESSAGE)

    confirmation = (
        "¡Listo! Tu visita quedó agendada. Te esperamos, y aquí tienes el enlace "
        f"de la reunión: {appointment.meet_link}"
    )
    return SchedulingTurnResult(outcome="booked", response=confirmation, appointment=appointment)


def _latest_top_pick(recommendations: list) -> uuid.UUID | None:
    """Rank-1 property of the most recent recommendation batch
    (design.md Decision 2 — call-site policy, not new repository behavior)."""
    if not recommendations:
        return None
    latest_generated_at = max(row.generated_at for row in recommendations)
    latest_batch = [row for row in recommendations if row.generated_at == latest_generated_at]
    top = min(latest_batch, key=lambda row: row.rank)
    return top.property_id
