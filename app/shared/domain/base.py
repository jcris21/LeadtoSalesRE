"""Base DDD building blocks shared by every bounded context."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime


def new_id() -> uuid.UUID:
    return uuid.uuid4()


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class ValueObject:
    """Marker base for immutable value objects. Equality is by value, never mutated in place."""


@dataclass(frozen=True)
class DomainEvent:
    """Immutable fact that happened in the domain. Published on the internal Event Bus (Outbox)."""

    event_id: uuid.UUID = field(default_factory=new_id)
    occurred_at: datetime = field(default_factory=utcnow)
    organization_id: uuid.UUID | None = None

    @property
    def event_type(self) -> str:
        return self.__class__.__name__


class Entity:
    """Base for entities with identity. Two entities are equal iff their ids match."""

    id: uuid.UUID

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Entity):
            return NotImplemented
        return self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)


class AggregateRoot(Entity):
    """Entity that is the consistency boundary for a cluster of objects.

    Collects domain events raised during a use case so the application layer can
    publish them to the Outbox after the transaction commits (never before —
    that would violate the transactional-outbox guarantee).
    """

    def __init__(self) -> None:
        self._domain_events: list[DomainEvent] = []

    def record_event(self, event: DomainEvent) -> None:
        self._domain_events.append(event)

    def pull_domain_events(self) -> list[DomainEvent]:
        events, self._domain_events = self._domain_events, []
        return events
