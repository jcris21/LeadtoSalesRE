"""Completeness Gate — Specification pattern (§7.8, QA-14).

Explicit precondition of the `Qualification -> Recommendation` transition,
deliberately OUTSIDE the FSM (the FSM stays generic; this business rule lives
in its own module — Architecture.md §10 Iter. 3). Single point of truth for
"can this profile advance?": returns the verdict AND the first missing
dimension so the Coordinator can ask a directed question instead of a vague one.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import get_settings
from app.modules.lead_qualification.domain.models import BuyerProfile
from app.shared.domain.base import ValueObject


@dataclass(frozen=True)
class GateResult(ValueObject):
    can_advance: bool
    completeness: float
    missing_dimension: str | None = None


class CompletenessGate:
    """`CompletenessGatePort.canAdvanceToRecommendation(profile)` (§8)."""

    def __init__(self, threshold: float | None = None):
        self._threshold = (
            threshold if threshold is not None else get_settings().profile_completeness_threshold
        )

    def can_advance_to_recommendation(self, profile: BuyerProfile) -> GateResult:
        completeness = profile.completeness()
        if completeness >= self._threshold:
            return GateResult(can_advance=True, completeness=completeness)
        missing = profile.missing_dimensions()
        return GateResult(
            can_advance=False,
            completeness=completeness,
            missing_dimension=missing[0] if missing else None,
        )
