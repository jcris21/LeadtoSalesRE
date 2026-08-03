"""Lead Readiness Service -- continuous score + financing readiness (US-214).

Extends (does not replace) `LeadScoringService`'s Hot/Warm/Cold objection-based
classification (US-209, `lead_scoring.py`) with an orthogonal, positive-signal
output: a continuous weighted score in [0, 100] and a 3-state
`FinancingReadiness` classification, both computed deterministically (no LLM)
from `BuyerProfile`. See design.md (lead-readiness-service-us-214) for the
original weight table and the READY/PRE_READY/DISCOVERY rule (Decision 2,
still current).

US-222 remapped `compute_readiness_score`'s weights onto the new Nivel 1 set
(search-pipeline-relevant dimensions), replacing the original six-signal
ticket mapping for the *score* only:

    intencion      -> property_type   (15)
    presupuesto    -> budget          (20)
    zona           -> locations       (15)
    (new)          -> bedrooms        (15)
    (new)          -> motivation      (15)
    (new)          -> must_haves      (20)

`classify_financing_readiness` intentionally still reads `financing_type`/
`timeline`/`locations` (Nivel 2 as of US-222) -- it is a financing-specific
classification independent of the completeness-gate Nivel split, confirmed
out of scope for US-222.
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

#: US-222 design.md Decision D5 weight table -- flat-captured signals over the
#: new Nivel 1 set, sums to exactly 100.
_INTENT_WEIGHT = 15.0
_BUDGET_WEIGHT = 20.0
_ZONE_WEIGHT = 15.0
_BEDROOMS_WEIGHT = 15.0
_MOTIVATION_WEIGHT = 15.0
_MUST_HAVES_WEIGHT = 20.0

#: US-222: `timeline`/`financing_type` no longer feed `compute_readiness_score`
#: (Nivel 2 as of US-222) -- the old `_TIMELINE_WEIGHTS`/`_FINANCING_WEIGHTS`
#: tier tables were removed since nothing else read them. They still gate
#: `classify_financing_readiness` below via the separate `_READY_FINANCING`/
#: `_READY_TIMELINE` frozensets, which are unaffected by this change.

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
    """US-222 design.md Decision D5: additive weighted sum across the six
    Nivel 1 (search-pipeline-relevant) signals, clamped to [0, 100]."""
    score = 0.0
    if profile.property_type is not None:
        score += _INTENT_WEIGHT
    if profile.budget is not None:
        score += _BUDGET_WEIGHT
    if profile.locations:
        score += _ZONE_WEIGHT
    if profile.bedrooms is not None:
        score += _BEDROOMS_WEIGHT
    if profile.motivation is not None:
        score += _MOTIVATION_WEIGHT
    if profile.must_haves:
        score += _MUST_HAVES_WEIGHT
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
