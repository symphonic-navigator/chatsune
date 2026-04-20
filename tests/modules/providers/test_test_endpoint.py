"""HTTP tests for POST /api/providers/accounts/{provider_id}/test.

The upstream probe is mocked via ``patch("httpx.AsyncClient")`` — same
pattern as ``tests/llm/test_connection_test_endpoint.py``.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import pytest_asyncio
from httpx import AsyncClient

from backend.modules.user._auth import create_access_token, generate_session_id


@pytest_asyncio.fixture
async def auth_headers():
    token = create_access_token(
        user_id="test-user-1",
        role="user",
        session_id=generate_session_id(),
    )
    return {"Authorization": f"Bearer {token}"}


async def _configure_xai(client: AsyncClient, headers: dict) -> None:
    """Upsert a dummy xAI account so the /test endpoint has something to probe."""
    resp = await client.put(
        "/api/providers/accounts/xai",
        json={"config": {"api_key": "xai-test-key"}},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text


def _mock_probe(status_code: int | None = 200, exc: Exception | None = None):
    """Return a context manager that patches httpx.AsyncClient.request.

    Either returns a response with ``status_code``, or raises ``exc``.
    """
    mock_response = MagicMock()
    mock_response.status_code = status_code
    patcher = patch("httpx.AsyncClient")

    def setup(mock_cls):
        mock_client = AsyncMock()
        if exc is not None:
            mock_client.request = AsyncMock(side_effect=exc)
        else:
            mock_client.request = AsyncMock(return_value=mock_response)
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        return mock_client

    return patcher, setup


async def test_test_endpoint_returns_ok_on_200(
    client: AsyncClient, auth_headers,
):
    await _configure_xai(client, auth_headers)
    patcher, setup = _mock_probe(status_code=200)
    with patcher as mock_cls:
        setup(mock_cls)
        resp = await client.post(
            "/api/providers/accounts/xai/test", headers=auth_headers,
        )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"status": "ok", "error": None}

    # Persisted: the follow-up GET reflects last_test_status=ok
    listing = await client.get("/api/providers/accounts", headers=auth_headers)
    xai = next(a for a in listing.json() if a["provider_id"] == "xai")
    assert xai["last_test_status"] == "ok"
    assert xai["last_test_error"] is None
    assert xai["last_test_at"] is not None


async def test_test_endpoint_rejects_on_401(
    client: AsyncClient, auth_headers,
):
    await _configure_xai(client, auth_headers)
    patcher, setup = _mock_probe(status_code=401)
    with patcher as mock_cls:
        setup(mock_cls)
        resp = await client.post(
            "/api/providers/accounts/xai/test", headers=auth_headers,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "error"
    assert "API key rejected by xAI" in body["error"]


async def test_test_endpoint_rejects_on_403(
    client: AsyncClient, auth_headers,
):
    await _configure_xai(client, auth_headers)
    patcher, setup = _mock_probe(status_code=403)
    with patcher as mock_cls:
        setup(mock_cls)
        resp = await client.post(
            "/api/providers/accounts/xai/test", headers=auth_headers,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "error"
    assert "API key rejected by xAI" in body["error"]


async def test_test_endpoint_reports_upstream_status(
    client: AsyncClient, auth_headers,
):
    await _configure_xai(client, auth_headers)
    patcher, setup = _mock_probe(status_code=500)
    with patcher as mock_cls:
        setup(mock_cls)
        resp = await client.post(
            "/api/providers/accounts/xai/test", headers=auth_headers,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "error"
    assert "500" in body["error"]
    assert "xAI" in body["error"]


async def test_test_endpoint_handles_network_exception(
    client: AsyncClient, auth_headers,
):
    await _configure_xai(client, auth_headers)
    patcher, setup = _mock_probe(exc=httpx.ConnectError("refused"))
    with patcher as mock_cls:
        setup(mock_cls)
        resp = await client.post(
            "/api/providers/accounts/xai/test", headers=auth_headers,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "error"
    assert "refused" in body["error"]


async def test_test_endpoint_404_on_unknown_provider(
    client: AsyncClient, auth_headers,
):
    resp = await client.post(
        "/api/providers/accounts/bogus/test", headers=auth_headers,
    )
    assert resp.status_code == 404


async def test_test_endpoint_404_on_missing_account(
    client: AsyncClient, auth_headers,
):
    # mistral exists in the registry but the user has no account yet.
    resp = await client.post(
        "/api/providers/accounts/mistral/test", headers=auth_headers,
    )
    assert resp.status_code == 404


async def test_test_endpoint_probes_ollama_with_post_api_me(
    client: AsyncClient, auth_headers,
):
    """Smoke-test that each provider's probe URL + method drives the request."""
    await client.put(
        "/api/providers/accounts/ollama_cloud",
        json={"config": {"api_key": "ollama-test"}},
        headers=auth_headers,
    )
    patcher, setup = _mock_probe(status_code=200)
    with patcher as mock_cls:
        mock_client = setup(mock_cls)
        resp = await client.post(
            "/api/providers/accounts/ollama_cloud/test", headers=auth_headers,
        )
    assert resp.status_code == 200
    # Assert that the mocked httpx client saw the exact probe method + URL.
    call = mock_client.request.await_args
    assert call.args[0] == "POST"
    assert call.args[1] == "https://ollama.com/api/me"
    assert call.kwargs["headers"]["Authorization"] == "Bearer ollama-test"


async def test_test_endpoint_requires_auth(client: AsyncClient):
    resp = await client.post("/api/providers/accounts/xai/test")
    assert resp.status_code in (401, 403)
