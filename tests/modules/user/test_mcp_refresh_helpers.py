"""Tests for proactive MCP registry refresh helpers."""

from __future__ import annotations

import pytest
from unittest.mock import patch

from backend.modules.tools._mcp_registry import GatewayHandle, SessionMcpRegistry
from backend.modules.tools import set_mcp_registry, remove_mcp_registry
from shared.dtos.inference import ToolDefinition


def _make_handle(name: str, tier: str = "remote") -> GatewayHandle:
    return GatewayHandle(
        id=f"gw-{name}",
        name=name,
        url=f"http://{name}.example/mcp",
        api_key=None,
        tier=tier,
        tool_definitions=[
            ToolDefinition(name=f"{name}__ping", description="p", parameters={}),
        ],
    )


@pytest.mark.asyncio
async def test_refresh_user_mcp_invalidates_and_rediscovers():
    """After _refresh_user_mcp, registries for the user's connections are
    cleared and eager_discover_mcp is invoked once per connection."""
    from backend.modules.user import _handlers

    user_id = "user-refresh-1"
    cid_a = "conn-a"
    cid_b = "conn-b"

    registry_a = SessionMcpRegistry()
    registry_a.register(_make_handle("old_gw"))
    registry_a.backend_discovered = True
    set_mcp_registry(cid_a, registry_a)

    registry_b = SessionMcpRegistry()
    registry_b.register(_make_handle("other"))
    registry_b.backend_discovered = True
    set_mcp_registry(cid_b, registry_b)

    eager_calls: list[tuple[str, str]] = []

    class _FakeManager:
        def connection_ids_for_user(self, uid: str) -> list[str]:
            return [cid_a, cid_b] if uid == user_id else []

    async def _fake_eager(connection_id: str, uid: str, *, always_emit: bool = False) -> None:
        eager_calls.append((connection_id, uid))

    try:
        with patch("backend.ws.manager.get_manager", return_value=_FakeManager()), \
             patch("backend.modules.tools.eager_discover_mcp", new=_fake_eager):
            await _handlers._refresh_user_mcp(user_id)

        assert sorted(eager_calls) == [(cid_a, user_id), (cid_b, user_id)]
    finally:
        remove_mcp_registry(cid_a)
        remove_mcp_registry(cid_b)


@pytest.mark.asyncio
async def test_refresh_user_mcp_no_active_connections_is_noop():
    from backend.modules.user import _handlers

    user_id = "user-refresh-empty"
    eager_calls: list = []

    class _EmptyManager:
        def connection_ids_for_user(self, uid: str) -> list[str]:
            return []

    async def _fake_eager(connection_id: str, uid: str, *, always_emit: bool = False) -> None:
        eager_calls.append((connection_id, uid))

    with patch("backend.ws.manager.get_manager", return_value=_EmptyManager()), \
         patch("backend.modules.tools.eager_discover_mcp", new=_fake_eager):
        await _handlers._refresh_user_mcp(user_id)

    assert eager_calls == []
