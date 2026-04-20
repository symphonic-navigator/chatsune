"""Internal domain types for the Premium Provider Accounts module."""
from dataclasses import dataclass, field
from typing import Any

from shared.dtos.providers import Capability


@dataclass(frozen=True)
class PremiumProviderDefinition:
    id: str
    display_name: str
    icon: str
    base_url: str
    capabilities: list[Capability]
    config_fields: list[dict[str, Any]]
    linked_integrations: list[str] = field(default_factory=list)
    secret_fields: frozenset[str] = frozenset({"api_key"})
