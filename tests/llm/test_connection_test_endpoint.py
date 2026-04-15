"""Tests for the POST /test adapter sub-router endpoint.

Verifies that calling the test endpoint:
1. Persists last_test_status / last_test_at / last_test_error on success.
2. Persists last_test_status / last_test_error on failure.
3. Publishes a Topics.LLM_CONNECTION_UPDATED event.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
import httpx
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from backend.modules.llm._adapters._types import ResolvedConnection
from backend.modules.llm._connections import ConnectionRepository
from shared.topics import Topics


# ---------------------------------------------------------------------------
# Minimal stub for EventBus so we can capture publish calls
# ---------------------------------------------------------------------------

class _FakeEventBus:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    async def publish(self, topic: str, event, *, target_user_ids=None) -> None:
        self.calls.append((topic, event))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_USER_ID = "user-test-abc"
_CONNECTION_ID = "conn-test-123"


def _make_resolved(url: str = "http://ollama.test:11434") -> ResolvedConnection:
    return ResolvedConnection(
        id=_CONNECTION_ID,
        user_id=_USER_ID,
        adapter_type="ollama_http",
        display_name="Test Conn",
        slug="test-conn",
        config={"url": url, "api_key": "", "max_parallel": 1},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _make_repo_doc(status: str, error: str | None = None) -> dict:
    now = datetime.now(UTC)
    return {
        "_id": _CONNECTION_ID,
        "user_id": _USER_ID,
        "adapter_type": "ollama_http",
        "display_name": "Test Conn",
        "slug": "test-conn",
        "config": {"url": "http://ollama.test:11434", "max_parallel": 1},
        "config_encrypted": {},
        "last_test_status": status,
        "last_test_error": error,
        "last_test_at": now,
        "created_at": now,
        "updated_at": now,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_connection_test_persists_status_on_success():
    """A 200 response from /api/tags must persist last_test_status='valid'."""
    from backend.modules.llm._adapters._ollama_http import _build_adapter_router

    c = _make_resolved()
    bus = _FakeEventBus()
    updated_doc = _make_repo_doc("valid", None)
    repo = MagicMock(spec=ConnectionRepository)
    repo.update_test_status = AsyncMock(return_value=updated_doc)

    # Import the handler function directly from the router
    router = _build_adapter_router()
    handler = None
    for route in router.routes:
        if route.path == "/test" and "POST" in route.methods:
            handler = route.endpoint
            break
    assert handler is not None, "POST /test route not found"

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await handler(c=c, event_bus=bus, repo=repo)

    assert result["valid"] is True
    assert result["error"] is None
    repo.update_test_status.assert_awaited_once_with(
        _USER_ID, _CONNECTION_ID, status="valid", error=None
    )


@pytest.mark.asyncio
async def test_connection_test_persists_status_on_failure():
    """A connection error must persist last_test_status='failed' with error message."""
    from backend.modules.llm._adapters._ollama_http import _build_adapter_router

    c = _make_resolved()
    bus = _FakeEventBus()
    error_msg = "Connection refused"
    updated_doc = _make_repo_doc("failed", error_msg)
    repo = MagicMock(spec=ConnectionRepository)
    repo.update_test_status = AsyncMock(return_value=updated_doc)

    router = _build_adapter_router()
    handler = None
    for route in router.routes:
        if route.path == "/test" and "POST" in route.methods:
            handler = route.endpoint
            break
    assert handler is not None

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception(error_msg))
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await handler(c=c, event_bus=bus, repo=repo)

    assert result["valid"] is False
    assert result["error"] == error_msg
    repo.update_test_status.assert_awaited_once_with(
        _USER_ID, _CONNECTION_ID, status="failed", error=error_msg
    )


@pytest.mark.asyncio
async def test_connection_test_publishes_connection_updated_event():
    """After a successful test the event bus must receive one LLM_CONNECTION_UPDATED event."""
    from backend.modules.llm._adapters._ollama_http import _build_adapter_router

    c = _make_resolved()
    bus = _FakeEventBus()
    updated_doc = _make_repo_doc("valid", None)
    repo = MagicMock(spec=ConnectionRepository)
    repo.update_test_status = AsyncMock(return_value=updated_doc)

    router = _build_adapter_router()
    handler = None
    for route in router.routes:
        if route.path == "/test" and "POST" in route.methods:
            handler = route.endpoint
            break
    assert handler is not None

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        await handler(c=c, event_bus=bus, repo=repo)

    assert len(bus.calls) == 1
    topic, event = bus.calls[0]
    assert topic == Topics.LLM_CONNECTION_UPDATED
