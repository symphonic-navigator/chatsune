"""Tests for McpExecutor.discover_tools — session header behaviour."""

import json
import sys

import httpx
import pytest

import backend.modules.tools._mcp_executor  # noqa: F401
_mcp_executor_mod = sys.modules["backend.modules.tools._mcp_executor"]

from backend.modules.tools._mcp_executor import McpExecutor  # noqa: E402


def _install_transport(monkeypatch, transport: httpx.AsyncBaseTransport) -> None:
    class _PatchedClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(_mcp_executor_mod.httpx, "AsyncClient", _PatchedClient)


def _tools_list_response(req_id: int) -> httpx.Response:
    req = httpx.Request("POST", "http://srv/mcp")
    return httpx.Response(
        200,
        request=req,
        headers={"content-type": "application/json"},
        content=json.dumps({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": [{"name": "t1", "description": "", "inputSchema": {}}]},
        }).encode(),
    )


@pytest.mark.asyncio
async def test_discover_tools_sends_mcp_session_id_header_when_set(monkeypatch):
    captured: list[dict] = []

    class _MockTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            captured.append(dict(request.headers))
            payload = json.loads(request.content)
            return _tools_list_response(payload["id"])

    _install_transport(monkeypatch, _MockTransport())

    executor = McpExecutor()
    tools = await executor.discover_tools(
        url="http://srv/mcp", api_key=None,
        session_id="sess-discovery",
    )
    assert len(tools) == 1
    assert captured[0].get("mcp-session-id") == "sess-discovery"


@pytest.mark.asyncio
async def test_discover_tools_omits_mcp_session_id_header_when_none(monkeypatch):
    captured: list[dict] = []

    class _MockTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            captured.append(dict(request.headers))
            payload = json.loads(request.content)
            return _tools_list_response(payload["id"])

    _install_transport(monkeypatch, _MockTransport())

    executor = McpExecutor()
    tools = await executor.discover_tools(url="http://srv/mcp", api_key=None)
    assert len(tools) == 1
    assert "mcp-session-id" not in captured[0]
