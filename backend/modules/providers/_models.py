"""Internal domain types for the Premium Provider Accounts module."""
from dataclasses import dataclass, field
from typing import Any, Literal

from shared.dtos.providers import Capability


@dataclass(frozen=True)
class PremiumProviderDefinition:
    id: str
    display_name: str
    icon: str
    base_url: str
    capabilities: list[Capability]
    config_fields: list[dict[str, Any]]
    probe_url: str
    probe_method: Literal["GET", "POST"] = "GET"
    linked_integrations: list[str] = field(default_factory=list)
    secret_fields: frozenset[str] = frozenset({"api_key"})
    # Lower value = earlier in the catalogue list. Ties break by
    # registration order (Python dicts preserve insertion order, and
    # ``sorted`` is stable). Default 100 keeps unspecified providers
    # at the tail of the list.
    sort_priority: int = 100
