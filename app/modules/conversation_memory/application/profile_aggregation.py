"""Profile Aggregation (US-211, Sprint 2.2): synthesizes a lead's accumulated
`conversation_memory` observations into two independent jsonb snapshots —
`buyer_profiles.ai_profile` (affinity scores for the Ranking Engine, US-305)
and `leads.buyer_persona` (communication/context signals for the future
Coordinator, AI-104).

Deterministic keyword-frequency scoring — no LLM call, same first-cut posture
as `memory_extraction.py` (see
`openspec/changes/affinity-profile-aggregation-us-211/design.md`).

Recompute contract (design.md D6): callers invoke `aggregate` only after
`extract_conversation_memory` returned a non-empty list — never on the
recommendation/search read path. Each run recomputes from the full eligible
observation set and overwrites its own column (D7): observations are
append-only, so recomputation is pure and idempotent.

Snapshot independence: this module is the sole writer of both columns; it
never touches `PROFILE_DIMENSIONS`, the US-208 dimensions, lead scoring, or
`conversation_memory` rows.

Tenant isolation: verifies the lead belongs to `organization_id` before
writing, mirroring `memory_extraction.py`'s `_assert_tenant`.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.conversation_memory.domain.models import (
    ConversationMemoryObservation,
    MemoryType,
)
from app.modules.conversation_memory.infrastructure.repository import (
    ConversationMemoryRepository,
)
from app.modules.lead_qualification.application.lead_sync import LeadNotFoundError
from app.modules.lead_qualification.infrastructure.repository import (
    BuyerProfileRepository,
    LeadRepository,
)
from app.shared.domain.base import utcnow

logger = logging.getLogger(__name__)

#: Eligibility floor (design.md D2): below AI-102's fixed 0.6 keyword
#: confidence so current observations qualify, while pre-filtering any future
#: low-confidence LLM output.
_MIN_CONFIDENCE = 0.5

#: Style adjectives in the "modern" family (design.md D3) — the share of these
#: over all observed style adjectives is `modern_score`.
_MODERN_ADJECTIVES = frozenset(
    {
        "moderno",
        "moderna",
        "contemporaneo",
        "contemporanea",
        "minimalista",
        "luminoso",
        "luminosa",
        "elegante",
    }
)

#: Family-context phrase buckets (design.md D3): children-presence phrases are
#: `family_score`'s numerator, explicit no-children phrases weigh in the
#: denominator only, and solo-living/pet phrases never move the score — they
#: are persona-only signals (D4).
_CHILDREN_MARKERS = ("hijos", "hijas", "ninos", "niños", "ninas", "niñas")
_NO_CHILDREN_MARKERS = ("no tenemos hijos", "no tengo hijos", "sin hijos")
_SOLO_MARKERS = ("vivimos solos", "vivimos solas", "vivo solo", "vivo sola")
_PET_MARKER = "mascota"


@dataclass(frozen=True)
class AggregationResult:
    """Which snapshots this run wrote — `None` means not written (no eligible
    observations, or no `buyer_profiles` row for `ai_profile`)."""

    ai_profile: dict | None
    buyer_persona: dict | None


async def _assert_tenant(
    session: AsyncSession, lead_id: uuid.UUID, organization_id: uuid.UUID
) -> None:
    lead = await LeadRepository(session).get(lead_id)
    if lead is None or lead.organization_id != organization_id:
        raise LeadNotFoundError(lead_id)


def _build_ai_profile(
    observations: list[ConversationMemoryObservation], computed_at: str
) -> dict:
    modern_weight = 0.0
    total_weight = 0.0
    family_signal = 0.0
    family_weight = 0.0

    for observation in observations:
        if observation.memory_type is MemoryType.STYLE_PREFERENCE:
            for adjective in observation.value.get("adjectives", ()):
                total_weight += observation.confidence
                if adjective in _MODERN_ADJECTIVES:
                    modern_weight += observation.confidence
        elif observation.memory_type is MemoryType.FAMILY_CONTEXT:
            for phrase in observation.value.get("phrases", ()):
                if any(marker in phrase for marker in _NO_CHILDREN_MARKERS):
                    family_weight += observation.confidence
                elif any(marker in phrase for marker in _SOLO_MARKERS) or _PET_MARKER in phrase:
                    continue  # persona-only signal, must not dilute the score
                elif any(marker in phrase for marker in _CHILDREN_MARKERS):
                    family_weight += observation.confidence
                    family_signal += observation.confidence

    return {
        "modern_score": round(modern_weight / total_weight, 4) if total_weight else 0.0,
        "family_score": round(family_signal / family_weight, 4) if family_weight else 0.0,
        "confidence": round(
            sum(o.confidence for o in observations) / len(observations), 4
        ),
        "observation_count": len(observations),
        "computed_at": computed_at,
    }


def _build_buyer_persona(
    observations: list[ConversationMemoryObservation], computed_at: str
) -> dict:
    family_stage: str | None = None
    has_pets = False

    for observation in observations:
        if observation.memory_type is not MemoryType.FAMILY_CONTEXT:
            continue
        for phrase in observation.value.get("phrases", ()):
            if _PET_MARKER in phrase:
                has_pets = True
            if any(marker in phrase for marker in _NO_CHILDREN_MARKERS) or any(
                marker in phrase for marker in _SOLO_MARKERS
            ):
                family_stage = "couple_no_children"
            elif any(marker in phrase for marker in _CHILDREN_MARKERS):
                family_stage = "family_with_children"

    return {
        "family_stage": family_stage,
        "has_pets": has_pets,
        # Only channel in the product today; tone-based keys wait for the
        # MemoryType.TONE extractor (design.md D4).
        "communication": "whatsapp",
        "computed_at": computed_at,
    }


class ProfileAggregationService:
    """US-211: recomputes both affinity snapshots from the lead's eligible
    `conversation_memory` observations."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def aggregate(
        self, *, lead_id: uuid.UUID, organization_id: uuid.UUID
    ) -> AggregationResult:
        await _assert_tenant(self._session, lead_id, organization_id)

        observations = await ConversationMemoryRepository(self._session).list_for_lead(
            lead_id, min_confidence=_MIN_CONFIDENCE
        )
        if not observations:
            logger.debug("No eligible observations for lead %s; skipping.", lead_id)
            return AggregationResult(ai_profile=None, buyer_persona=None)

        computed_at = utcnow().isoformat()
        ai_profile = _build_ai_profile(observations, computed_at)
        buyer_persona = _build_buyer_persona(observations, computed_at)

        profile_written = await BuyerProfileRepository(self._session).set_ai_profile(
            lead_id, ai_profile
        )
        if not profile_written:
            # Graceful degradation (design.md D5): no buyer_profiles row yet —
            # persona still lands; creating the profile is capture's job.
            logger.debug("Lead %s has no buyer_profile; ai_profile skipped.", lead_id)
        await LeadRepository(self._session).set_buyer_persona(lead_id, buyer_persona)

        logger.info(
            "Aggregated %d observations for lead %s (ai_profile=%s).",
            len(observations),
            lead_id,
            "written" if profile_written else "skipped",
        )
        return AggregationResult(
            ai_profile=ai_profile if profile_written else None,
            buyer_persona=buyer_persona,
        )
