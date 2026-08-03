"""Deepening turn (US-220): confirms which Top-3 option interested the lead
before a scheduling slot is trusted to resolve a specific property.

`GeminiRecommendationNarrator.narrate` (recommendation module) already closes
the Top-3 message with a preference question, and `scheduling_turn.py`
(US-212) already books a visit once the lead states a slot — but nothing
between those two steps confirmed *which* property the lead actually wants,
so `_latest_top_pick` always resolved to the pipeline's rank-1 property
regardless of what the lead said. This module closes that gap with a
deterministic (non-LLM) orchestration step, gated on
`ConversationState.RECOMMENDATION`, the same additive/short-circuit shape
already established by `scheduling_turn.run_scheduling_turn` and the US-218
DNI nudge.

No new persistence: the lead's selection is recorded by
`RecommendationRepository.mark_selected`, which reuses the existing (until
now unused) `RecommendationORM.feedback` JSON column — `scheduling_turn.py`'s
`_latest_top_pick` reads that same marker via `is_lead_selected` and prefers
it over rank-1 (design.md Decision 2/3, openspec/changes/pre-agenda-deepening-us-220).
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.conversation_ownership.application.scheduling_turn import (
    extract_confirmed_slot,
    is_lead_selected,
)
from app.modules.conversation_ownership.domain.models import Conversation
from app.modules.recommendation.infrastructure.repository import RecommendationRepository

DeepeningOutcome = Literal["asked", "selected", "not_applicable"]

#: Deterministic — never invented by an LLM, same posture as the scheduling
#: turn's own fallback messages.
DEEPENING_QUESTION = (
    "Antes de coordinar una visita, cuéntame: ¿cuál de estas opciones te llamó más la atención?"
)

#: Rank-1/2/3 only (Top-3 scope) — a lead saying "primera"/"segunda"/"tercera"
#: (or the masculine "primero"/"segundo"/"tercero") names an option without a
#: number.
_ORDINAL_RANKS: dict[str, int] = {
    "primera": 1,
    "primero": 1,
    "segunda": 2,
    "segundo": 2,
    "tercera": 3,
    "tercero": 3,
}

#: "opción 2" / "opcion N" / "número 2" / "numero N" / "la 2" — each pattern
#: has its own capture group so a single compiled regex can recognize all of
#: them; only ranks 1-3 are ever accepted (Top-3 scope), checked by the
#: caller after a match.
_OPTION_RE = re.compile(
    r"opcion\s*(?:numero\s*)?(\d)"
    r"|numero\s*(\d)"
    r"|\bla\s+(\d)\b"
    r"|^\s*(\d)\s*$"
)


def _normalize(text: str) -> str:
    """Accent-insensitive, lowercase — same normalization spirit as the
    other keyword extractors in `qualification_flow.py`."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def extract_selected_rank(text: str) -> int | None:
    """Deterministic option recognition — same "no match -> None, never
    guess" contract as `extract_confirmed_slot`/`extract_identity`. Recognizes
    the ordinal words ("primera"/"primero", ...), "opción N"/"número N", "la
    N", or a bare digit alone; returns `None` otherwise."""
    normalized = _normalize(text.strip())
    if not normalized:
        return None
    for word, rank in _ORDINAL_RANKS.items():
        if re.search(rf"\b{re.escape(word)}\b", normalized):
            return rank
    match = _OPTION_RE.search(normalized)
    if match is None:
        return None
    for group in match.groups():
        if group is not None:
            rank = int(group)
            if 1 <= rank <= 3:
                return rank
    return None


@dataclass(frozen=True)
class DeepeningTurnResult:
    """Outcome of one deepening turn attempt. `response` is set only for
    `outcome == "asked"` — the caller SHALL use it as this turn's reply,
    short-circuiting `ResponderPort` (mirrors `SchedulingTurnResult`'s own
    contract). Every other outcome leaves the turn's reply untouched."""

    outcome: DeepeningOutcome
    response: str | None = None
    selected_property_id: uuid.UUID | None = None


async def run_deepening_turn(
    session: AsyncSession, *, conversation: Conversation, text: str
) -> DeepeningTurnResult:
    """Only meaningful while `conversation.state is ConversationState.RECOMMENDATION`
    — callers are expected to gate on that themselves (mirrors
    `run_scheduling_turn`'s own contract)."""
    if conversation.lead_id is None:
        return DeepeningTurnResult(outcome="not_applicable")

    repo = RecommendationRepository(session)
    recommendations = await repo.list_for_lead(conversation.lead_id)
    if not recommendations:
        return DeepeningTurnResult(outcome="not_applicable")

    latest_generated_at = max(row.generated_at for row in recommendations)
    latest_batch = [row for row in recommendations if row.generated_at == latest_generated_at]
    if len(latest_batch) < 2:
        # A single-property recommendation has nothing to deepen on
        # (design.md Decision 1) — also what keeps every existing single-item
        # scheduling-turn fixture untouched by this change.
        return DeepeningTurnResult(outcome="not_applicable")
    if any(is_lead_selected(row) for row in latest_batch):
        # Already resolved for this batch — never re-ask.
        return DeepeningTurnResult(outcome="not_applicable")
    if extract_confirmed_slot(text) is not None:
        # The lead jumped straight to a slot without naming an option —
        # `run_scheduling_turn`'s own rank-1 fallback still applies; the
        # deepening question must never block a slot the lead already gave
        # (design.md Decision 4).
        return DeepeningTurnResult(outcome="not_applicable")

    rank = extract_selected_rank(text)
    chosen = next((row for row in latest_batch if row.rank == rank), None) if rank else None
    if chosen is None:
        return DeepeningTurnResult(outcome="asked", response=DEEPENING_QUESTION)

    await repo.mark_selected(conversation.lead_id, chosen.property_id, latest_generated_at)
    return DeepeningTurnResult(outcome="selected", selected_property_id=chosen.property_id)
