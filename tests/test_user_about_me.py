import pytest
from unittest.mock import AsyncMock, patch


async def test_get_user_about_me_returns_value():
    mock_repo = AsyncMock()
    mock_repo.get_about_me.return_value = "I like cats"

    with patch("backend.modules.user.UserRepository", return_value=mock_repo), \
         patch("backend.modules.user.get_db"):
        from backend.modules.user import get_user_about_me
        result = await get_user_about_me("user-1")
        assert result == "I like cats"
        mock_repo.get_about_me.assert_awaited_once_with("user-1")


async def test_get_user_about_me_returns_none_when_missing():
    mock_repo = AsyncMock()
    mock_repo.get_about_me.return_value = None

    with patch("backend.modules.user.UserRepository", return_value=mock_repo), \
         patch("backend.modules.user.get_db"):
        from backend.modules.user import get_user_about_me
        result = await get_user_about_me("user-1")
        assert result is None


async def test_get_user_about_me_returns_none_when_user_not_found():
    mock_repo = AsyncMock()
    mock_repo.get_about_me.return_value = None

    with patch("backend.modules.user.UserRepository", return_value=mock_repo), \
         patch("backend.modules.user.get_db"):
        from backend.modules.user import get_user_about_me
        result = await get_user_about_me("nonexistent")
        assert result is None
        mock_repo.get_about_me.assert_awaited_once_with("nonexistent")
