from unittest.mock import AsyncMock, MagicMock
import pytest
from backend.ws.manager import ConnectionManager


def make_ws():
    ws = MagicMock()
    ws.send_json = AsyncMock()
    return ws


async def test_connect_registers_user():
    mgr = ConnectionManager()
    ws = make_ws()
    await mgr.connect("user1", "user", ws)
    assert "user1" in mgr._connections
    assert mgr._user_roles["user1"] == "user"


async def test_disconnect_removes_connection():
    mgr = ConnectionManager()
    ws = make_ws()
    await mgr.connect("user1", "user", ws)
    await mgr.disconnect("user1", ws)
    assert "user1" not in mgr._connections
    assert "user1" not in mgr._user_roles


async def test_disconnect_keeps_entry_when_other_sessions_remain():
    mgr = ConnectionManager()
    ws1, ws2 = make_ws(), make_ws()
    await mgr.connect("user1", "user", ws1)
    await mgr.connect("user1", "user", ws2)
    await mgr.disconnect("user1", ws1)
    assert "user1" in mgr._connections
    assert ws1 not in mgr._connections["user1"].values()
    assert ws2 in mgr._connections["user1"].values()


async def test_send_to_user_delivers_event():
    mgr = ConnectionManager()
    ws = make_ws()
    await mgr.connect("user1", "user", ws)
    await mgr.send_to_user("user1", {"type": "test"})
    ws.send_json.assert_awaited_once_with({"type": "test"})


async def test_send_to_user_ignores_missing_user():
    mgr = ConnectionManager()
    # Should not raise
    await mgr.send_to_user("nonexistent", {"type": "test"})


async def test_send_to_users_delivers_to_all():
    mgr = ConnectionManager()
    ws1, ws2 = make_ws(), make_ws()
    await mgr.connect("user1", "user", ws1)
    await mgr.connect("user2", "user", ws2)
    await mgr.send_to_users(["user1", "user2"], {"type": "test"})
    ws1.send_json.assert_awaited_once()
    ws2.send_json.assert_awaited_once()


async def test_broadcast_to_roles_only_sends_to_matching_role():
    mgr = ConnectionManager()
    admin_ws = make_ws()
    user_ws = make_ws()
    await mgr.connect("admin1", "admin", admin_ws)
    await mgr.connect("user1", "user", user_ws)
    await mgr.broadcast_to_roles(["admin"], {"type": "test"})
    admin_ws.send_json.assert_awaited_once_with({"type": "test"})
    user_ws.send_json.assert_not_awaited()


async def test_broadcast_to_multiple_roles():
    mgr = ConnectionManager()
    admin_ws = make_ws()
    master_ws = make_ws()
    user_ws = make_ws()
    await mgr.connect("admin1", "admin", admin_ws)
    await mgr.connect("master1", "master_admin", master_ws)
    await mgr.connect("user1", "user", user_ws)
    await mgr.broadcast_to_roles(["admin", "master_admin"], {"type": "test"})
    admin_ws.send_json.assert_awaited_once()
    master_ws.send_json.assert_awaited_once()
    user_ws.send_json.assert_not_awaited()


def test_user_ids_by_role():
    mgr = ConnectionManager()
    mgr._user_roles = {"a1": "admin", "m1": "master_admin", "u1": "user"}
    result = mgr.user_ids_by_role("admin")
    assert result == ["a1"]
