"""Ownership Policy Engine — skeleton (Iteración 2 / Sprint 1).

`OwnershipPolicyEnginePort.evaluate(context) -> OwnershipDecision`. In this
iteration only two scenarios of the E14 matrix are resolved:

- Scenario 1 — conversation never had a human owner -> AI owns it.
- Scenario 8 — guardrail bypass: the lead explicitly asked for a broker ->
  transfer directly, no rule evaluation.

Every other scenario raises `NotImplementedPlaceholder` explicitly — never a
silent default (Architecture.md §8: "otros escenarios devuelven
NotImplementedPlaceholder explícito, nunca un default silencioso"). The full
10-scenario configurable matrix arrives in Iteración 6.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from app.modules.conversation_ownership.domain.models import Conversation, OwnerType
from app.shared.domain.base import ValueObject


class NotImplementedPlaceholder(Exception):
    """The E14 matrix scenario needed for this context is not implemented in the
    Sprint 1 skeleton. Callers must surface this — silently defaulting an owner
    would corrupt the decision audit trail."""

    def __init__(self, scenario: str):
        self.scenario = scenario
        super().__init__(f"Ownership scenario '{scenario}' not implemented in Sprint 1 skeleton")


@dataclass(frozen=True)
class OwnershipContext(ValueObject):
    """Input snapshot for one evaluation. Grows with later iterations (pipeline
    stage, broker availability, intent, reactivation source...)."""

    conversation: Conversation
    broker_requested: str | None = None
    is_guardrail_bypass: bool = False
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class OwnershipDecision(ValueObject):
    scenario: str
    selected_owner: OwnerType
    owner_id: uuid.UUID | None
    explanation: str
    inputs_snapshot: dict


class OwnershipPolicyEngine:
    """Domain service. Stateless — persistence of decisions is the caller's job
    (OwnershipDecisionRepository), so the engine stays replayable and testable."""

    def evaluate(self, context: OwnershipContext) -> OwnershipDecision:
        snapshot = {
            "conversation_id": str(context.conversation.id),
            "state": context.conversation.state.value,
            "current_owner": context.conversation.ownership.owner_type.value,
            "broker_requested": context.broker_requested,
            "is_guardrail_bypass": context.is_guardrail_bypass,
        }

        if context.is_guardrail_bypass:
            requested = context.broker_requested or "un asesor humano"
            return OwnershipDecision(
                scenario="scenario_8_broker_requested",
                selected_owner=OwnerType.HUMAN,
                owner_id=None,  # broker directory lands in Sprint 4 (Appointment module)
                explanation=f"El cliente solicitó explícitamente a {requested}",
                inputs_snapshot=snapshot,
            )

        never_had_human = context.conversation.ownership.owner_type in (
            OwnerType.UNASSIGNED,
            OwnerType.AI,
        )
        if never_had_human:
            return OwnershipDecision(
                scenario="scenario_1_never_human",
                selected_owner=OwnerType.AI,
                owner_id=None,
                explanation=(
                    "Conversación sin historial con broker humano: la AI toma ownership "
                    "para conducir el happy path"
                ),
                inputs_snapshot=snapshot,
            )

        raise NotImplementedPlaceholder("reactivation_or_prior_human_scenarios_2_to_7_9_10")
