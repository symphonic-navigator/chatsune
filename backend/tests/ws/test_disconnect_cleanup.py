"""Tests that the WS-disconnect cleanup no longer cancels inflight inferences."""

import asyncio
import pytest

from backend.modules.chat._orchestrator import (
    _cancel_events,
    _inflight,
)
from backend.ws.router import _run_disconnect_cleanup  # exposed by Task 3


@pytest.fixture(autouse=True)
def _clear_registry():
    _cancel_events.clear()
    _inflight.clear()
    yield
    _cancel_events.clear()
    _inflight.clear()


@pytest.mark.asyncio
async def test_disconnect_cleanup_does_not_cancel_inflight():
    event = asyncio.Event()
    _cancel_events["cor-1"] = event
    _inflight["cor-1"] = ("user-a", "session-x")

    # Simulate disconnect with no reconnect: inference must keep running.
    await _run_disconnect_cleanup(
        user_id="user-a",
        connection_id="conn-1",
        has_reconnect=False,
    )

    assert not event.is_set(), "inference must NOT be cancelled by disconnect"
