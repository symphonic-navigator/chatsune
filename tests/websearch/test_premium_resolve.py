"""Websearch resolves API keys through the Premium Provider service.

After Task 13, ``backend.modules.websearch.search`` / ``fetch`` must look up
credentials via :class:`PremiumProviderService` instead of the legacy
``websearch_user_credentials`` collection. The provider id
``ollama_cloud_search`` maps to premium provider ``ollama_cloud``.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.modules.providers._repository import (
    PremiumProviderAccountRepository,
)


@pytest.fixture
async def user_with_ollama_cloud_premium(mock_db, monkeypatch):
    """Seed a premium Ollama Cloud account and patch websearch's get_db."""
    import backend.modules.websearch as websearch_mod

    monkeypatch.setattr(websearch_mod, "get_db", lambda: mock_db)

    repo = PremiumProviderAccountRepository(mock_db)
    await repo.create_indexes()
    await repo.upsert("user-oc", "ollama_cloud", {"api_key": "ollama-cloud-key"})
    return "user-oc"


async def test_search_uses_premium_account_key(
    user_with_ollama_cloud_premium, mock_db,
):
    from backend.modules.websearch import search

    captured: dict[str, object] = {}

    async def fake_search(self, api_key, query, max_results):
        captured["api_key"] = api_key
        captured["query"] = query
        captured["max_results"] = max_results
        return []

    with patch(
        "backend.modules.websearch._adapters._ollama_cloud.OllamaCloudSearchAdapter.search",
        new=fake_search,
    ):
        await search(
            user_with_ollama_cloud_premium, "ollama_cloud_search", "q", 5,
        )

    assert captured["api_key"] == "ollama-cloud-key"
    assert captured["query"] == "q"


async def test_search_raises_when_no_premium_account(mock_db, monkeypatch):
    import backend.modules.websearch as websearch_mod

    monkeypatch.setattr(websearch_mod, "get_db", lambda: mock_db)

    from backend.modules.websearch import (
        WebSearchCredentialNotFoundError,
        search,
    )

    with pytest.raises(WebSearchCredentialNotFoundError):
        await search("fresh-user", "ollama_cloud_search", "q", 5)
