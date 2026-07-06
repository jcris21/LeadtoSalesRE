"""Minimal versioned Prompt Registry (Sprint 0). Insert-only versions; the
administration UI over this registry is E12, delivered in Sprint 6."""

import uuid

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.intelligence_ai_admin.infrastructure.db_models import (
    PromptTemplateORM,
    PromptVersionORM,
)
from app.modules.intelligence_ai_admin.infrastructure.repository import PromptRegistryRepository
from app.shared.domain.base import new_id, utcnow


class PromptRegistryService:
    def __init__(self, session: AsyncSession):
        self._session = session
        self._repo = PromptRegistryRepository(session)

    async def publish_version(
        self,
        organization_id: uuid.UUID,
        agent_name: str,
        version: str,
        content: str,
        activate: bool = True,
    ) -> uuid.UUID:
        template = await self._repo.get_template(organization_id, agent_name)
        if template is None:
            template = PromptTemplateORM(
                id=new_id(), organization_id=organization_id, agent_name=agent_name
            )
            await self._repo.add_template(template)
            await self._session.flush()

        if activate:
            await self._repo.deactivate_all_versions(template.id)

        version_id = new_id()
        await self._repo.add_version(
            PromptVersionORM(
                id=version_id,
                prompt_template_id=template.id,
                version=version,
                content=content,
                active=activate,
                created_at=utcnow(),
            )
        )
        await self._session.commit()
        return version_id

    async def get_active_prompt(
        self, organization_id: uuid.UUID, agent_name: str
    ) -> PromptVersionORM:
        """Per-organization active prompt lookup used by every AI agent before invoking the LLM."""
        template = await self._repo.get_template(organization_id, agent_name)
        if template is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No prompt template for agent '{agent_name}' in this organization",
            )
        active = await self._repo.get_active_version(template.id)
        if active is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No active prompt version for agent '{agent_name}'",
            )
        return active
