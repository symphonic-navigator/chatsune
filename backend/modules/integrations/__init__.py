"""Integrations module — plugin-based local service integrations.

Public API: import only from this file.
"""

import logging
from datetime import datetime, timezone
from uuid import uuid4

from backend.modules.integrations._handlers import router
from backend.modules.integrations._registry import (
    get as get_integration,
    get_all as get_all_integrations,
)
from backend.modules.integrations._repository import IntegrationRepository
from shared.dtos.inference import ToolDefinition
from shared.events.integrations import (
    IntegrationSecretsClearedEvent,
    IntegrationSecretsHydratedEvent,
)
from shared.topics import Topics

_log = logging.getLogger(__name__)


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
            integrations_config = persona.get("integrations_config")
            if integrations_config and integrations_config.get("enabled_integration_ids"):
                # Persona has explicit integration config — filter to only those
                persona_integrations = set(integrations_config["enabled_integration_ids"])
                enabled = [eid for eid in enabled if eid in persona_integrations]
            # No integrations_config or empty list = all user-enabled integrations are active

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


async def emit_integration_secrets_for_user(
    *,
    user_id: str,
    repo: IntegrationRepository,
    event_bus,
) -> None:
    """Emit one hydrated event per enabled integration that has secret fields."""
    for integration_id, secrets in await repo.list_enabled_with_secrets(user_id):
        event = IntegrationSecretsHydratedEvent(
            integration_id=integration_id,
            secrets=secrets,
            correlation_id=str(uuid4()),
            timestamp=datetime.now(timezone.utc),
        )
        await event_bus.publish(
            topic=Topics.INTEGRATION_SECRETS_HYDRATED,
            event=event,
            target_user_ids=[user_id],
        )


async def emit_integration_secrets_cleared(
    *,
    user_id: str,
    integration_id: str,
    event_bus,
) -> None:
    """Emit a secrets-cleared event so the frontend drops cached secrets."""
    event = IntegrationSecretsClearedEvent(
        integration_id=integration_id,
        correlation_id=str(uuid4()),
        timestamp=datetime.now(timezone.utc),
    )
    await event_bus.publish(
        topic=Topics.INTEGRATION_SECRETS_CLEARED,
        event=event,
        target_user_ids=[user_id],
    )


async def delete_all_for_user(user_id: str) -> int:
    """Delete every integration config owned by ``user_id``.

    Called by the user self-delete (right-to-be-forgotten) cascade.
    """
    from backend.database import get_db
    repo = IntegrationRepository(get_db())
    count = await repo.delete_all_for_user(user_id)
    _log.info(
        "integrations.delete_all_for_user user_id=%s deleted=%d",
        user_id, count,
    )
    return count


__all__ = [
    "router",
    "init_indexes",
    "get_integration",
    "get_all_integrations",
    "get_enabled_integration_ids",
    "get_integration_tools",
    "get_integration_prompt_extensions",
    "emit_integration_secrets_for_user",
    "emit_integration_secrets_cleared",
    "delete_all_for_user",
]
