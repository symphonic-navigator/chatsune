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
