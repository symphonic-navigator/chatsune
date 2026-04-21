"""Tests for effective_enabled_map — linked integrations derive from Premium accounts."""

import pytest

from backend.modules.integrations import _handlers as integrations_handlers_mod
from backend.modules.integrations._repository import IntegrationRepository
from backend.modules.providers._repository import PremiumProviderAccountRepository


@pytest.fixture(autouse=True)
def _patch_get_db(monkeypatch, mock_db):
    """Route the integrations module-level ``get_db`` to the test database."""
    # effective_enabled_map imports get_db locally — we patch every module
    # that touches the db in this code path.
    monkeypatch.setattr(integrations_handlers_mod, "get_db", lambda: mock_db)
    # Also patch the underlying backend.database.get_db for deferred imports
    # inside the function body.
    import backend.database as database_mod
    monkeypatch.setattr(database_mod, "get_db", lambda: mock_db)


@pytest.mark.asyncio
async def test_linked_integration_enabled_when_premium_account_exists(mock_db):
    repo = PremiumProviderAccountRepository(mock_db)
    await repo.upsert("u-xai", "xai", {"api_key": "k"})

    from backend.modules.integrations import effective_enabled_map
    m = await effective_enabled_map("u-xai")
    assert m["xai_voice"] is True


@pytest.mark.asyncio
async def test_linked_integration_disabled_when_no_premium_account(mock_db):
    from backend.modules.integrations import effective_enabled_map
    m = await effective_enabled_map("fresh-user")
    assert m["xai_voice"] is False
    assert m["mistral_voice"] is False


@pytest.mark.asyncio
async def test_unlinked_integration_follows_explicit_enabled(mock_db):
    repo = IntegrationRepository(mock_db)
    await repo.upsert_config(
        user_id="u-lov", integration_id="lovense", enabled=True,
        config={"ip": "192.168.0.1"},
    )

    from backend.modules.integrations import effective_enabled_map
    m = await effective_enabled_map("u-lov")
    assert m["lovense"] is True


@pytest.mark.asyncio
async def test_unlinked_integration_disabled_by_default(mock_db):
    from backend.modules.integrations import effective_enabled_map
    m = await effective_enabled_map("fresh-user")
    assert m["lovense"] is False


@pytest.mark.asyncio
async def test_list_user_configs_synthesises_entry_for_linked_integration(mock_db):
    """The ``/api/integrations/configs`` handler must include a synthetic
    entry for linked integrations that have an active Premium Provider
    Account but no ``user_integration_configs`` document.

    Without the synthetic entry, the frontend store never sees
    ``configs[xai_voice]`` and voice-provider dropdowns filter it out
    even though xAI is effectively enabled.
    """
    # Create a Premium xAI account but NO integration config document.
    repo = PremiumProviderAccountRepository(mock_db)
    await repo.upsert("u-xai", "xai", {"api_key": "k"})

    result = await integrations_handlers_mod.list_user_configs(user={"sub": "u-xai"})

    by_id = {c.integration_id: c for c in result}
    assert "xai_voice" in by_id, (
        "xai_voice missing from /configs response — frontend store would "
        "not see the integration at all"
    )
    xai_entry = by_id["xai_voice"]
    assert xai_entry.effective_enabled is True
    # Synthetic entry has no stored doc — stored enabled is False, config is empty.
    assert xai_entry.enabled is False
    assert xai_entry.config == {}
