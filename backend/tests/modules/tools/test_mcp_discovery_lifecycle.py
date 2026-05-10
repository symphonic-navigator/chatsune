"""Tests for _discover_single_gateway lifecycle integration."""

from unittest.mock import AsyncMock, patch

import pytest

from backend.modules.tools._mcp_discovery import _discover_single_gateway
from shared.dtos.mcp import McpGatewayConfigDto


def _config(**overrides) -> McpGatewayConfigDto:
    defaults = dict(
        id="gw-1",
        name="testgw",
        url="http://example.com",
        api_key=None,
        enabled=True,
        disabled_tools=[],
        server_configs={},
        tool_overrides=[],
    )
    defaults.update(overrides)
    return McpGatewayConfigDto(**defaults)


@pytest.mark.asyncio
async def test_discover_single_gateway_initialises_and_stashes_session_id():
    raw_tools = [{"name": "t", "description": "", "inputSchema": {}, "_gateway_server": "s"}]

    with patch(
        "backend.modules.tools._mcp_discovery._executor.initialise",
        new=AsyncMock(return_value="sess-from-init"),
    ), patch(
        "backend.modules.tools._mcp_discovery._executor.discover_tools",
        new=AsyncMock(return_value=raw_tools),
    ) as discover_mock:
        handle, status = await _discover_single_gateway(_config(), tier="admin")

    assert handle is not None
    assert handle.session_id == "sess-from-init"
    assert status.reachable is True
    discover_mock.assert_awaited_once()
    # session id is forwarded into discover_tools
    call_kwargs = discover_mock.await_args.kwargs
    assert call_kwargs.get("session_id") == "sess-from-init"


@pytest.mark.asyncio
async def test_discover_single_gateway_handles_stateless_initialise():
    raw_tools = [{"name": "t", "description": "", "inputSchema": {}, "_gateway_server": "s"}]
    with patch(
        "backend.modules.tools._mcp_discovery._executor.initialise",
        new=AsyncMock(return_value=None),
    ), patch(
        "backend.modules.tools._mcp_discovery._executor.discover_tools",
        new=AsyncMock(return_value=raw_tools),
    ) as discover_mock:
        handle, status = await _discover_single_gateway(_config(), tier="admin")

    assert handle is not None
    assert handle.session_id is None
    assert status.reachable is True
    assert discover_mock.await_args.kwargs.get("session_id") is None


@pytest.mark.asyncio
async def test_discover_single_gateway_unreachable_when_init_and_list_both_fail():
    with patch(
        "backend.modules.tools._mcp_discovery._executor.initialise",
        new=AsyncMock(return_value=None),
    ), patch(
        "backend.modules.tools._mcp_discovery._executor.discover_tools",
        new=AsyncMock(return_value=[]),
    ):
        handle, status = await _discover_single_gateway(_config(), tier="admin")

    assert handle is None
    assert status.reachable is False
