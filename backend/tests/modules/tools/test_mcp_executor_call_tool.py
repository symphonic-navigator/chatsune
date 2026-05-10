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


@pytest.mark.asyncio
async def test_call_tool_on_404_reinitialises_and_retries(monkeypatch):
    """First call returns 404; executor re-runs initialise and retries; second call succeeds."""
    requests_log: list[tuple[str, dict]] = []
    state = {"new_session_id": "sess-fresh"}

    class _MockTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            method = payload.get("method")
            requests_log.append((method, dict(request.headers)))
            if method == "tools/call":
                # Stale session id → 404; fresh one → 200.
                if request.headers.get("mcp-session-id") == "sess-stale":
                    return httpx.Response(404, request=request)
                return _ok_call_response(payload["id"])
            if method == "initialize":
                return httpx.Response(
                    200, request=request,
                    headers={
                        "content-type": "application/json",
                        "mcp-session-id": state["new_session_id"],
                    },
                    content=json.dumps({
                        "jsonrpc": "2.0", "id": payload["id"], "result": {},
                    }).encode(),
                )
            # notifications/initialized
            return httpx.Response(202, request=request)

    _install_transport(monkeypatch, _MockTransport())

    refreshed: list[str] = []

    async def _on_refresh(new_id: str) -> None:
        refreshed.append(new_id)

    executor = McpExecutor()
    out = await executor.call_tool(
        url="http://srv/mcp", api_key=None,
        tool_name="t", arguments={},
        session_id="sess-stale",
        on_session_refresh=_on_refresh,
    )

    assert json.loads(out)["error"] is None
    assert refreshed == ["sess-fresh"]

    methods = [m for m, _ in requests_log]
    # 1st tools/call (404), then initialize, notifications/initialized, retry tools/call
    assert methods == [
        "tools/call",
        "initialize",
        "notifications/initialized",
        "tools/call",
    ]
    # Retry call carried the fresh session id
    retry_headers = requests_log[-1][1]
    assert retry_headers.get("mcp-session-id") == "sess-fresh"


@pytest.mark.asyncio
async def test_call_tool_on_404_does_not_retry_when_no_session_id(monkeypatch):
    """Stateless servers don't have a session id; a 404 must not trigger reinit."""
    methods: list[str] = []

    class _MockTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            methods.append(payload.get("method"))
            return httpx.Response(404, request=request)

    _install_transport(monkeypatch, _MockTransport())

    executor = McpExecutor()
    out = await executor.call_tool(
        url="http://srv/mcp", api_key=None,
        tool_name="t", arguments={},
        # session_id=None
    )
    parsed = json.loads(out)
    assert parsed["error"]  # some error string
    assert methods == ["tools/call"]  # no retry attempted


@pytest.mark.asyncio
async def test_call_tool_on_404_returns_error_when_reinit_fails(monkeypatch):
    """Re-init also fails → executor returns an error string instead of raising."""
    methods: list[str] = []

    class _MockTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            method = payload.get("method")
            methods.append(method)
            if method == "tools/call":
                return httpx.Response(404, request=request)
            if method == "initialize":
                return httpx.Response(503, request=request)
            return httpx.Response(202, request=request)

    _install_transport(monkeypatch, _MockTransport())

    executor = McpExecutor()
    out = await executor.call_tool(
        url="http://srv/mcp", api_key=None,
        tool_name="t", arguments={},
        session_id="sess-stale",
    )
    parsed = json.loads(out)
    assert "re-initialise" in parsed["error"].lower() or "session" in parsed["error"].lower()
    # tools/call (404) → initialize (503); no retry call attempted
    assert "tools/call" in methods
    assert methods.count("tools/call") == 1


@pytest.mark.asyncio
async def test_call_tool_no_double_retry_after_second_404(monkeypatch):
    """After a successful re-init, if the retry call ALSO returns 404, do not loop further."""
    methods: list[str] = []

    class _MockTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            method = payload.get("method")
            methods.append(method)
            if method == "tools/call":
                return httpx.Response(404, request=request)
            if method == "initialize":
                return httpx.Response(
                    200, request=request,
                    headers={
                        "content-type": "application/json",
                        "mcp-session-id": "sess-fresh",
                    },
                    content=json.dumps({
                        "jsonrpc": "2.0", "id": payload["id"], "result": {},
                    }).encode(),
                )
            return httpx.Response(202, request=request)

    _install_transport(monkeypatch, _MockTransport())

    executor = McpExecutor()
    out = await executor.call_tool(
        url="http://srv/mcp", api_key=None,
        tool_name="t", arguments={},
        session_id="sess-stale",
    )
    parsed = json.loads(out)
    assert parsed["error"]
    # Two tools/call attempts: original + one retry. No third.
    assert methods.count("tools/call") == 2
    assert methods.count("initialize") == 1
