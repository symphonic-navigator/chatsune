"""HTTP handler tests for the Premium Provider Accounts module.

These tests exercise the real router via the shared ``client`` fixture (defined
in ``tests/conftest.py``), which spins up the FastAPI app against the dedicated
``chatsune_test`` MongoDB/Redis instances. Auth follows the pattern used by
``tests/test_system_prompt_preview_endpoint.py``: mint a JWT directly via
``create_access_token`` rather than going through the login endpoint.
"""
from httpx import AsyncClient
import pytest
import pytest_asyncio

from backend.modules.user._auth import create_access_token, generate_session_id


@pytest_asyncio.fixture
async def auth_headers():
    """Bearer-token headers for a plain (non-admin) test user."""
    token = create_access_token(
        user_id="test-user-1",
        role="user",
        session_id=generate_session_id(),
    )
    return {"Authorization": f"Bearer {token}"}


async def test_catalogue_lists_providers(client: AsyncClient, auth_headers):
    resp = await client.get("/api/providers/catalogue", headers=auth_headers)
    assert resp.status_code == 200
    ids = [p["id"] for p in resp.json()]
    assert set(ids) == {"xai", "mistral", "ollama_cloud"}


async def test_list_accounts_empty(client: AsyncClient, auth_headers):
    resp = await client.get("/api/providers/accounts", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


async def test_upsert_and_read(client: AsyncClient, auth_headers):
    r1 = await client.put(
        "/api/providers/accounts/xai",
        json={"config": {"api_key": "xai-abc"}},
        headers=auth_headers,
    )
    assert r1.status_code == 200, r1.text
    body = r1.json()
    assert body["provider_id"] == "xai"
    assert body["config"]["api_key"] == {"is_set": True}

    r2 = await client.get("/api/providers/accounts", headers=auth_headers)
    assert len(r2.json()) == 1


async def test_upsert_rejects_unknown_provider(client: AsyncClient, auth_headers):
    resp = await client.put(
        "/api/providers/accounts/bogus",
        json={"config": {"api_key": "x"}},
        headers=auth_headers,
    )
    assert resp.status_code == 404


async def test_delete_account(client: AsyncClient, auth_headers):
    await client.put(
        "/api/providers/accounts/xai",
        json={"config": {"api_key": "xai-abc"}},
        headers=auth_headers,
    )
    resp = await client.delete(
        "/api/providers/accounts/xai", headers=auth_headers,
    )
    assert resp.status_code == 204


async def test_requires_auth(client: AsyncClient):
    resp = await client.get("/api/providers/catalogue")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_delete_rejects_unknown_provider(client: AsyncClient, auth_headers):
    resp = await client.delete("/api/providers/accounts/bogus", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_404_when_no_account_for_known_provider(
    client: AsyncClient, auth_headers,
):
    # Known provider, but no account -> 404 (no-op).
    resp = await client.delete("/api/providers/accounts/xai", headers=auth_headers)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Premium-provider model listing: GET /accounts/{id}/models and
# POST /accounts/{id}/refresh
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_models_404_for_unknown_provider(
    client: AsyncClient, auth_headers,
):
    resp = await client.get(
        "/api/providers/accounts/bogus/models", headers=auth_headers,
    )
    assert resp.status_code == 404
    assert "unknown" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_list_models_404_when_user_has_no_account(
    client: AsyncClient, auth_headers,
):
    # xai is registered, but this user has never configured an account.
    resp = await client.get(
        "/api/providers/accounts/xai/models", headers=auth_headers,
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "No account configured"


@pytest.mark.asyncio
async def test_list_models_empty_for_provider_without_llm_adapter(
    client: AsyncClient, auth_headers,
):
    # Mistral is in the Premium registry but has no LLM adapter today.
    # With an account configured we must return 200 + [] rather than 404,
    # because "no LLM models" is a structural fact, not a fault.
    await client.put(
        "/api/providers/accounts/mistral",
        json={"config": {"api_key": "mistral-abc"}},
        headers=auth_headers,
    )
    resp = await client.get(
        "/api/providers/accounts/mistral/models", headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_models_returns_adapter_output(
    client: AsyncClient, auth_headers, monkeypatch,
):
    """Happy path: configure xAI, call GET .../models, get the adapter's list."""
    from backend.modules.llm._adapters import _xai_http
    from shared.dtos.llm import ModelMetaDto

    captured: dict = {}

    async def fake_fetch_models(self, c):
        captured["connection_slug"] = c.slug
        captured["base_url"] = c.config["url"]
        captured["api_key"] = c.config.get("api_key")
        return [
            ModelMetaDto(
                connection_id=c.id,
                connection_display_name=c.display_name,
                connection_slug=c.slug,
                model_id="grok-4.1-fast",
                display_name="Grok 4.1 Fast",
                context_window=200_000,
                supports_reasoning=True,
                supports_vision=True,
                supports_tool_calls=True,
            ),
        ]

    monkeypatch.setattr(
        _xai_http.XaiHttpAdapter, "fetch_models", fake_fetch_models,
    )

    await client.put(
        "/api/providers/accounts/xai",
        json={"config": {"api_key": "xai-abc"}},
        headers=auth_headers,
    )
    resp = await client.get(
        "/api/providers/accounts/xai/models", headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body) == 1
    assert body[0]["model_id"] == "grok-4.1-fast"
    assert body[0]["unique_id"] == "xai:grok-4.1-fast"
    # Adapter received the decrypted credential and the registry-fixed URL.
    assert captured["api_key"] == "xai-abc"
    assert captured["base_url"] == "https://api.x.ai/v1"
    assert captured["connection_slug"] == "xai"


@pytest.mark.asyncio
async def test_list_models_returns_empty_on_adapter_exception(
    client: AsyncClient, auth_headers, monkeypatch,
):
    """Adapter blows up → GET degrades to []; refresh is the explicit retry path."""
    from backend.modules.llm._adapters import _xai_http

    async def boom(self, c):
        raise RuntimeError("upstream 500")

    monkeypatch.setattr(_xai_http.XaiHttpAdapter, "fetch_models", boom)

    await client.put(
        "/api/providers/accounts/xai",
        json={"config": {"api_key": "xai-abc"}},
        headers=auth_headers,
    )
    resp = await client.get(
        "/api/providers/accounts/xai/models", headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_models_serves_from_cache_on_second_call(
    client: AsyncClient, auth_headers, monkeypatch,
):
    from backend.modules.llm._adapters import _xai_http
    from shared.dtos.llm import ModelMetaDto

    call_count = {"n": 0}

    async def counting_fetch(self, c):
        call_count["n"] += 1
        return [
            ModelMetaDto(
                connection_id=c.id,
                connection_display_name=c.display_name,
                connection_slug=c.slug,
                model_id="grok-4.1-fast",
                display_name="Grok 4.1 Fast",
                context_window=200_000,
                supports_reasoning=True,
                supports_vision=True,
                supports_tool_calls=True,
            ),
        ]

    monkeypatch.setattr(_xai_http.XaiHttpAdapter, "fetch_models", counting_fetch)

    await client.put(
        "/api/providers/accounts/xai",
        json={"config": {"api_key": "xai-abc"}},
        headers=auth_headers,
    )
    r1 = await client.get(
        "/api/providers/accounts/xai/models", headers=auth_headers,
    )
    r2 = await client.get(
        "/api/providers/accounts/xai/models", headers=auth_headers,
    )
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json() == r2.json()
    assert call_count["n"] == 1, "second GET must hit the Redis cache"


@pytest.mark.asyncio
async def test_refresh_unknown_provider_404(client: AsyncClient, auth_headers):
    resp = await client.post(
        "/api/providers/accounts/bogus/refresh", headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_refresh_404_when_no_account(client: AsyncClient, auth_headers):
    resp = await client.post(
        "/api/providers/accounts/xai/refresh", headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_refresh_drops_cache_and_returns_202(
    client: AsyncClient, auth_headers, monkeypatch,
):
    from backend.modules.llm._adapters import _xai_http
    from shared.dtos.llm import ModelMetaDto

    call_count = {"n": 0}

    async def counting_fetch(self, c):
        call_count["n"] += 1
        return [
            ModelMetaDto(
                connection_id=c.id,
                connection_display_name=c.display_name,
                connection_slug=c.slug,
                model_id="grok-4.1-fast",
                display_name="Grok 4.1 Fast",
                context_window=200_000,
                supports_reasoning=True,
                supports_vision=True,
                supports_tool_calls=True,
            ),
        ]

    monkeypatch.setattr(_xai_http.XaiHttpAdapter, "fetch_models", counting_fetch)

    await client.put(
        "/api/providers/accounts/xai",
        json={"config": {"api_key": "xai-abc"}},
        headers=auth_headers,
    )
    # Warm the cache.
    await client.get("/api/providers/accounts/xai/models", headers=auth_headers)
    assert call_count["n"] == 1
    # Refresh must drop the cache and re-fetch.
    r = await client.post(
        "/api/providers/accounts/xai/refresh", headers=auth_headers,
    )
    assert r.status_code == 202
    assert call_count["n"] == 2


@pytest.mark.asyncio
async def test_refresh_502_when_adapter_fails(
    client: AsyncClient, auth_headers, monkeypatch,
):
    from backend.modules.llm._adapters import _xai_http

    async def boom(self, c):
        raise RuntimeError("upstream 500")

    monkeypatch.setattr(_xai_http.XaiHttpAdapter, "fetch_models", boom)

    await client.put(
        "/api/providers/accounts/xai",
        json={"config": {"api_key": "xai-abc"}},
        headers=auth_headers,
    )
    r = await client.post(
        "/api/providers/accounts/xai/refresh", headers=auth_headers,
    )
    assert r.status_code == 502
    assert "upstream 500" in r.json()["detail"]
