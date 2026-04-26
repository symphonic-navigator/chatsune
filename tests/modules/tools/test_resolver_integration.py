"""Integration-level tests for get_active_definitions with per-user resolver.

Verifies that ``get_active_definitions(user_id=...)`` calls ``available_groups_for_user``
and includes/excludes ``generate_image`` based on whether the user has an active
image configuration.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.modules.tools import get_active_definitions


@pytest.mark.asyncio
async def test_generate_image_present_when_active_config():
    """generate_image must appear in definitions when the user has an active config."""
    mock_svc = MagicMock()
    mock_svc.get_active_config = AsyncMock(return_value=MagicMock())  # not None

    with patch("backend.modules.images.get_image_service", return_value=mock_svc):
        definitions = await get_active_definitions(user_id="u1")

    names = {d.name for d in definitions}
    assert "generate_image" in names


@pytest.mark.asyncio
async def test_generate_image_absent_when_no_active_config():
    """generate_image must NOT appear when the user has no active image config."""
    mock_svc = MagicMock()
    mock_svc.get_active_config = AsyncMock(return_value=None)

    with patch("backend.modules.images.get_image_service", return_value=mock_svc):
        definitions = await get_active_definitions(user_id="u1")

    names = {d.name for d in definitions}
    assert "generate_image" not in names


@pytest.mark.asyncio
async def test_other_tools_present_regardless_of_image_config():
    """Non-image tools must remain in the definition list in both cases."""
    mock_svc = MagicMock()
    mock_svc.get_active_config = AsyncMock(return_value=None)

    with patch("backend.modules.images.get_image_service", return_value=mock_svc):
        definitions = await get_active_definitions(user_id="u1")

    names = {d.name for d in definitions}
    assert "write_journal_entry" in names
    assert "knowledge_search" in names


@pytest.mark.asyncio
async def test_no_user_id_falls_back_to_static_groups():
    """When no user_id is given, ImageService is not called and all static groups
    are returned (image_generation included by definition list but without executor)."""
    mock_svc = MagicMock()
    mock_svc.get_active_config = AsyncMock(return_value=MagicMock())

    with patch("backend.modules.images.get_image_service", return_value=mock_svc):
        definitions = await get_active_definitions()  # no user_id

    # ImageService must not have been queried
    mock_svc.get_active_config.assert_not_called()
    # Non-image tools must still be present
    names = {d.name for d in definitions}
    assert "write_journal_entry" in names
