"""Tests for McpExecutor.initialise — the MCP Streamable HTTP handshake."""

import json
import sys

import httpx
import pytest

# backend.modules.tools.__init__ shadows '_mcp_executor' at package level with
# the McpExecutor singleton.  We must retrieve the actual module object via
# sys.modules (populated after any import touches the package).
import backend.modules.tools._mcp_executor  # ensure module is loaded  # noqa: F401
_mcp_executor_mod = sys.modules["backend.modules.tools._mcp_executor"]

from backend.modules.tools._mcp_executor import (  # noqa: E402
    MCP_PROTOCOL_VERSION,
    McpExecutor,
)


def _json_response(payload: dict, *, headers: dict | None = None) -> httpx.Response:
    """Build a fake JSON httpx.Response with a plausible Request attached."""
    req = httpx.Request("POST", "http://srv/mcp")
    return httpx.Response(
        200,
        request=req,
        headers={"content-type": "application/json", **(headers or {})},
        content=json.dumps(payload).encode(),
    )


def _sse_response(payload: dict, *, headers: dict | None = None) -> httpx.Response:
    """Build a fake SSE httpx.Response — single data line then close."""
    req = httpx.Request("POST", "http://srv/mcp")
    body = f"data: {json.dumps(payload)}\n\n".encode()
    return httpx.Response(
        200,
        request=req,
        headers={"content-type": "text/event-stream", **(headers or {})},
        content=body,
    )


def _install_transport(monkeypatch, transport: httpx.AsyncBaseTransport) -> None:
    """Patch httpx.AsyncClient in the executor module to use the given transport.

    Uses a subclass so that super().__init__() hits the real AsyncClient.__init__
    — avoiding the infinite-recursion that a simple factory replacement would cause.
    """
    class _PatchedClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(_mcp_executor_mod.httpx, "AsyncClient", _PatchedClient)


@pytest.mark.asyncio
async def test_initialise_three_step_handshake_with_session_id(monkeypatch):
    """initialise → notifications/initialized; both carry the session id when one is issued."""
    requests: list[tuple[str, dict]] = []  # (method-from-payload, headers)

    class _MockTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            requests.append((payload.get("method"), dict(request.headers)))
            method = payload.get("method")
            if method == "initialize":
                return _json_response(
                    {"jsonrpc": "2.0", "id": payload["id"], "result": {}},
                    headers={"mcp-session-id": "sess-abc"},
                )
            if method == "notifications/initialized":
                return httpx.Response(202, request=request)
            return httpx.Response(404, request=request)

    _install_transport(monkeypatch, _MockTransport())

    executor = McpExecutor()
    session_id = await executor.initialise(url="http://srv/mcp", api_key=None)

    assert session_id == "sess-abc"
    assert [m for m, _ in requests] == ["initialize", "notifications/initialized"]
    # The notification carries Mcp-Session-Id when one was issued
    notif_headers = requests[1][1]
    assert notif_headers.get("mcp-session-id") == "sess-abc"


@pytest.mark.asyncio
async def test_initialise_returns_none_when_no_session_id_header(monkeypatch):
    """Stateless servers respond without Mcp-Session-Id — we treat it as None."""
    class _MockTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            if payload.get("method") == "initialize":
                # No mcp-session-id header
                return _json_response(
                    {"jsonrpc": "2.0", "id": payload["id"], "result": {}},
                )
            return httpx.Response(202, request=request)

    _install_transport(monkeypatch, _MockTransport())

    executor = McpExecutor()
    session_id = await executor.initialise(url="http://srv/mcp", api_key=None)
    assert session_id is None


@pytest.mark.asyncio
async def test_initialise_returns_none_on_5xx(monkeypatch):
    """Server error → return None so caller can route the error like an unreachable gateway."""
    class _MockTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, request=request)

    _install_transport(monkeypatch, _MockTransport())

    executor = McpExecutor()
    session_id = await executor.initialise(url="http://srv/mcp", api_key=None)
    assert session_id is None


@pytest.mark.asyncio
async def test_initialise_handles_sse_response_body(monkeypatch):
    """When server replies via SSE, initialise still extracts the session id from the header."""
    requests: list[str] = []

    class _MockTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            requests.append(payload.get("method"))
            if payload.get("method") == "initialize":
                return _sse_response(
                    {"jsonrpc": "2.0", "id": payload["id"], "result": {}},
                    headers={"mcp-session-id": "sess-sse"},
                )
            return httpx.Response(202, request=request)

    _install_transport(monkeypatch, _MockTransport())

    executor = McpExecutor()
    session_id = await executor.initialise(url="http://srv/mcp", api_key=None)
    assert session_id == "sess-sse"
    assert requests == ["initialize", "notifications/initialized"]


@pytest.mark.asyncio
async def test_initialise_payload_advertises_protocol_version_and_capabilities(monkeypatch):
    captured: dict = {}

    class _MockTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            if payload.get("method") == "initialize":
                captured.update(payload)
                return _json_response(
                    {"jsonrpc": "2.0", "id": payload["id"], "result": {}},
                    headers={"mcp-session-id": "x"},
                )
            return httpx.Response(202, request=request)

    _install_transport(monkeypatch, _MockTransport())

    executor = McpExecutor()
    await executor.initialise(url="http://srv/mcp", api_key=None)

    params = captured["params"]
    assert params["protocolVersion"] == MCP_PROTOCOL_VERSION
    assert params["capabilities"] == {}
    assert params["clientInfo"]["name"] == "chatsune"
    assert isinstance(params["clientInfo"]["version"], str)
