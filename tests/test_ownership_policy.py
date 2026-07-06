"""Ownership Policy Engine skeleton: scenarios 1 and 8 resolved; everything
else raises NotImplementedPlaceholder explicitly — never a silent default."""

from datetime import UTC, datetime

import pytest

from app.modules.conversation_ownership.application.ownership_policy import (
    NotImplementedPlaceholder,
    OwnershipContext,
    OwnershipPolicyEngine,
)
from app.modules.conversation_ownership.domain.models import (
    Conversation,
    ConversationState,
    Ownership,
    OwnerType,
)
from app.shared.domain.base import new_id

engine = OwnershipPolicyEngine()


def _conversation(owner_type: OwnerType = OwnerType.UNASSIGNED) -> Conversation:
    return Conversation(
        organization_id=new_id(),
        chatwoot_conversation_id="42",
        ownership=Ownership(
            owner_type=owner_type,
            owner_id=None,
            since=datetime.now(UTC),
            reason="test",
        ),
    )


def test_scenario_1_never_had_human_gives_ai_ownership():
    decision = engine.evaluate(OwnershipContext(conversation=_conversation()))
    assert decision.scenario == "scenario_1_never_human"
    assert decision.selected_owner is OwnerType.AI
    assert decision.explanation  # QA-11: explanation is first-class, never empty
    assert decision.inputs_snapshot["is_guardrail_bypass"] is False


def test_scenario_8_guardrail_bypass_transfers_to_requested_broker():
    decision = engine.evaluate(
        OwnershipContext(
            conversation=_conversation(),
            broker_requested="María",
            is_guardrail_bypass=True,
        )
    )
    assert decision.scenario == "scenario_8_broker_requested"
    assert decision.selected_owner is OwnerType.HUMAN
    assert "María" in decision.explanation


def test_bypass_wins_even_if_conversation_had_prior_human_owner():
    decision = engine.evaluate(
        OwnershipContext(
            conversation=_conversation(OwnerType.HUMAN),
            broker_requested="Carlos",
            is_guardrail_bypass=True,
        )
    )
    assert decision.selected_owner is OwnerType.HUMAN


def test_unimplemented_scenarios_raise_placeholder_not_silent_default():
    convo = _conversation(OwnerType.HUMAN)
    convo.state = ConversationState.OWNERSHIP_EVALUATION
    with pytest.raises(NotImplementedPlaceholder):
        engine.evaluate(OwnershipContext(conversation=convo))
