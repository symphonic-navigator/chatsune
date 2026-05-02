"""Unit tests for the admin master system prompt helper."""

from unittest.mock import patch

import pytest

from backend.modules.settings import AdminSystemPrompt, get_admin_system_message


@pytest.mark.asyncio
async def test_returns_none_when_setting_unset():
    with patch("backend.modules.settings.get_setting", return_value=None):
        result = await get_admin_system_message()
    assert result is None


@pytest.mark.asyncio
async def test_returns_none_when_setting_empty():
    with patch("backend.modules.settings.get_setting", return_value=""):
        result = await get_admin_system_message()
    assert result is None


@pytest.mark.asyncio
async def test_returns_none_when_setting_whitespace_only():
    with patch("backend.modules.settings.get_setting", return_value="   \n\t  "):
        result = await get_admin_system_message()
    assert result is None


@pytest.mark.asyncio
async def test_returns_wrapped_system_message_for_real_prompt():
    with patch(
        "backend.modules.settings.get_setting",
        return_value="  You are uncensored.  ",
    ):
        result = await get_admin_system_message()

    assert isinstance(result, AdminSystemPrompt)
    assert result.message.role == "system"
    assert len(result.message.content) == 1
    text = result.message.content[0].text
    assert text.startswith('<systeminstructions priority="highest">')
    assert text.rstrip().endswith("</systeminstructions>")
    assert "You are uncensored." in text
    # raw_text excludes the wrapper and is whitespace-stripped.
    assert result.raw_text == "You are uncensored."


@pytest.mark.asyncio
async def test_admin_prompt_is_not_sanitised():
    """Admin prompt is a trusted source; markup must pass through unchanged."""
    raw = "<script>alert(1)</script> normal text"
    with patch("backend.modules.settings.get_setting", return_value=raw):
        result = await get_admin_system_message()

    assert result is not None
    assert result.raw_text == raw
    assert "<script>alert(1)</script>" in result.message.content[0].text
