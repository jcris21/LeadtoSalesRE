"""Follow-up turn (US-222): asks for the still-missing Nivel 2 qualification
dimensions (`timeline`, `financing_type`, `decision_maker_mode`) once the lead
has confirmed interest in a specific recommended property.

US-222 reclassified `PROFILE_DIMENSIONS` so `timeline`/`financing_type`/
`decision_maker_mode` no longer block the completeness gate (they are sales
follow-up signals, not search-pipeline inputs) -- but they are still useful to
capture. This module is the deterministic (non-LLM) mechanism that asks for
them, gated on the lead having already selected a Top-3 property via
`deepening_turn.run_deepening_turn`/`RecommendationRepository.mark_selected`
(US-220), so the follow-up question never interrupts the Discovery ->
Recommendation path itself.

Checks persisted selection state (`is_lead_selected`) on every applicable
turn, not just the exact turn the selection happened on (design.md Decision
D3, `us-222-reclassify-qualification-levels`) -- `deepening_turn` itself only
returns `"selected"` once, on the resolving turn, and `"not_applicable"`
every turn after.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.conversation_ownership.application.scheduling_turn import is_lead_selected
from app.modules.conversation_ownership.domain.models import Conversation
from app.modules.lead_qualification.infrastructure.repository import BuyerProfileRepository
from app.modules.recommendation.infrastructure.repository import RecommendationRepository

FollowupOutcome = Literal["asked", "not_applicable"]

#: US-222: the three Nivel 2 dimensions this turn can ask about, in
#: `PROFILE_DIMENSIONS` order -- a literal set, not derived from
#: `PROFILE_DIMENSIONS` slicing, so this module's behavior never silently
#: shifts if the tuple's order changes again later (design.md Migration Plan).
_NIVEL_2_DIMENSIONS: tuple[str, ...] = ("timeline", "financing_type", "decision_maker_mode")

#: Deterministic — never invented by an LLM, same posture as
#: `deepening_turn.DEEPENING_QUESTION`.
_FOLLOWUP_QUESTIONS: dict[str, str] = {
    "timeline": "Una última pregunta para ayudarte mejor: ¿en cuánto tiempo te gustaría concretar la compra?",
    "financing_type": "¿Cómo estás pensando financiar la compra: al contado, con crédito aprobado, preaprobado, o aún evaluando opciones?",
    "decision_maker_mode": "¿La decisión de compra la tomas tú solo, en pareja, o junto con tu familia?",
}


@dataclass(frozen=True)
class FollowupTurnResult:
    """Outcome of one follow-up turn attempt. `response` is set only for
    `outcome == "asked"` -- the caller SHALL use it as this turn's reply,
    short-circuiting `ResponderPort` (mirrors `DeepeningTurnResult`'s own
    contract)."""

    outcome: FollowupOutcome
    response: str | None = None


async def run_followup_turn(
    session: AsyncSession, *, conversation: Conversation, text: str
) -> FollowupTurnResult:
    """Only meaningful while `conversation.state is ConversationState.RECOMMENDATION`
    and the lead has already selected a specific property -- callers are
    expected to gate on state themselves (mirrors `run_deepening_turn`'s own
    contract) and to skip calling this when `run_deepening_turn` already
    short-circuited this turn (spec: "Top-3 disambiguation question takes
    precedence")."""
    if conversation.lead_id is None:
        return FollowupTurnResult(outcome="not_applicable")

    rec_repo = RecommendationRepository(session)
    recommendations = await rec_repo.list_for_lead(conversation.lead_id)
    if not recommendations:
        return FollowupTurnResult(outcome="not_applicable")

    latest_generated_at = max(row.generated_at for row in recommendations)
    latest_batch = [row for row in recommendations if row.generated_at == latest_generated_at]
    if not any(is_lead_selected(row) for row in latest_batch):
        # No selection yet for the latest batch -- deepening_turn's job, not
        # this one's.
        return FollowupTurnResult(outcome="not_applicable")

    profile = await BuyerProfileRepository(session).get_by_lead_id(conversation.lead_id)
    if profile is None:
        return FollowupTurnResult(outcome="not_applicable")

    missing = [d for d in profile.missing_dimensions() if d in _NIVEL_2_DIMENSIONS]
    if not missing:
        return FollowupTurnResult(outcome="not_applicable")

    return FollowupTurnResult(outcome="asked", response=_FOLLOWUP_QUESTIONS[missing[0]])
