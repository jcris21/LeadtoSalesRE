import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.security import AuthenticatedPrincipal, get_current_principal
from app.modules.intelligence_ai_admin.application.prompt_registry_service import (
    PromptRegistryService,
)

router = APIRouter(prefix="/prompts", tags=["prompt-registry"])


class PublishPromptVersionRequest(BaseModel):
    agent_name: str
    version: str
    content: str
    activate: bool = True


class PromptVersionResponse(BaseModel):
    version_id: uuid.UUID


class ActivePromptResponse(BaseModel):
    version_id: uuid.UUID
    version: str
    content: str


@router.post("", response_model=PromptVersionResponse, status_code=201)
async def publish_prompt_version(
    request: PublishPromptVersionRequest,
    session: AsyncSession = Depends(get_db_session),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> PromptVersionResponse:
    service = PromptRegistryService(session)
    version_id = await service.publish_version(
        organization_id=principal.organization_id,
        agent_name=request.agent_name,
        version=request.version,
        content=request.content,
        activate=request.activate,
    )
    return PromptVersionResponse(version_id=version_id)


@router.get("/{agent_name}/active", response_model=ActivePromptResponse)
async def get_active_prompt(
    agent_name: str,
    session: AsyncSession = Depends(get_db_session),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> ActivePromptResponse:
    service = PromptRegistryService(session)
    active = await service.get_active_prompt(principal.organization_id, agent_name)
    return ActivePromptResponse(
        version_id=active.id, version=active.version, content=active.content
    )
