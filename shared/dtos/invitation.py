"""DTOs for one-time invitation-link self-registration."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class CreateInvitationResponseDto(BaseModel):
    """Returned to admins after they generate a fresh invitation link.

    The URL itself is built client-side from ``window.location.origin`` so
    the backend does not need to know its public hostname.
    """

    token: str
    expires_at: datetime


class ValidateInvitationResponseDto(BaseModel):
    """Public response from POST /api/invitations/{token}/validate.

    The HTTP status is always 200 — the reason lives in the body to prevent
    enumeration via response codes.
    """

    valid: bool
    reason: Literal["expired", "used", "not_found"] | None = None


class RegisterViaInvitationRequestDto(BaseModel):
    """Submitted by the unauthenticated user during self-registration."""

    username: str = Field(min_length=3, max_length=64)
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=128)
    h_auth: str        # client-derived Argon2 hash, urlsafe-base64
    h_kek: str         # client-derived KEK, urlsafe-base64
    recovery_key: str  # client-generated; backend wraps DEK with this


class RegisterViaInvitationResponseDto(BaseModel):
    success: bool
    user_id: str
