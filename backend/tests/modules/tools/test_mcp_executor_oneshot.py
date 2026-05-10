"""Tests for McpExecutor.*_oneshot — proxy-route helpers that run init+call per request."""

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


@pytest.mark.asyncio
async def test_call_tool_oneshot_runs_initialise_then_call(monkeypatch):
    methods: list[str] = []

    class _MockTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            method = payload.get("method")
            methods.append(method)
            if method == "initialize":
                return httpx.Response(
                    200, request=request,
                    headers={
                        "content-type": "application/json",
                        "mcp-session-id": "sess-oneshot",
                    },
                    content=json.dumps({
                        "jsonrpc": "2.0", "id": payload["id"], "result": {},
                    }).encode(),
                )
            if method == "notifications/initialized":
                return httpx.Response(202, request=request)
            if method == "tools/call":
                # Confirm session id is forwarded.
                assert request.headers.get("mcp-session-id") == "sess-oneshot"
                return httpx.Response(
                    200, request=request,
                    headers={"content-type": "application/json"},
                    content=json.dumps({
                        "jsonrpc": "2.0", "id": payload["id"],
                        "result": {"content": [{"type": "text", "text": "hi"}]},
                    }).encode(),
                )
            return httpx.Response(404, request=request)

    _install_transport(monkeypatch, _MockTransport())

    executor = McpExecutor()
    out = await executor.call_tool_oneshot(
        url="http://srv/mcp", api_key=None,
        tool_name="t", arguments={},
    )
    assert json.loads(out)["stdout"] == "hi"
    assert methods == ["initialize", "notifications/initialized", "tools/call"]


@pytest.mark.asyncio
async def test_discover_tools_oneshot_runs_initialise_then_list(monkeypatch):
    methods: list[str] = []

    class _MockTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            method = payload.get("method")
            methods.append(method)
            if method == "initialize":
                return httpx.Response(
                    200, request=request,
                    headers={
                        "content-type": "application/json",
                        "mcp-session-id": "sess-discover",
                    },
                    content=json.dumps({
                        "jsonrpc": "2.0", "id": payload["id"], "result": {},
                    }).encode(),
                )
            if method == "notifications/initialized":
                return httpx.Response(202, request=request)
            if method == "tools/list":
                assert request.headers.get("mcp-session-id") == "sess-discover"
                return httpx.Response(
                    200, request=request,
                    headers={"content-type": "application/json"},
                    content=json.dumps({
                        "jsonrpc": "2.0", "id": payload["id"],
                        "result": {"tools": [{"name": "t1", "description": "", "inputSchema": {}}]},
                    }).encode(),
                )
            return httpx.Response(404, request=request)

    _install_transport(monkeypatch, _MockTransport())

    executor = McpExecutor()
    tools = await executor.discover_tools_oneshot(url="http://srv/mcp", api_key=None)
    assert len(tools) == 1
    assert methods == ["initialize", "notifications/initialized", "tools/list"]


@pytest.mark.asyncio
async def test_oneshot_helpers_work_with_stateless_server(monkeypatch):
    """When initialise returns no session id, the call still proceeds without header."""
    methods: list[str] = []

    class _MockTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            method = payload.get("method")
            methods.append(method)
            if method == "initialize":
                return httpx.Response(
                    200, request=request,
                    headers={"content-type": "application/json"},
                    content=json.dumps({
                        "jsonrpc": "2.0", "id": payload["id"], "result": {},
                    }).encode(),
                )
            if method == "notifications/initialized":
                return httpx.Response(202, request=request)
            assert "mcp-session-id" not in request.headers
            return httpx.Response(
                200, request=request,
                headers={"content-type": "application/json"},
                content=json.dumps({
                    "jsonrpc": "2.0", "id": payload["id"],
                    "result": {"content": [{"type": "text", "text": "ok"}]},
                }).encode(),
            )

    _install_transport(monkeypatch, _MockTransport())

    executor = McpExecutor()
    out = await executor.call_tool_oneshot(
        url="http://srv/mcp", api_key=None,
        tool_name="t", arguments={},
    )
    assert json.loads(out)["error"] is None
    assert methods == ["initialize", "notifications/initialized", "tools/call"]
