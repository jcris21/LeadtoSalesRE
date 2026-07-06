import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.intelligence_ai_admin.infrastructure.db_models import (
    AIDecisionTraceORM,
    PromptTemplateORM,
    PromptVersionORM,
)


class PromptRegistryRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_template(
        self, organization_id: uuid.UUID, agent_name: str
    ) -> PromptTemplateORM | None:
        result = await self._session.execute(
            select(PromptTemplateORM).where(
                PromptTemplateORM.organization_id == organization_id,
                PromptTemplateORM.agent_name == agent_name,
            )
        )
        return result.scalar_one_or_none()

    async def add_template(self, template: PromptTemplateORM) -> None:
        self._session.add(template)

    async def get_active_version(self, prompt_template_id: uuid.UUID) -> PromptVersionORM | None:
        result = await self._session.execute(
            select(PromptVersionORM).where(
                PromptVersionORM.prompt_template_id == prompt_template_id,
                PromptVersionORM.active.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def deactivate_all_versions(self, prompt_template_id: uuid.UUID) -> None:
        await self._session.execute(
            update(PromptVersionORM)
            .where(PromptVersionORM.prompt_template_id == prompt_template_id)
            .values(active=False)
        )

    async def add_version(self, version: PromptVersionORM) -> None:
        self._session.add(version)


class AIDecisionTraceRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def add(self, trace: AIDecisionTraceORM) -> None:
        self._session.add(trace)
