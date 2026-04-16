from unittest.mock import AsyncMock

import pytest

from backend.modules.llm._csp._registry import SidecarRegistry


@pytest.mark.asyncio
async def test_register_and_lookup():
    reg = SidecarRegistry(event_bus=AsyncMock())
    conn = AsyncMock()
    conn.homelab_id = "H1"
    await reg.register(user_id="u1", conn=conn)
    assert reg.get("H1") is conn
    assert "H1" in reg.online_homelab_ids()


@pytest.mark.asyncio
async def test_unregister_removes_and_emits_status_event():
    bus = AsyncMock()
    reg = SidecarRegistry(event_bus=bus)
    conn = AsyncMock()
    conn.homelab_id = "H1"
    await reg.register(user_id="u1", conn=conn)
    bus.reset_mock()
    await reg.unregister("H1")
    assert reg.get("H1") is None
    bus.publish.assert_awaited_once()
    kwargs = bus.publish.call_args.kwargs
    assert kwargs["target_user_ids"] == ["u1"]


@pytest.mark.asyncio
async def test_last_wins_closes_older_connection():
    reg = SidecarRegistry(event_bus=AsyncMock())
    old = AsyncMock()
    old.homelab_id = "H1"
    await reg.register(user_id="u1", conn=old)
    new = AsyncMock()
    new.homelab_id = "H1"
    await reg.register(user_id="u1", conn=new)
    old.send.assert_awaited()
    assert reg.get("H1") is new


@pytest.mark.asyncio
async def test_revoke_closes_connection_with_auth_revoked_frame():
    reg = SidecarRegistry(event_bus=AsyncMock())
    conn = AsyncMock()
    conn.homelab_id = "H1"
    await reg.register(user_id="u1", conn=conn)
    await reg.revoke("H1")
    # both auth_revoked sent and close called
    assert conn.send.await_count >= 1
    conn.close.assert_awaited()
    assert reg.get("H1") is None
