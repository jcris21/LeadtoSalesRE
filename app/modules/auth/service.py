import uuid

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    AuthenticatedPrincipal,
    create_access_token,
    hash_password,
    verify_password,
)
from app.modules.auth.repository import AdminUserRepository
from app.modules.auth.schemas import LoginRequest, RegisterAdminRequest, TokenResponse
from app.modules.organization.infrastructure.db_models import AdminUserORM
from app.shared.domain.base import new_id, utcnow


class AuthService:
    def __init__(self, session: AsyncSession):
        self._session = session
        self._users = AdminUserRepository(session)

    async def register_admin(self, request: RegisterAdminRequest) -> uuid.UUID:
        existing = await self._users.get_by_email(request.email)
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
            )
        user_id = new_id()
        await self._users.add(
            AdminUserORM(
                id=user_id,
                organization_id=request.organization_id,
                email=request.email,
                hashed_password=hash_password(request.password),
                role=request.role,
                is_active=True,
                created_at=utcnow(),
            )
        )
        await self._session.commit()
        return user_id

    async def login(self, request: LoginRequest) -> TokenResponse:
        user = await self._users.get_by_email(request.email)
        if (
            user is None
            or not user.is_active
            or not verify_password(request.password, user.hashed_password)
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
            )
        token = create_access_token(
            AuthenticatedPrincipal(
                user_id=user.id,
                organization_id=user.organization_id,
                email=user.email,
                role=user.role,
            )
        )
        return TokenResponse(access_token=token)
