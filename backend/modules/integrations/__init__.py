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
from backend.modules.integrations._voice_expression_tags import (
    INLINE_TAGS as VOICE_EXPRESSION_INLINE_TAGS,
    WRAPPING_TAGS as VOICE_EXPRESSION_WRAPPING_TAGS,
    build_system_prompt_extension as build_voice_expression_prompt_extension,
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


async def effective_enabled_map(user_id: str) -> dict[str, bool]:
    """Return ``{integration_id: enabled}`` applying premium-link semantics.

    For integrations with ``linked_premium_provider`` set, "enabled" means
    the user has a matching Premium Provider Account — the stored per-user
    ``enabled`` flag is ignored (there is no UI to toggle it independently
    from the account, and a linked integration is useless without the
    account). For unlinked integrations (e.g. ``lovense``) the per-user
    config's ``enabled`` flag is respected as before.
    """
    from backend.database import get_db
    from backend.modules.integrations._registry import get_all as _get_all
    from backend.modules.providers import PremiumProviderService
    from backend.modules.providers._repository import (
        PremiumProviderAccountRepository,
    )

    definitions = _get_all()
    repo = IntegrationRepository(get_db())
    configs = await repo.get_user_configs(user_id)
    cfg_map = {c["integration_id"]: c for c in configs}

    providers = PremiumProviderService(
        PremiumProviderAccountRepository(get_db()),
    )

    result: dict[str, bool] = {}
    for iid, defn in definitions.items():
        if defn.linked_premium_provider:
            result[iid] = await providers.has_account(
                user_id, defn.linked_premium_provider,
            )
        else:
            cfg = cfg_map.get(iid)
            if cfg is None:
                # No explicit config doc — fall back to the integration's
                # default. This makes "default-on" a code property, not
                # something we have to backfill into the database.
                result[iid] = defn.default_enabled
            else:
                # Explicit user choice always wins (True or False).
                result[iid] = bool(cfg.get("enabled", False))
    return result


async def is_effective_enabled(user_id: str, integration_id: str) -> bool:
    """Convenience wrapper around ``effective_enabled_map``."""
    m = await effective_enabled_map(user_id)
    return m.get(integration_id, False)


async def get_enabled_integration_ids(user_id: str, persona_id: str | None = None) -> list[str]:
    """Return integration IDs that are enabled for a user (and optionally filtered by persona).

    The per-persona allowlist (``integrations_config.enabled_integration_ids``)
    only filters integrations whose definition has ``assignable=True``.
    Non-assignable integrations (e.g. voice providers) stay active whenever
    user-enabled, irrespective of the persona's allowlist — this preserves
    TTS / prompt-extension behaviour for legacy personas that have never
    opted in explicitly. Assignable integrations are strict: missing or
    empty allowlist means excluded, by design.
    """
    effective = await effective_enabled_map(user_id)
    enabled = [iid for iid, on in effective.items() if on]

    if persona_id is None:
        return enabled

    from backend.modules.persona import get_persona
    persona = await get_persona(persona_id, user_id)
    if not persona:
        return enabled

    integrations_config = persona.get("integrations_config") or {}
    explicit_ids = set(integrations_config.get("enabled_integration_ids") or [])
    definitions = get_all_integrations()

    result: list[str] = []
    for iid in enabled:
        defn = definitions.get(iid)
        if defn and defn.assignable:
            # Strict opt-in: must be explicitly listed by the persona.
            if iid in explicit_ids:
                result.append(iid)
        else:
            # Non-assignable: always active when user-enabled.
            result.append(iid)
    return result


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
    db=None,
    event_bus,
) -> None:
    """Emit one hydrated event per enabled integration that has secret fields."""
    if db is None:
        from backend.database import get_db
        db = get_db()
    repo = IntegrationRepository(db)
    items = await repo.list_enabled_with_secrets(user_id)
    for integration_id, secrets in items:
        defn = get_integration(integration_id)
        if defn is None or not defn.hydrate_secrets:
            continue
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
    "effective_enabled_map",
    "is_effective_enabled",
    "get_enabled_integration_ids",
    "get_integration_tools",
    "get_integration_prompt_extensions",
    "emit_integration_secrets_for_user",
    "emit_integration_secrets_cleared",
    "delete_all_for_user",
    "VOICE_EXPRESSION_INLINE_TAGS",
    "VOICE_EXPRESSION_WRAPPING_TAGS",
    "build_voice_expression_prompt_extension",
]
