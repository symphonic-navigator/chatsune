"""Regression: MCP_TOOLS_REGISTERED must not echo local-tier gateways back."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from backend.modules.tools._mcp_registry import GatewayHandle, SessionMcpRegistry
from shared.dtos.inference import ToolDefinition


def _make_handle(name: str, tier: str) -> GatewayHandle:
    return GatewayHandle(
        id=f"gw-{name}",
        name=name,
        url=f"http://{name}.example/mcp",
        api_key=None,
        tier=tier,
        tool_definitions=[
            ToolDefinition(
                name=f"{name}__ping",
                description="ping",
                parameters={},
            ),
        ],
    )


@pytest.mark.asyncio
async def test_eager_discover_mcp_event_excludes_local_tier():
    """Pre-populate the registry with local + remote, force eager_discover_mcp
    to emit, and assert the published event payload contains no tier=local
    entries."""
    from backend.modules.tools import (
        eager_discover_mcp,
        set_mcp_registry,
        remove_mcp_registry,
    )

    connection_id = "conn-test-filter-local"
    user_id = "user-test"

    registry = SessionMcpRegistry()
    registry.register(_make_handle("local_gw", "local"))
    registry.register(_make_handle("remote_gw", "remote"))
    # Mark backend_discovered=False so eager_discover_mcp does NOT short-circuit
    set_mcp_registry(connection_id, registry)

    captured: list = []

    class _FakeBus:
        async def publish(self, topic, event, **kwargs):
            captured.append((topic, event))

    # Provide one enabled admin gateway so the early-return guard
    # (`if not any(gw.enabled ...)`) does not bail before the emit step.
    # `discover_backend_gateways` is mocked to return an empty registry,
    # so the merge step preserves the pre-populated local + remote handles.
    enabled_admin_gw = {
        "id": "gw-admin-stub",
        "name": "admin_stub",
        "url": "http://admin.example/mcp",
        "api_key": None,
        "enabled": True,
    }

    with patch(
        "backend.modules.user.get_admin_mcp_gateways",
        new=AsyncMock(return_value=[enabled_admin_gw]),
    ), patch(
        "backend.modules.user.get_user_mcp_gateways",
        new=AsyncMock(return_value=[]),
    ), patch(
        "backend.modules.tools._mcp_discovery.discover_backend_gateways",
        new=AsyncMock(return_value=SessionMcpRegistry()),
    ), patch(
        "backend.ws.event_bus.get_event_bus",
        return_value=_FakeBus(),
    ):
        await eager_discover_mcp(connection_id, user_id)

    remove_mcp_registry(connection_id)

    # Event was emitted because the registry already had gateways
    assert len(captured) == 1, f"Expected 1 event, got {len(captured)}"
    _topic, event = captured[0]
    namespaces = [g.namespace for g in event.gateways]
    assert "remote_gw" in namespaces
    assert "local_gw" not in namespaces, (
        f"Local-tier gateway leaked into MCP_TOOLS_REGISTERED payload: "
        f"{namespaces}"
    )


@pytest.mark.asyncio
async def test_eager_discover_mcp_always_emit_publishes_empty_event():
    """When always_emit=True, eager_discover_mcp publishes a MCP_TOOLS_REGISTERED
    event even when no gateways are configured — required so the frontend can
    clear stale sessionGateways after the user deletes their last remote gateway."""
    from backend.modules.tools import (
        eager_discover_mcp,
        remove_mcp_registry,
    )

    connection_id = "conn-test-empty-emit"
    user_id = "user-test"

    # NOT pre-populating any registry — simulates "after delete, nothing left"
    captured: list = []

    class _FakeBus:
        async def publish(self, topic, event, **kwargs):
            captured.append((topic, event))

    with patch(
        "backend.modules.user.get_admin_mcp_gateways",
        new=AsyncMock(return_value=[]),
    ), patch(
        "backend.modules.user.get_user_mcp_gateways",
        new=AsyncMock(return_value=[]),
    ), patch(
        "backend.ws.event_bus.get_event_bus",
        return_value=_FakeBus(),
    ):
        await eager_discover_mcp(connection_id, user_id, always_emit=True)

    remove_mcp_registry(connection_id)

    # Event was emitted despite zero gateways
    assert len(captured) == 1, f"Expected 1 event, got {len(captured)}"
    _topic, event = captured[0]
    assert event.gateways == [], f"Expected empty gateways list, got {event.gateways}"
    assert event.total_tools == 0
