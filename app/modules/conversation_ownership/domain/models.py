"""Domain model for the Conversation & Ownership bounded context (M2, Sprint 1).

Conversation is a local projection of a Chatwoot conversation plus the domain
state Chatwoot doesn't model: lifecycle state, ownership and dormancy
(Architecture.md §4.3). Chatwoot remains SoR for messages; this aggregate owns
the state machine (QA-09). Ownership is a value object replaced — never
mutated — on each transfer, giving an auditable ownership history.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from app.shared.domain.base import AggregateRoot, DomainEvent, ValueObject, new_id, utcnow


class ConversationState(StrEnum):
    """Full lifecycle per ArchitecturalDrivers v0.2 — including Dormant,
    Reactivated and OwnershipEvaluation, the single gateway every re-entry
    must pass through."""

    NEW = "New"
    AI_OWNED = "AIOwned"
    QUALIFICATION = "Qualification"
    RECOMMENDATION = "Recommendation"
    APPOINTMENT = "Appointment"
    OWNERSHIP_EVALUATION = "OwnershipEvaluation"
    UNASSIGNED = "Unassigned"
    ASSIGNED_HUMAN = "AssignedHuman"
    VISIT = "Visit"
    NEGOTIATION = "Negotiation"
    DORMANT = "Dormant"
    REACTIVATED = "Reactivated"
    CLOSED_WON = "ClosedWon"
    CLOSED_LOST = "ClosedLost"


class OwnerType(StrEnum):
    AI = "ai"
    HUMAN = "human"
    UNASSIGNED = "unassigned"


class Channel(StrEnum):
    WHATSAPP = "whatsapp"
    WEB = "web"
    OTHER = "other"


#: Allowed transitions table (QA-09): the FSM rejects anything not listed here,
#: without persisting. Dormant is reachable from every ACTIVE state via decay;
#: Reactivated -> OwnershipEvaluation is the only re-entry path (E14).
_ACTIVE_STATES: frozenset[ConversationState] = frozenset(
    {
        ConversationState.NEW,
        ConversationState.AI_OWNED,
        ConversationState.QUALIFICATION,
        ConversationState.RECOMMENDATION,
        ConversationState.APPOINTMENT,
        ConversationState.UNASSIGNED,
        ConversationState.ASSIGNED_HUMAN,
        ConversationState.VISIT,
        ConversationState.NEGOTIATION,
    }
)

ALLOWED_TRANSITIONS: dict[ConversationState, frozenset[ConversationState]] = {
    ConversationState.NEW: frozenset(
        {
            ConversationState.AI_OWNED,
            ConversationState.ASSIGNED_HUMAN,
            ConversationState.OWNERSHIP_EVALUATION,
        }
    ),
    ConversationState.AI_OWNED: frozenset(
        {ConversationState.QUALIFICATION, ConversationState.ASSIGNED_HUMAN}
    ),
    ConversationState.QUALIFICATION: frozenset(
        {ConversationState.RECOMMENDATION, ConversationState.ASSIGNED_HUMAN}
    ),
    ConversationState.RECOMMENDATION: frozenset(
        {ConversationState.APPOINTMENT, ConversationState.ASSIGNED_HUMAN}
    ),
    ConversationState.APPOINTMENT: frozenset(
        {ConversationState.VISIT, ConversationState.ASSIGNED_HUMAN}
    ),
    ConversationState.VISIT: frozenset(
        {
            ConversationState.NEGOTIATION,
            ConversationState.ASSIGNED_HUMAN,
            ConversationState.CLOSED_LOST,
        }
    ),
    ConversationState.NEGOTIATION: frozenset(
        {
            ConversationState.CLOSED_WON,
            ConversationState.CLOSED_LOST,
            ConversationState.ASSIGNED_HUMAN,
        }
    ),
    ConversationState.OWNERSHIP_EVALUATION: frozenset(
        {
            ConversationState.AI_OWNED,
            ConversationState.ASSIGNED_HUMAN,
            ConversationState.UNASSIGNED,
        }
    ),
    ConversationState.UNASSIGNED: frozenset(
        {ConversationState.AI_OWNED, ConversationState.ASSIGNED_HUMAN}
    ),
    ConversationState.ASSIGNED_HUMAN: frozenset(
        {
            ConversationState.VISIT,
            ConversationState.NEGOTIATION,
            ConversationState.CLOSED_WON,
            ConversationState.CLOSED_LOST,
        }
    ),
    ConversationState.DORMANT: frozenset({ConversationState.REACTIVATED}),
    ConversationState.REACTIVATED: frozenset({ConversationState.OWNERSHIP_EVALUATION}),
    ConversationState.CLOSED_WON: frozenset(),
    ConversationState.CLOSED_LOST: frozenset(),
}


class InvalidTransitionError(Exception):
    """Raised by the FSM when a transition is not in ALLOWED_TRANSITIONS.
    Nothing is persisted when this raises (QA-09 verifiable, Architecture.md §7.6)."""

    def __init__(self, current: ConversationState, target: ConversationState):
        self.current = current
        self.target = target
        super().__init__(f"Invalid conversation transition: {current.value} -> {target.value}")


@dataclass(frozen=True)
class Ownership(ValueObject):
    """Immutable snapshot of who owns the conversation, since when, and why."""

    owner_type: OwnerType
    owner_id: uuid.UUID | None
    since: datetime
    reason: str

    @classmethod
    def unassigned(cls) -> Ownership:
        return cls(
            owner_type=OwnerType.UNASSIGNED, owner_id=None, since=utcnow(), reason="not evaluated"
        )


# --- Domain events (Architecture.md §9) ---------------------------------------------------------


# Event payloads are JSON-serialized into the outbox — UUIDs travel as strings.


@dataclass(frozen=True)
class MessageReceived(DomainEvent):
    conversation_id: str = ""
    chatwoot_conversation_id: str = ""
    sender: str = ""
    text: str = ""
    message_timestamp: str = ""


@dataclass(frozen=True)
class ResponseReady(DomainEvent):
    conversation_id: str = ""
    chatwoot_conversation_id: str = ""
    response: str = ""


@dataclass(frozen=True)
class OwnershipTransferred(DomainEvent):
    conversation_id: str = ""
    from_owner: str = ""
    to_owner: str = ""
    explanation: str = ""


@dataclass(frozen=True)
class ConversationWentDormant(DomainEvent):
    conversation_id: str = ""
    last_contact_at: str = ""


# --- Aggregate -----------------------------------------------------------------------------------


@dataclass
class Conversation(AggregateRoot):
    """Aggregate root owning the conversation state machine and ownership history."""

    organization_id: uuid.UUID
    chatwoot_conversation_id: str
    channel: Channel = Channel.WHATSAPP
    state: ConversationState = ConversationState.NEW
    ownership: Ownership = field(default_factory=Ownership.unassigned)
    last_contact_at: datetime = field(default_factory=utcnow)
    id: uuid.UUID = field(default_factory=new_id)
    created_at: datetime = field(default_factory=utcnow)

    def __post_init__(self) -> None:
        super().__init__()

    def transition_to(
        self,
        target: ConversationState,
        *,
        reason: str,
        owner_type: OwnerType | None = None,
        owner_id: uuid.UUID | None = None,
    ) -> Ownership:
        """Validate against the allowed-transitions table and apply. Raises
        InvalidTransitionError WITHOUT mutating anything if not allowed (QA-09)."""
        if target not in ALLOWED_TRANSITIONS[self.state]:
            raise InvalidTransitionError(self.state, target)

        self.state = target
        if owner_type is not None:
            self._replace_ownership(owner_type, owner_id, reason)
        return self.ownership

    def decay_to_dormant(self) -> None:
        """Per-stage inactivity decay: any ACTIVE state can fall to Dormant
        (ArchitecturalDrivers — Dormant reachable from any active state)."""
        if self.state not in _ACTIVE_STATES:
            raise InvalidTransitionError(self.state, ConversationState.DORMANT)
        self.state = ConversationState.DORMANT
        self.record_event(
            ConversationWentDormant(
                organization_id=self.organization_id,
                conversation_id=str(self.id),
                last_contact_at=self.last_contact_at.isoformat(),
            )
        )

    def _replace_ownership(
        self, owner_type: OwnerType, owner_id: uuid.UUID | None, reason: str
    ) -> None:
        previous = self.ownership
        self.ownership = Ownership(
            owner_type=owner_type, owner_id=owner_id, since=utcnow(), reason=reason
        )
        if previous.owner_type != owner_type or previous.owner_id != owner_id:
            self.record_event(
                OwnershipTransferred(
                    organization_id=self.organization_id,
                    conversation_id=str(self.id),
                    from_owner=previous.owner_type.value,
                    to_owner=owner_type.value,
                    explanation=reason,
                )
            )

    def touch(self, at: datetime | None = None) -> None:
        """Record lead activity — resets the dormancy clock."""
        self.last_contact_at = at or utcnow()
