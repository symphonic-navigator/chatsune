from datetime import datetime
from enum import StrEnum
from typing import Literal

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
    recent_emojis: list[str] = Field(default_factory=list)


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


# ---------------------------------------------------------------------------
# Per-user key infrastructure — Tasks 9/12/13 will wire these into handlers.
# The *V2Dto suffix is intentional: the plain-name variants already exist
# above and are still consumed by live endpoints. Swapping happens per-task.
# ---------------------------------------------------------------------------


class KdfParamsRequestDto(BaseModel):
    username: str


class Argon2ParamsDto(BaseModel):
    memory_kib: int
    iterations: int
    parallelism: int


class KdfParamsResponseDto(BaseModel):
    kdf_salt: str   # urlsafe-base64
    kdf_params: Argon2ParamsDto
    password_hash_version: int | None = None  # None signals legacy-user path


class LoginRequestV2Dto(BaseModel):
    """New-format login request. Replaces LoginRequestDto once Task 9 rewires the handler."""

    username: str
    h_auth: str     # urlsafe-base64, 32 bytes
    h_kek: str      # urlsafe-base64, 32 bytes


class LoginLegacyRequestDto(BaseModel):
    username: str
    password: str   # plaintext, last time it is accepted — upgrades the row
    h_auth: str
    h_kek: str


class RecoveryRequiredResponseDto(BaseModel):
    status: Literal["recovery_required"] = "recovery_required"


class RecoverDekRequestDto(BaseModel):
    username: str
    h_auth: str
    h_kek: str
    recovery_key: str


class DeclineRecoveryRequestDto(BaseModel):
    username: str


class ChangePasswordRequestV2Dto(BaseModel):
    """New-format change-password request. Replaces ChangePasswordRequestDto once Task 12 rewires the handler."""

    h_auth_old: str
    h_kek_old: str
    h_auth_new: str
    h_kek_new: str


class SetupRequestV2Dto(BaseModel):
    """New-format setup request. Replaces SetupRequestDto once Task 13 rewires the handler."""

    username: str
    email: str
    display_name: str
    pin: str
    h_auth: str
    h_kek: str
    recovery_key: str


class LoginLegacyResponseDto(BaseModel):
    access_token: str
    refresh_token: str | None = None
    expires_in: int
    recovery_key: str   # returned exactly once on migration
