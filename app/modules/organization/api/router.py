import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.security import AuthenticatedPrincipal, get_current_principal
from app.modules.organization.api.schemas import (
    ChatwootConfigDTO,
    CreateOrganizationRequest,
    CrmConfigDTO,
    GoogleWorkspaceConfigDTO,
    OrganizationConfigResponse,
    OrganizationResponse,
    UpsertOrganizationConfigRequest,
    WhatsappConfigDTO,
)
from app.modules.organization.application.service import OrganizationService
from app.modules.organization.domain.models import (
    ChatwootConfig,
    CrmConfig,
    GoogleWorkspaceConfig,
    OrganizationConfig,
    WhatsappBusinessConfig,
)

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.post("", status_code=status.HTTP_201_CREATED, response_model=OrganizationResponse)
async def create_organization(
    request: CreateOrganizationRequest, session: AsyncSession = Depends(get_db_session)
) -> OrganizationResponse:
    service = OrganizationService(session)
    org = await service.create_organization(request.name)
    return OrganizationResponse(id=org.id, name=org.name, status=org.status.value)


@router.get("/{organization_id}", response_model=OrganizationResponse)
async def get_organization(
    organization_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> OrganizationResponse:
    if principal.organization_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Cross-organization access denied"
        )
    service = OrganizationService(session)
    org = await service.get_organization(organization_id)
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    return OrganizationResponse(id=org.id, name=org.name, status=org.status.value)


@router.put("/{organization_id}/config", response_model=OrganizationConfigResponse)
async def upsert_organization_config(
    organization_id: uuid.UUID,
    request: UpsertOrganizationConfigRequest,
    session: AsyncSession = Depends(get_db_session),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> OrganizationConfigResponse:
    if principal.organization_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Cross-organization access denied"
        )
    service = OrganizationService(session)
    config = OrganizationConfig(
        organization_id=organization_id,
        chatwoot=ChatwootConfig(**request.chatwoot.model_dump()) if request.chatwoot else None,
        whatsapp=WhatsappBusinessConfig(**request.whatsapp.model_dump())
        if request.whatsapp
        else None,
        crm=CrmConfig(**request.crm.model_dump()) if request.crm else None,
        google_workspace=(
            GoogleWorkspaceConfig(**request.google_workspace.model_dump())
            if request.google_workspace
            else None
        ),
    )
    saved = await service.upsert_config(config)
    return OrganizationConfigResponse(
        organization_id=saved.organization_id,
        chatwoot=ChatwootConfigDTO(**vars(saved.chatwoot)) if saved.chatwoot else None,
        whatsapp=WhatsappConfigDTO(**vars(saved.whatsapp)) if saved.whatsapp else None,
        crm=CrmConfigDTO(**vars(saved.crm)) if saved.crm else None,
        google_workspace=(
            GoogleWorkspaceConfigDTO(**vars(saved.google_workspace))
            if saved.google_workspace
            else None
        ),
        updated_at=saved.updated_at,
        is_complete_for_activation=saved.is_complete_for_activation(),
    )
