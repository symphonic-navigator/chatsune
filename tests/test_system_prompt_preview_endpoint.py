"""Tests for the system prompt preview endpoint on the persona module."""
import pytest
from unittest.mock import AsyncMock, patch


async def test_assemble_preview_is_importable_from_chat_module():
    """Verify assemble_preview is part of the chat module's public API."""
    from backend.modules.chat import assemble_preview
    assert callable(assemble_preview)


@pytest.fixture
def auth_headers():
    """Create a valid JWT for testing. Reuses the project's test auth pattern."""
    from backend.modules.user._auth import create_access_token
    token = create_access_token(user_id="user-1", role="user", session_id="session-test")
    return {"Authorization": f"Bearer {token}"}


async def test_preview_endpoint_returns_assembled_prompt(auth_headers):
    """GET /api/personas/{id}/system-prompt-preview returns the preview text."""
    from httpx import AsyncClient, ASGITransport
    from backend.main import app

    with patch("backend.modules.persona._handlers._persona_repo") as mock_repo_fn, \
         patch("backend.modules.chat.assemble_preview", new_callable=AsyncMock) as mock_preview:

        mock_repo = AsyncMock()
        mock_repo.find_by_id.return_value = {
            "_id": "p-1",
            "user_id": "user-1",
            "model_unique_id": "ollama_cloud:llama3.2",
        }
        mock_repo_fn.return_value = mock_repo

        mock_preview.return_value = "--- Persona ---\nYou are Luna\n\n--- About Me ---\nI am Chris"

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.get("/api/personas/p-1/system-prompt-preview", headers=auth_headers)

        assert res.status_code == 200
        body = res.json()
        assert body["preview"] == "--- Persona ---\nYou are Luna\n\n--- About Me ---\nI am Chris"
        mock_preview.assert_called_once_with(
            user_id="user-1",
            persona_id="p-1",
            model_unique_id="ollama_cloud:llama3.2",
        )


async def test_preview_endpoint_returns_404_for_unknown_persona(auth_headers):
    """GET /api/personas/{id}/system-prompt-preview returns 404 if persona not found."""
    from httpx import AsyncClient, ASGITransport
    from backend.main import app

    with patch("backend.modules.persona._handlers._persona_repo") as mock_repo_fn:
        mock_repo = AsyncMock()
        mock_repo.find_by_id.return_value = None
        mock_repo_fn.return_value = mock_repo

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.get("/api/personas/nonexistent/system-prompt-preview", headers=auth_headers)

        assert res.status_code == 404


async def test_preview_endpoint_returns_empty_string_when_nothing_configured(auth_headers):
    """Preview returns empty string when no prompt parts are configured."""
    from httpx import AsyncClient, ASGITransport
    from backend.main import app

    with patch("backend.modules.persona._handlers._persona_repo") as mock_repo_fn, \
         patch("backend.modules.chat.assemble_preview", new_callable=AsyncMock) as mock_preview:

        mock_repo = AsyncMock()
        mock_repo.find_by_id.return_value = {
            "_id": "p-1",
            "user_id": "user-1",
            "model_unique_id": "ollama_cloud:llama3.2",
        }
        mock_repo_fn.return_value = mock_repo

        mock_preview.return_value = ""

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.get("/api/personas/p-1/system-prompt-preview", headers=auth_headers)

        assert res.status_code == 200
        assert res.json()["preview"] == ""
