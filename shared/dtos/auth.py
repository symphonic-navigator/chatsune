from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, EmailStr, Field, field_validator


class Role(StrEnum):
    USER = "user"
    ADMIN = "admin"
    MASTER_ADMIN = "master_admin"


class UserDto(BaseModel):
    id: str
    username: str
    email: str
    display_name: str
    role: str
    is_active: bool
    must_change_password: bool
    created_at: datetime
    updated_at: datetime


class SetupRequestDto(BaseModel):
    pin: str
    username: str
    email: EmailStr
    password: str


class LoginRequestDto(BaseModel):
    username: str
    password: str


class CreateUserRequestDto(BaseModel):
    username: str
    email: EmailStr
    display_name: str = Field(max_length=64)
    role: str = "user"

    @field_validator("display_name")
    @classmethod
    def strip_and_validate_display_name(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("Display name cannot be blank")
        return stripped


class UpdateUserRequestDto(BaseModel):
    display_name: str | None = None
    email: EmailStr | None = None
    is_active: bool | None = None
    role: str | None = None


class ChangePasswordRequestDto(BaseModel):
    current_password: str
    new_password: str


class TokenResponseDto(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class SetupResponseDto(BaseModel):
    user: UserDto
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class CreateUserResponseDto(BaseModel):
    user: UserDto
    generated_password: str


class ResetPasswordResponseDto(BaseModel):
    user: UserDto
    generated_password: str


class AuditLogEntryDto(BaseModel):
    id: str
    timestamp: datetime
    actor_id: str
    action: str
    resource_type: str
    resource_id: str | None = None
    detail: dict | None = None


class UpdateAboutMeDto(BaseModel):
    about_me: str | None = Field(default=None, max_length=4000)


class UpdateDisplayNameDto(BaseModel):
    display_name: str = Field(..., max_length=64)

    @field_validator("display_name")
    @classmethod
    def strip_and_validate(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("Display name cannot be blank")
        return stripped
