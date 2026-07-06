"""Repository translating between the Organization domain model and its ORM rows."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.organization.domain.models import (
    ChatwootConfig,
    CrmConfig,
    GoogleWorkspaceConfig,
    Organization,
    OrganizationConfig,
    OrgStatus,
    WhatsappBusinessConfig,
)
from app.modules.organization.infrastructure.db_models import OrganizationConfigORM, OrganizationORM
from app.shared.domain.base import utcnow


class OrganizationRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def add(self, org: Organization) -> None:
        self._session.add(
            OrganizationORM(
                id=org.id, name=org.name, status=org.status.value, created_at=org.created_at
            )
        )

    async def get(self, organization_id: uuid.UUID) -> Organization | None:
        row = await self._session.get(OrganizationORM, organization_id)
        if row is None:
            return None
        return Organization(name=row.name, id=row.id, status=OrgStatus(row.status))

    async def list_all(self) -> list[Organization]:
        result = await self._session.execute(select(OrganizationORM))
        return [
            Organization(name=r.name, id=r.id, status=OrgStatus(r.status))
            for r in result.scalars().all()
        ]

    async def save_status(self, org: Organization) -> None:
        row = await self._session.get(OrganizationORM, org.id)
        if row is not None:
            row.status = org.status.value


class OrganizationConfigRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get(self, organization_id: uuid.UUID) -> OrganizationConfig | None:
        row = await self._session.get(OrganizationConfigORM, organization_id)
        if row is None:
            return None
        return OrganizationConfig(
            organization_id=row.organization_id,
            chatwoot=ChatwootConfig(**row.chatwoot_config) if row.chatwoot_config else None,
            whatsapp=WhatsappBusinessConfig(**row.whatsapp_config) if row.whatsapp_config else None,
            crm=CrmConfig(**row.crm_config) if row.crm_config else None,
            google_workspace=(
                GoogleWorkspaceConfig(**row.google_workspace_config)
                if row.google_workspace_config
                else None
            ),
            updated_at=row.updated_at,
        )

    async def upsert(self, config: OrganizationConfig) -> None:
        row = await self._session.get(OrganizationConfigORM, config.organization_id)
        payload = dict(
            chatwoot_config=vars(config.chatwoot) if config.chatwoot else None,
            whatsapp_config=vars(config.whatsapp) if config.whatsapp else None,
            crm_config=vars(config.crm) if config.crm else None,
            google_workspace_config=vars(config.google_workspace)
            if config.google_workspace
            else None,
            updated_at=utcnow(),
        )
        if row is None:
            self._session.add(
                OrganizationConfigORM(organization_id=config.organization_id, **payload)
            )
        else:
            for key, value in payload.items():
                setattr(row, key, value)
