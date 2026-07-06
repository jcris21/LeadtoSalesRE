import uuid

from pydantic import BaseModel, EmailStr


class RegisterAdminRequest(BaseModel):
    organization_id: uuid.UUID
    email: EmailStr
    password: str
    role: str = "admin"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
