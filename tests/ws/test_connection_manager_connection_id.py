import pytest
from unittest.mock import AsyncMock, MagicMock

from backend.ws.manager import ConnectionManager


class _FakeWs:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)


@pytest.mark.asyncio
async def test_connect_assigns_connection_id():
    mgr = ConnectionManager()
    ws = _FakeWs()
    conn_id = await mgr.connect("user-a", "user", ws)  # returns the assigned id
    assert isinstance(conn_id, str) and len(conn_id) >= 8
    assert mgr.has_connections("user-a")


@pytest.mark.asyncio
async def test_two_connections_get_distinct_ids():
    mgr = ConnectionManager()
    ws_a, ws_b = _FakeWs(), _FakeWs()
    a = await mgr.connect("user-a", "user", ws_a)
    b = await mgr.connect("user-a", "user", ws_b)
    assert a != b


@pytest.mark.asyncio
async def test_send_to_connection_reaches_only_target():
    mgr = ConnectionManager()
    ws_a, ws_b = _FakeWs(), _FakeWs()
    a = await mgr.connect("user-a", "user", ws_a)
    b = await mgr.connect("user-a", "user", ws_b)

    await mgr.send_to_connection("user-a", a, {"type": "hello"})

    assert ws_a.sent == [{"type": "hello"}]
    assert ws_b.sent == []


@pytest.mark.asyncio
async def test_send_to_connection_unknown_id_is_silent_noop():
    mgr = ConnectionManager()
    ws = _FakeWs()
    await mgr.connect("user-a", "user", ws)
    # Must not raise — delivery is best-effort.
    await mgr.send_to_connection("user-a", "no-such-id", {"type": "hello"})
    assert ws.sent == []


@pytest.mark.asyncio
async def test_disconnect_removes_only_the_matching_connection():
    mgr = ConnectionManager()
    ws_a, ws_b = _FakeWs(), _FakeWs()
    a = await mgr.connect("user-a", "user", ws_a)
    b = await mgr.connect("user-a", "user", ws_b)

    await mgr.disconnect("user-a", ws_a)

    # User still has one connection — ws_b
    assert mgr.has_connections("user-a")
    await mgr.send_to_connection("user-a", b, {"type": "still-here"})
    assert ws_b.sent == [{"type": "still-here"}]


@pytest.mark.asyncio
async def test_send_to_user_still_broadcasts_to_all_connections():
    mgr = ConnectionManager()
    ws_a, ws_b = _FakeWs(), _FakeWs()
    await mgr.connect("user-a", "user", ws_a)
    await mgr.connect("user-a", "user", ws_b)
    await mgr.send_to_user("user-a", {"type": "broadcast"})
    assert ws_a.sent == [{"type": "broadcast"}]
    assert ws_b.sent == [{"type": "broadcast"}]
