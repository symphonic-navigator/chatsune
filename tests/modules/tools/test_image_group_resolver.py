"""Tests for the available_groups_for_user resolver in the tool registry."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.modules.tools._registry import available_groups_for_user


@pytest.mark.asyncio
async def test_image_group_present_when_active_config():
    svc = MagicMock()
    svc.get_active_config = AsyncMock(return_value=MagicMock())  # not None
    groups = await available_groups_for_user(user_id="u1", image_service=svc)
    assert "image_generation" in groups
    assert groups["image_generation"].executor is not None


@pytest.mark.asyncio
async def test_image_group_absent_when_no_active_config():
    svc = MagicMock()
    svc.get_active_config = AsyncMock(return_value=None)
    groups = await available_groups_for_user(user_id="u1", image_service=svc)
    assert "image_generation" not in groups


@pytest.mark.asyncio
async def test_other_tool_groups_unchanged():
    """Resolver must not strip or mutate non-image groups."""
    svc = MagicMock()
    svc.get_active_config = AsyncMock(return_value=None)
    groups = await available_groups_for_user(user_id="u1", image_service=svc)
    # web_search, artefacts, etc. should still be there
    assert "web_search" in groups
    assert "artefacts" in groups


@pytest.mark.asyncio
async def test_resolver_returns_fresh_dict():
    """Mutating the returned dict must not affect the cached get_groups() result."""
    from backend.modules.tools._registry import get_groups

    svc = MagicMock()
    svc.get_active_config = AsyncMock(return_value=None)
    groups = await available_groups_for_user(user_id="u1", image_service=svc)
    # Inject a spurious key into the returned dict
    groups["__test_sentinel__"] = None  # type: ignore[assignment]

    # The cache must be unaffected
    assert "__test_sentinel__" not in get_groups()
