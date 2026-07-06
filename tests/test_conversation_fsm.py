"""Conversation State Machine (QA-09): every transition validated against the
allowed-transitions table; invalid transitions raise without mutating."""

import pytest

from app.modules.conversation_ownership.domain.models import (
    Conversation,
    ConversationState,
    ConversationWentDormant,
    InvalidTransitionError,
    OwnershipTransferred,
    OwnerType,
)
from app.shared.domain.base import new_id


def _conversation(state: ConversationState = ConversationState.NEW) -> Conversation:
    return Conversation(organization_id=new_id(), chatwoot_conversation_id="42", state=state)


def test_new_conversation_can_become_ai_owned():
    convo = _conversation()
    convo.transition_to(ConversationState.AI_OWNED, reason="scenario 1", owner_type=OwnerType.AI)
    assert convo.state is ConversationState.AI_OWNED
    assert convo.ownership.owner_type is OwnerType.AI
    assert convo.ownership.reason == "scenario 1"


def test_invalid_transition_raises_and_mutates_nothing():
    convo = _conversation()  # New — never went through Negotiation
    original_ownership = convo.ownership
    with pytest.raises(InvalidTransitionError):
        convo.transition_to(ConversationState.CLOSED_WON, reason="nope")
    assert convo.state is ConversationState.NEW
    assert convo.ownership is original_ownership
    assert convo.pull_domain_events() == []


def test_closed_states_are_terminal():
    convo = _conversation(ConversationState.CLOSED_WON)
    with pytest.raises(InvalidTransitionError):
        convo.transition_to(ConversationState.AI_OWNED, reason="reopen")


def test_ownership_transfer_records_event_with_explanation():
    convo = _conversation()
    convo.transition_to(
        ConversationState.ASSIGNED_HUMAN,
        reason="cliente solicitó a María",
        owner_type=OwnerType.HUMAN,
    )
    events = convo.pull_domain_events()
    transfer = next(e for e in events if isinstance(e, OwnershipTransferred))
    assert transfer.from_owner == "unassigned"
    assert transfer.to_owner == "human"
    assert transfer.explanation == "cliente solicitó a María"


def test_ownership_is_replaced_not_mutated_on_transfer():
    convo = _conversation()
    first = convo.transition_to(
        ConversationState.AI_OWNED, reason="scenario 1", owner_type=OwnerType.AI
    )
    second = convo.transition_to(
        ConversationState.ASSIGNED_HUMAN, reason="bypass", owner_type=OwnerType.HUMAN
    )
    assert first is not second
    assert first.owner_type is OwnerType.AI  # old snapshot untouched


def test_decay_to_dormant_from_active_state_emits_event():
    convo = _conversation(ConversationState.QUALIFICATION)
    convo.decay_to_dormant()
    assert convo.state is ConversationState.DORMANT
    events = convo.pull_domain_events()
    assert any(isinstance(e, ConversationWentDormant) for e in events)


def test_dormant_cannot_decay_again():
    convo = _conversation(ConversationState.DORMANT)
    with pytest.raises(InvalidTransitionError):
        convo.decay_to_dormant()


def test_reentry_only_through_ownership_evaluation():
    convo = _conversation(ConversationState.DORMANT)
    with pytest.raises(InvalidTransitionError):
        convo.transition_to(ConversationState.AI_OWNED, reason="skip evaluation")
    convo.transition_to(ConversationState.REACTIVATED, reason="lead replied")
    with pytest.raises(InvalidTransitionError):
        convo.transition_to(ConversationState.QUALIFICATION, reason="skip evaluation")
    convo.transition_to(ConversationState.OWNERSHIP_EVALUATION, reason="E14 gateway")
    assert convo.state is ConversationState.OWNERSHIP_EVALUATION
