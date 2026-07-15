"""Lead Scoring Service — Hot/Warm/Cold classification (US-209, §7.8-adjacent).

`LeadScoringService.record_objection` persists a new `Objection` row and
recomputes `Lead.lead_score`/`lead_classification` synchronously in the same
transaction, mirroring `BuyerProfileCaptureService.update_profile`'s
read-after-write style. See design.md (lead-objections-classification-us-209)
for the scoring rule rationale and the known conflict with `Lead.mark_synced`
overwriting `lead_score` from wacrm.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.lead_qualification.application.lead_sync import LeadNotFoundError
from app.modules.lead_qualification.domain.models import (
    LeadClassification,
    Objection,
    ObjectionRecorded,
    ObjectionType,
)
from app.modules.lead_qualification.infrastructure.repository import (
    LeadObjectionRepository,
    LeadRepository,
)
from app.shared.infrastructure import event_bus

#: Per-distinct-objection-type penalty (design.md Decision 1).
_PENALTY_PER_DISTINCT_TYPE = 15.0
#: Per-occurrence penalty, applied for every objection row regardless of type.
_PENALTY_PER_OCCURRENCE = 5.0

_HOT_THRESHOLD = 70.0
_WARM_THRESHOLD = 40.0


def compute_lead_score(*, distinct_objection_types: int, total_objection_count: int) -> float:
    """design.md Decision 1: base 100 minus a per-type and a per-occurrence
    penalty, floored at 0."""
    penalty = (
        _PENALTY_PER_DISTINCT_TYPE * distinct_objection_types
        + _PENALTY_PER_OCCURRENCE * total_objection_count
    )
    return max(0.0, 100.0 - penalty)


def classify(lead_score: float) -> LeadClassification:
    """design.md Decision 1 thresholds: >=70 Hot, 40-69.99 Warm, <40 Cold."""
    if lead_score >= _HOT_THRESHOLD:
        return LeadClassification.HOT
    if lead_score >= _WARM_THRESHOLD:
        return LeadClassification.WARM
    return LeadClassification.COLD


class LeadScoringService:
    def __init__(self, session: AsyncSession):
        self._session = session
        self._leads = LeadRepository(session)
        self._objections = LeadObjectionRepository(session)

    async def record_objection(
        self,
        lead_id: uuid.UUID,
        *,
        organization_id: uuid.UUID,
        objection_type: ObjectionType,
        raw_text: str,
    ) -> tuple[float, LeadClassification]:
        """Persists the `Objection`, recomputes `Lead.lead_score`/
        `lead_classification`, and publishes `ObjectionRecorded`. Caller owns
        the transaction (same session as the conversational turn)."""
        lead = await self._leads.get(lead_id)
        if lead is None or lead.organization_id != organization_id:
            raise LeadNotFoundError(lead_id)

        objection = Objection(
            lead_id=lead_id,
            organization_id=organization_id,
            type=objection_type,
            raw_text=raw_text,
        )
        await self._objections.add(objection)

        total_count = await self._objections.count_for_lead(lead_id)
        distinct_types = await self._objections.count_distinct_types_for_lead(lead_id)

        lead_score = compute_lead_score(
            distinct_objection_types=distinct_types, total_objection_count=total_count
        )
        lead_classification = classify(lead_score)
        lead.apply_objection_scoring(
            lead_score=lead_score, lead_classification=lead_classification
        )
        await self._leads.save(lead)

        await event_bus.publish(
            self._session,
            [
                ObjectionRecorded(
                    organization_id=lead.organization_id,
                    lead_id=str(lead_id),
                    crm_lead_id=lead.crm_lead_id,
                    objection_type=objection_type.value,
                    lead_score=lead_score,
                    lead_classification=lead_classification.value,
                )
            ],
        )
        return lead_score, lead_classification
