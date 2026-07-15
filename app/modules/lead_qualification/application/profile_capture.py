"""BuyerProfile Capture Service — progressive profiling (§6.2, E3).

`BuyerProfileCapturePort.update_profile(leadId, ProfilePatch) -> completeness%`:
validates ranges before persisting (ProfileValidationError never reaches the
row), applies one increment at a time, and publishes `ProfileCompleted` exactly
when the profile CROSSES the completeness threshold (QA-14) — not on every
subsequent update, so wacrm isn't re-notified for every refinement.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.lead_qualification.application.lead_sync import LeadNotFoundError
from app.modules.lead_qualification.domain.models import (
    BuyerProfile,
    ProfileCompleted,
    ProfilePatch,
    ProfileValidationError,
)
from app.modules.lead_qualification.infrastructure.repository import (
    BuyerProfileRepository,
    LeadRepository,
)
from app.shared.infrastructure import event_bus


class BuyerProfileCaptureService:
    def __init__(self, session: AsyncSession, *, completeness_threshold: float | None = None):
        self._session = session
        self._profiles = BuyerProfileRepository(session)
        self._leads = LeadRepository(session)
        self._threshold = (
            completeness_threshold
            if completeness_threshold is not None
            else get_settings().profile_completeness_threshold
        )

    async def update_profile(self, lead_id: uuid.UUID, patch: ProfilePatch) -> float:
        """Apply one progressive-profiling increment; returns updated completeness %.
        Caller owns the transaction (same session as the conversational turn)."""
        if patch.is_empty():
            raise ProfileValidationError("ProfilePatch carries no dimension")

        lead = await self._leads.get(lead_id)
        if lead is None:
            raise LeadNotFoundError(lead_id)

        profile = await self._profiles.get_by_lead_id(lead_id)
        if profile is None:
            profile = BuyerProfile(lead_id=lead_id)

        was_complete = profile.completeness() >= self._threshold
        profile.apply(patch)
        await self._profiles.save(lead.organization_id, profile)

        completeness = profile.completeness()
        if completeness >= self._threshold and not was_complete:
            await event_bus.publish(
                self._session,
                [
                    ProfileCompleted(
                        organization_id=lead.organization_id,
                        lead_id=str(lead_id),
                        crm_lead_id=lead.crm_lead_id,
                        completeness=completeness,
                        profile=self._snapshot(profile),
                    )
                ],
            )
        return completeness

    @staticmethod
    def _snapshot(profile: BuyerProfile) -> dict:
        return {
            "budget": (
                {"minimum": profile.budget.minimum, "maximum": profile.budget.maximum}
                if profile.budget
                else None
            ),
            "locations": list(profile.locations),
            "property_type": profile.property_type.value if profile.property_type else None,
            "timeline": profile.timeline.value if profile.timeline else None,
            "must_haves": list(profile.must_haves),
            "financing_type": profile.financing_type.value if profile.financing_type else None,
            "decision_maker_mode": (
                profile.decision_maker_mode.value if profile.decision_maker_mode else None
            ),
        }
