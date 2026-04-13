"""Integrations module — plugin-based local service integrations.

Public API: import only from this file.
"""

from backend.modules.integrations._handlers import router
from backend.modules.integrations._registry import (
    get as get_integration,
    get_all as get_all_integrations,
)
from backend.modules.integrations._repository import IntegrationRepository
from shared.dtos.inference import ToolDefinition


async def init_indexes(db) -> None:
    """Create MongoDB indexes for the integrations module."""
    repo = IntegrationRepository(db)
    await repo.init_indexes()


async def get_enabled_integration_ids(user_id: str, persona_id: str | None = None) -> list[str]:
    """Return integration IDs that are enabled for a user (and optionally filtered by persona)."""
    from backend.database import get_db
    repo = IntegrationRepository(get_db())
    configs = await repo.get_user_configs(user_id)
    enabled = [c["integration_id"] for c in configs if c.get("enabled")]

    if persona_id is not None:
        from backend.modules.persona import get_persona
        persona = await get_persona(persona_id, user_id)
        if persona:
            persona_integrations = (persona.get("integrations_config") or {}).get(
                "enabled_integration_ids", []
            )
            if persona_integrations:
                enabled = [eid for eid in enabled if eid in persona_integrations]
            else:
                enabled = []

    return enabled


async def get_integration_tools(
    user_id: str,
    persona_id: str | None = None,
) -> list[ToolDefinition]:
    """Return tool definitions for all integrations enabled for this user+persona."""
    enabled_ids = await get_enabled_integration_ids(user_id, persona_id)
    tools: list[ToolDefinition] = []
    for iid in enabled_ids:
        defn = get_integration(iid)
        if defn and defn.tool_definitions:
            tools.extend(defn.tool_definitions)
    return tools


async def get_integration_prompt_extensions(
    user_id: str,
    persona_id: str | None = None,
) -> str | None:
    """Return combined system prompt extension for all active integrations."""
    enabled_ids = await get_enabled_integration_ids(user_id, persona_id)
    parts: list[str] = []
    for iid in enabled_ids:
        defn = get_integration(iid)
        if defn and defn.system_prompt_template:
            parts.append(defn.system_prompt_template)
    return "\n\n".join(parts) if parts else None


__all__ = [
    "router",
    "init_indexes",
    "get_integration",
    "get_all_integrations",
    "get_enabled_integration_ids",
    "get_integration_tools",
    "get_integration_prompt_extensions",
]
