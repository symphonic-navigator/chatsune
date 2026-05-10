"""Tests for McpExecutor — backend-side MCP JSON-RPC client."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from backend.modules.tools._mcp_executor import McpExecutor


@pytest.fixture
def executor():
    return McpExecutor()


class TestMcpExecutor:
    @pytest.mark.asyncio
    async def test_successful_call(self, executor):
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "content": [{"type": "text", "text": "file contents here"}],
            },
        }
        with patch("backend.modules.tools._mcp_executor.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post.return_value = mock_response
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
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "jsonrpc": "2.0", "id": 1,
            "result": {"content": [{"type": "text", "text": "ok"}]},
        }
        with patch("backend.modules.tools._mcp_executor.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post.return_value = mock_response
            mock_client_cls.return_value = mock_client

            await executor.call_tool(
                url="http://example.com/mcp",
                api_key="sk-test-key",
                tool_name="search",
                arguments={"q": "test"},
            )

            call_kwargs = mock_client.post.call_args
            assert call_kwargs.kwargs["headers"]["Authorization"] == "Bearer sk-test-key"

    @pytest.mark.asyncio
    async def test_timeout_returns_error(self, executor):
        import httpx
        with patch("backend.modules.tools._mcp_executor.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post.side_effect = httpx.TimeoutException("timed out")
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
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "jsonrpc": "2.0", "id": 1,
            "error": {"code": -32601, "message": "Tool not found"},
        }
        with patch("backend.modules.tools._mcp_executor.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post.return_value = mock_response
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
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.json.return_value = {
            "jsonrpc": "2.0", "id": 1,
            "result": {"content": [{"type": "text", "text": "ok"}]},
        }
        with patch("backend.modules.tools._mcp_executor.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post.return_value = mock_response
            mock_client_cls.return_value = mock_client

            await executor.call_tool(
                url="http://example.com/mcp",
                api_key=None,
                tool_name="ping",
                arguments={},
            )
            sent_headers = mock_client.post.call_args.kwargs["headers"]
            accept = sent_headers.get("Accept", "")
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
