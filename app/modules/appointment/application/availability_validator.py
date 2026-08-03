"""Availability Validator (US-402, Sprint 4.1).

Architecture.md §7.13/§8: the deterministic bottleneck no appointment flow may
bypass — no slot is proposed or confirmed to a lead without `check()` running
first, and it runs again automatically 2-4h before an already-booked visit
(caller-supplied `source=AvailabilityCheckSource.REVALIDATION_2_4H`).

MVP decision logic (design.md Decision 2 — no real-time broker/owner
availability feed exists yet):
- No `broker_id` given, or the broker doesn't exist / is inactive ->
  `unavailable` (a deterministic conflict, not a guess).
- A prior `AvailabilityCheck` for the exact same `(property_id, slot)`
  already resolved `unavailable` -> propagate `unavailable` (never
  re-litigate a known conflict).
- A prior check already resolved `confirmed` -> propagate `confirmed`
  (idempotent: re-checking, e.g. the 2-4h re-validation, does not demote an
  already-confirmed slot back to pending).
- Otherwise -> `pending`. This is the deliberately conservative default: the
  system SHALL NOT invent a `confirmed` result out of nothing (spec.md
  "Pending status requires explicit human confirmation"). A `confirmed`
  result only ever exists because it was recorded explicitly (manual broker
  confirmation flow, out of scope for this HU — see design.md Non-Goals).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.appointment.domain.models import (
    AvailabilityCheck,
    AvailabilityCheckSource,
    AvailabilityStatus,
)
from app.modules.appointment.infrastructure.repository import (
    AvailabilityCheckRepository,
    BrokerRepository,
)
from app.shared.infrastructure.observability import trace_decision


class AvailabilityValidatorPort(Protocol):
    """`AvailabilityValidatorPort.check(propertyId, slot) -> confirmed | pending
    | unavailable` (Architecture.md §8). Never caches beyond this call — every
    invocation is a fresh, persisted `AvailabilityCheck`."""

    async def check(
        self,
        *,
        organization_id: uuid.UUID,
        property_id: uuid.UUID,
        slot: datetime,
        broker_id: uuid.UUID | None = None,
        source: AvailabilityCheckSource = AvailabilityCheckSource.INITIAL,
    ) -> AvailabilityStatus: ...


class AvailabilityValidatorService:
    """`AvailabilityValidatorPort` implementation. Deterministic, no LLM
    involvement — the cuello de botella de validación obligatorio."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._brokers = BrokerRepository(session)
        self._checks = AvailabilityCheckRepository(session)

    async def check(
        self,
        *,
        organization_id: uuid.UUID,
        property_id: uuid.UUID,
        slot: datetime,
        broker_id: uuid.UUID | None = None,
        source: AvailabilityCheckSource = AvailabilityCheckSource.INITIAL,
    ) -> AvailabilityStatus:
        async with trace_decision(
            self._session, organization_id=organization_id, agent_name="availability_validator"
        ) as recorder:
            status = await self._resolve(broker_id=broker_id, property_id=property_id, slot=slot)
            recorder.set_output({"status": status.value, "source": source.value})

        await self._checks.save(
            AvailabilityCheck(
                organization_id=organization_id,
                property_id=property_id,
                broker_id=broker_id,
                slot=slot,
                status=status,
                source=source,
            )
        )
        return status

    async def _resolve(
        self, *, broker_id: uuid.UUID | None, property_id: uuid.UUID, slot: datetime
    ) -> AvailabilityStatus:
        if broker_id is not None:
            broker = await self._brokers.get_by_id(broker_id)
            if broker is None or not broker.active:
                return AvailabilityStatus.UNAVAILABLE

        prior = await self._checks.list_for_property_and_slot(property_id, slot)
        if any(c.status is AvailabilityStatus.UNAVAILABLE for c in prior):
            return AvailabilityStatus.UNAVAILABLE
        if any(c.status is AvailabilityStatus.CONFIRMED for c in prior):
            return AvailabilityStatus.CONFIRMED

        # No real-time broker/owner availability feed in the MVP (design.md
        # Decision 2) — never guess `confirmed`; the broker confirms manually.
        return AvailabilityStatus.PENDING
