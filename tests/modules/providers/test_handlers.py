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
