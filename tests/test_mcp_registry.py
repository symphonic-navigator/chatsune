"""Tests for SessionMcpRegistry."""

import pytest

from backend.modules.tools._mcp_registry import SessionMcpRegistry, GatewayHandle
from shared.dtos.inference import ToolDefinition


def _make_handle(
    name: str = "test",
    tier: str = "remote",
    tools: list[ToolDefinition] | None = None,
) -> GatewayHandle:
    return GatewayHandle(
        id="gw-1",
        name=name,
        url="http://localhost:9100",
        api_key=None,
        tier=tier,
        tool_definitions=tools or [
            ToolDefinition(
                name=f"{name}__read_file",
                description="Read a file",
                parameters={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
            ),
        ],
    )


class TestSessionMcpRegistry:
    def test_register_and_resolve(self):
        reg = SessionMcpRegistry()
        handle = _make_handle(name="homelab")
        reg.register(handle)
        gw, original = reg.resolve("homelab__read_file")
        assert gw.name == "homelab"
        assert original == "read_file"

    def test_resolve_unknown_raises(self):
        reg = SessionMcpRegistry()
        with pytest.raises(KeyError):
            reg.resolve("unknown__tool")

    def test_is_mcp_tool(self):
        reg = SessionMcpRegistry()
        reg.register(_make_handle(name="homelab"))
        assert reg.is_mcp_tool("homelab__read_file") is True
        assert reg.is_mcp_tool("web_search") is False
        assert reg.is_mcp_tool("unknown__tool") is False

    def test_all_definitions_sorted(self):
        reg = SessionMcpRegistry()
        reg.register(_make_handle(name="zeta", tools=[
            ToolDefinition(name="zeta__z_tool", description="Z", parameters={}),
        ]))
        reg.register(_make_handle(name="alpha", tools=[
            ToolDefinition(name="alpha__a_tool", description="A", parameters={}),
        ]))
        defs = reg.all_definitions()
        assert [d.name for d in defs] == ["alpha__a_tool", "zeta__z_tool"]

    def test_duplicate_namespace_raises(self):
        reg = SessionMcpRegistry()
        reg.register(_make_handle(name="homelab"))
        with pytest.raises(ValueError, match="already registered"):
            reg.register(_make_handle(name="homelab"))
