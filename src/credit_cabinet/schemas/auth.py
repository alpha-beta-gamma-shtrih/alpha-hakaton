from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, field_validator

from credit_cabinet.models.enums import Role


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    password: SecretStr = Field(min_length=1, max_length=1024)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value):
        return value.strip().lower() if isinstance(value, str) else value


class UserResponse(BaseModel):
    id: UUID
    email: str
    display_name: str
    role: Role
    # Context is read-only here; later actions must validate every referenced resource.
    ui_context: dict


class SessionResponse(BaseModel):
    user: UserResponse
    absolute_expires_at: datetime
    idle_expires_at: datetime


class CSRFResponse(BaseModel):
    csrf_token: str
