"""Post-login auto-probing for migrated Premium Provider Accounts."""
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient, Response

from backend.config import settings


async def _setup_master_admin_response(client: AsyncClient) -> Response:
    resp = await client.post(
        "/api/setup",
        json={
            "pin": settings.master_admin_pin,
            "username": "admin",
            "email": "admin@example.com",
            "password": "SecurePass123",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp


async def _setup_master_admin(client: AsyncClient) -> dict:
    resp = await _setup_master_admin_response(client)
    return resp.json()


async def _upsert_provider(client: AsyncClient, token: str, provider_id: str) -> None:
    resp = await client.put(
        f"/api/providers/accounts/{provider_id}",
        json={"config": {"api_key": f"{provider_id}-test-key"}},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text


def _mock_probe(status_code: int = 200):
    mock_response = MagicMock()
    mock_response.status_code = status_code
    patcher = patch("httpx.AsyncClient")

    def setup(mock_cls):
        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_response)
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        return mock_client

    return patcher, setup


async def test_login_auto_tests_untested_premium_provider_accounts(client: AsyncClient):
    setup_data = await _setup_master_admin(client)
    setup_token = setup_data["access_token"]
    for provider_id in ("xai", "mistral", "ollama_cloud"):
        await _upsert_provider(client, setup_token, provider_id)

    patcher, setup_probe = _mock_probe(status_code=200)
    with patcher as mock_cls:
        mock_client = setup_probe(mock_cls)
        login_resp = await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "SecurePass123"},
        )

    assert login_resp.status_code == 200, login_resp.text
    assert mock_client.request.await_count == 3
    calls = mock_client.request.await_args_list
    assert [c.args[1] for c in calls] == [
        "https://api.x.ai/v1/models",
        "https://api.mistral.ai/v1/models",
        "https://ollama.com/api/me",
    ]

    token = login_resp.json()["access_token"]
    listing = await client.get(
        "/api/providers/accounts",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert listing.status_code == 200, listing.text
    statuses = {a["provider_id"]: a["last_test_status"] for a in listing.json()}
    assert statuses == {
        "xai": "ok",
        "mistral": "ok",
        "ollama_cloud": "ok",
    }


async def test_login_does_not_retest_accounts_with_test_status(client: AsyncClient):
    setup_data = await _setup_master_admin(client)
    token = setup_data["access_token"]
    await _upsert_provider(client, token, "xai")

    patcher, setup_probe = _mock_probe(status_code=200)
    with patcher as mock_cls:
        setup_probe(mock_cls)
        test_resp = await client.post(
            "/api/providers/accounts/xai/test",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert test_resp.status_code == 200, test_resp.text

    patcher, setup_probe = _mock_probe(status_code=500)
    with patcher as mock_cls:
        mock_client = setup_probe(mock_cls)
        login_resp = await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "SecurePass123"},
        )

    assert login_resp.status_code == 200, login_resp.text
    assert mock_client.request.await_count == 0


async def test_refresh_auto_tests_untested_premium_provider_accounts(client: AsyncClient):
    setup_resp = await _setup_master_admin_response(client)
    token = setup_resp.json()["access_token"]
    await _upsert_provider(client, token, "mistral")

    patcher, setup_probe = _mock_probe(status_code=200)
    with patcher as mock_cls:
        mock_client = setup_probe(mock_cls)
        client.cookies.set("refresh_token", setup_resp.cookies["refresh_token"])
        refresh_resp = await client.post(
            "/api/auth/refresh",
        )

    assert refresh_resp.status_code == 200, refresh_resp.text
    assert mock_client.request.await_count == 1
    assert mock_client.request.await_args.args[1] == "https://api.mistral.ai/v1/models"
