import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.auth.schemas import LoginRequest, RegisterAdminRequest, TokenResponse
from app.modules.auth.service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", status_code=201)
async def register_admin(
    request: RegisterAdminRequest, session: AsyncSession = Depends(get_db_session)
) -> dict[str, uuid.UUID]:
    service = AuthService(session)
    user_id = await service.register_admin(request)
    return {"user_id": user_id}


@router.post("/login", response_model=TokenResponse)
async def login(
    request: LoginRequest, session: AsyncSession = Depends(get_db_session)
) -> TokenResponse:
    service = AuthService(session)
    return await service.login(request)
