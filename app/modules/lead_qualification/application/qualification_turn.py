"""Qualification Turn — the Coordinator-facing orchestrator that closes gap G1
(docs/e2e-manual-chat-checklist.md): every incoming lead message runs through
the deterministic extractors of `qualification_flow.py` (Prompt Chaining,
Agentic_System pattern #1), so the chat itself fills the BuyerProfile and
fires `ProfileCompleted` — no QA endpoint involved.

Routing guards live here, because the orchestrator owns which sub-extractors
run on a given message: `has_budget_signal` keeps bare small numbers ("en 3
meses") from being captured as budget by the greedy amount regex.

When NO deterministic extractor finds a profile signal, the optional
generative extractor (`infrastructure/generative_extractor.py`) classifies the
message against the still-missing dimensions; its schema-validated output is
persisted through the same `BuyerProfileCaptureService.update_profile` write
path, so the QA-14 threshold/`ProfileCompleted` semantics are identical for
both extraction routes.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.lead_qualification.application.lead_sync import LeadNotFoundError
from app.modules.lead_qualification.application.profile_capture import (
    BuyerProfileCaptureService,
)
from app.modules.lead_qualification.application.qualification_flow import (
    extract_bedrooms,
    extract_budget,
    extract_financing_and_decision_mode,
    extract_locations,
    extract_motivation,
    extract_objection,
    extract_property_type,
    extract_timeline_and_must_haves,
    has_budget_signal,
)
from app.modules.lead_qualification.domain.models import (
    PROFILE_DIMENSIONS,
    ObjectionType,
    ProfilePatch,
    ProfileValidationError,
)
from app.modules.lead_qualification.infrastructure.generative_extractor import (
    GenerativeExtractorPort,
)
from app.modules.lead_qualification.infrastructure.repository import (
    BuyerProfileRepository,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class QualificationTurnResult:
    """What one lead message contributed to qualification."""

    patches: tuple[ProfilePatch, ...]
    reprompts: tuple[str, ...]
    objection: ObjectionType | None
    used_generative_fallback: bool = False

    def captured_dimensions(self) -> tuple[str, ...]:
        return tuple(
            dimension
            for dimension in PROFILE_DIMENSIONS
            if any(getattr(patch, dimension) is not None for patch in self.patches)
        )

    def summary(self) -> str:
        """One-line audit string for the AI decision trace."""
        captured = self.captured_dimensions()
        if not captured and not self.reprompts and self.objection is None:
            return "no_signal"
        parts = [f"captured:{','.join(captured) or '-'}"]
        if self.reprompts:
            parts.append(f"reprompts:{len(self.reprompts)}")
        if self.objection is not None:
            parts.append(f"objection:{self.objection.value}")
        if self.used_generative_fallback:
            parts.append("via:generative")
        return " ".join(parts)


_DETERMINISTIC_EXTRACTORS = (
    extract_locations,
    extract_property_type,
    extract_timeline_and_must_haves,
    extract_financing_and_decision_mode,
    extract_bedrooms,
    extract_motivation,
)


async def run_qualification_turn(
    session: AsyncSession,
    *,
    lead_id: uuid.UUID,
    organization_id: uuid.UUID,
    text: str,
    generative_extractor: GenerativeExtractorPort | None = None,
) -> QualificationTurnResult:
    """Runs every applicable extractor over one lead message, persisting via
    the extractors' own write paths (same session => same transaction as the
    conversational turn, so `ProfileCompleted` shares the caller's outbox
    commit)."""
    patches: list[ProfilePatch] = []
    reprompts: list[str] = []
    try:
        extractors = list(_DETERMINISTIC_EXTRACTORS)
        if has_budget_signal(text):
            extractors.insert(0, extract_budget)
        for extractor in extractors:
            result = await extractor(
                session, lead_id=lead_id, organization_id=organization_id, text=text
            )
            if isinstance(result, ProfilePatch):
                patches.append(result)
            elif isinstance(result, str):
                reprompts.append(result)
        objection = await extract_objection(
            session, lead_id=lead_id, organization_id=organization_id, text=text
        )
    except LeadNotFoundError:
        # The lead vanished (merged/removed) after linking — qualification
        # skips this turn; the conversational reply must still happen.
        logger.warning(
            "Qualification skipped: lead %s not found for organization %s",
            lead_id,
            organization_id,
        )
        return QualificationTurnResult(patches=(), reprompts=(), objection=None)

    used_fallback = False
    if not patches and not reprompts and generative_extractor is not None:
        patch = await _generative_fallback(
            session, extractor=generative_extractor, lead_id=lead_id, text=text
        )
        if patch is not None:
            patches.append(patch)
            used_fallback = True

    return QualificationTurnResult(
        patches=tuple(patches),
        reprompts=tuple(reprompts),
        objection=objection,
        used_generative_fallback=used_fallback,
    )


async def _generative_fallback(
    session: AsyncSession,
    *,
    extractor: GenerativeExtractorPort,
    lead_id: uuid.UUID,
    text: str,
) -> ProfilePatch | None:
    """Second-pass classification on keyword mismatch only (the trade-off
    settled in the affinity-profile design review): the LLM sees just the
    still-missing dimensions, and anything it returns for them was already
    schema-validated by the port implementation."""
    profile = await BuyerProfileRepository(session).get_by_lead_id(lead_id)
    missing = profile.missing_dimensions() if profile is not None else PROFILE_DIMENSIONS
    if not missing:
        return None
    try:
        patch = await extractor.extract(text=text, missing_dimensions=tuple(missing))
    except Exception:  # noqa: BLE001 — a fallback failure must never break the turn
        logger.exception("Generative extractor failed; continuing without it")
        return None
    if patch is None or patch.is_empty():
        return None
    try:
        await BuyerProfileCaptureService(session).update_profile(lead_id, patch)
    except (ProfileValidationError, LeadNotFoundError):
        return None
    return patch
