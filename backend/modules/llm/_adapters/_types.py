"""Internal types passed into adapters by the generic connection resolver."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ResolvedConnection:
    """Plain + decrypted config for adapter use. Never persist this."""
    id: str
    user_id: str
    adapter_type: str
    display_name: str
    slug: str
    config: dict  # merged plain + decrypted secrets
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class AdapterTemplate:
    """UX preset shown in the add-connection wizard."""
    id: str
    display_name: str
    slug_prefix: str
    config_defaults: dict


@dataclass(frozen=True)
class ConfigFieldHint:
    """Lightweight form-rendering hint. Not a full schema engine."""
    name: str
    type: str          # "string" | "url" | "secret" | "integer"
    label: str
    required: bool = True
    min: int | None = None
    max: int | None = None
    placeholder: str | None = None
