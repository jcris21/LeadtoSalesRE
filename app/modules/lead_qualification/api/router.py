"""Support/QA endpoints for progressive profiling (US-202-US-205, design.md
"Support endpoints are REST, one per dimension"). These are NOT the
conversational entry point - they exist to exercise/test the
`BuyerProfileCaptureService.update_profile` write path independently of the
(future) Coordinator Agent / LLM extraction in `qualification_flow.py`. Do not
link these from any customer-facing route.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.security import AuthenticatedPrincipal, get_current_principal
from app.modules.lead_qualification.api.schemas import (
    BudgetCaptureRequest,
    LocationsCaptureRequest,
    MustHavesCaptureRequest,
    ProfileCaptureResponse,
    PropertyTypeCaptureRequest,
    TimelineCaptureRequest,
)
from app.modules.lead_qualification.application.lead_sync import LeadNotFoundError
from app.modules.lead_qualification.application.profile_capture import (
    BuyerProfileCaptureService,
)
from app.modules.lead_qualification.domain.models import (
    MoneyRange,
    ProfilePatch,
    ProfileValidationError,
)
from app.modules.lead_qualification.infrastructure.repository import (
    BuyerProfileRepository,
    LeadRepository,
)

router = APIRouter(prefix="/leads", tags=["lead-qualification"])


async def _verify_lead_ownership(
    session: AsyncSession, lead_id: uuid.UUID, organization_id: uuid.UUID
) -> None:
    lead = await LeadRepository(session).get(lead_id)
    if lead is None or lead.organization_id != organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")


async def _apply_patch(
    session: AsyncSession, lead_id: uuid.UUID, patch: ProfilePatch
) -> ProfileCaptureResponse:
    service = BuyerProfileCaptureService(session)
    try:
        completeness = await service.update_profile(lead_id, patch)
    except ProfileValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except LeadNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found") from exc
    await session.commit()

    profile = await BuyerProfileRepository(session).get_by_lead_id(lead_id)
    captured = list(profile.captured_dimensions()) if profile is not None else []
    return ProfileCaptureResponse(completeness=completeness, captured_dimensions=captured)


@router.post("/{lead_id}/profile/budget", response_model=ProfileCaptureResponse)
async def capture_budget(
    lead_id: uuid.UUID,
    request: BudgetCaptureRequest,
    session: AsyncSession = Depends(get_db_session),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> ProfileCaptureResponse:
    await _verify_lead_ownership(session, lead_id, principal.organization_id)
    try:
        patch = ProfilePatch(budget=MoneyRange(minimum=request.minimum, maximum=request.maximum))
    except ProfileValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return await _apply_patch(session, lead_id, patch)


@router.post("/{lead_id}/profile/locations", response_model=ProfileCaptureResponse)
async def capture_locations(
    lead_id: uuid.UUID,
    request: LocationsCaptureRequest,
    session: AsyncSession = Depends(get_db_session),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> ProfileCaptureResponse:
    await _verify_lead_ownership(session, lead_id, principal.organization_id)
    try:
        patch = ProfilePatch(locations=tuple(request.locations))
    except ProfileValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return await _apply_patch(session, lead_id, patch)


@router.post("/{lead_id}/profile/property-type", response_model=ProfileCaptureResponse)
async def capture_property_type(
    lead_id: uuid.UUID,
    request: PropertyTypeCaptureRequest,
    session: AsyncSession = Depends(get_db_session),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> ProfileCaptureResponse:
    await _verify_lead_ownership(session, lead_id, principal.organization_id)
    patch = ProfilePatch(property_type=request.property_type)
    return await _apply_patch(session, lead_id, patch)


@router.post("/{lead_id}/profile/timeline", response_model=ProfileCaptureResponse)
async def capture_timeline(
    lead_id: uuid.UUID,
    request: TimelineCaptureRequest,
    session: AsyncSession = Depends(get_db_session),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> ProfileCaptureResponse:
    await _verify_lead_ownership(session, lead_id, principal.organization_id)
    patch = ProfilePatch(timeline=request.timeline)
    return await _apply_patch(session, lead_id, patch)


@router.post("/{lead_id}/profile/must-haves", response_model=ProfileCaptureResponse)
async def capture_must_haves(
    lead_id: uuid.UUID,
    request: MustHavesCaptureRequest,
    session: AsyncSession = Depends(get_db_session),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> ProfileCaptureResponse:
    await _verify_lead_ownership(session, lead_id, principal.organization_id)
    try:
        patch = ProfilePatch(must_haves=tuple(request.must_haves))
    except ProfileValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return await _apply_patch(session, lead_id, patch)
