"""Tests for POST /api/websearch/providers/{provider_id}/test.

Verifies that:
1. When body is empty, the stored key is fetched and the adapter is called
   with the query "capital of paris".
2. When neither a body key nor a stored key exists, HTTP 400 is returned.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from backend.modules.websearch._credentials import WebSearchCredentialRepository
from shared.dtos.websearch import WebSearchTestRequestDto


# ---------------------------------------------------------------------------
# Minimal stubs
# ---------------------------------------------------------------------------

class _FakeEventBus:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    async def publish(self, topic: str, event, *, target_user_ids=None) -> None:
        self.calls.append((topic, event))


_USER_ID = "user-ws-test-001"
_PROVIDER_ID = "ollama_cloud_search"
_STORED_KEY = "stored-api-key-xyz"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user() -> dict:
    return {"sub": _USER_ID}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_test_endpoint_uses_stored_key_when_body_empty():
    """With an empty body the handler must fall back to the stored credential
    and invoke the adapter with the query 'capital of paris'."""
    from backend.modules.websearch._handlers import test_credential

    bus = _FakeEventBus()
    user = _make_user()

    # Stub repo: get_key returns the stored key, update_test returns a doc
    mock_repo = MagicMock(spec=WebSearchCredentialRepository)
    mock_repo.get_key = AsyncMock(return_value=_STORED_KEY)
    mock_repo.update_test = AsyncMock(return_value=None)

    # Stub adapter class that records search calls
    search_calls: list[tuple[str, str, int]] = []

    async def _fake_search(api_key: str, query: str, n: int) -> list:
        search_calls.append((api_key, query, n))
        return []

    mock_adapter_instance = MagicMock()
    mock_adapter_instance.search = _fake_search
    mock_adapter_cls = MagicMock(return_value=mock_adapter_instance)

    fake_registry = {_PROVIDER_ID: mock_adapter_cls}
    fake_base_urls = {_PROVIDER_ID: "https://ollama.com"}

    with (
        patch("backend.modules.websearch._handlers.SEARCH_ADAPTER_REGISTRY", fake_registry),
        patch("backend.modules.websearch._handlers.SEARCH_PROVIDER_BASE_URLS", fake_base_urls),
        patch("backend.modules.websearch._handlers._repo", return_value=mock_repo),
    ):
        result = await test_credential(
            provider_id=_PROVIDER_ID,
            body=WebSearchTestRequestDto(api_key=None),
            user=user,
            event_bus=bus,
        )

    assert result["valid"] is True
    assert result["error"] is None

    # Adapter must have been called with the stored key and the new canary query
    assert len(search_calls) == 1
    assert search_calls[0][0] == _STORED_KEY
    assert search_calls[0][1] == "capital of paris"

    mock_repo.get_key.assert_awaited_once_with(_USER_ID, _PROVIDER_ID)


@pytest.mark.asyncio
async def test_test_endpoint_returns_400_when_no_key():
    """When no body key is given and no stored key exists the handler must
    raise HTTP 400 with the appropriate detail message."""
    from backend.modules.websearch._handlers import test_credential

    bus = _FakeEventBus()
    user = _make_user()

    mock_repo = MagicMock(spec=WebSearchCredentialRepository)
    mock_repo.get_key = AsyncMock(return_value=None)

    fake_registry = {_PROVIDER_ID: MagicMock()}
    fake_base_urls = {_PROVIDER_ID: "https://ollama.com"}

    with (
        patch("backend.modules.websearch._handlers.SEARCH_ADAPTER_REGISTRY", fake_registry),
        patch("backend.modules.websearch._handlers.SEARCH_PROVIDER_BASE_URLS", fake_base_urls),
        patch("backend.modules.websearch._handlers._repo", return_value=mock_repo),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await test_credential(
                provider_id=_PROVIDER_ID,
                body=WebSearchTestRequestDto(api_key=None),
                user=user,
                event_bus=bus,
            )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "No API key provided and none stored"
