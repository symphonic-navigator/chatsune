"""Voice adapters must resolve their per-user API key via PremiumProviderService."""

import pytest

from backend.modules.integrations._voice_adapters import _xai as xai_mod
from backend.modules.integrations._voice_adapters._xai import XaiVoiceAdapter
from backend.modules.providers._repository import PremiumProviderAccountRepository


@pytest.mark.asyncio
async def test_xai_adapter_resolves_key_via_premium_service(monkeypatch, mock_db):
    repo = PremiumProviderAccountRepository(mock_db)
    await repo.upsert("user-1", "xai", {"api_key": "xai-test-key"})

    # The adapter reads the db via a module-level ``get_db`` import so tests
    # can swap it. Route it to the test database for this call.
    monkeypatch.setattr(xai_mod, "get_db", lambda: mock_db)

    adapter = XaiVoiceAdapter(http=None)
    key = await adapter._resolve_user_key("user-1")
    assert key == "xai-test-key"


@pytest.mark.asyncio
async def test_xai_adapter_raises_when_premium_account_missing(monkeypatch, mock_db):
    monkeypatch.setattr(xai_mod, "get_db", lambda: mock_db)
    adapter = XaiVoiceAdapter(http=None)
    with pytest.raises(LookupError):
        await adapter._resolve_user_key("fresh-user")
