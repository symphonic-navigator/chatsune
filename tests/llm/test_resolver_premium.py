"""Premium Provider dispatch in the LLM resolver.

When ``model_unique_id`` begins with a reserved Premium Provider slug
(``xai``, ``mistral``, ``ollama_cloud``), :func:`resolve_for_model` must
route credential lookup through ``PremiumProviderService`` and synthesise
a :class:`ResolvedConnection` carrying the registry-fixed ``base_url``
and the user's decrypted ``api_key``. For any other slug, the function
falls back to the per-user Connection repository unchanged.
"""

import pytest

from backend.modules.llm import (
    LlmConnectionNotFoundError,
    _resolver as resolver_mod,
)
from backend.modules.llm._connections import ConnectionRepository
from backend.modules.llm._resolver import resolve_for_model
from backend.modules.providers._repository import (
    PremiumProviderAccountRepository,
)


@pytest.fixture
async def premium_db(mock_db, monkeypatch):
    """mock_db + premium_provider_accounts isolation + get_db patch."""
    await mock_db["premium_provider_accounts"].drop()
    monkeypatch.setattr(resolver_mod, "get_db", lambda: mock_db)
    yield mock_db
    await mock_db["premium_provider_accounts"].drop()


@pytest.fixture
async def user_with_xai_account(premium_db):
    repo = PremiumProviderAccountRepository(premium_db)
    await repo.create_indexes()
    await repo.upsert("user-xai", "xai", {"api_key": "xai-abc"})
    return "user-xai"


@pytest.fixture
async def user_with_ollama_cloud(premium_db):
    repo = PremiumProviderAccountRepository(premium_db)
    await repo.create_indexes()
    await repo.upsert("user-oc", "ollama_cloud", {"api_key": "oc-abc"})
    return "user-oc"


@pytest.fixture
async def user_with_local_ollama(premium_db):
    repo = ConnectionRepository(premium_db)
    await repo.create_indexes()
    doc = await repo.create(
        user_id="user-local",
        adapter_type="ollama_http",
        display_name="my-homeserver",
        slug="my-homeserver",
        config={"url": "http://192.168.0.10:11434"},
    )
    return ("user-local", doc["slug"])


async def test_resolves_premium_xai(user_with_xai_account):
    resolved = await resolve_for_model(user_with_xai_account, "xai:grok-3")
    assert resolved.adapter_type == "xai_http"
    assert resolved.slug == "xai"
    assert resolved.config["url"] == "https://api.x.ai"
    assert resolved.config["api_key"] == "xai-abc"


async def test_resolves_premium_ollama_cloud(user_with_ollama_cloud):
    resolved = await resolve_for_model(
        user_with_ollama_cloud, "ollama_cloud:llama3.2",
    )
    assert resolved.adapter_type == "ollama_http"
    assert resolved.slug == "ollama_cloud"
    assert resolved.config["url"] == "https://ollama.com"
    assert resolved.config["api_key"] == "oc-abc"


async def test_missing_premium_account_raises(premium_db):
    with pytest.raises(LlmConnectionNotFoundError):
        await resolve_for_model("fresh-user", "xai:grok-3")


async def test_local_connection_still_resolved(user_with_local_ollama):
    user_id, conn_slug = user_with_local_ollama
    resolved = await resolve_for_model(user_id, f"{conn_slug}:llama3.2")
    assert resolved is not None
    assert resolved.slug == conn_slug
    assert resolved.config["url"] == "http://192.168.0.10:11434"
