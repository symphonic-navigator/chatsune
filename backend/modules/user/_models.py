from datetime import datetime, timezone

from bson import ObjectId
from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

DEFAULT_RECENT_EMOJIS: tuple[str, ...] = ("👍", "❤️", "😂", "🤘", "😊", "🔥")
RECENT_EMOJIS_MAX: int = 6


class UserDocument(BaseModel):
    """Internal MongoDB document model for users. Never expose outside the user module."""

    id: str = Field(alias="_id")
    username: str
    email: str
    display_name: str
    password_hash: str
    password_hash_version: int | None = None
    role: str  # "master_admin" | "admin" | "user"
    is_active: bool = True
    must_change_password: bool = False
    recent_emojis: list[str] = Field(default_factory=lambda: list(DEFAULT_RECENT_EMOJIS))
    # Mindspace: separate LRU for the project emoji-picker. Distinct
    # from ``recent_emojis`` (which seeds with chat-message defaults)
    # so the two pickers never bleed into each other. Defaults to
    # empty — pre-Mindspace users have no project history yet.
    recent_project_emojis: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    model_config = {"populate_by_name": True}


class Argon2Params(BaseModel):
    memory_kib: int = 65536
    iterations: int = 3
    parallelism: int = 4


class WrappedDekPair(BaseModel):
    wrapped_by_password: bytes
    wrapped_by_recovery: bytes
    created_at: datetime


class UserKeysDocument(BaseModel):
    """Per-user key material and KDF parameters (collection: ``user_keys``).

    One document per user. ``deks`` is keyed by stringified version so the
    DEK can be rotated without migrating the field shape: each new rotation
    simply adds another entry and bumps ``current_dek_version``.
    """

    user_id: str
    kdf_salt: bytes = Field(..., min_length=32, max_length=32)
    kdf_params: Argon2Params = Field(default_factory=Argon2Params)
    current_dek_version: int = 1
    deks: dict[str, WrappedDekPair]
    dek_recovery_required: bool = False
    created_at: datetime
    updated_at: datetime


class AuditLogDocument(BaseModel):
    """Internal MongoDB document model for audit log entries."""

    id: str = Field(alias="_id")
    timestamp: datetime = Field(default_factory=_utcnow)
    actor_id: str
    action: str
    resource_type: str
    resource_id: str | None = None
    detail: dict | None = None

    model_config = {"populate_by_name": True}


class InvitationTokenDocument(BaseModel):
    """One-time admin-generated link that lets a new user self-register.

    The token field is a URL-safe random string (~43 chars) generated via
    ``secrets.token_urlsafe(32)``. The ``expires_at`` field drives MongoDB TTL
    cleanup.
    """

    model_config = {"arbitrary_types_allowed": True, "populate_by_name": True}

    id: ObjectId = Field(alias="_id")
    token: str
    created_at: datetime
    expires_at: datetime
    used: bool = False
    used_at: datetime | None = None
    used_by_user_id: str | None = None
    created_by: str
