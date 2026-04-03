import pytest
from unittest.mock import AsyncMock, patch


async def test_get_setting_returns_value():
    mock_repo = AsyncMock()
    mock_repo.find.return_value = {"_id": "system_prompt", "value": "Be helpful", "updated_at": None, "updated_by": None}

    with patch("backend.modules.settings.SettingsRepository", return_value=mock_repo), \
         patch("backend.modules.settings.get_db"):
        from backend.modules.settings import get_setting
        result = await get_setting("system_prompt")
        assert result == "Be helpful"


async def test_get_setting_returns_none_when_missing():
    mock_repo = AsyncMock()
    mock_repo.find.return_value = None

    with patch("backend.modules.settings.SettingsRepository", return_value=mock_repo), \
         patch("backend.modules.settings.get_db"):
        from backend.modules.settings import get_setting
        result = await get_setting("nonexistent")
        assert result is None
