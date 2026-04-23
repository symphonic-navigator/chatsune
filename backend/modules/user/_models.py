from datetime import datetime

from pydantic import BaseModel, Field


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
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

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
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    actor_id: str
    action: str
    resource_type: str
    resource_id: str | None = None
    detail: dict | None = None

    model_config = {"populate_by_name": True}
