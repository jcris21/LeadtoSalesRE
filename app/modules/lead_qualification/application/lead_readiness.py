"""Lead Readiness Service -- continuous score + financing readiness (US-214).

Extends (does not replace) `LeadScoringService`'s Hot/Warm/Cold objection-based
classification (US-209, `lead_scoring.py`) with an orthogonal, positive-signal
output: a continuous weighted score in [0, 100] and a 3-state
`FinancingReadiness` classification, both computed deterministically (no LLM)
from `BuyerProfile`. See design.md (lead-readiness-service-us-214) for the
weight table (Decision 1) and the READY/PRE_READY/DISCOVERY rule (Decision 2).

The ticket names six signals (intencion, presupuesto, zona, horizonte, forma
de pago, decisor) that are mapped onto existing `BuyerProfile` fields:

    intencion      -> property_type
    presupuesto    -> budget
    zona           -> locations
    horizonte      -> timeline (urgency-scaled)
    forma de pago  -> financing_type (readiness-scaled)
    decisor        -> decision_maker_mode
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.lead_qualification.domain.models import (
    BuyerProfile,
    FinancingReadiness,
    FinancingType,
    Timeline,
)
from app.modules.lead_qualification.infrastructure.repository import BuyerProfileRepository

#: design.md Decision 1 weight table -- flat-captured signals. Sums with the
#: max tier of _TIMELINE_WEIGHTS/_FINANCING_WEIGHTS to exactly 100.
_INTENT_WEIGHT = 15.0
_BUDGET_WEIGHT = 20.0
_ZONE_WEIGHT = 15.0
_DECISION_MAKER_WEIGHT = 10.0

#: design.md Decision 1: horizonte is urgency-scaled, not flat-captured.
_TIMELINE_WEIGHTS: dict[Timeline, float] = {
    Timeline.IMMEDIATE: 20.0,
    Timeline.THREE_MONTHS: 15.0,
    Timeline.SIX_MONTHS: 10.0,
    Timeline.OVER_SIX_MONTHS: 5.0,
    Timeline.EXPLORING: 2.0,
}

#: design.md Decision 1: forma de pago is readiness-scaled, not flat-captured.
_FINANCING_WEIGHTS: dict[FinancingType, float] = {
    FinancingType.CASH: 20.0,
    FinancingType.MORTGAGE_APPROVED: 20.0,
    FinancingType.MORTGAGE_PREAPPROVED: 15.0,
    FinancingType.EVALUATING: 8.0,
}

#: design.md Decision 2: financing_type values strong enough for READY.
_READY_FINANCING = frozenset({FinancingType.CASH, FinancingType.MORTGAGE_APPROVED})
#: design.md Decision 2: timeline values urgent enough for READY.
_READY_TIMELINE = frozenset({Timeline.IMMEDIATE, Timeline.THREE_MONTHS})


@dataclass(frozen=True)
class LeadReadinessResult:
    """Output of `LeadReadinessService.evaluate` (US-214): the continuous
    score and the 3-state financing readiness classification."""

    readiness_score: float
    financing_readiness: FinancingReadiness


def compute_readiness_score(profile: BuyerProfile) -> float:
    """design.md Decision 1: additive weighted sum across the six named
    readiness signals, clamped to [0, 100]."""
    score = 0.0
    if profile.property_type is not None:
        score += _INTENT_WEIGHT
    if profile.budget is not None:
        score += _BUDGET_WEIGHT
    if profile.locations:
        score += _ZONE_WEIGHT
    if profile.timeline is not None:
        score += _TIMELINE_WEIGHTS[profile.timeline]
    if profile.financing_type is not None:
        score += _FINANCING_WEIGHTS[profile.financing_type]
    if profile.decision_maker_mode is not None:
        score += _DECISION_MAKER_WEIGHT
    return max(0.0, min(100.0, score))


def classify_financing_readiness(profile: BuyerProfile) -> FinancingReadiness:
    """design.md Decision 2 rule:

    - READY: financing_type in {cash, mortgage_approved} AND timeline in
      {immediate, 3_months} AND locations captured.
    - PRE_READY: financing_type captured (any value) AND at least one of
      timeline/locations is also captured.
    - DISCOVERY: everything else.
    """
    if (
        profile.financing_type in _READY_FINANCING
        and profile.timeline in _READY_TIMELINE
        and profile.locations
    ):
        return FinancingReadiness.READY
    if profile.financing_type is not None and (
        profile.timeline is not None or profile.locations
    ):
        return FinancingReadiness.PRE_READY
    return FinancingReadiness.DISCOVERY


class LeadReadinessService:
    def __init__(self, session: AsyncSession):
        self._session = session
        self._profiles = BuyerProfileRepository(session)

    async def evaluate(self, profile: BuyerProfile) -> LeadReadinessResult:
        """Computes the continuous score + financing readiness and persists
        both onto the profile's `buyer_profiles` row (design.md Decision 3:
        isolated writer, mirrors `LeadScoringService.record_objection`'s
        read-after-write style). Caller owns the transaction."""
        readiness_score = compute_readiness_score(profile)
        financing_readiness = classify_financing_readiness(profile)
        await self._profiles.set_readiness(
            profile.lead_id,
            readiness_score=readiness_score,
            financing_readiness=financing_readiness,
        )
        return LeadReadinessResult(
            readiness_score=readiness_score, financing_readiness=financing_readiness
        )
