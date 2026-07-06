"""Application service: orchestrates the Organization aggregate, its repository
and the transactional outbox publish — the only place that should call both."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.organization.domain.models import Organization, OrganizationConfig
from app.modules.organization.infrastructure.repository import (
    OrganizationConfigRepository,
    OrganizationRepository,
)
from app.shared.infrastructure.event_bus import publish


class OrganizationService:
    def __init__(self, session: AsyncSession):
        self._session = session
        self._orgs = OrganizationRepository(session)
        self._configs = OrganizationConfigRepository(session)

    async def create_organization(self, name: str) -> Organization:
        org = Organization.create(name)
        await self._orgs.add(org)
        await publish(self._session, org.pull_domain_events())
        await self._session.commit()
        return org

    async def get_organization(self, organization_id: uuid.UUID) -> Organization | None:
        return await self._orgs.get(organization_id)

    async def list_organizations(self) -> list[Organization]:
        return await self._orgs.list_all()

    async def get_config(self, organization_id: uuid.UUID) -> OrganizationConfig | None:
        return await self._configs.get(organization_id)

    async def upsert_config(self, config: OrganizationConfig) -> OrganizationConfig:
        await self._configs.upsert(config)
        org = await self._orgs.get(config.organization_id)
        if org is not None and config.is_complete_for_activation():
            org.activate()
            await self._orgs.save_status(org)
        await self._session.commit()
        return config
