"""Tests for the Ollama HTTP adapter — URL-based billing classification."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from backend.modules.llm._adapters._ollama_http import (
    OllamaHttpAdapter,
    _billing_category_for_url,
)
from backend.modules.llm._adapters._types import ResolvedConnection


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolved_conn(
    *,
    url: str = "http://localhost:11434",
    api_key: str = "",
) -> ResolvedConnection:
    now = datetime.now(UTC)
    return ResolvedConnection(
        id="conn-ollama-1",
        user_id="u1",
        adapter_type="ollama_http",
        display_name="Chris's Ollama",
        slug="chris-ollama",
        config={
            "url": url,
            "api_key": api_key,
            "max_parallel": 1,
        },
        created_at=now,
        updated_at=now,
    )


def _install_mock_transport(monkeypatch, handler):
    """Patch httpx.AsyncClient in the adapter module to use a MockTransport."""
    from backend.modules.llm._adapters import _ollama_http

    class _PatchedClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(_ollama_http.httpx, "AsyncClient", _PatchedClient)


def _tags_show_handler(request: httpx.Request) -> httpx.Response:
    """Minimal handler that serves /api/tags and /api/show with a single model
    that has the fields required by the DTO filter (non-zero context window)."""
    path = request.url.path
    if path.endswith("/api/tags"):
        return httpx.Response(200, json={"models": [{"name": "llama3.2:latest"}]})
    if path.endswith("/api/show"):
        return httpx.Response(
            200,
            json={
                "capabilities": ["tools"],
                "model_info": {
                    "llama.context_length": 8192,
                    "general.parameter_count": 3_000_000_000,
                },
                "details": {
                    "parameter_size": "3B",
                    "quantization_level": "Q4_0",
                },
            },
        )
    return httpx.Response(404)


# ---------------------------------------------------------------------------
# _billing_category_for_url — pure unit tests
# ---------------------------------------------------------------------------


def test_billing_category_for_ollama_cloud_apex():
    assert _billing_category_for_url("https://ollama.com") == "subscription"


def test_billing_category_for_ollama_cloud_with_trailing_slash():
    assert _billing_category_for_url("https://ollama.com/") == "subscription"


def test_billing_category_for_ollama_cloud_subdomain():
    assert _billing_category_for_url("https://api.ollama.com") == "subscription"


def test_billing_category_for_localhost():
    assert _billing_category_for_url("http://localhost:11434") == "free"


def test_billing_category_for_localhost_ip():
    assert _billing_category_for_url("http://127.0.0.1:11434") == "free"


def test_billing_category_for_custom_self_hosted():
    assert _billing_category_for_url("https://my.homelab.net:11434") == "free"


def test_billing_category_for_lookalike_domain_is_free():
    # Guard against the classic endswith("ollama.com") trap — a host like
    # "ollamafake.com" must not be classified as subscription.
    assert _billing_category_for_url("https://ollamafake.com") == "free"


# ---------------------------------------------------------------------------
# fetch_models — end-to-end billing labelling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_models_labels_local_connection_as_free(monkeypatch):
    _install_mock_transport(monkeypatch, _tags_show_handler)
    adapter = OllamaHttpAdapter()
    conn = _resolved_conn(url="http://localhost:11434")
    metas = await adapter.fetch_models(conn)
    assert metas
    for m in metas:
        assert m.billing_category == "free"


@pytest.mark.asyncio
async def test_fetch_models_labels_cloud_connection_as_subscription(monkeypatch):
    _install_mock_transport(monkeypatch, _tags_show_handler)
    adapter = OllamaHttpAdapter()
    conn = _resolved_conn(url="https://ollama.com", api_key="test-key")
    metas = await adapter.fetch_models(conn)
    assert metas
    for m in metas:
        assert m.billing_category == "subscription"
