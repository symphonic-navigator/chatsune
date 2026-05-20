"""Lifecycle hooks fire on first-connect / last-disconnect edges."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.ws.manager import ConnectionManager


def _fake_ws() -> MagicMock:
    ws = MagicMock()
    ws.send_json = AsyncMock()
    return ws


@pytest.mark.asyncio
async def test_first_connect_hook_fires_only_on_first_socket():
    mgr = ConnectionManager()
    hook = AsyncMock()
    mgr.register_on_first_connect(hook)

    await mgr.connect("user-a", "user", _fake_ws())
    await mgr.connect("user-a", "user", _fake_ws())
    await mgr.connect("user-b", "user", _fake_ws())

    assert hook.await_count == 2
    hook.assert_any_await("user-a")
    hook.assert_any_await("user-b")


@pytest.mark.asyncio
async def test_last_disconnect_hook_fires_only_when_last_socket_leaves():
    mgr = ConnectionManager()
    hook = AsyncMock()
    mgr.register_on_last_disconnect(hook)

    ws1, ws2 = _fake_ws(), _fake_ws()
    await mgr.connect("user-a", "user", ws1)
    await mgr.connect("user-a", "user", ws2)

    await mgr.disconnect("user-a", ws1)
    assert hook.await_count == 0  # still one socket left

    await mgr.disconnect("user-a", ws2)
    assert hook.await_count == 1
    hook.assert_awaited_with("user-a")


@pytest.mark.asyncio
async def test_hook_exception_does_not_break_connect():
    mgr = ConnectionManager()

    async def bad_hook(user_id: str) -> None:
        raise RuntimeError("boom")

    mgr.register_on_first_connect(bad_hook)
    # Must not raise:
    cid = await mgr.connect("user-a", "user", _fake_ws())
    assert cid in mgr.connection_ids_for_user("user-a")
