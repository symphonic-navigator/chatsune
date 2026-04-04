"""Tests for the system prompt preview endpoint on the persona module."""
import pytest
from unittest.mock import AsyncMock, patch


async def test_assemble_preview_is_importable_from_chat_module():
    """Verify assemble_preview is part of the chat module's public API."""
    from backend.modules.chat import assemble_preview
    assert callable(assemble_preview)
