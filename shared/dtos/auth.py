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


class DeleteAccountRequestDto(BaseModel):
    """Body of ``DELETE /api/users/me``.

    ``confirm_username`` must match the authenticated user's current
    username character-for-character. This stops an accidental delete
    triggered by a pre-focused button or an attacker with a stolen
    short-lived access token who doesn't know the victim's username.
    """

    confirm_username: str


class DeleteAccountResponseDto(BaseModel):
    """Response of a successful self-delete request.

    ``slug`` points to the Redis-backed deletion report; the frontend
    redirects to a public confirmation page that fetches the report via
    ``GET /api/auth/deletion-report/{slug}``. ``success`` reflects
    whether the user document itself was removed (matches the report's
    own ``success`` field).
    """

    slug: str
    success: bool
