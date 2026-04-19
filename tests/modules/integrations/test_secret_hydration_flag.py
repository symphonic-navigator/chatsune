"""Hydration skip when hydrate_secrets=False."""
import pytest
from unittest.mock import AsyncMock

from backend.modules.integrations import emit_integration_secrets_for_user
from backend.modules.integrations._models import IntegrationDefinition
from backend.modules.integrations import _registry as integration_registry
from shared.dtos.integrations import IntegrationCapability


@pytest.mark.asyncio
async def test_skips_integrations_with_hydrate_secrets_false(monkeypatch):
    """Integrations with hydrate_secrets=False must not trigger a hydration event."""
    defn = IntegrationDefinition(
        id="_test_no_hydrate",
        display_name="Test",
        description="",
        icon="",
        execution_mode="hybrid",
        config_fields=[{"key": "api_key", "field_type": "password", "secret": True}],
        capabilities=[IntegrationCapability.TTS_PROVIDER],
        hydrate_secrets=False,
    )
    monkeypatch.setitem(integration_registry._registry, "_test_no_hydrate", defn)

    class FakeRepo:
        async def list_enabled_with_secrets(self, user_id):
            return [("_test_no_hydrate", {"api_key": "secret"})]

    # IntegrationRepository is imported at the top of backend.modules.integrations,
    # so monkeypatching that module's attribute is sufficient.
    monkeypatch.setattr(
        "backend.modules.integrations.IntegrationRepository",
        lambda *_a, **_kw: FakeRepo(),
    )

    event_bus = AsyncMock()
    await emit_integration_secrets_for_user(
        user_id="u1", db=object(), event_bus=event_bus,
    )

    event_bus.publish.assert_not_called()


@pytest.mark.asyncio
async def test_emits_when_hydrate_secrets_true(monkeypatch):
    """Integrations with hydrate_secrets=True (default) must emit a hydration event."""
    defn = IntegrationDefinition(
        id="_test_hydrate",
        display_name="Test",
        description="",
        icon="",
        execution_mode="hybrid",
        config_fields=[{"key": "api_key", "field_type": "password", "secret": True}],
        capabilities=[IntegrationCapability.TTS_PROVIDER],
        hydrate_secrets=True,
    )
    monkeypatch.setitem(integration_registry._registry, "_test_hydrate", defn)

    class FakeRepo:
        async def list_enabled_with_secrets(self, user_id):
            return [("_test_hydrate", {"api_key": "secret"})]

    monkeypatch.setattr(
        "backend.modules.integrations.IntegrationRepository",
        lambda *_a, **_kw: FakeRepo(),
    )

    event_bus = AsyncMock()
    await emit_integration_secrets_for_user(
        user_id="u1", db=object(), event_bus=event_bus,
    )

    event_bus.publish.assert_called_once()
