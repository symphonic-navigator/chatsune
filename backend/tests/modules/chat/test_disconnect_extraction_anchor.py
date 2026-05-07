"""Disconnect-extraction trigger fires when (no connections) AND (no inflight)."""

import asyncio
import pytest
from unittest.mock import AsyncMock, patch

from backend.modules.chat._orchestrator import (
    _cancel_events,
    _disconnect_extraction_done,
    _disconnect_extraction_locks,
    _inflight,
    maybe_trigger_disconnect_extraction,
)


@pytest.fixture(autouse=True)
def _clear_registry():
    _cancel_events.clear()
    _inflight.clear()
    _disconnect_extraction_done.clear()
    _disconnect_extraction_locks.clear()
    yield
    _cancel_events.clear()
    _inflight.clear()
    _disconnect_extraction_done.clear()
    _disconnect_extraction_locks.clear()


@pytest.mark.asyncio
async def test_trigger_fires_when_user_offline_and_no_inflight():
    with patch(
        "backend.modules.chat._orchestrator.trigger_disconnect_extraction",
        new=AsyncMock(),
    ) as mock_trigger, patch(
        "backend.modules.chat._orchestrator._has_connections",
        return_value=False,
    ):
        await maybe_trigger_disconnect_extraction("user-a")
        mock_trigger.assert_awaited_once_with("user-a")


@pytest.mark.asyncio
async def test_trigger_does_not_fire_while_inflight_remains():
    _inflight["cor-1"] = ("user-a", "session-x")
    _cancel_events["cor-1"] = asyncio.Event()
    with patch(
        "backend.modules.chat._orchestrator.trigger_disconnect_extraction",
        new=AsyncMock(),
    ) as mock_trigger, patch(
        "backend.modules.chat._orchestrator._has_connections",
        return_value=False,
    ):
        await maybe_trigger_disconnect_extraction("user-a")
        mock_trigger.assert_not_awaited()


@pytest.mark.asyncio
async def test_trigger_does_not_fire_while_user_still_connected():
    with patch(
        "backend.modules.chat._orchestrator.trigger_disconnect_extraction",
        new=AsyncMock(),
    ) as mock_trigger, patch(
        "backend.modules.chat._orchestrator._has_connections",
        return_value=True,
    ):
        await maybe_trigger_disconnect_extraction("user-a")
        mock_trigger.assert_not_awaited()


@pytest.mark.asyncio
async def test_concurrent_invocations_trigger_only_once():
    """Two inferences finish at the same instant -> only one extraction."""
    with patch(
        "backend.modules.chat._orchestrator.trigger_disconnect_extraction",
        new=AsyncMock(),
    ) as mock_trigger, patch(
        "backend.modules.chat._orchestrator._has_connections",
        return_value=False,
    ):
        await asyncio.gather(
            maybe_trigger_disconnect_extraction("user-a"),
            maybe_trigger_disconnect_extraction("user-a"),
            maybe_trigger_disconnect_extraction("user-a"),
        )
        # Lock serialises them; the first wins, the others see "already
        # triggered for this offline window" and skip.
        assert mock_trigger.await_count == 1
