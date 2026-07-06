import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.organization.infrastructure.db_models import AdminUserORM


class AdminUserRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_email(self, email: str) -> AdminUserORM | None:
        result = await self._session.execute(
            select(AdminUserORM).where(AdminUserORM.email == email)
        )
        return result.scalar_one_or_none()

    async def add(self, user: AdminUserORM) -> None:
        self._session.add(user)

    async def get(self, user_id: uuid.UUID) -> AdminUserORM | None:
        return await self._session.get(AdminUserORM, user_id)
