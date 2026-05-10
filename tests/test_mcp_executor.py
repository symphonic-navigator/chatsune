"""Tests for McpExecutor — backend-side MCP JSON-RPC client."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.modules.tools._mcp_executor import McpExecutor


@pytest.fixture
def executor():
    return McpExecutor()


class _FakeJsonResp:
    """Stand-in for the async-context-manager returned by `client.stream(...)`
    when the server responds with `Content-Type: application/json`."""

    def __init__(self, body: dict):
        self.headers = {"content-type": "application/json"}
        self._body = json.dumps(body).encode("utf-8")

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def aread(self):
        return self._body


class TestMcpExecutor:
    @pytest.mark.asyncio
    async def test_successful_call(self, executor):
        captured: dict = {}

        def _stream(method, url, json, headers):
            captured["method"] = method
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return _FakeJsonResp({
                "jsonrpc": "2.0",
                "id": json["id"],
                "result": {
                    "content": [{"type": "text", "text": "file contents here"}],
                },
            })

        with patch("backend.modules.tools._mcp_executor.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.stream = _stream
            mock_client_cls.return_value = mock_client

            result = await executor.call_tool(
                url="http://localhost:9100/mcp",
                api_key=None,
                tool_name="read_file",
                arguments={"path": "/tmp/test.txt"},
            )

        parsed = json.loads(result)
        assert parsed["stdout"] == "file contents here"
        assert parsed["error"] is None

    @pytest.mark.asyncio
    async def test_call_with_auth(self, executor):
        captured: dict = {}

        def _stream(method, url, json, headers):
            captured["headers"] = headers
            return _FakeJsonResp({
                "jsonrpc": "2.0", "id": json["id"],
                "result": {"content": [{"type": "text", "text": "ok"}]},
            })

        with patch("backend.modules.tools._mcp_executor.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.stream = _stream
            mock_client_cls.return_value = mock_client

            await executor.call_tool(
                url="http://example.com/mcp",
                api_key="sk-test-key",
                tool_name="search",
                arguments={"q": "test"},
            )

            assert captured["headers"]["Authorization"] == "Bearer sk-test-key"

    @pytest.mark.asyncio
    async def test_timeout_returns_error(self, executor):
        import httpx
        with patch("backend.modules.tools._mcp_executor.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.stream = MagicMock(side_effect=httpx.TimeoutException("timed out"))
            mock_client_cls.return_value = mock_client

            result = await executor.call_tool(
                url="http://localhost:9100/mcp",
                api_key=None,
                tool_name="slow_tool",
                arguments={},
            )

        parsed = json.loads(result)
        assert parsed["error"] is not None
        assert "timeout" in parsed["error"].lower()

    @pytest.mark.asyncio
    async def test_jsonrpc_error_returns_error(self, executor):
        def _stream(method, url, json, headers):
            return _FakeJsonResp({
                "jsonrpc": "2.0", "id": json["id"],
                "error": {"code": -32601, "message": "Tool not found"},
            })

        with patch("backend.modules.tools._mcp_executor.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.stream = _stream
            mock_client_cls.return_value = mock_client

            result = await executor.call_tool(
                url="http://localhost:9100/mcp",
                api_key=None,
                tool_name="missing",
                arguments={},
            )

        parsed = json.loads(result)
        assert parsed["error"] is not None
        assert "not found" in parsed["error"].lower()

    @pytest.mark.asyncio
    async def test_call_tool_sends_streamable_accept_header(self, executor):
        captured: dict = {}

        def _stream(method, url, json, headers):
            captured["headers"] = headers
            return _FakeJsonResp({
                "jsonrpc": "2.0", "id": json["id"],
                "result": {"content": [{"type": "text", "text": "ok"}]},
            })

        with patch("backend.modules.tools._mcp_executor.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.stream = _stream
            mock_client_cls.return_value = mock_client

            await executor.call_tool(
                url="http://example.com/mcp",
                api_key=None,
                tool_name="ping",
                arguments={},
            )
            accept = captured["headers"].get("Accept", "")
            assert "application/json" in accept
            assert "text/event-stream" in accept

    @pytest.mark.asyncio
    async def test_discover_tools_sends_streamable_accept_header(self, executor):
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.json.return_value = {
            "jsonrpc": "2.0", "id": 1, "result": {"tools": []},
        }
        with patch("backend.modules.tools._mcp_executor.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post.return_value = mock_response
            mock_client_cls.return_value = mock_client

            await executor.discover_tools(url="http://example.com/mcp", api_key=None)
            sent_headers = mock_client.post.call_args.kwargs["headers"]
            accept = sent_headers.get("Accept", "")
            assert "application/json" in accept
            assert "text/event-stream" in accept

    @pytest.mark.asyncio
    async def test_call_tool_handles_sse_response(self, executor):
        """Server returns Content-Type: text/event-stream — parse the data: line."""
        captured: dict = {}

        class _FakeStreamResp:
            def __init__(self):
                self.headers = {"content-type": "text/event-stream; charset=utf-8"}
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def aiter_lines(self):
                resp_id = captured["id"]
                yield (
                    f"data: {{\"jsonrpc\":\"2.0\",\"id\":{resp_id},"
                    "\"result\":{\"content\":[{\"type\":\"text\",\"text\":\"sse-result\"}]}}"
                )
                yield ""

        def _stream(method, url, json, headers):
            captured["id"] = json["id"]
            return _FakeStreamResp()

        with patch("backend.modules.tools._mcp_executor.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.stream = _stream
            mock_client_cls.return_value = mock_client

            result = await executor.call_tool(
                url="http://fastmcp.example/mcp",
                api_key=None,
                tool_name="ping",
                arguments={},
            )
            parsed = json.loads(result)
            assert parsed["stdout"] == "sse-result"
            assert parsed["error"] is None

    @pytest.mark.asyncio
    async def test_call_tool_skips_sse_notifications(self, executor):
        """Progress notification arrives before the matching response — must skip the
        notification and return the response."""
        captured: dict = {}

        class _FakeStreamResp:
            def __init__(self):
                self.headers = {"content-type": "text/event-stream"}
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def aiter_lines(self):
                # 1) progress notification (no id) — must be ignored
                yield "data: {\"jsonrpc\":\"2.0\",\"method\":\"notifications/progress\",\"params\":{\"progress\":50}}"
                yield ""
                # 2) the matching response
                resp_id = captured["id"]
                yield (
                    f"data: {{\"jsonrpc\":\"2.0\",\"id\":{resp_id},"
                    "\"result\":{\"content\":[{\"type\":\"text\",\"text\":\"final\"}]}}"
                )
                yield ""

        def _stream(method, url, json, headers):
            captured["id"] = json["id"]
            return _FakeStreamResp()

        with patch("backend.modules.tools._mcp_executor.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.stream = _stream
            mock_client_cls.return_value = mock_client

            result = await executor.call_tool(
                url="http://fastmcp.example/mcp", api_key=None,
                tool_name="ping", arguments={},
            )
            parsed = json.loads(result)
            assert parsed["stdout"] == "final"
            assert parsed["error"] is None

    @pytest.mark.asyncio
    async def test_call_tool_sse_closed_without_response(self, executor):
        """Stream ends without ever producing a matching JSON-RPC reply."""
        class _FakeStreamResp:
            def __init__(self):
                self.headers = {"content-type": "text/event-stream"}
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def aiter_lines(self):
                yield "data: {\"jsonrpc\":\"2.0\",\"method\":\"notifications/progress\",\"params\":{\"progress\":50}}"
                yield ""

        with patch("backend.modules.tools._mcp_executor.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.stream = lambda *a, **kw: _FakeStreamResp()
            mock_client_cls.return_value = mock_client

            result = await executor.call_tool(
                url="http://fastmcp.example/mcp", api_key=None,
                tool_name="ping", arguments={},
            )
            parsed = json.loads(result)
            assert parsed["stdout"] == ""
            assert "error" in parsed and parsed["error"]
