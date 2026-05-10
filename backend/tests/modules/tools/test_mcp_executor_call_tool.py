"""Tests for McpExecutor.call_tool — session header behaviour."""

import json
import sys

import httpx
import pytest

import backend.modules.tools._mcp_executor  # noqa: F401  (loads module into sys.modules)
_mcp_executor_mod = sys.modules["backend.modules.tools._mcp_executor"]

from backend.modules.tools._mcp_executor import McpExecutor  # noqa: E402


def _install_transport(monkeypatch, transport: httpx.AsyncBaseTransport) -> None:
    """Patch httpx.AsyncClient in the executor module to use the given transport."""
    class _PatchedClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(_mcp_executor_mod.httpx, "AsyncClient", _PatchedClient)


def _ok_call_response(req_id: int) -> httpx.Response:
    req = httpx.Request("POST", "http://srv/mcp")
    return httpx.Response(
        200,
        request=req,
        headers={"content-type": "application/json"},
        content=json.dumps({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"content": [{"type": "text", "text": "ok"}]},
        }).encode(),
    )


@pytest.mark.asyncio
async def test_call_tool_sends_mcp_session_id_header_when_set(monkeypatch):
    captured_headers: list[dict] = []

    class _MockTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            captured_headers.append(dict(request.headers))
            payload = json.loads(request.content)
            return _ok_call_response(payload["id"])

    _install_transport(monkeypatch, _MockTransport())

    executor = McpExecutor()
    out = await executor.call_tool(
        url="http://srv/mcp", api_key=None,
        tool_name="t", arguments={},
        session_id="sess-xyz",
    )

    parsed = json.loads(out)
    assert parsed["error"] is None
    assert captured_headers[0].get("mcp-session-id") == "sess-xyz"


@pytest.mark.asyncio
async def test_call_tool_omits_mcp_session_id_header_when_none(monkeypatch):
    captured_headers: list[dict] = []

    class _MockTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            captured_headers.append(dict(request.headers))
            payload = json.loads(request.content)
            return _ok_call_response(payload["id"])

    _install_transport(monkeypatch, _MockTransport())

    executor = McpExecutor()
    out = await executor.call_tool(
        url="http://srv/mcp", api_key=None,
        tool_name="t", arguments={},
        # session_id defaults to None
    )
    assert json.loads(out)["error"] is None
    assert "mcp-session-id" not in captured_headers[0]
