"""JWT bearer auth + password hashing for the admin API (Sprint 0 "Authentication").

Scope: authenticates human admin/broker users against AdminUser records. It does
NOT implement RBAC beyond a single `role` claim — the fuller RBAC + audit log
required by QA-08 (CRM data protection) lands with E7/E12, this is the minimum
viable gate to protect the Sprint 0 admin endpoints.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel

from app.core.config import get_settings

_bearer_scheme = HTTPBearer(auto_error=False)

# Using the `bcrypt` package directly rather than passlib's CryptContext:
# passlib 1.7.x's bcrypt backend-detection probe breaks against bcrypt>=4.1
# (misreads its own 72-byte test string as an over-length password). passlib
# is unmaintained upstream with no fix; bcrypt's own API is the safer choice.
_BCRYPT_MAX_BYTES = 72


class AuthenticatedPrincipal(BaseModel):
    user_id: uuid.UUID
    organization_id: uuid.UUID
    email: str
    role: str


def hash_password(password: str) -> str:
    truncated = password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(truncated, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    truncated = plain.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    return bcrypt.checkpw(truncated, hashed.encode("utf-8"))


def create_access_token(principal: AuthenticatedPrincipal) -> str:
    settings = get_settings()
    expire = datetime.now(UTC) + timedelta(minutes=settings.jwt_expires_minutes)
    payload = {
        "sub": str(principal.user_id),
        "org": str(principal.organization_id),
        "email": principal.email,
        "role": principal.role,
        "exp": expire,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> AuthenticatedPrincipal:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        ) from exc
    return AuthenticatedPrincipal(
        user_id=uuid.UUID(payload["sub"]),
        organization_id=uuid.UUID(payload["org"]),
        email=payload["email"],
        role=payload["role"],
    )


async def get_current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> AuthenticatedPrincipal:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    return decode_access_token(credentials.credentials)
