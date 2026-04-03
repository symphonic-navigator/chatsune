from datetime import datetime

from pydantic import BaseModel, EmailStr


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
    display_name: str
    role: str = "user"


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
    about_me: str | None = None
